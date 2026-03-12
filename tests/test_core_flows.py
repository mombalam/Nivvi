from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nivvi.domain.models import AccountType, ActionType, Direction, PortfolioRecommendation, TaxPackage
from nivvi.services.action_service import ActionService
from nivvi.services.audit_service import AuditService
from nivvi.services.forecast_service import ForecastService
from nivvi.services.household_service import HouseholdService
from nivvi.services.policy_service import PolicyService
from nivvi.services.timeline_service import TimelineService
from nivvi.storage.in_memory import InMemoryStore
from nivvi.workflows.orchestrator import AgentOrchestrator


def build_services() -> tuple[HouseholdService, ForecastService, ActionService, TimelineService, InMemoryStore]:
    store = InMemoryStore()
    audit = AuditService(store)
    policy = PolicyService(store)
    household = HouseholdService(store, audit)
    forecast = ForecastService(store)
    action = ActionService(store, policy, audit)
    timeline = TimelineService(store)
    return household, forecast, action, timeline, store


def test_two_step_approval_required_before_dispatch() -> None:
    household, _, action_service, _, _ = build_services()
    household.create_or_get_household("h1", "Demo")
    household.connect_account("h1", "ING", AccountType.BANK, "EUR", 2500.0)

    action = action_service.create_proposal(
        household_id="h1",
        action_type=ActionType.TRANSFER,
        amount=200.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="bill_payment",
        rationale=["Test flow"],
    )

    try:
        action_service.dispatch(action.id)
    except ValueError as exc:
        assert "approved" in str(exc)
    else:
        raise AssertionError("Dispatch should fail until approval is complete")

    action_service.approve(action.id, "confirm")
    action_service.approve(action.id, "authorize")
    receipt = action_service.dispatch(action.id, idempotency_key="test_1")
    assert receipt.result == "success"


def test_policy_violations_are_recorded() -> None:
    household, _, action_service, _, store = build_services()
    household.create_or_get_household("h2", "Demo")
    household.connect_account("h2", "ING", AccountType.BANK, "EUR", 5000.0)
    household.add_rule(
        household_id="h2",
        scope="global",
        daily_amount_limit=1000.0,
        max_single_action=300.0,
        blocked_categories=["gambling"],
        blocked_action_types=[],
        require_approval_always=True,
    )

    action = action_service.create_proposal(
        household_id="h2",
        action_type=ActionType.TRANSFER,
        amount=500.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="gambling",
        rationale=["Should violate"],
    )

    assert any("max_single_action" in msg for msg in action.violations)
    assert any("blocked" in msg for msg in action.violations)
    assert store.actions[action.id].violations == action.violations


def test_forecast_includes_shortfall_flag_for_negative_trend() -> None:
    household, forecast_service, _, _, _ = build_services()
    household.create_or_get_household("h3", "Demo")
    account = household.connect_account("h3", "ING", AccountType.BANK, "EUR", 300.0)

    for day in range(1, 12):
        household.import_transaction(
            household_id="h3",
            account_id=account.id,
            amount=120.0,
            currency="EUR",
            direction=Direction.DEBIT,
            description="Recurring spend",
            category="living",
            booked_at=datetime.now(timezone.utc) - timedelta(days=day),
        )

    points = forecast_service.forecast("h3", 30)
    assert points
    assert any("shortfall_risk" in point.risk_flags for point in points)


def test_timeline_includes_nl_tax_guard_deadline() -> None:
    household, _, _, timeline_service, _ = build_services()
    household.create_or_get_household("h4", "Demo")

    timeline = timeline_service.timeline("h4", 500)
    assert any(item.source == "nl_tax_guard" for item in timeline)


