from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from nivvi.domain.models import ActionStatus, Direction
from nivvi.services.forecast_service import ForecastService
from nivvi.services.policy_service import PolicyService
from nivvi.services.timeline_service import TimelineService
from nivvi.services.utils import utc_now
from nivvi.storage.in_memory import InMemoryStore


class DashboardService:
    def __init__(
        self,
        store: InMemoryStore,
        forecast_service: ForecastService,
        timeline_service: TimelineService,
        policy_service: PolicyService | None = None,
    ) -> None:
        self.store = store
        self.forecast_service = forecast_service
        self.timeline_service = timeline_service
        self.policy_service = policy_service

    def today(self, household_id: str) -> dict:
        now = utc_now()
        alerts: list[dict] = []

        forecast = self.forecast_service.forecast(household_id, 30)
        shortfall_point = next((point for point in forecast if "shortfall_risk" in point.risk_flags), None)
        if shortfall_point:
            alerts.append(
                {
                    "type": "cashflow_shortfall",
                    "title": "Potential shortfall detected",
                    "date": shortfall_point.date.isoformat(),
                    "p10_balance": shortfall_point.p10_balance,
                }
            )

        deadlines = self.timeline_service.timeline(household_id, 14)
        for deadline in deadlines[:3]:
            alerts.append(
                {
                    "type": "deadline",
                    "title": deadline.title,
                    "due_at": deadline.due_at.isoformat(),
                    "penalty_risk": deadline.penalty_risk,
                }
            )

        pending_actions = [
            action
            for action in self.store.actions.values()
            if action.household_id == household_id
            and action.status in {ActionStatus.DRAFT, ActionStatus.PENDING_AUTHORIZATION, ActionStatus.APPROVED}
        ]

        intervention_kinds = {"expense_shock", "income_shock", "weekly_plan_drift"}
        interventions = [
            message
            for message in self.store.chat_messages
            if message.household_id == household_id
            and message.sender == "agent"
            and message.metadata.get("kind") in intervention_kinds
            and message.created_at >= (now - timedelta(days=7))
        ]
        interventions = sorted(interventions, key=lambda item: item.created_at, reverse=True)[:5]

        return {
            "date": now.isoformat(),
            "alerts": alerts,
            "agent_interventions": [
                {
                    "id": item.id,
                    "kind": item.metadata.get("kind"),
                    "text": item.text,
                    "action_id": item.metadata.get("action_id"),
                    "created_at": item.created_at.isoformat(),
                }
                for item in interventions
            ],
            "pending_actions": [
                {
                    "id": action.id,
                    "action_type": action.action_type.value,
                    "amount": action.amount,
                    "currency": action.currency,
                    "status": action.status.value,
                    "due_at": action.due_at.isoformat() if action.due_at else None,
                }
                for action in sorted(pending_actions, key=lambda item: item.created_at, reverse=True)
            ],
            "counts": {
                "alerts": len(alerts),
                "pending_actions": len(pending_actions),
                "agent_interventions": len(interventions),
                "overdue_deadlines": len(
                    [
                        deadline
                        for deadline in self.store.deadlines.values()
                        if deadline.household_id == household_id
                        and deadline.due_at < now
                        and deadline.status.value == "pending"
                    ]
                ),
            },
        }

    def planning_insights(self, household_id: str) -> dict:
        now = utc_now()
        settings = self._agent_settings(household_id)
        drift_threshold_ratio = 1.0 + (float(settings["weekly_drift_threshold_percent"]) / 100.0)

        current_start = now - timedelta(days=7)
        baseline_start = now - timedelta(days=35)
        baseline_end = current_start

        current_by_category: dict[str, float] = defaultdict(float)
        baseline_by_category: dict[str, float] = defaultdict(float)

        for tx in self.store.transactions.values():
            if tx.household_id != household_id or tx.direction != Direction.DEBIT:
                continue
            if tx.booked_at >= current_start:
                current_by_category[tx.category] += tx.amount
            elif baseline_start <= tx.booked_at < baseline_end:
                baseline_by_category[tx.category] += tx.amount

        categories = sorted(set(current_by_category.keys()) | set(baseline_by_category.keys()))
        items: list[dict] = []
        for category in categories:
            current_amount = round(current_by_category.get(category, 0.0), 2)
            baseline_weekly = round(baseline_by_category.get(category, 0.0) / 4.0, 2)
            delta = round(current_amount - baseline_weekly, 2)
            ratio = (current_amount / baseline_weekly) if baseline_weekly > 0 else None

            if ratio is None:
                trend = "new_or_unplanned" if current_amount > 0 else "no_recent_activity"
                is_above_threshold = current_amount >= max(
                    200.0,
                    float(settings["weekly_min_delta_amount"]) * 2.0,
                )
            elif ratio >= drift_threshold_ratio:
                trend = "above_baseline"
                is_above_threshold = True
            elif ratio >= 0.8:
                trend = "near_baseline"
                is_above_threshold = False
            else:
                trend = "below_baseline"
                is_above_threshold = False

            items.append(
                {
                    "category": category,
                    "current_7d": current_amount,
                    "baseline_weekly": baseline_weekly,
                    "delta": delta,
                    "delta_pct": round((ratio - 1.0) * 100.0, 1) if ratio is not None else None,
                    "trend": trend,
                    "is_above_threshold": is_above_threshold,
                }
            )

        items.sort(key=lambda item: abs(item["delta"]), reverse=True)
        return {
            "household_id": household_id,
            "window": {"current_days": 7, "baseline_days": 28},
            "threshold_percent": float(settings["weekly_drift_threshold_percent"]),
            "items": items[:8],
            "generated_at": now.isoformat(),
        }

    def _agent_settings(self, household_id: str) -> dict[str, float | int | bool]:
        if self.policy_service is None:
            return dict(PolicyService.AGENT_SETTINGS_DEFAULTS)
        return self.policy_service.resolve_agent_settings(household_id)
