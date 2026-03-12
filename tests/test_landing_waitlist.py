from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nivvi.main import app


def test_marketing_and_app_routes_are_split() -> None:
    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        assert "Wealth." in landing.text
        assert "Mastered." in landing.text
        assert "Nivvi is your AI money manager." in landing.text
        assert "Reimagined." in landing.text
        assert "Power." in landing.text
        assert "Simplified." in landing.text
        assert "Family." in landing.text
        assert "Stay Sovereign" not in landing.text
        assert "Join the dedicated waitlist page" not in landing.text
        assert 'href="#"' not in landing.text
        assert 'href="/legal/privacy"' not in landing.text
        assert 'href="/waitlist"' in landing.text
        assert 'data-analytics-event="cta_click_hero"' in landing.text
        assert 'data-analytics-event="cta_click_midpage"' in landing.text
        assert "/static/screens/Dashboard.png?v=20260310b" in landing.text
        assert "/static/screens/Accounts.png?v=20260310b" in landing.text
        assert "/static/screens/Moves.png?v=20260310b" in landing.text
        assert "/static/brand/logo.png?v=20260305c" in landing.text
        assert '/static/fonts/fonts.css?v=20260312a' in landing.text
        assert '/static/vendor/tailwindcss-browser-4.js?v=20260312a' in landing.text
        assert '/static/vendor/iconify-icon-3.0.0.min.js?v=20260312a' in landing.text
        assert "fonts.googleapis.com" not in landing.text
        assert "fonts.gstatic.com" not in landing.text
        assert "cdn.jsdelivr.net/npm/@tailwindcss/browser" not in landing.text
        assert "code.iconify.design" not in landing.text
        assert 'loading="eager"' in landing.text

        companion = client.get("/app")
        assert companion.status_code == 200
        assert "Companion App" in companion.text
        assert '/static/fonts/fonts.css?v=20260312a' in companion.text
        assert "fonts.googleapis.com" not in companion.text
        assert "fonts.gstatic.com" not in companion.text

        waitlist = client.get("/waitlist")
        assert waitlist.status_code == 200
        assert "Get early access" in waitlist.text
        assert "I agree to receive launch updates and accept" in waitlist.text
        assert "class=\"waitlist-form" in waitlist.text
        assert 'name="full_name"' in waitlist.text
        assert 'name="last_name"' not in waitlist.text
        assert 'name="phone_number"' in waitlist.text
        assert 'data-success-redirect="/waitlist/success"' in waitlist.text
        assert '/static/fonts/fonts.css?v=20260312a' in waitlist.text
        assert '/static/vendor/tailwindcss-browser-4.js?v=20260312a' in waitlist.text
        assert "fonts.googleapis.com" not in waitlist.text
        assert "fonts.gstatic.com" not in waitlist.text
        assert "cdn.jsdelivr.net/npm/@tailwindcss/browser" not in waitlist.text
        assert "John Appleseed" not in waitlist.text
        assert "john@appleseed.com" not in waitlist.text

        waitlist_success = client.get("/waitlist/success")
        assert waitlist_success.status_code == 200
        assert "You&apos;re on the list" in waitlist_success.text
        assert '/static/fonts/fonts.css?v=20260312a' in waitlist_success.text
        assert '/static/vendor/tailwindcss-browser-4.js?v=20260312a' in waitlist_success.text
        assert "fonts.googleapis.com" not in waitlist_success.text
        assert "fonts.gstatic.com" not in waitlist_success.text
        assert "cdn.jsdelivr.net/npm/@tailwindcss/browser" not in waitlist_success.text


def test_legal_pages_exist() -> None:
    with TestClient(app) as client:
        privacy = client.get("/legal/privacy")
        assert privacy.status_code == 200
        assert "Privacy Notice" in privacy.text
        assert "Data We Collect" in privacy.text

        terms = client.get("/legal/terms")
        assert terms.status_code == 200
        assert "Terms of Use" in terms.text
        assert "Service Scope" in terms.text


def test_waitlist_create_and_dedupe() -> None:
    with TestClient(app) as client:
        email = f"lead_{uuid4().hex[:8]}@example.com"
        payload = {
            "first_name": "Ama",
            "last_name": "Mensah",
            "email": email,
            "phone_number": "+31 6 1234 5678",
            "marketing_consent": True,
            "source": "landing_hero",
            "utm": {"utm_source": "linkedin", "utm_campaign": "prelaunch"},
        }

        first = client.post("/v1/waitlist", json=payload)
        assert first.status_code == 200
        assert first.json()["status"] == "created"

        second = client.post("/v1/waitlist", json=payload)
        assert second.status_code == 200
        assert second.json()["status"] == "already_exists"
        assert second.json()["id"] == first.json()["id"]


@pytest.mark.parametrize(
    "event_name",
    [
        "landing_view",
        "cta_click_hero",
        "cta_click_midpage",
        "faq_expand",
    ],
)
def test_waitlist_validation_and_analytics(event_name: str) -> None:
    with TestClient(app) as client:
        bad_email = client.post(
            "/v1/waitlist",
            json={
                "first_name": "Kojo",
                "email": "invalid-email",
                "marketing_consent": True,
                "source": "landing_hero",
                "utm": {},
            },
        )
        assert bad_email.status_code == 422

        no_consent = client.post(
            "/v1/waitlist",
            json={
                "first_name": "Kojo",
                "email": f"kojo_{uuid4().hex[:8]}@example.com",
                "marketing_consent": False,
                "source": "landing_hero",
                "utm": {},
            },
        )
        assert no_consent.status_code == 400

        bad_phone = client.post(
            "/v1/waitlist",
            json={
                "first_name": "Kojo",
                "email": f"kojo_phone_{uuid4().hex[:8]}@example.com",
                "phone_number": "invalid-phone",
                "marketing_consent": True,
                "source": "landing_hero",
                "utm": {},
            },
        )
        assert bad_phone.status_code == 422

        analytics = client.post(
            "/v1/analytics/events",
            json={
                "event_name": event_name,
                "page": "landing",
                "properties": {"section": "hero"},
            },
        )
        assert analytics.status_code == 200
        assert analytics.json()["status"] == "ok"
