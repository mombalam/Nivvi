from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from nivvi.marketing_main import app


def test_marketing_entrypoint_is_landing_first() -> None:
    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        assert "Wealth." in landing.text
        assert "Get early access" in landing.text

        waitlist_page = client.get("/waitlist")
        assert waitlist_page.status_code == 200
        assert "class=\"waitlist-form" in waitlist_page.text

        waitlist_success = client.get("/waitlist/success")
        assert waitlist_success.status_code == 200
        assert "You&apos;re on the list" in waitlist_success.text

        assert client.get("/legal/privacy").status_code == 200
        assert client.get("/legal/terms").status_code == 200

        # Companion app and product APIs are intentionally excluded from marketing app.
        assert client.get("/app").status_code == 404
        assert client.get("/v1/actions/proposals").status_code == 404


def test_marketing_waitlist_and_analytics_endpoints() -> None:
    with TestClient(app) as client:
        email = f"mk_{uuid4().hex[:8]}@example.com"
        payload = {
            "first_name": "Ama",
            "last_name": "Mensah",
            "email": email,
            "phone_number": "+31 6 1234 5678",
            "marketing_consent": True,
            "source": "waitlist_page",
            "utm": {"utm_source": "landing", "utm_campaign": "prelaunch"},
        }

        created = client.post("/v1/waitlist", json=payload)
        assert created.status_code == 200
        assert created.json()["status"] == "created"

        duplicate = client.post("/v1/waitlist", json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "already_exists"
        assert duplicate.json()["id"] == created.json()["id"]

        analytics = client.post(
            "/v1/analytics/events",
            json={
                "event_name": "cta_click_hero",
                "page": "waitlist",
                "properties": {"destination": "/static/waitlist.html"},
            },
        )
        assert analytics.status_code == 200
        assert analytics.json()["status"] == "ok"


def test_marketing_admin_waitlist_listing_requires_key(monkeypatch) -> None:
    monkeypatch.setenv("NIVVI_ADMIN_KEY", "test-admin-key")

    with TestClient(app) as client:
        email = f"admin_{uuid4().hex[:8]}@example.com"
        created = client.post(
            "/v1/waitlist",
            json={
                "first_name": "Mo",
                "email": email,
                "marketing_consent": True,
                "source": "waitlist_page",
                "utm": {"utm_source": "landing"},
            },
        )
        assert created.status_code == 200

        unauthorized = client.get("/v1/admin/waitlist/leads")
        assert unauthorized.status_code == 401

        leads = client.get("/v1/admin/waitlist/leads", headers={"x-admin-key": "test-admin-key"})
        assert leads.status_code == 200
        payload = leads.json()
        assert payload["total_count"] >= 1
        assert any(item["email"] == email for item in payload["items"])

        csv_export = client.get("/v1/admin/waitlist/leads.csv", headers={"x-admin-key": "test-admin-key"})
        assert csv_export.status_code == 200
        assert csv_export.headers["content-type"].startswith("text/csv")
        assert "email" in csv_export.text
        assert email in csv_export.text
