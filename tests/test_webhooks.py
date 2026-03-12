from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from nivvi.main import app


def _create_household_and_account(client: TestClient, household_id: str) -> str:
    response = client.post(
        "/v1/connect/accounts",
        json={
            "household_id": household_id,
            "household_name": "Webhook Test Household",
            "accounts": [
                {
                    "institution": "ING",
                    "account_type": "bank",
                    "currency": "EUR",
                    "balance": 3300,
                    "metadata": {},
                }
            ],
        },
    )
    assert response.status_code == 200
    return response.json()["account_ids"][0]


def test_whatsapp_verification_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "nivvi_verify_token")

    with TestClient(app) as client:
        ok = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "nivvi_verify_token",
                "hub.challenge": "12345",
            },
        )
        assert ok.status_code == 200
        assert ok.text == "12345"

        bad = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "12345",
            },
        )
        assert bad.status_code == 403


def test_whatsapp_webhook_signature_and_processing(monkeypatch) -> None:
    household_id = f"wa_{uuid4().hex[:8]}"
    app_secret = "whatsapp_secret"
    monkeypatch.setenv("WHATSAPP_APP_SECRET", app_secret)

    with TestClient(app) as client:
        _create_household_and_account(client, household_id)

        link = client.post(
            "/v1/chat/identities/link",
            json={
                "household_id": household_id,
                "channel": "whatsapp",
                "user_handle": "233555111111",
            },
        )
        assert link.status_code == 200

        action = client.post(
            "/v1/actions/proposals",
            json={
                "household_id": household_id,
                "action_type": "transfer",
                "amount": 180,
                "currency": "EUR",
                "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "category": "bill_payment",
                "rationale": ["webhook command test"],
            },
        )
        assert action.status_code == 200
        action_id = action.json()["id"]

        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "233555111111",
                                        "id": "wamid.HBgM123",
                                        "timestamp": "1710000000",
                                        "type": "text",
                                        "text": {"body": f"confirm {action_id}"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }

        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        rejected = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"content-type": "application/json"},
        )
        assert rejected.status_code == 403

        accepted = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": f"sha256={signature}",
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["processed"] == 1

        actions = client.get(f"/v1/actions?household_id={household_id}")
        assert actions.status_code == 200
        assert actions.json()["items"][0]["status"] == "pending_authorization"


def test_telegram_webhook_secret_and_identity_resolution(monkeypatch) -> None:
    household_id = f"tg_{uuid4().hex[:8]}"
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "tg-secret")

    with TestClient(app) as client:
        _create_household_and_account(client, household_id)

        payload = {
            "update_id": 10000,
            "message": {
                "message_id": 1365,
                "from": {"id": 556677, "first_name": "Niv", "username": "niv_user"},
                "chat": {"id": 556677, "type": "private"},
                "date": 1710000000,
                "text": "today",
            },
        }

        blocked = client.post("/webhooks/telegram", json=payload)
        assert blocked.status_code == 403

        link = client.post(
            "/v1/chat/identities/link",
            json={
                "household_id": household_id,
                "channel": "telegram",
                "user_handle": "556677",
            },
        )
        assert link.status_code == 200

        accepted = client.post(
            "/webhooks/telegram",
            json=payload,
            headers={"x-telegram-bot-api-secret-token": "tg-secret"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["processed"] == 1

        messages = client.get(f"/v1/chat/messages?household_id={household_id}&channel=telegram")
        assert messages.status_code == 200
        items = messages.json()["items"]
        assert any(item["sender"] == "agent" for item in items)
