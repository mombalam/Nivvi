from __future__ import annotations

from datetime import datetime

from nivvi.domain.models import ActionProposal, ActionStatus, ActionType, UserRule
from nivvi.storage.in_memory import InMemoryStore


class PolicyService:
    AGENT_SETTINGS_DEFAULTS = {
        "anomaly_detection_enabled": True,
        "anomaly_expense_multiplier": 1.75,
        "anomaly_income_multiplier": 2.0,
        "anomaly_min_expense_amount": 150.0,
        "anomaly_min_income_amount": 300.0,
        "weekly_planning_enabled": True,
        "weekly_drift_threshold_percent": 20.0,
        "weekly_min_delta_amount": 50.0,
        "weekly_cooldown_days": 6,
    }

    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def validate_action(self, proposal: ActionProposal) -> list[str]:
        violations: list[str] = []
        rules = self.active_rules(proposal.household_id)

        for rule in rules:
            if rule.max_single_action is not None and proposal.amount > rule.max_single_action:
                violations.append(
                    f"Action exceeds max_single_action ({rule.max_single_action:.2f} {proposal.currency})"
                )

            if rule.daily_amount_limit is not None:
                same_day_total = self._same_day_approved_total(
                    household_id=proposal.household_id,
                    date=proposal.created_at,
                    ignore_action_id=proposal.id,
                )
                if same_day_total + proposal.amount > rule.daily_amount_limit:
                    violations.append(
                        f"Action exceeds daily_amount_limit ({rule.daily_amount_limit:.2f} {proposal.currency})"
                    )

            if proposal.category in rule.blocked_categories:
                violations.append(f"Category '{proposal.category}' is blocked by rule {rule.rule_id}")

            if proposal.action_type in rule.blocked_action_types:
                violations.append(
                    f"Action type '{proposal.action_type.value}' is blocked by rule {rule.rule_id}"
                )

        return violations

    def _same_day_approved_total(self, household_id: str, date: datetime, ignore_action_id: str) -> float:
        total = 0.0
        for action in self.store.actions.values():
            if action.household_id != household_id:
                continue
            if action.id == ignore_action_id:
                continue
            if action.status not in {ActionStatus.APPROVED, ActionStatus.DISPATCHED}:
                continue
            if action.created_at.date() != date.date():
                continue
            total += action.amount
        return total

    def requires_approval(self, household_id: str, action_type: ActionType) -> bool:
        # Current product policy enforces explicit approval per action type.
        return True

    def active_rules(self, household_id: str) -> list[UserRule]:
        rules = [rule for rule in self.store.rules.get(household_id, []) if rule.is_active]
        if not rules:
            return []

        # Deterministic resolution: keep highest-version active rule per scope.
        by_scope: dict[str, UserRule] = {}
        for rule in rules:
            existing = by_scope.get(rule.scope)
            if existing is None or (rule.version, rule.created_at) > (existing.version, existing.created_at):
                by_scope[rule.scope] = rule

        return sorted(by_scope.values(), key=lambda item: (item.scope, item.version, item.created_at))

    def resolve_agent_settings(self, household_id: str) -> dict[str, float | int | bool]:
        settings: dict[str, float | int | bool] = dict(self.AGENT_SETTINGS_DEFAULTS)
        rules = self.active_rules(household_id)

        global_rule = next((rule for rule in reversed(rules) if rule.scope == "global"), None)
        if global_rule:
            settings.update(self._agent_settings_from_rule(global_rule))

        scoped_rules = [rule for rule in rules if rule.scope != "global"]
        for rule in scoped_rules:
            settings.update(self._agent_settings_from_rule(rule))

        return settings

    @staticmethod
    def _agent_settings_from_rule(rule: UserRule) -> dict[str, float | int | bool]:
        return {
            "anomaly_detection_enabled": rule.anomaly_detection_enabled,
            "anomaly_expense_multiplier": rule.anomaly_expense_multiplier,
            "anomaly_income_multiplier": rule.anomaly_income_multiplier,
            "anomaly_min_expense_amount": rule.anomaly_min_expense_amount,
            "anomaly_min_income_amount": rule.anomaly_min_income_amount,
            "weekly_planning_enabled": rule.weekly_planning_enabled,
            "weekly_drift_threshold_percent": rule.weekly_drift_threshold_percent,
            "weekly_min_delta_amount": rule.weekly_min_delta_amount,
            "weekly_cooldown_days": rule.weekly_cooldown_days,
        }
