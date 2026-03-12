from __future__ import annotations

from datetime import datetime, timedelta

from nivvi.domain.models import (
    AccountType,
    ExecutionAttempt,
    ActionPreview,
    ActionProposal,
    ActionStatus,
    ActionType,
    ExecutionReceipt,
)
from nivvi.services.audit_service import AuditService
from nivvi.services.policy_service import PolicyService
from nivvi.services.provider_service import ProviderService
from nivvi.services.utils import as_utc, generate_id, utc_now
from nivvi.storage.in_memory import InMemoryStore
from nivvi.storage.relational_persistence import RelationalPersistence


class ActionService:
    def __init__(
        self,
        store: InMemoryStore,
        policy: PolicyService,
        audit: AuditService,
        provider_service: ProviderService | None = None,
        relational_persistence: RelationalPersistence | None = None,
    ) -> None:
        self.store = store
        self.policy = policy
        self.audit = audit
        self.provider_service = provider_service
        self.relational_persistence = relational_persistence

    def create_proposal(
        self,
        household_id: str,
        action_type: ActionType,
        amount: float,
        currency: str,
        due_at: datetime | None,
        category: str,
        rationale: list[str],
    ) -> ActionProposal:
        proposal = ActionProposal(
            id=generate_id("act"),
            household_id=household_id,
            action_type=action_type,
            amount=amount,
            currency=currency,
            due_at=as_utc(due_at) if due_at else None,
            category=category,
            rationale=rationale,
            risk_score=self._risk_score(household_id, amount),
            requires_approval=self.policy.requires_approval(household_id, action_type),
        )

        violations = self.policy.validate_action(proposal)
        proposal.violations = violations
        proposal.updated_at = utc_now()

        self.store.actions[proposal.id] = proposal
        self._persist_action(proposal)
        self.audit.log(
            household_id,
            "action.proposed",
            proposal.id,
            {
                "action_type": action_type.value,
                "amount": amount,
                "currency": currency,
                "risk_score": proposal.risk_score,
                "violations": violations,
            },
        )
        return proposal

    def preview(self, action_id: str) -> ActionPreview:
        action = self.store.actions[action_id]
        liquid_balance = self._liquid_balance(action.household_id)

        projected = liquid_balance - action.amount
        fee_impact = round(max(action.amount * 0.0025, 0), 2)

        deadline_impact = "neutral"
        if action.due_at and action.due_at <= (utc_now() + timedelta(days=7)):
            deadline_impact = "reduces_near_term_deadline_risk"

        goal_impact = "supports_goal" if action.action_type == ActionType.INVEST else "supports_cashflow_stability"

        preview = ActionPreview(
            action_id=action_id,
            projected_balance_after=round(projected, 2),
            fee_impact=fee_impact,
            goal_impact=goal_impact,
            deadline_impact=deadline_impact,
            notes=[
                "Includes conservative fee estimate.",
                "Projection assumes no additional unplanned transactions.",
            ],
        )
        return preview

    def approve(self, action_id: str, step: str) -> ActionProposal:
        action = self.store.actions[action_id]
        if action.status in {ActionStatus.REJECTED, ActionStatus.DISPATCHED}:
            raise ValueError(f"Cannot approve action in state {action.status.value}")

        if step == "confirm":
            action.approval_step = max(action.approval_step, 1)
            action.status = ActionStatus.PENDING_AUTHORIZATION
        elif step == "authorize":
            if action.approval_step < 1:
                raise ValueError("Action must be confirmed before authorization")
            action.approval_step = 2
            action.status = ActionStatus.APPROVED
        else:
            raise ValueError("step must be one of: confirm, authorize")

        action.updated_at = utc_now()
        self.audit.log(
            action.household_id,
            "action.approved_step",
            action.id,
            {"step": step, "approval_step": action.approval_step, "status": action.status.value},
        )
        self._persist_action(action)
        self._persist_approval(action, step)
        return action

    def reject(self, action_id: str, reason: str | None = None) -> ActionProposal:
        action = self.store.actions[action_id]
        action.status = ActionStatus.REJECTED
        action.updated_at = utc_now()
        self._persist_action(action)
        self.audit.log(
            action.household_id,
            "action.rejected",
            action.id,
            {"reason": reason or "No reason provided"},
        )
        return action

    def dispatch(self, action_id: str, idempotency_key: str | None = None) -> ExecutionReceipt:
        action = self.store.actions[action_id]
        normalized_key = self._normalize_idempotency_key(idempotency_key)
        existing_receipt = self.store.executions.get(action.id)
        existing_action_for_key = (
            self.store.execution_idempotency_keys.get(normalized_key) if normalized_key else None
        )

        if existing_action_for_key and existing_action_for_key != action.id:
            raise ValueError("Idempotency key already used for another action")

        if existing_action_for_key == action.id and existing_receipt is not None:
            self.audit.log(
                action.household_id,
                "execution.idempotent_replay",
                action.id,
                {
                    "idempotency_key": normalized_key,
                    "partner_ref": existing_receipt.partner_ref,
                    "result": existing_receipt.result,
                },
            )
            return existing_receipt

        if action.status == ActionStatus.DISPATCHED:
            raise ValueError("Action has already been dispatched")
        if action.status == ActionStatus.FAILED and normalized_key is None:
            raise ValueError("Retrying failed dispatch requires idempotency_key")
        if action.status not in {ActionStatus.APPROVED, ActionStatus.FAILED}:
            raise ValueError("Action must be approved before dispatch")

        previous_status = action.status

        if self.provider_service and not self.provider_service.is_execution_enabled(action.action_type):
            raise ValueError(f"Execution disabled for action type '{action.action_type.value}'")

        violations = self.policy.validate_action(action)
        if violations:
            raise ValueError("Policy check failed before dispatch: " + "; ".join(violations))

        readiness_violations = self._execution_readiness_violations(action)
        if readiness_violations:
            self.audit.log(
                action.household_id,
                "execution.blocked",
                action.id,
                {
                    "action_type": action.action_type.value,
                    "reasons": readiness_violations,
                },
            )
            raise ValueError("Execution readiness check failed: " + "; ".join(readiness_violations))

        provider_name: str | None = None
        fallback_used = False
        provider_attempts: list[str] = []
        if self.provider_service:
            dispatch_result = self.provider_service.dispatch_action(
                household_id=action.household_id,
                action=action,
                idempotency_key=normalized_key,
            )
            partner_ref = dispatch_result.partner_ref
            result = dispatch_result.result
            message = dispatch_result.message
            provider_name = dispatch_result.provider_name
            fallback_used = dispatch_result.fallback_used
            provider_attempts = dispatch_result.provider_attempts or []
        else:
            partner_ref = f"partner_{normalized_key or generate_id('exec')}"
            result = "success"
            message = "Dispatched to partner rail"
            if action.amount >= 100_000:
                result = "failed"
                message = "Amount exceeds partner sandbox threshold"

        if result == "success":
            action.status = ActionStatus.DISPATCHED
        else:
            action.status = ActionStatus.FAILED

        action.updated_at = utc_now()

        receipt = ExecutionReceipt(
            action_id=action.id,
            partner_ref=partner_ref,
            submitted_at=utc_now(),
            result=result,
            reversible_until=utc_now() + timedelta(hours=24) if result == "success" else None,
            message=message,
            provider_name=provider_name,
            fallback_used=fallback_used,
            provider_attempts=provider_attempts,
        )
        self.store.executions[action.id] = receipt
        attempt = ExecutionAttempt(
            action_id=action.id,
            attempt_number=len(self.store.execution_attempts[action.id]) + 1,
            idempotency_key=normalized_key,
            partner_ref=partner_ref,
            result=result,
            message=message,
            status_before=previous_status,
            status_after=action.status,
            provider_name=provider_name,
        )
        self.store.execution_attempts[action.id].append(attempt)
        self._persist_action(action)
        self._persist_execution(action, receipt)
        self._persist_execution_attempt(action, attempt)
        if normalized_key:
            self.store.execution_idempotency_keys[normalized_key] = action.id
        self.audit.log(
            action.household_id,
            "execution.dispatched",
            action.id,
            {
                "partner_ref": partner_ref,
                "result": result,
                "message": message,
                "attempt": "retry" if previous_status == ActionStatus.FAILED else "initial",
                "idempotency_key": normalized_key,
                "provider_name": provider_name,
                "fallback_used": fallback_used,
                "provider_attempts": provider_attempts,
            },
        )
        return receipt

    def retry_dispatch(
        self,
        action_id: str,
        idempotency_key: str,
        retry_reason: str | None = None,
    ) -> ExecutionReceipt:
        action = self.store.actions[action_id]
        if action.status != ActionStatus.FAILED:
            raise ValueError("Retry endpoint only supports actions in failed state")

        receipt = self.dispatch(action_id, idempotency_key=idempotency_key)
        self.audit.log(
            action.household_id,
            "execution.retry_requested",
            action.id,
            {
                "idempotency_key": self._normalize_idempotency_key(idempotency_key),
                "retry_reason": retry_reason or "No reason provided",
                "result": receipt.result,
            },
        )
        return receipt

    def list_actions(self, household_id: str | None = None) -> list[ActionProposal]:
        if household_id is None:
            return list(self.store.actions.values())
        return [action for action in self.store.actions.values() if action.household_id == household_id]

    def get_execution(self, action_id: str) -> ExecutionReceipt | None:
        return self.store.executions.get(action_id)

    def list_execution_attempts(self, action_id: str) -> list[ExecutionAttempt]:
        attempts = self.store.execution_attempts.get(action_id, [])
        return sorted(attempts, key=lambda item: item.attempt_number)

    def _liquid_balance(self, household_id: str) -> float:
        balance = 0.0
        for account in self.store.accounts.values():
            if account.household_id != household_id:
                continue
            if account.account_type not in {AccountType.BANK, AccountType.CARD}:
                continue
            balance += account.balance
        return balance

    def _risk_score(self, household_id: str, amount: float) -> float:
        liquid = max(self._liquid_balance(household_id), 1.0)
        ratio = amount / liquid
        return round(min(1.0, max(0.0, ratio)), 3)

    def _execution_readiness_violations(self, action: ActionProposal) -> list[str]:
        violations: list[str] = []

        if action.action_type == ActionType.INVEST:
            recommendation = self.store.portfolio_recommendations.get(action.household_id)
            if recommendation is None:
                violations.append("No portfolio recommendation is available for this household")
                return violations

            suitability_blockers = self._suitability_blockers(recommendation.suitability_flags)
            if suitability_blockers:
                violations.append(
                    "Investment suitability gate failed: " + ", ".join(suitability_blockers)
                )

        if action.action_type == ActionType.TAX_SUBMISSION:
            package = self.store.tax_packages.get(action.household_id)
            if package is None:
                violations.append("Tax package has not been prepared")
                return violations

            missing_items = [item.strip() for item in package.missing_items if item.strip()]
            if missing_items:
                violations.append("Tax package is incomplete: " + ", ".join(missing_items))

        return violations

    @staticmethod
    def _suitability_blockers(flags: list[str]) -> list[str]:
        blockers: list[str] = []
        for raw_flag in flags:
            normalized = raw_flag.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered.startswith(("info:", "note:", "warn:")):
                continue
            if any(
                token in lowered
                for token in (
                    "non_compliant",
                    "unsuitable",
                    "ineligible",
                    "restricted",
                    "block",
                    "fail",
                )
            ):
                blockers.append(normalized)
        return blockers

    @staticmethod
    def _normalize_idempotency_key(idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        normalized = idempotency_key.strip()
        return normalized or None

    def _persist_action(self, action: ActionProposal) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_action(action)

    def _persist_approval(self, action: ActionProposal, step: str) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.record_approval(
            approval_id=generate_id("apr"),
            action_id=action.id,
            household_id=action.household_id,
            step=step,
            approval_step=action.approval_step,
            status=action.status.value,
            actor_user_id=None,
            created_at=utc_now(),
        )

    def _persist_execution(self, action: ActionProposal, receipt: ExecutionReceipt) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_execution(action.household_id, receipt)

    def _persist_execution_attempt(self, action: ActionProposal, attempt: ExecutionAttempt) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.append_execution_attempt(
            attempt_id=generate_id("eat"),
            household_id=action.household_id,
            attempt=attempt,
        )
