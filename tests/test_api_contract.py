from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from nivvi.main import app


client = TestClient(app)


def test_http_flow_connect_import_approve_dispatch() -> None:
    household_id = f"h_{uuid4().hex[:8]}"

    connect = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "API Test Household",
            "accounts": [
                {
                    "institution": "ING",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 4200,
                    "metadata": {},
                }
            ],
        },
    )
    assert connect.status_code == 200
    account_id = connect.json()["account_ids"][0]

    imported = client.post(
        "/v1/providers/ingest",
        json={
            "household_id": household_id,
            "transactions": [
                {
                    "account_id": account_id,
                    "amount": 1450,
                    "currency": "EUR",
                    "direction": "debit",
                    "description": "Rent",
                    "category": "housing",
                    "booked_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                }
            ],
            "deadlines": [
                {
                    "source": "utility",
                    "title": "Energy bill",
                    "jurisdiction": "NL",
                    "due_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
                    "penalty_risk": "medium",
                    "amount": 120,
                }
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["transactions_ingested"] == 1

    rule = client.post(
        "/v1/rules",
        json={
            "household_id": household_id,
            "scope": "global",
            "daily_amount_limit": 3000,
            "max_single_action": 2000,
            "blocked_categories": ["gambling"],
            "blocked_action_types": [],
            "require_approval_always": True,
            "anomaly_detection_enabled": True,
            "anomaly_expense_multiplier": 1.9,
            "anomaly_income_multiplier": 2.2,
            "anomaly_min_expense_amount": 180,
            "anomaly_min_income_amount": 360,
            "weekly_planning_enabled": True,
            "weekly_drift_threshold_percent": 25,
            "weekly_min_delta_amount": 65,
            "weekly_cooldown_days": 5,
        },
    )
    assert rule.status_code == 200
    rule_payload = rule.json()
    assert rule_payload["anomaly_expense_multiplier"] == 1.9
    assert rule_payload["weekly_cooldown_days"] == 5

    action = client.post(
        "/v1/actions/proposals",
        json={
            "household_id": household_id,
            "action_type": "transfer",
            "amount": 400,
            "currency": "EUR",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "category": "bill_payment",
            "rationale": ["deadline protection"],
        },
    )
    assert action.status_code == 200
    action_id = action.json()["id"]

    preview = client.get(f"/v1/actions/{action_id}/preview")
    assert preview.status_code == 200
    assert "projected_balance_after" in preview.json()

    confirm = client.post(f"/v1/actions/{action_id}/approve", json={"step": "confirm"})
    assert confirm.status_code == 200
    authorize = client.post(f"/v1/actions/{action_id}/approve", json={"step": "authorize"})
    assert authorize.status_code == 200

    idempotency_key = f"test_{uuid4().hex[:8]}"

    dispatch = client.post(
        f"/v1/executions/{action_id}/dispatch",
        json={"idempotency_key": idempotency_key},
    )
    assert dispatch.status_code == 200
    assert dispatch.json()["result"] == "success"
    partner_ref = dispatch.json()["partner_ref"]

    replay = client.post(
        f"/v1/executions/{action_id}/dispatch",
        json={"idempotency_key": idempotency_key},
    )
    assert replay.status_code == 200
    assert replay.json()["partner_ref"] == partner_ref

    execution_state = client.get(f"/v1/executions/{action_id}")
    assert execution_state.status_code == 200
    assert execution_state.json()["latest"]["partner_ref"] == partner_ref
    assert len(execution_state.json()["attempts"]) == 1

    another_action = client.post(
        "/v1/actions/proposals",
        json={
            "household_id": household_id,
            "action_type": "transfer",
            "amount": 300,
            "currency": "EUR",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "category": "bill_payment",
            "rationale": ["idempotency conflict check"],
        },
    )
    assert another_action.status_code == 200
    another_action_id = another_action.json()["id"]
    assert client.post(f"/v1/actions/{another_action_id}/approve", json={"step": "confirm"}).status_code == 200
    assert client.post(f"/v1/actions/{another_action_id}/approve", json={"step": "authorize"}).status_code == 200

    idempotency_conflict = client.post(
        f"/v1/executions/{another_action_id}/dispatch",
        json={"idempotency_key": idempotency_key},
    )
    assert idempotency_conflict.status_code == 400
    assert "already used for another action" in idempotency_conflict.json()["detail"]

    audit = client.get(f"/v1/audit/events?household_id={household_id}")
    assert audit.status_code == 200
    event_types = [event["event_type"] for event in audit.json()["events"]]
    assert "execution.dispatched" in event_types


def test_failed_execution_retry_endpoint_and_attempt_history() -> None:
    household_id = f"h_{uuid4().hex[:8]}"

    connect = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "API Retry Household",
            "accounts": [
                {
                    "institution": "ING",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 250000,
                    "metadata": {},
                }
            ],
        },
    )
    assert connect.status_code == 200

    action = client.post(
        "/v1/actions/proposals",
        json={
            "household_id": household_id,
            "action_type": "transfer",
            "amount": 120000,
            "currency": "EUR",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "category": "bill_payment",
            "rationale": ["retry endpoint contract"],
        },
    )
    assert action.status_code == 200
    action_id = action.json()["id"]
    assert client.post(f"/v1/actions/{action_id}/approve", json={"step": "confirm"}).status_code == 200
    assert client.post(f"/v1/actions/{action_id}/approve", json={"step": "authorize"}).status_code == 200

    failed_dispatch = client.post(
        f"/v1/executions/{action_id}/dispatch",
        json={"idempotency_key": "retry_a"},
    )
    assert failed_dispatch.status_code == 200
    assert failed_dispatch.json()["result"] == "failed"
    first_partner_ref = failed_dispatch.json()["partner_ref"]

    invalid_retry = client.post(
        f"/v1/executions/{action_id}/retry",
        json={"idempotency_key": "   ", "retry_reason": "empty key should fail"},
    )
    assert invalid_retry.status_code == 422

    retry = client.post(
        f"/v1/executions/{action_id}/retry",
        json={"idempotency_key": "retry_b", "retry_reason": "partner timeout"},
    )
    assert retry.status_code == 200
    assert retry.json()["result"] == "failed"
    assert retry.json()["partner_ref"] != first_partner_ref

    execution_state = client.get(f"/v1/executions/{action_id}")
    assert execution_state.status_code == 200
    attempts = execution_state.json()["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["attempt_number"] == 1
    assert attempts[1]["attempt_number"] == 2


def test_invest_and_tax_execution_readiness_gates() -> None:
    household_id = f"h_{uuid4().hex[:8]}"

    connect = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "API Compliance Household",
            "accounts": [
                {
                    "institution": "ABN AMRO",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 9000,
                    "metadata": {},
                }
            ],
        },
    )
    assert connect.status_code == 200

    invest_rec = client.post(
        "/v1/invest/recommendation",
        json={
            "household_id": household_id,
            "model_id": "balanced_v1",
            "target_alloc": {"equity": 0.6, "bond": 0.4},
            "delta_orders": [{"ticker": "VWCE", "amount": 300}],
            "suitability_flags": ["non_compliant_risk_profile"],
        },
    )
    assert invest_rec.status_code == 200

    invest_action = client.post(
        "/v1/actions/proposals",
        json={
            "household_id": household_id,
            "action_type": "invest",
            "amount": 300,
            "currency": "EUR",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "category": "goal_investing",
            "rationale": ["suitability gate contract"],
        },
    )
    assert invest_action.status_code == 200
    invest_action_id = invest_action.json()["id"]
    assert client.post(f"/v1/actions/{invest_action_id}/approve", json={"step": "confirm"}).status_code == 200
    assert client.post(f"/v1/actions/{invest_action_id}/approve", json={"step": "authorize"}).status_code == 200

    blocked_invest_dispatch = client.post(
        f"/v1/executions/{invest_action_id}/dispatch",
        json={"idempotency_key": "invest_blocked_a"},
    )
    assert blocked_invest_dispatch.status_code == 400
    assert "suitability gate failed" in blocked_invest_dispatch.json()["detail"]

    invest_rec_clear = client.post(
        "/v1/invest/recommendation",
        json={
            "household_id": household_id,
            "model_id": "balanced_v1",
            "target_alloc": {"equity": 0.6, "bond": 0.4},
            "delta_orders": [{"ticker": "VWCE", "amount": 300}],
            "suitability_flags": [],
        },
    )
    assert invest_rec_clear.status_code == 200

    invest_dispatch = client.post(
        f"/v1/executions/{invest_action_id}/dispatch",
        json={"idempotency_key": "invest_pass_a"},
    )
    assert invest_dispatch.status_code == 200
    assert invest_dispatch.json()["result"] == "success"

    tax_package = client.post(
        "/v1/tax/package",
        json={
            "household_id": household_id,
            "jurisdiction": "NL",
            "forms": ["M-form"],
            "inputs": {"year": "2025"},
            "missing_items": ["Annual income statement"],
            "submission_mode": "partner_one_click_submit",
        },
    )
    assert tax_package.status_code == 200

    tax_action = client.post(
        "/v1/actions/proposals",
        json={
            "household_id": household_id,
            "action_type": "tax_submission",
            "amount": 80,
            "currency": "EUR",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "category": "tax_filing",
            "rationale": ["tax completeness gate contract"],
        },
    )
    assert tax_action.status_code == 200
    tax_action_id = tax_action.json()["id"]
    assert client.post(f"/v1/actions/{tax_action_id}/approve", json={"step": "confirm"}).status_code == 200
    assert client.post(f"/v1/actions/{tax_action_id}/approve", json={"step": "authorize"}).status_code == 200

    blocked_tax_dispatch = client.post(
        f"/v1/executions/{tax_action_id}/dispatch",
        json={"idempotency_key": "tax_blocked_a"},
    )
    assert blocked_tax_dispatch.status_code == 400
    assert "Tax package is incomplete" in blocked_tax_dispatch.json()["detail"]

    tax_package_complete = client.post(
        "/v1/tax/package",
        json={
            "household_id": household_id,
            "jurisdiction": "NL",
            "forms": ["M-form"],
            "inputs": {"year": "2025"},
            "missing_items": [],
            "submission_mode": "partner_one_click_submit",
        },
    )
    assert tax_package_complete.status_code == 200

    tax_dispatch = client.post(
        f"/v1/executions/{tax_action_id}/dispatch",
        json={"idempotency_key": "tax_pass_a"},
    )
    assert tax_dispatch.status_code == 200
    assert tax_dispatch.json()["result"] == "success"


def test_rule_upsert_history_and_active_listing() -> None:
    household_id = f"h_{uuid4().hex[:8]}"

    connect = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "API Rule Version Household",
            "accounts": [
                {
                    "institution": "ING",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 2000,
                    "metadata": {},
                }
            ],
        },
    )
    assert connect.status_code == 200

    first = client.post(
        "/v1/rules",
        json={
            "household_id": household_id,
            "scope": "global",
            "daily_amount_limit": 1000,
            "max_single_action": 400,
            "blocked_categories": ["gambling"],
            "blocked_action_types": [],
            "require_approval_always": True,
        },
    )
    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert first.json()["is_active"] is True

    second = client.post(
        "/v1/rules",
        json={
            "household_id": household_id,
            "scope": "global",
            "daily_amount_limit": 2000,
            "max_single_action": 900,
            "blocked_categories": [],
            "blocked_action_types": [],
            "require_approval_always": True,
        },
    )
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert second.json()["is_active"] is True

    active_rules = client.get(f"/v1/rules?household_id={household_id}")
    assert active_rules.status_code == 200
    active_items = active_rules.json()["items"]
    assert len(active_items) == 1
    assert active_items[0]["rule_id"] == second.json()["rule_id"]

    history = client.get(f"/v1/rules?household_id={household_id}&include_inactive=true")
    assert history.status_code == 200
    history_items = history.json()["items"]
    assert len(history_items) == 2
    prior = next(item for item in history_items if item["rule_id"] == first.json()["rule_id"])
    assert prior["is_active"] is False
    assert prior["superseded_by_rule_id"] == second.json()["rule_id"]


