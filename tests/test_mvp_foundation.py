from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from nivvi.main import STORE, app


def test_provider_connection_sync_and_execution_fallback() -> None:
    household_id = f"prov_{uuid4().hex[:8]}"
    with TestClient(app) as client:
        connected = client.post(
            "/v1/connect/accounts",
            json={
                "household_id": household_id,
                "household_name": "Provider Flow Household",
                "accounts": [
                    {
                        "institution": "ING",
                        "account_type": "bank",
                        "currency": "EUR",
                        "balance": 5000,
                        "metadata": {},
                    }
                ],
            },
        )
        assert connected.status_code == 200

        primary = client.post(
            "/v1/providers/connections",
            json={
                "household_id": household_id,
                "provider_name": "sandbox_primary",
                "domain": "payments",
                "is_primary": True,
                "is_enabled": True,
                "metadata": {"simulate_fail": True},
            },
        )
        assert primary.status_code == 200

        fallback = client.post(
            "/v1/providers/connections",
            json={
                "household_id": household_id,
                "provider_name": "sandbox_fallback",
                "domain": "payments",
                "is_primary": False,
                "is_enabled": True,
                "metadata": {},
            },
        )
        assert fallback.status_code == 200

        sync = client.post(
            "/v1/providers/sync",
            json={"household_id": household_id, "domain": "payments"},
        )
        assert sync.status_code == 200
        assert sync.json()["item"]["status"] == "success"
        sync_id = sync.json()["item"]["id"]

        sync_state = client.get(f"/v1/providers/sync/{sync_id}")
        assert sync_state.status_code == 200
        assert sync_state.json()["item"]["household_id"] == household_id

        action = client.post(
            "/v1/actions/proposals",
            json={
                "household_id": household_id,
                "action_type": "transfer",
                "amount": 240,
                "currency": "EUR",
                "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "category": "bill_payment",
                "rationale": ["provider fallback test"],
            },
        )
        assert action.status_code == 200
        action_id = action.json()["id"]
        assert client.post(f"/v1/actions/{action_id}/approve", json={"step": "confirm"}).status_code == 200
        assert client.post(f"/v1/actions/{action_id}/approve", json={"step": "authorize"}).status_code == 200

        dispatched = client.post(
            f"/v1/executions/{action_id}/dispatch",
            json={"idempotency_key": f"prov_{uuid4().hex[:8]}"},
        )
        assert dispatched.status_code == 200
        payload = dispatched.json()
        assert payload["result"] == "success"
        assert payload["provider_name"] == "sandbox_fallback"
        assert payload["fallback_used"] is True


