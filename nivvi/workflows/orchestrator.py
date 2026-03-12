from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import median

from nivvi.domain.models import ActionStatus, ActionType, Direction, Transaction
from nivvi.services.action_service import ActionService
from nivvi.services.audit_service import AuditService
from nivvi.services.forecast_service import ForecastService
from nivvi.services.utils import utc_now


class AgentOrchestrator:
    """Runs baseline daily and event-driven recommendation loops."""

    def __init__(
        self,
        forecast_service: ForecastService,
        action_service: ActionService,
        audit_service: AuditService,
    ) -> None:
        self.forecast_service = forecast_service
        self.action_service = action_service
        self.audit_service = audit_service
        self.store = action_service.store

    def run_daily_monitor(self, household_id: str) -> list[str]:
        emitted_actions: list[str] = []
        points = self.forecast_service.forecast(household_id, 30)
        has_open_protection_action = self._has_open_action_for_category(household_id, "cashflow_protection")

        shortfall = next((point for point in points if "shortfall_risk" in point.risk_flags), None)
        if shortfall and not has_open_protection_action:
            amount = abs(shortfall.p10_balance) + 100.0
            proposal = self.action_service.create_proposal(
                household_id=household_id,
                action_type=ActionType.TRANSFER,
                amount=round(amount, 2),
                currency="EUR",
                due_at=utc_now() + timedelta(days=2),
                category="cashflow_protection",
                rationale=[
                    "Forecast p10 balance falls below zero.",
                    "Draft transfer can prevent overdraft/late fee risk.",
                ],
            )
            emitted_actions.append(proposal.id)

        self.audit_service.log(
            household_id,
            "orchestrator.daily_monitor",
            household_id,
            {"actions_emitted": emitted_actions},
        )
        return emitted_actions

    def simulate_loops(
        self,
        household_id: str,
        include_daily_monitor: bool = True,
        include_event_anomaly: bool = True,
        include_weekly_planning: bool = True,
    ) -> dict:
        daily_result = (
            self._simulate_daily_monitor(household_id)
            if include_daily_monitor
            else {"status": "skipped", "would_emit_action": None}
        )
        anomaly_result = (
            self.simulate_event_anomaly_loop(household_id)
            if include_event_anomaly
            else {"status": "skipped", "would_emit_actions": []}
        )
        weekly_result = (
            self.simulate_weekly_planning_loop(household_id)
            if include_weekly_planning
            else {"status": "skipped", "would_emit_action": None}
        )

        would_emit_total = 0
        if daily_result.get("would_emit_action"):
            would_emit_total += 1
        would_emit_total += len(anomaly_result.get("would_emit_actions", []))
        if weekly_result.get("would_emit_action"):
            would_emit_total += 1

        return {
            "household_id": household_id,
            "generated_at": utc_now().isoformat(),
            "daily_monitor": daily_result,
            "event_anomaly": anomaly_result,
            "weekly_planning": weekly_result,
            "would_emit_actions_total": would_emit_total,
        }

    def run_event_anomaly_loop(self, household_id: str) -> dict:
        settings = self._agent_settings(household_id)
        if not settings["anomaly_detection_enabled"]:
            self.audit_service.log(
                household_id,
                "orchestrator.event_anomaly_loop",
                household_id,
                {"status": "disabled", "actions_emitted": []},
            )
            return {
                "status": "disabled",
                "scanned_transactions": 0,
                "anomalies_detected": 0,
                "actions_emitted": [],
                "interventions": [],
            }

        now = utc_now()
        last_scan = self.store.last_anomaly_scan_at.get(household_id, now - timedelta(days=2))
        candidates = sorted(
            [
                tx
                for tx in self.store.transactions.values()
                if tx.household_id == household_id
                and tx.id not in self.store.anomaly_processed_transactions
                and tx.created_at >= last_scan
            ],
            key=lambda item: item.created_at,
        )

        actions_emitted: list[str] = []
        interventions: list[dict] = []
        anomalies: list[dict] = []

        for tx in candidates:
            anomaly = self._classify_transaction_anomaly(household_id, tx, settings)
            self.store.anomaly_processed_transactions.add(tx.id)
            if anomaly is None:
                continue
            anomalies.append(anomaly)

            category = (
                "anomaly_expense_protection"
                if anomaly["kind"] == "expense_shock"
                else "anomaly_income_allocation"
            )
            if self._has_open_action_for_category(household_id, category):
                continue

            action_amount = round(anomaly["recommended_action_amount"], 2)
            due_days = 2 if anomaly["kind"] == "expense_shock" else 3
            proposal = self.action_service.create_proposal(
                household_id=household_id,
                action_type=ActionType.TRANSFER,
                amount=action_amount,
                currency=tx.currency,
                due_at=now + timedelta(days=due_days),
                category=category,
                rationale=[
                    f"Anomalous transaction detected: {tx.description} ({tx.category})",
                    (
                        f"Observed {tx.amount:.2f} {tx.currency} vs historical baseline "
                        f"{anomaly['baseline_amount']:.2f} {tx.currency}"
                    ),
                    (
                        "Drafted protection transfer to preserve runway."
                        if anomaly["kind"] == "expense_shock"
                        else "Drafted allocation transfer to assign income intentionally."
                    ),
                ],
            )
            actions_emitted.append(proposal.id)
            interventions.append(
                {
                    "kind": anomaly["kind"],
                    "transaction_id": tx.id,
                    "action_id": proposal.id,
                    "text": (
                        f"Spending shock: {tx.amount:.2f} {tx.currency} for {tx.category}. "
                        f"I drafted {action_amount:.2f} {tx.currency} to protect your buffer. "
                        f"Reply 'actions' to review."
                        if anomaly["kind"] == "expense_shock"
                        else f"Income shock: {tx.amount:.2f} {tx.currency} received in {tx.category}. "
                        f"I drafted {action_amount:.2f} {tx.currency} allocation to keep goals on track. "
                        f"Reply 'actions' to review."
                    ),
                }
            )

        self.store.last_anomaly_scan_at[household_id] = now
        self.audit_service.log(
            household_id,
            "orchestrator.event_anomaly_loop",
            household_id,
            {
                "status": "completed",
                "scanned_transactions": len(candidates),
                "anomalies_detected": len(anomalies),
                "actions_emitted": actions_emitted,
            },
        )
        return {
            "status": "completed",
            "scanned_transactions": len(candidates),
            "anomalies_detected": len(anomalies),
            "actions_emitted": actions_emitted,
            "interventions": interventions,
        }

    def simulate_event_anomaly_loop(self, household_id: str) -> dict:
        settings = self._agent_settings(household_id)
        if not settings["anomaly_detection_enabled"]:
            return {
                "status": "disabled",
                "scanned_transactions": 0,
                "anomalies_detected": 0,
                "would_emit_actions": [],
            }

        now = utc_now()
        last_scan = self.store.last_anomaly_scan_at.get(household_id, now - timedelta(days=2))
        candidates = sorted(
            [
                tx
                for tx in self.store.transactions.values()
                if tx.household_id == household_id
                and tx.id not in self.store.anomaly_processed_transactions
                and tx.created_at >= last_scan
            ],
            key=lambda item: item.created_at,
        )

        anomalies_detected = 0
        simulated_open_categories = set(self._open_action_categories(household_id))
        would_emit_actions: list[dict] = []

        for tx in candidates:
            anomaly = self._classify_transaction_anomaly(household_id, tx, settings)
            if anomaly is None:
                continue
            anomalies_detected += 1

            category = (
                "anomaly_expense_protection"
                if anomaly["kind"] == "expense_shock"
                else "anomaly_income_allocation"
            )
            if category in simulated_open_categories:
                continue
            simulated_open_categories.add(category)

            action_amount = round(anomaly["recommended_action_amount"], 2)
            due_days = 2 if anomaly["kind"] == "expense_shock" else 3
            would_emit_actions.append(
                {
                    "category": category,
                    "action_type": ActionType.TRANSFER.value,
                    "amount": action_amount,
                    "currency": tx.currency,
                    "due_at": (now + timedelta(days=due_days)).isoformat(),
                    "transaction_id": tx.id,
                    "anomaly_kind": anomaly["kind"],
                    "baseline_amount": anomaly["baseline_amount"],
                    "threshold_amount": anomaly["threshold_amount"],
                    "description": tx.description,
                }
            )

        return {
            "status": "completed",
            "scanned_transactions": len(candidates),
            "anomalies_detected": anomalies_detected,
            "would_emit_actions": would_emit_actions,
        }

    def run_weekly_planning_loop(self, household_id: str) -> dict:
        settings = self._agent_settings(household_id)
        if not settings["weekly_planning_enabled"]:
            self.audit_service.log(
                household_id,
                "orchestrator.weekly_planning_loop",
                household_id,
                {"status": "disabled", "actions_emitted": []},
            )
            return {
                "ran": False,
                "reason": "disabled",
                "actions_emitted": [],
                "interventions": [],
                "drift_categories": [],
            }

        now = utc_now()
        last_run = self.store.last_weekly_planning_at.get(household_id)
        cooldown_days = int(settings["weekly_cooldown_days"])
        if last_run and (now - last_run) < timedelta(days=cooldown_days):
            return {
                "ran": False,
                "reason": "cooldown",
                "actions_emitted": [],
                "interventions": [],
                "drift_categories": [],
            }

        drift_items = self._weekly_drift_items(household_id, settings, now=now)
        min_delta_amount = float(settings["weekly_min_delta_amount"])
        top_drifts = drift_items[:3]
        actions_emitted: list[str] = []
        interventions: list[dict] = []

        if top_drifts:
            total_delta = sum(item["delta"] for item in top_drifts)
            recommendation_amount = round(max(min_delta_amount, total_delta * 0.5), 2)
            if not self._has_open_action_for_category(household_id, "weekly_rebalance"):
                household = self.store.households.get(household_id)
                proposal = self.action_service.create_proposal(
                    household_id=household_id,
                    action_type=ActionType.TRANSFER,
                    amount=recommendation_amount,
                    currency=household.base_currency if household else "EUR",
                    due_at=now + timedelta(days=3),
                    category="weekly_rebalance",
                    rationale=[
                        "Weekly spending drift exceeded baseline.",
                        "Rebalance draft can preserve month-end liquidity.",
                        "Top drift categories: " + ", ".join(item["category"] for item in top_drifts),
                    ],
                )
                actions_emitted.append(proposal.id)
                interventions.append(
                    {
                        "kind": "weekly_plan_drift",
                        "week_key": now.date().isoformat(),
                        "action_id": proposal.id,
                        "text": (
                            "Weekly drift detected: "
                            + "; ".join(
                                f"{item['category']} +{item['delta']:.2f} EUR vs baseline"
                                for item in top_drifts[:2]
                            )
                            + f". I drafted {recommendation_amount:.2f} EUR rebalance. Reply 'actions' to review."
                        ),
                    }
                )

        self.store.last_weekly_planning_at[household_id] = now
        self.audit_service.log(
            household_id,
            "orchestrator.weekly_planning_loop",
            household_id,
            {
                "drift_categories": top_drifts,
                "actions_emitted": actions_emitted,
            },
        )
        return {
            "ran": True,
            "actions_emitted": actions_emitted,
            "interventions": interventions,
            "drift_categories": top_drifts,
        }

    def simulate_weekly_planning_loop(self, household_id: str) -> dict:
        settings = self._agent_settings(household_id)
        if not settings["weekly_planning_enabled"]:
            return {
                "status": "disabled",
                "reason": "disabled",
                "drift_categories": [],
                "would_emit_action": None,
            }

        now = utc_now()
        last_run = self.store.last_weekly_planning_at.get(household_id)
        cooldown_days = int(settings["weekly_cooldown_days"])
        if last_run and (now - last_run) < timedelta(days=cooldown_days):
            return {
                "status": "cooldown",
                "reason": "cooldown",
                "drift_categories": [],
                "would_emit_action": None,
            }

        drift_items = self._weekly_drift_items(household_id, settings, now=now)
        top_drifts = drift_items[:3]
        would_emit_action = None
        min_delta_amount = float(settings["weekly_min_delta_amount"])

        if top_drifts and not self._has_open_action_for_category(household_id, "weekly_rebalance"):
            total_delta = sum(item["delta"] for item in top_drifts)
            recommendation_amount = round(max(min_delta_amount, total_delta * 0.5), 2)
            household = self.store.households.get(household_id)
            would_emit_action = {
                "category": "weekly_rebalance",
                "action_type": ActionType.TRANSFER.value,
                "amount": recommendation_amount,
                "currency": household.base_currency if household else "EUR",
                "due_at": (now + timedelta(days=3)).isoformat(),
            }

        return {
            "status": "completed",
            "drift_categories": top_drifts,
            "would_emit_action": would_emit_action,
        }

    def _classify_transaction_anomaly(
        self,
        household_id: str,
        tx: Transaction,
        settings: dict[str, float | int | bool],
    ) -> dict | None:
        historical_amounts = [
            item.amount
            for item in self.store.transactions.values()
            if item.household_id == household_id
            and item.id != tx.id
            and item.category == tx.category
            and item.direction == tx.direction
            and item.booked_at < tx.booked_at
        ]
        overall_historical_amounts = [
            item.amount
            for item in self.store.transactions.values()
            if item.household_id == household_id
            and item.id != tx.id
            and item.direction == tx.direction
            and item.booked_at < tx.booked_at
        ]
        baseline = median(historical_amounts) if historical_amounts else 0.0
        overall_baseline = median(overall_historical_amounts) if overall_historical_amounts else 0.0

        if tx.direction == Direction.DEBIT:
            expense_multiplier = float(settings["anomaly_expense_multiplier"])
            min_expense_amount = float(settings["anomaly_min_expense_amount"])
            if baseline > 0:
                threshold = max(min_expense_amount, baseline * expense_multiplier)
                baseline_for_message = baseline
            elif overall_baseline > 0:
                threshold = max(min_expense_amount * 1.5, overall_baseline * expense_multiplier * 1.2)
                baseline_for_message = overall_baseline
            else:
                threshold = max(700.0, min_expense_amount)
                baseline_for_message = 0.0
            if tx.amount < threshold:
                return None
            return {
                "kind": "expense_shock",
                "baseline_amount": round(baseline_for_message, 2),
                "threshold_amount": round(threshold, 2),
                "recommended_action_amount": max(50.0, tx.amount * 0.4),
            }

        if tx.direction == Direction.CREDIT:
            income_multiplier = float(settings["anomaly_income_multiplier"])
            min_income_amount = float(settings["anomaly_min_income_amount"])
            if baseline > 0:
                threshold = max(min_income_amount, baseline * income_multiplier)
                baseline_for_message = baseline
            elif overall_baseline > 0:
                threshold = max(min_income_amount * 1.5, overall_baseline * income_multiplier * 1.2)
                baseline_for_message = overall_baseline
            else:
                threshold = max(1500.0, min_income_amount)
                baseline_for_message = 0.0
            if tx.amount < threshold:
                return None
            return {
                "kind": "income_shock",
                "baseline_amount": round(baseline_for_message, 2),
                "threshold_amount": round(threshold, 2),
                "recommended_action_amount": max(50.0, tx.amount * 0.3),
            }
        return None

    def _has_open_action_for_category(self, household_id: str, category: str) -> bool:
        return any(
            action.household_id == household_id
            and action.category == category
            and action.status in {ActionStatus.DRAFT, ActionStatus.PENDING_AUTHORIZATION, ActionStatus.APPROVED}
            for action in self.action_service.list_actions(household_id)
        )

    def _open_action_categories(self, household_id: str) -> set[str]:
        return {
            action.category
            for action in self.action_service.list_actions(household_id)
            if action.status in {ActionStatus.DRAFT, ActionStatus.PENDING_AUTHORIZATION, ActionStatus.APPROVED}
        }

    def _agent_settings(self, household_id: str) -> dict[str, float | int | bool]:
        return self.action_service.policy.resolve_agent_settings(household_id)

    def _simulate_daily_monitor(self, household_id: str) -> dict:
        points = self.forecast_service.forecast(household_id, 30)
        shortfall = next((point for point in points if "shortfall_risk" in point.risk_flags), None)
        if shortfall is None:
            return {"status": "completed", "risk_detected": False, "would_emit_action": None}

        if self._has_open_action_for_category(household_id, "cashflow_protection"):
            return {
                "status": "completed",
                "risk_detected": True,
                "reason": "open_action_exists",
                "would_emit_action": None,
            }

        amount = round(abs(shortfall.p10_balance) + 100.0, 2)
        return {
            "status": "completed",
            "risk_detected": True,
            "would_emit_action": {
                "category": "cashflow_protection",
                "action_type": ActionType.TRANSFER.value,
                "amount": amount,
                "currency": "EUR",
                "due_at": (utc_now() + timedelta(days=2)).isoformat(),
                "shortfall_date": shortfall.date.isoformat(),
                "p10_balance": shortfall.p10_balance,
            },
        }

    def _weekly_drift_items(
        self,
        household_id: str,
        settings: dict[str, float | int | bool],
        now,
    ) -> list[dict]:
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

        drift_items: list[dict] = []
        drift_threshold_ratio = 1.0 + (float(settings["weekly_drift_threshold_percent"]) / 100.0)
        min_delta_amount = float(settings["weekly_min_delta_amount"])
        for category, current_amount in current_by_category.items():
            baseline_weekly = baseline_by_category.get(category, 0.0) / 4.0
            if baseline_weekly > 0:
                if current_amount <= baseline_weekly * drift_threshold_ratio:
                    continue
                delta = current_amount - baseline_weekly
            else:
                if current_amount < max(200.0, min_delta_amount * 2):
                    continue
                delta = current_amount
            if delta < min_delta_amount:
                continue
            drift_items.append(
                {
                    "category": category,
                    "current_amount": round(current_amount, 2),
                    "baseline_weekly": round(baseline_weekly, 2),
                    "delta": round(delta, 2),
                }
            )

        drift_items.sort(key=lambda item: item["delta"], reverse=True)
        return drift_items
