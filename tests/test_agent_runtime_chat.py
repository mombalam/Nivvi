from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from nivvi.main import app


def _setup_household(client: TestClient, household_id: str) -> str:
    connect = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "Chat Runtime Test",
            "accounts": [
                {
                    "institution": "ING",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 2600,
                    "metadata": {},
                }
            ],
        },
    )
    assert connect.status_code == 200
    return connect.json()["account_ids"][0]


def test_chat_command_flow_for_action_approval() -> None:
    with TestClient(app) as client:
        household_id = f"chat_{uuid4().hex[:8]}"
        _setup_household(client, household_id)

        action = client.post(
            "/v1/actions/proposals",
            json={
                "household_id": household_id,
                "action_type": "transfer",
                "amount": 120,
                "currency": "EUR",
                "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "category": "bill_payment",
                "rationale": ["chat approval test"],
            },
        )
        assert action.status_code == 200
        action_id = action.json()["id"]

        confirm = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": f"confirm {action_id}",
            },
        )
        assert confirm.status_code == 200
        assert "confirmed" in confirm.json()["outbound"]["text"].lower()

        authorize = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": f"authorize {action_id}",
            },
        )
        assert authorize.status_code == 200
        assert "authorized" in authorize.json()["outbound"]["text"].lower()

        dispatch = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": f"dispatch {action_id}",
            },
        )
        assert dispatch.status_code == 200
        assert "dispatch result" in dispatch.json()["outbound"]["text"].lower()

        messages = client.get(f"/v1/chat/messages?household_id={household_id}&channel=whatsapp")
        assert messages.status_code == 200
        assert len(messages.json()["items"]) >= 6


def test_chat_natural_language_intent_and_smart_approve_flow() -> None:
    with TestClient(app) as client:
        household_id = f"nl_{uuid4().hex[:8]}"
        _setup_household(client, household_id)

        action = client.post(
            "/v1/actions/proposals",
            json={
                "household_id": household_id,
                "action_type": "transfer",
                "amount": 95,
                "currency": "EUR",
                "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "category": "savings",
                "rationale": ["natural language flow"],
            },
        )
        assert action.status_code == 200
        action_id = action.json()["id"]

        brief = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": "What should I prioritize first this week?",
            },
        )
        assert brief.status_code == 200
        assert "advisor brief" in brief.json()["outbound"]["text"].lower()

        smart_confirm = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": f"Please approve {action_id}",
            },
        )
        assert smart_confirm.status_code == 200
        assert "confirmed" in smart_confirm.json()["outbound"]["text"].lower()

        smart_authorize = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": f"approve {action_id}",
            },
        )
        assert smart_authorize.status_code == 200
        assert "authorized" in smart_authorize.json()["outbound"]["text"].lower()

        dispatch = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": f"Please execute {action_id}",
            },
        )
        assert dispatch.status_code == 200
        assert "dispatch result" in dispatch.json()["outbound"]["text"].lower()

        capabilities = client.post(
            "/v1/chat/events",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_id": "user_1",
                "message": "What can you do?",
            },
        )
        assert capabilities.status_code == 200
        assert "ai money manager" in capabilities.json()["outbound"]["text"].lower()


def test_agent_runtime_control_endpoints() -> None:
    with TestClient(app) as client:
        household_id = f"rt_{uuid4().hex[:8]}"
        _setup_household(client, household_id)

        status = client.get("/v1/agent/runtime")
        assert status.status_code == 200
        assert "running" in status.json()

        run_cycle = client.post("/v1/agent/runtime/run-cycle")
        assert run_cycle.status_code == 200
        assert "result" in run_cycle.json()

        stop = client.post("/v1/agent/runtime/stop")
        assert stop.status_code == 200
        assert stop.json()["running"] is False

        start = client.post("/v1/agent/runtime/start", json={"interval_seconds": 30})
        assert start.status_code == 200
        assert start.json()["running"] is True
        assert start.json()["interval_seconds"] == 30