def test_agent_loop_simulation_and_planning_insights_are_side_effect_free() -> None:
    household_id = f"h_{uuid4().hex[:8]}"

    connect = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "API Sim Household",
            "accounts": [
                {
                    "institution": "ING",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 3500,
                    "metadata": {},
                }
            ],
        },
    )
    assert connect.status_code == 200
    account_id = connect.json()["account_ids"][0]

    for amount, days_ago in [(45, 30), (40, 24), (42, 18), (38, 12)]:
        imported = client.post(
            "/v1/providers/ingest",
            json={
                "household_id": household_id,
                "transactions": [
                    {
                        "account_id": account_id,
                        "amount": amount,
                        "currency": "EUR",
                        "direction": "debit",
                        "description": "Groceries baseline",
                        "category": "groceries",
                        "booked_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
                    }
                ],
                "deadlines": [],
            },
        )
        assert imported.status_code == 200

    shock = client.post(
        "/v1/providers/ingest",
        json={
            "household_id": household_id,
            "transactions": [
                {
                    "account_id": account_id,
                    "amount": 620,
                    "currency": "EUR",
                    "direction": "debit",
                    "description": "Emergency repair",
                    "category": "home_repair",
                    "booked_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "deadlines": [],
        },
    )
    assert shock.status_code == 200

    actions_before = client.get(f"/v1/actions?household_id={household_id}")
    assert actions_before.status_code == 200
    before_count = len(actions_before.json()["items"])

    simulation = client.post(
        "/v1/agent/loops/simulate",
        json={
            "household_id": household_id,
            "include_daily_monitor": True,
            "include_event_anomaly": True,
            "include_weekly_planning": True,
        },
    )
    assert simulation.status_code == 200
    payload = simulation.json()
    assert payload["household_id"] == household_id
    assert "generated_at" in payload
    assert "event_anomaly" in payload
    assert "would_emit_actions" in payload["event_anomaly"]

    actions_after = client.get(f"/v1/actions?household_id={household_id}")
    assert actions_after.status_code == 200
    assert len(actions_after.json()["items"]) == before_count

    insights = client.get(f"/v1/planning/insights?household_id={household_id}")
    assert insights.status_code == 200
    insights_payload = insights.json()
    assert insights_payload["household_id"] == household_id
    assert "items" in insights_payload