def test_dispatch_idempotent_replay_and_key_collision() -> None:
    household, _, action_service, _, _ = build_services()
    household.create_or_get_household("h5", "Demo")
    household.connect_account("h5", "ING", AccountType.BANK, "EUR", 4200.0)

    first_action = action_service.create_proposal(
        household_id="h5",
        action_type=ActionType.TRANSFER,
        amount=320.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="bill_payment",
        rationale=["idempotency replay"],
    )
    action_service.approve(first_action.id, "confirm")
    action_service.approve(first_action.id, "authorize")

    first_receipt = action_service.dispatch(first_action.id, idempotency_key="dispatch_1")
    replay_receipt = action_service.dispatch(first_action.id, idempotency_key="dispatch_1")
    assert replay_receipt.partner_ref == first_receipt.partner_ref
    assert replay_receipt.result == first_receipt.result

    second_action = action_service.create_proposal(
        household_id="h5",
        action_type=ActionType.TRANSFER,
        amount=210.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=2),
        category="bill_payment",
        rationale=["idempotency conflict"],
    )
    action_service.approve(second_action.id, "confirm")
    action_service.approve(second_action.id, "authorize")

    with pytest.raises(ValueError, match="already used for another action"):
        action_service.dispatch(second_action.id, idempotency_key="dispatch_1")


def test_failed_dispatch_retry_requires_key_and_allows_safe_retry() -> None:
    household, _, action_service, _, _ = build_services()
    household.create_or_get_household("h6", "Demo")
    household.connect_account("h6", "ING", AccountType.BANK, "EUR", 250000.0)

    action = action_service.create_proposal(
        household_id="h6",
        action_type=ActionType.TRANSFER,
        amount=150000.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="bill_payment",
        rationale=["simulate partner failure and retry"],
    )
    action_service.approve(action.id, "confirm")
    action_service.approve(action.id, "authorize")

    first_failure = action_service.dispatch(action.id, idempotency_key="fail_try_1")
    assert first_failure.result == "failed"

    with pytest.raises(ValueError, match="requires idempotency_key"):
        action_service.dispatch(action.id)

    replay_failure = action_service.dispatch(action.id, idempotency_key="fail_try_1")
    assert replay_failure.partner_ref == first_failure.partner_ref

    second_failure = action_service.dispatch(action.id, idempotency_key="fail_try_2")
    assert second_failure.result == "failed"
    assert second_failure.partner_ref != first_failure.partner_ref


def test_invest_dispatch_blocked_by_suitability_gate() -> None:
    household, _, action_service, _, store = build_services()
    household.create_or_get_household("h7", "Demo")
    household.connect_account("h7", "ING", AccountType.BANK, "EUR", 5000.0)
    store.portfolio_recommendations["h7"] = PortfolioRecommendation(
        household_id="h7",
        model_id="balanced_v1",
        target_alloc={"equity": 0.6, "bond": 0.4},
        delta_orders=[{"ticker": "VWCE", "amount": 200.0}],
        suitability_flags=["non_compliant_risk_profile"],
    )

    action = action_service.create_proposal(
        household_id="h7",
        action_type=ActionType.INVEST,
        amount=200.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="goal_investing",
        rationale=["invest gate coverage"],
    )
    action_service.approve(action.id, "confirm")
    action_service.approve(action.id, "authorize")

    with pytest.raises(ValueError, match="suitability gate failed"):
        action_service.dispatch(action.id, idempotency_key="invest_gate_1")


def test_tax_submission_dispatch_blocked_until_package_complete() -> None:
    household, _, action_service, _, store = build_services()
    household.create_or_get_household("h8", "Demo")
    household.connect_account("h8", "ING", AccountType.BANK, "EUR", 5000.0)
    store.tax_packages["h8"] = TaxPackage(
        household_id="h8",
        jurisdiction="NL",
        forms=["M-form"],
        inputs={"year": "2025"},
        missing_items=["Annual income statement"],
        submission_mode="partner_one_click_submit",
    )

    action = action_service.create_proposal(
        household_id="h8",
        action_type=ActionType.TAX_SUBMISSION,
        amount=100.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="tax_filing",
        rationale=["tax completeness gate coverage"],
    )
    action_service.approve(action.id, "confirm")
    action_service.approve(action.id, "authorize")

    with pytest.raises(ValueError, match="Tax package is incomplete"):
        action_service.dispatch(action.id, idempotency_key="tax_gate_1")

    store.tax_packages["h8"] = TaxPackage(
        household_id="h8",
        jurisdiction="NL",
        forms=["M-form"],
        inputs={"year": "2025"},
        missing_items=[],
        submission_mode="partner_one_click_submit",
    )
    receipt = action_service.dispatch(action.id, idempotency_key="tax_gate_2")
    assert receipt.result == "success"


