from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from nivvi.domain.models import ActionStatus, ChatChannel, ChatMessage
from nivvi.services.action_service import ActionService
from nivvi.services.audit_service import AuditService
from nivvi.services.dashboard_service import DashboardService
from nivvi.services.utils import generate_id
from nivvi.storage.in_memory import InMemoryStore
from nivvi.storage.relational_persistence import RelationalPersistence


@dataclass
class ChatReply:
    inbound: ChatMessage
    outbound: ChatMessage


class ChatService:
    """Processes inbound chat events from WhatsApp/Telegram style channels."""

    ACTION_ID_PATTERN = re.compile(r"\bact_[a-z0-9]{8,}\b")

    def __init__(
        self,
        store: InMemoryStore,
        action_service: ActionService,
        dashboard_service: DashboardService,
        audit_service: AuditService,
        relational_persistence: RelationalPersistence | None = None,
    ) -> None:
        self.store = store
        self.action_service = action_service
        self.dashboard_service = dashboard_service
        self.audit_service = audit_service
        self.relational_persistence = relational_persistence

    def handle_event(
        self,
        household_id: str,
        channel: ChatChannel,
        user_id: str,
        message: str,
        metadata: dict | None = None,
    ) -> ChatReply:
        normalized_message = (message or "").strip()
        inbound = self._append_message(
            household_id=household_id,
            channel=channel,
            user_id=user_id,
            sender="user",
            text=normalized_message,
            metadata=metadata or {},
        )

        try:
            response_text = self._route_command(household_id, normalized_message)
        except ValueError as error:
            response_text = f"Command error: {error}. {self._help_text()}"

        outbound = self._append_message(
            household_id=household_id,
            channel=channel,
            user_id=user_id,
            sender="agent",
            text=response_text,
            metadata={"in_reply_to": inbound.id},
        )

        self.audit_service.log(
            household_id,
            "chat.event_processed",
            inbound.id,
            {
                "channel": channel.value,
                "user_id": user_id,
                "message": normalized_message,
                "reply_message_id": outbound.id,
            },
        )

        return ChatReply(inbound=inbound, outbound=outbound)

    def list_messages(self, household_id: str, channel: ChatChannel | None = None) -> list[ChatMessage]:
        messages = [
            item
            for item in self.store.chat_messages
            if item.household_id == household_id and (channel is None or item.channel == channel)
        ]
        return sorted(messages, key=lambda item: item.created_at)

    def _append_message(
        self,
        household_id: str,
        channel: ChatChannel,
        user_id: str | None,
        sender: str,
        text: str,
        metadata: dict,
    ) -> ChatMessage:
        message = ChatMessage(
            id=generate_id("msg"),
            household_id=household_id,
            channel=channel,
            user_id=user_id,
            sender=sender,
            text=text,
            metadata=metadata,
        )
        self.store.chat_messages.append(message)
        if self.relational_persistence is not None:
            self.relational_persistence.upsert_chat_message(message)
        return message

    def _route_command(self, household_id: str, message: str) -> str:
        if not message:
            return self._help_text()

        command, *rest = message.split()
        command = command.lower()

        handler_map = self._handler_map()

        if command in handler_map:
            return handler_map[command](household_id, rest)

        inferred = self._infer_natural_language_intent(message)
        if inferred is not None:
            inferred_command, inferred_args = inferred
            self.audit_service.log(
                household_id,
                "chat.intent_inferred",
                household_id,
                {
                    "input": message,
                    "intent": inferred_command,
                    "args": inferred_args,
                },
            )
            return handler_map[inferred_command](household_id, inferred_args)

        return self._cmd_brief(household_id, [])

    def _cmd_help(self, household_id: str, args: list[str]) -> str:
        del household_id, args
        return self._help_text()

    def _cmd_brief(self, household_id: str, args: list[str]) -> str:
        del args
        dashboard = self.dashboard_service.today(household_id)
        counts = dashboard["counts"]
        alerts = dashboard["alerts"]
        pending_actions = dashboard["pending_actions"]

        sections = [
            (
                "Advisor brief: "
                f"{counts['alerts']} alerts, {counts['pending_actions']} pending actions, "
                f"{counts['overdue_deadlines']} overdue deadlines."
            )
        ]

        shortfall_alert = next((item for item in alerts if item.get("type") == "cashflow_shortfall"), None)
        if shortfall_alert:
            sections.append(
                "Priority: shortfall risk detected. "
                f"Projected low point {shortfall_alert.get('p10_balance', 0.0):.2f} "
                f"on {str(shortfall_alert.get('date', ''))[:10]}."
            )
        elif alerts:
            first_alert = alerts[0]
            if first_alert.get("type") == "deadline":
                sections.append(
                    "Priority: upcoming deadline "
                    f"'{first_alert.get('title', 'item')}' due {str(first_alert.get('due_at', ''))[:10]}."
                )

        if pending_actions:
            top_action = pending_actions[0]
            action_id = top_action["id"]
            sections.append(
                "Top action: "
                f"{action_id} [{top_action['status']}] {top_action['action_type']} "
                f"{top_action['amount']:.2f} {top_action['currency']}."
            )
            sections.append(f"Reply 'preview {action_id}' or 'approve {action_id}'.")
        else:
            sections.append("No pending approvals right now.")

        return " ".join(sections)

    def _cmd_today(self, household_id: str, args: list[str]) -> str:
        del args
        dashboard = self.dashboard_service.today(household_id)
        return (
            f"Today: {dashboard['counts']['alerts']} alerts, "
            f"{dashboard['counts']['pending_actions']} pending actions, "
            f"{dashboard['counts']['overdue_deadlines']} overdue deadlines."
        )

    def _cmd_actions(self, household_id: str, args: list[str]) -> str:
        del args
        actions = self.action_service.list_actions(household_id)
        open_actions = [
            action
            for action in actions
            if action.status in {ActionStatus.DRAFT, ActionStatus.PENDING_AUTHORIZATION, ActionStatus.APPROVED}
        ]
        if not open_actions:
            return "No open actions."
        lines = [
            f"{action.id} [{action.status.value}] {action.action_type.value} {action.amount:.2f} {action.currency}"
            for action in sorted(open_actions, key=lambda item: item.created_at, reverse=True)[:5]
        ]
        return "Open actions:\n" + "\n".join(lines)

    def _cmd_preview(self, household_id: str, args: list[str]) -> str:
        del household_id
        action_id = self._require_action_id(args)
        preview = self.action_service.preview(action_id)
        return (
            f"Preview {action_id}: projected balance {preview.projected_balance_after:.2f}, "
            f"fee impact {preview.fee_impact:.2f}, goal impact {preview.goal_impact}."
        )

    def _cmd_confirm(self, household_id: str, args: list[str]) -> str:
        del household_id
        action_id = self._require_action_id(args)
        action = self.action_service.approve(action_id, "confirm")
        return f"Action {action.id} confirmed. Next step: authorize {action.id}"

    def _cmd_authorize(self, household_id: str, args: list[str]) -> str:
        del household_id
        action_id = self._require_action_id(args)
        action = self.action_service.approve(action_id, "authorize")
        return f"Action {action.id} authorized and ready for dispatch."

    def _cmd_approve(self, household_id: str, args: list[str]) -> str:
        del household_id
        action_id = self._require_action_id(args)
        action = self.store.actions.get(action_id)
        if action is None:
            raise ValueError(f"Unknown action_id '{action_id}'")

        if action.status == ActionStatus.REJECTED:
            return f"Action {action.id} is rejected and cannot be approved."
        if action.status == ActionStatus.DISPATCHED:
            return f"Action {action.id} is already dispatched."
        if action.status == ActionStatus.APPROVED:
            return f"Action {action.id} is already authorized. Next step: dispatch {action.id}"
        if action.status == ActionStatus.FAILED:
            return (
                f"Action {action.id} is in failed state. Retry with dispatch {action.id} <idempotency_key> "
                "or use the retry endpoint."
            )

        if action.approval_step < 1 or action.status == ActionStatus.DRAFT:
            action = self.action_service.approve(action_id, "confirm")
            return f"Action {action.id} confirmed. Next step: approve {action.id}"

        action = self.action_service.approve(action_id, "authorize")
        return f"Action {action.id} authorized and ready for dispatch."

    def _cmd_reject(self, household_id: str, args: list[str]) -> str:
        del household_id
        action_id = self._require_action_id(args)
        reason = " ".join(args[1:]).strip() if len(args) > 1 else "Rejected via chat"
        action = self.action_service.reject(action_id, reason)
        return f"Action {action.id} rejected."

    def _cmd_dispatch(self, household_id: str, args: list[str]) -> str:
        del household_id
        action_id = self._require_action_id(args)
        idempotency_key = args[1].strip() if len(args) > 1 else None
        receipt = self.action_service.dispatch(action_id, idempotency_key=idempotency_key)
        return f"Dispatch result for {action_id}: {receipt.result} ({receipt.partner_ref})"

    @staticmethod
    def _require_action_id(args: list[str]) -> str:
        if not args:
            raise ValueError("Command requires action_id")
        return args[0]

    def _handler_map(self) -> dict[str, Callable[[str, list[str]], str]]:
        return {
            "help": self._cmd_help,
            "brief": self._cmd_brief,
            "summary": self._cmd_brief,
            "status": self._cmd_brief,
            "today": self._cmd_today,
            "actions": self._cmd_actions,
            "preview": self._cmd_preview,
            "confirm": self._cmd_confirm,
            "authorize": self._cmd_authorize,
            "approve": self._cmd_approve,
            "reject": self._cmd_reject,
            "dispatch": self._cmd_dispatch,
        }

    def _infer_natural_language_intent(self, message: str) -> tuple[str, list[str]] | None:
        text = " ".join((message or "").strip().lower().split())
        action_id = self._extract_action_id(text)

        if self._contains_any(
            text,
            (
                "what can you do",
                "capabilities",
                "how can you help",
                "what do you do",
                "help me",
            ),
        ):
            return ("help", [])

        if self._contains_any(
            text,
            (
                "what should i prioritize",
                "what should i do",
                "how am i doing",
                "money check",
                "check in",
                "check-in",
                "give me a brief",
                "give me a summary",
            ),
        ):
            return ("brief", [])

        if self._contains_any(
            text,
            (
                "show actions",
                "pending actions",
                "what actions",
                "action queue",
                "what can i approve",
            ),
        ):
            return ("actions", [])

        if action_id:
            if self._contains_any(text, ("preview", "impact", "what happens")):
                return ("preview", [action_id])
            if self._contains_any(text, ("authorize", "final approve", "final approval")):
                return ("authorize", [action_id])
            if self._contains_any(text, ("reject", "decline", "skip", "cancel")):
                return ("reject", [action_id])
            if self._contains_any(text, ("dispatch", "execute", "run", "go ahead", "do it")):
                return ("dispatch", [action_id])
            if self._contains_any(text, ("approve", "confirm")):
                return ("approve", [action_id])

        if self._contains_any(text, ("today", "dashboard status", "status today")):
            return ("today", [])

        return None

    def _extract_action_id(self, text: str) -> str | None:
        match = self.ACTION_ID_PATTERN.search(text)
        if not match:
            return None
        return match.group(0)

    @staticmethod
    def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _help_text() -> str:
        return (
            "I act as your AI money manager. Ask naturally (for example: "
            "'What should I prioritize this week?') or use commands: brief, today, actions, "
            "preview <id>, approve <id>, confirm <id>, authorize <id>, reject <id> [reason], "
            "dispatch <id> [idempotency_key], help"
        )