def test_event_anomaly_loop_emits_action_and_chat_intervention() -> None:
    with TestClient(app) as client:
        household_id = f"anomaly_{uuid4().hex[:8]}"
        account_id = _setup_household(client, household_id)

        for amount, days_ago in [(42, 15), (39, 14), (45, 13), (41, 12)]:
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
                            "description": "Groceries",
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
                        "description": "Emergency dental bill",
                        "category": "healthcare",
                        "booked_at": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "deadlines": [],
            },
        )
        assert shock.status_code == 200

        run_cycle = client.post("/v1/agent/runtime/run-cycle")
        assert run_cycle.status_code == 200
        assert run_cycle.json()["result"]["emitted_by_loop"]["anomaly_loop"] >= 1

        actions = client.get(f"/v1/actions?household_id={household_id}")
        assert actions.status_code == 200
        anomaly_actions = [
            item for item in actions.json()["items"] if item["category"] == "anomaly_expense_protection"
        ]
        assert len(anomaly_actions) == 1

        messages = client.get(f"/v1/chat/messages?household_id={household_id}&channel=whatsapp")
        assert messages.status_code == 200
        intervention_messages = [
            item
            for item in messages.json()["items"]
            if item["sender"] == "agent" and item["metadata"].get("kind") == "expense_shock"
        ]
        assert intervention_messages

        run_again = client.post("/v1/agent/runtime/run-cycle")
        assert run_again.status_code == 200
        actions_after = client.get(f"/v1/actions?household_id={household_id}")
        assert actions_after.status_code == 200
        anomaly_actions_after = [
            item for item in actions_after.json()["items"] if item["category"] == "anomaly_expense_protection"
        ]
        assert len(anomaly_actions_after) == 1


def test_weekly_planning_loop_emits_rebalance_once_per_window() -> None:
    with TestClient(app) as client:
        household_id = f"weekly_{uuid4().hex[:8]}"
        account_id = _setup_household(client, household_id)

        for days_ago in [34, 30, 26, 22, 18, 14, 12, 10]:
            imported = client.post(
                "/v1/providers/ingest",
                json={
                    "household_id": household_id,
                    "transactions": [
                        {
                            "account_id": account_id,
                            "amount": 30,
                            "currency": "EUR",
                            "direction": "debit",
                            "description": "Dining baseline",
                            "category": "dining",
                            "booked_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
                        }
                    ],
                    "deadlines": [],
                },
            )
            assert imported.status_code == 200

        for days_ago in [5, 2]:
            imported = client.post(
                "/v1/providers/ingest",
                json={
                    "household_id": household_id,
                    "transactions": [
                        {
                            "account_id": account_id,
                            "amount": 120,
                            "currency": "EUR",
                            "direction": "debit",
                            "description": "Dining increase",
                            "category": "dining",
                            "booked_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
                        }
                    ],
                    "deadlines": [],
                },
            )
            assert imported.status_code == 200

        run_cycle = client.post("/v1/agent/runtime/run-cycle")
        assert run_cycle.status_code == 200
        assert run_cycle.json()["result"]["emitted_by_loop"]["weekly_planning"] >= 1

        actions = client.get(f"/v1/actions?household_id={household_id}")
        assert actions.status_code == 200
        weekly_actions = [item for item in actions.json()["items"] if item["category"] == "weekly_rebalance"]
        assert len(weekly_actions) == 1

        messages = client.get(f"/v1/chat/messages?household_id={household_id}&channel=whatsapp")
        assert messages.status_code == 200
        weekly_messages = [
            item
            for item in messages.json()["items"]
            if item["sender"] == "agent" and item["metadata"].get("kind") == "weekly_plan_drift"
        ]
        assert weekly_messages

        run_again = client.post("/v1/agent/runtime/run-cycle")
        assert run_again.status_code == 200
        actions_after = client.get(f"/v1/actions?household_id={household_id}")
        assert actions_after.status_code == 200
        weekly_actions_after = [
            item for item in actions_after.json()["items"] if item["category"] == "weekly_rebalance"
        ]
        assert len(weekly_actions_after) == 1
