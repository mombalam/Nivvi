from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from nivvi.domain.models import ChatChannel
from nivvi.services.audit_service import AuditService
from nivvi.services.chat_service import ChatService
from nivvi.storage.in_memory import InMemoryStore
from nivvi.storage.relational_persistence import RelationalPersistence


@dataclass
class InboundProviderMessage:
    channel: ChatChannel
    user_handle: str
    text: str
    metadata: dict[str, Any]


@dataclass
class WebhookProcessResult:
    processed: int
    ignored: int
    unmatched: int
    responses: list[dict[str, Any]]


class WebhookService:
    """Parses and processes provider webhook payloads for WhatsApp and Telegram."""

    def __init__(
        self,
        store: InMemoryStore,
        chat_service: ChatService,
        audit_service: AuditService,
        relational_persistence: RelationalPersistence | None = None,
    ) -> None:
        self.store = store
        self.chat_service = chat_service
        self.audit_service = audit_service
        self.relational_persistence = relational_persistence

    @staticmethod
    def identity_key(channel: ChatChannel, user_handle: str) -> str:
        return f"{channel.value}:{user_handle.strip()}"

    def link_identity(self, household_id: str, channel: ChatChannel, user_handle: str) -> dict[str, str]:
        key = self.identity_key(channel, user_handle)
        self.store.channel_identities[key] = household_id
        if self.relational_persistence is not None:
            self.relational_persistence.upsert_channel_identity(
                identity_key=key,
                household_id=household_id,
                channel=channel.value,
                user_handle=user_handle,
            )
        self.audit_service.log(
            household_id,
            "channel.identity_linked",
            key,
            {"channel": channel.value, "user_handle": user_handle},
        )
        return {"key": key, "household_id": household_id}

    def list_identities(self, household_id: str | None = None) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for key, resolved_household in self.store.channel_identities.items():
            if household_id is not None and resolved_household != household_id:
                continue
            channel, user_handle = key.split(":", maxsplit=1)
            items.append(
                {
                    "household_id": resolved_household,
                    "channel": channel,
                    "user_handle": user_handle,
                }
            )
        return sorted(items, key=lambda item: (item["household_id"], item["channel"], item["user_handle"]))

    def process_whatsapp_payload(self, payload: dict[str, Any]) -> WebhookProcessResult:
        messages = self.parse_whatsapp_payload(payload)
        return self._process_messages(messages)

    def process_telegram_payload(self, payload: dict[str, Any]) -> WebhookProcessResult:
        messages = self.parse_telegram_payload(payload)
        return self._process_messages(messages)

    def parse_whatsapp_payload(self, payload: dict[str, Any]) -> list[InboundProviderMessage]:
        events: list[InboundProviderMessage] = []

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                contact_names = {
                    item.get("wa_id"): item.get("profile", {}).get("name")
                    for item in contacts
                    if item.get("wa_id")
                }
                for message in value.get("messages", []):
                    user_handle = str(message.get("from") or "").strip()
                    text = self._whatsapp_text(message)
                    if not user_handle or not text:
                        continue
                    events.append(
                        InboundProviderMessage(
                            channel=ChatChannel.WHATSAPP,
                            user_handle=user_handle,
                            text=text,
                            metadata={
                                "provider": "meta_whatsapp",
                                "message_id": message.get("id"),
                                "timestamp": message.get("timestamp"),
                                "contact_name": contact_names.get(user_handle),
                                "raw_type": message.get("type"),
                            },
                        )
                    )

        return events

    def parse_telegram_payload(self, payload: dict[str, Any]) -> list[InboundProviderMessage]:
        events: list[InboundProviderMessage] = []

        # Telegram sends one update per webhook call; still support list-shaped payload fallback.
        updates: list[dict[str, Any]]
        if "result" in payload and isinstance(payload.get("result"), list):
            updates = [item for item in payload["result"] if isinstance(item, dict)]
        else:
            updates = [payload]

        for update in updates:
            message = update.get("message") or update.get("edited_message")
            if not isinstance(message, dict):
                continue
            text = str(message.get("text") or "").strip()
            if not text:
                continue

            from_user = message.get("from", {}) if isinstance(message.get("from"), dict) else {}
            chat = message.get("chat", {}) if isinstance(message.get("chat"), dict) else {}

            user_id = from_user.get("id") or chat.get("id")
            if user_id is None:
                continue

            events.append(
                InboundProviderMessage(
                    channel=ChatChannel.TELEGRAM,
                    user_handle=str(user_id),
                    text=text,
                    metadata={
                        "provider": "telegram",
                        "update_id": update.get("update_id"),
                        "message_id": message.get("message_id"),
                        "chat_id": chat.get("id"),
                        "username": from_user.get("username"),
                        "first_name": from_user.get("first_name"),
                    },
                )
            )

        return events

    @staticmethod
    def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str | None) -> bool:
        if not app_secret:
            return True
        if not signature_header:
            return False
        if not signature_header.startswith("sha256="):
            return False

        expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        provided = signature_header.split("=", maxsplit=1)[1]
        return hmac.compare_digest(provided, expected)

    @staticmethod
    def verify_telegram_secret(secret_header: str | None, expected_secret: str | None) -> bool:
        if not expected_secret:
            return True
        if not secret_header:
            return False
        return hmac.compare_digest(secret_header, expected_secret)

    def _process_messages(self, messages: list[InboundProviderMessage]) -> WebhookProcessResult:
        processed = 0
        ignored = 0
        unmatched = 0
        responses: list[dict[str, Any]] = []

        for message in messages:
            if not message.text:
                ignored += 1
                continue

            resolved_household = self._resolve_household(message)
            if resolved_household is None:
                unmatched += 1
                self.audit_service.log(
                    "system",
                    "channel.identity_missing",
                    message.user_handle,
                    {
                        "channel": message.channel.value,
                        "user_handle": message.user_handle,
                        "message": message.text,
                    },
                )
                continue

            reply = self.chat_service.handle_event(
                household_id=resolved_household,
                channel=message.channel,
                user_id=message.user_handle,
                message=message.text,
                metadata=message.metadata,
            )
            processed += 1
            responses.append(
                {
                    "household_id": resolved_household,
                    "user_handle": message.user_handle,
                    "channel": message.channel.value,
                    "outbound_text": reply.outbound.text,
                }
            )

        return WebhookProcessResult(
            processed=processed,
            ignored=ignored,
            unmatched=unmatched,
            responses=responses,
        )

    def _resolve_household(self, message: InboundProviderMessage) -> str | None:
        identity = self.identity_key(message.channel, message.user_handle)
        resolved = self.store.channel_identities.get(identity)
        if resolved:
            return resolved

        # Controlled bootstrap: allow first-party explicit self-link command.
        normalized = message.text.strip()
        if normalized.lower().startswith("link "):
            candidate = normalized.split(maxsplit=1)[1].strip()
            if candidate and candidate in self.store.households:
                self.store.channel_identities[identity] = candidate
                if self.relational_persistence is not None:
                    self.relational_persistence.upsert_channel_identity(
                        identity_key=identity,
                        household_id=candidate,
                        channel=message.channel.value,
                        user_handle=message.user_handle,
                    )
                self.audit_service.log(
                    candidate,
                    "channel.identity_linked_via_chat",
                    identity,
                    {"channel": message.channel.value, "user_handle": message.user_handle},
                )
                return candidate

        return None

    @staticmethod
    def _whatsapp_text(message: dict[str, Any]) -> str:
        message_type = message.get("type")
        if message_type == "text":
            return str(message.get("text", {}).get("body") or "").strip()

        if message_type == "interactive":
            interactive = message.get("interactive", {})
            button_reply = interactive.get("button_reply", {})
            list_reply = interactive.get("list_reply", {})
            text = button_reply.get("title") or list_reply.get("title") or list_reply.get("description")
            return str(text or "").strip()

        return ""