def test_optional_auth_household_isolation() -> None:
    household_id = f"auth_{uuid4().hex[:8]}"
    with TestClient(app) as client:
        client.app.dependency_overrides = {}

        import os

        previous_auth = os.getenv("NIVVI_REQUIRE_AUTH")
        previous_bootstrap = os.getenv("NIVVI_BOOTSTRAP_TOKEN")
        bootstrap = f"bootstrap_{uuid4().hex[:8]}"
        os.environ["NIVVI_REQUIRE_AUTH"] = "true"
        os.environ["NIVVI_BOOTSTRAP_TOKEN"] = bootstrap
        try:
            denied_beta_call = client.post("/v1/beta/users", json={"email": f"noauth_{uuid4().hex[:6]}@example.com"})
            assert denied_beta_call.status_code == 401

            admin_headers = {"Authorization": f"Bearer {bootstrap}"}
            user1 = client.post(
                "/v1/beta/users",
                json={"email": f"user1_{uuid4().hex[:6]}@example.com"},
                headers=admin_headers,
            )
            assert user1.status_code == 200
            user1_id = user1.json()["item"]["id"]
            token1 = client.post(
                f"/v1/beta/users/{user1_id}/tokens",
                json={"label": "owner"},
                headers=admin_headers,
            )
            assert token1.status_code == 200
            bearer1 = token1.json()["item"]["token"]

            user2 = client.post(
                "/v1/beta/users",
                json={"email": f"user2_{uuid4().hex[:6]}@example.com"},
                headers=admin_headers,
            )
            assert user2.status_code == 200
            user2_id = user2.json()["item"]["id"]
            token2 = client.post(
                f"/v1/beta/users/{user2_id}/tokens",
                json={"label": "outsider"},
                headers=admin_headers,
            )
            assert token2.status_code == 200
            bearer2 = token2.json()["item"]["token"]

            outsider_beta_call = client.post(
                "/v1/beta/users",
                json={"email": f"blocked_{uuid4().hex[:6]}@example.com"},
                headers={"Authorization": f"Bearer {bearer1}"},
            )
            assert outsider_beta_call.status_code == 403

            connected = client.post(
                "/v1/connect/accounts",
                json={
                    "household_id": household_id,
                    "household_name": "Auth Household",
                    "accounts": [
                        {
                            "institution": "ING",
                            "account_type": "bank",
                            "currency": "EUR",
                            "balance": 1000,
                            "metadata": {},
                        }
                    ],
                },
                headers={"Authorization": f"Bearer {bearer1}"},
            )
            assert connected.status_code == 200

            denied = client.get(
                f"/v1/households/{household_id}/ledger",
                headers={"Authorization": f"Bearer {bearer2}"},
            )
            assert denied.status_code == 403

            add_viewer = client.post(
                f"/v1/beta/households/{household_id}/memberships",
                json={"user_id": user2_id, "role": "viewer"},
                headers=admin_headers,
            )
            assert add_viewer.status_code == 200

            viewer_read = client.get(
                f"/v1/households/{household_id}/ledger",
                headers={"Authorization": f"Bearer {bearer2}"},
            )
            assert viewer_read.status_code == 200

            viewer_write = client.post(
                "/v1/actions/proposals",
                json={
                    "household_id": household_id,
                    "action_type": "transfer",
                    "amount": 50,
                    "currency": "EUR",
                    "category": "viewer_write_block",
                    "rationale": ["viewer should not write"],
                },
                headers={"Authorization": f"Bearer {bearer2}"},
            )
            assert viewer_write.status_code == 403

            allowed = client.get(
                f"/v1/households/{household_id}/ledger",
                headers={"Authorization": f"Bearer {bearer1}"},
            )
            assert allowed.status_code == 200
        finally:
            if previous_auth is None:
                os.environ.pop("NIVVI_REQUIRE_AUTH", None)
            else:
                os.environ["NIVVI_REQUIRE_AUTH"] = previous_auth
            if previous_bootstrap is None:
                os.environ.pop("NIVVI_BOOTSTRAP_TOKEN", None)
            else:
                os.environ["NIVVI_BOOTSTRAP_TOKEN"] = previous_bootstrap


def test_provider_sessions_household_sync_and_runtime_metrics() -> None:
    household_id = f"sync_{uuid4().hex[:8]}"
    with TestClient(app) as client:
        connected = client.post(
            "/v1/connect/accounts",
            json={
                "household_id": household_id,
                "household_name": "Sync Household",
                "accounts": [
                    {
                        "institution": "ING",
                        "account_type": "bank",
                        "currency": "EUR",
                        "balance": 2100,
                        "metadata": {},
                    }
                ],
            },
        )
        assert connected.status_code == 200

        session_create = client.post(
            "/v1/providers/sessions",
            json={
                "household_id": household_id,
                "provider_name": "sandbox_primary",
                "domain": "aggregation",
                "redirect_url": "https://example.com/redirect",
            },
        )
        assert session_create.status_code == 200
        session_id = session_create.json()["item"]["id"]
        assert session_create.json()["item"]["status"] == "created"

        session_complete = client.post(
            f"/v1/providers/sessions/{session_id}/complete",
            json={"success": True, "provider_session_ref": f"ext_{uuid4().hex[:6]}"},
        )
        assert session_complete.status_code == 200
        assert session_complete.json()["item"]["status"] == "exchanged"

        sessions = client.get(f"/v1/providers/sessions?household_id={household_id}")
        assert sessions.status_code == 200
        assert len(sessions.json()["items"]) >= 1

        sync_run = client.post(
            f"/v1/households/{household_id}/sync",
            json={"domains": ["aggregation", "payments"]},
        )
        assert sync_run.status_code == 200
        run_id = sync_run.json()["item"]["id"]
        assert len(sync_run.json()["jobs"]) == 2

        sync_status = client.get(f"/v1/households/{household_id}/sync/{run_id}")
        assert sync_status.status_code == 200
        assert sync_status.json()["item"]["id"] == run_id
        assert len(sync_status.json()["jobs"]) == 2

        run_cycle = client.post("/v1/agent/runtime/run-cycle")
        assert run_cycle.status_code == 200
        metrics = client.get("/v1/agent/runtime/metrics?limit=5")
        assert metrics.status_code == 200
        payload = metrics.json()
        assert payload["summary"]["count"] >= 1
        assert payload["items"][0]["duration_ms"] >= 0