def test_anomaly_loop_can_be_disabled_via_rule() -> None:
    household, forecast_service, action_service, _, store = build_services()
    audit = AuditService(store)
    orchestrator = AgentOrchestrator(forecast_service, action_service, audit)

    household.create_or_get_household("h9", "Demo")
    account = household.connect_account("h9", "ING", AccountType.BANK, "EUR", 5000.0)
    household.add_rule(
        household_id="h9",
        scope="global",
        daily_amount_limit=None,
        max_single_action=None,
        blocked_categories=[],
        blocked_action_types=[],
        require_approval_always=True,
        anomaly_detection_enabled=False,
    )

    household.import_transaction(
        household_id="h9",
        account_id=account.id,
        amount=1000.0,
        currency="EUR",
        direction=Direction.DEBIT,
        description="Unexpected maintenance",
        category="housing",
        booked_at=datetime.now(timezone.utc),
    )

    result = orchestrator.run_event_anomaly_loop("h9")
    assert result["status"] == "disabled"
    assert result["actions_emitted"] == []


def test_weekly_drift_threshold_respects_rule_configuration() -> None:
    household, forecast_service, action_service, _, store = build_services()
    audit = AuditService(store)
    orchestrator = AgentOrchestrator(forecast_service, action_service, audit)

    household.create_or_get_household("h10", "Demo")
    account = household.connect_account("h10", "ING", AccountType.BANK, "EUR", 5000.0)
    household.add_rule(
        household_id="h10",
        scope="global",
        daily_amount_limit=None,
        max_single_action=None,
        blocked_categories=[],
        blocked_action_types=[],
        require_approval_always=True,
        weekly_drift_threshold_percent=200.0,
        weekly_min_delta_amount=50.0,
    )

    for days_ago in [30, 26, 22, 18]:
        household.import_transaction(
            household_id="h10",
            account_id=account.id,
            amount=50.0,
            currency="EUR",
            direction=Direction.DEBIT,
            description="Dining baseline",
            category="dining",
            booked_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )

    for days_ago in [3, 2]:
        household.import_transaction(
            household_id="h10",
            account_id=account.id,
            amount=70.0,
            currency="EUR",
            direction=Direction.DEBIT,
            description="Dining higher spend",
            category="dining",
            booked_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )

    result = orchestrator.run_weekly_planning_loop("h10")
    assert result["ran"] is True
    assert result["actions_emitted"] == []


def test_rule_upsert_versions_and_policy_uses_active_rule_only() -> None:
    household, _, action_service, _, store = build_services()
    household.create_or_get_household("h11", "Demo")
    household.connect_account("h11", "ING", AccountType.BANK, "EUR", 5000.0)

    first_rule = household.add_rule(
        household_id="h11",
        scope="global",
        daily_amount_limit=None,
        max_single_action=None,
        blocked_categories=["gambling"],
        blocked_action_types=[],
        require_approval_always=True,
    )
    second_rule = household.add_rule(
        household_id="h11",
        scope="global",
        daily_amount_limit=None,
        max_single_action=None,
        blocked_categories=[],
        blocked_action_types=[],
        require_approval_always=True,
    )

    assert first_rule.version == 1
    assert first_rule.is_active is False
    assert first_rule.superseded_by_rule_id == second_rule.rule_id
    assert second_rule.version == 2
    assert second_rule.is_active is True
    assert len(store.rules["h11"]) == 2

    action = action_service.create_proposal(
        household_id="h11",
        action_type=ActionType.TRANSFER,
        amount=120.0,
        currency="EUR",
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        category="gambling",
        rationale=["active rule should decide"],
    )
    assert not any("blocked" in violation for violation in action.violations)