def test_provider_kill_switch_blocks_all_execution_providers() -> None:
    household_id = f"kill_{uuid4().hex[:8]}"
    with TestClient(app) as client:
        import os

        previous = os.getenv("NIVVI_DISABLED_EXECUTION_PROVIDERS")
        os.environ["NIVVI_DISABLED_EXECUTION_PROVIDERS"] = "sandbox_primary,sandbox_fallback"
        try:
            connected = client.post(
                "/v1/connect/accounts",
                json={
                    "household_id": household_id,
                    "household_name": "Kill Switch Household",
                    "accounts": [
                        {
                            "institution": "Bunq",
                            "account_type": "bank",
                            "currency": "EUR",
                            "balance": 3500,
                            "metadata": {},
                        }
                    ],
                },
            )
            assert connected.status_code == 200

            action = client.post(
                "/v1/actions/proposals",
                json={
                    "household_id": household_id,
                    "action_type": "transfer",
                    "amount": 150,
                    "currency": "EUR",
                    "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                    "category": "cash_move",
                    "rationale": ["kill switch test"],
                },
            )
            assert action.status_code == 200
            action_id = action.json()["id"]
            assert client.post(f"/v1/actions/{action_id}/approve", json={"step": "confirm"}).status_code == 200
            assert client.post(f"/v1/actions/{action_id}/approve", json={"step": "authorize"}).status_code == 200

            dispatched = client.post(
                f"/v1/executions/{action_id}/dispatch",
                json={"idempotency_key": f"kill_{uuid4().hex[:8]}"},
            )
            assert dispatched.status_code == 200
            payload = dispatched.json()
            assert payload["result"] == "failed"
            assert "disabled" in payload["message"].lower()
        finally:
            if previous is None:
                os.environ.pop("NIVVI_DISABLED_EXECUTION_PROVIDERS", None)
            else:
                os.environ["NIVVI_DISABLED_EXECUTION_PROVIDERS"] = previous


def test_launch_gate_endpoint_reports_checks() -> None:
    household_id = f"gate_{uuid4().hex[:8]}"
    with TestClient(app) as client:
        connected = client.post(
            "/v1/connect/accounts",
            json={
                "household_id": household_id,
                "household_name": "Launch Gate Household",
                "accounts": [
                    {
                        "institution": "ING",
                        "account_type": "bank",
                        "currency": "EUR",
                        "balance": 4000,
                        "metadata": {},
                    }
                ],
            },
        )
        assert connected.status_code == 200

        for domain in ("payments", "investing", "tax_submission"):
            linked = client.post(
                "/v1/providers/connections",
                json={
                    "household_id": household_id,
                    "provider_name": "sandbox_primary",
                    "domain": domain,
                    "is_primary": True,
                    "is_enabled": True,
                },
            )
            assert linked.status_code == 200

        assert client.post("/v1/agent/runtime/run-cycle").status_code == 200

        launch_gate = client.get(f"/v1/beta/launch-gate?household_id={household_id}")
        assert launch_gate.status_code == 200
        payload = launch_gate.json()
        assert payload["household_scope"] == household_id
        assert "checks" in payload
        assert "execution_domains_connected" in payload["checks"]


def test_audit_integrity_endpoint_detects_tampering() -> None:
    household_id = f"audit_{uuid4().hex[:8]}"
    with TestClient(app) as client:
        connected = client.post(
            "/v1/connect/accounts",
            json={
                "household_id": household_id,
                "household_name": "Audit Household",
                "accounts": [
                    {
                        "institution": "ING",
                        "account_type": "bank",
                        "currency": "EUR",
                        "balance": 1200,
                        "metadata": {},
                    }
                ],
            },
        )
        assert connected.status_code == 200

        before = client.get(f"/v1/audit/integrity?household_id={household_id}")
        assert before.status_code == 200
        assert before.json()["valid"] is True
        assert before.json()["checked_events"] >= 1

        first_event = next(item for item in STORE.audit_events if item.household_id == household_id)
        first_event.details["tampered"] = "yes"

        after = client.get(f"/v1/audit/integrity?household_id={household_id}")
        assert after.status_code == 200
        assert after.json()["valid"] is False
        reasons = [item["reason"] for item in after.json()["broken_links"]]
        assert "event_hash_mismatch" in reasons
