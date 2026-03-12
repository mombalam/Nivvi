from __future__ import annotations

import os

from nivvi.domain.models import BetaApiToken, BetaUser, HouseholdMembership
from nivvi.services.audit_service import AuditService
from nivvi.services.utils import generate_id
from nivvi.storage.in_memory import InMemoryStore


class AuthService:
    """Beta auth and household isolation controls (optional, env-gated)."""

    def __init__(self, store: InMemoryStore, audit_service: AuditService) -> None:
        self.store = store
        self.audit_service = audit_service

    @property
    def auth_required(self) -> bool:
        return str(os.getenv("NIVVI_REQUIRE_AUTH", "false")).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def bootstrap_token(self) -> str | None:
        token = os.getenv("NIVVI_BOOTSTRAP_TOKEN")
        if not token:
            return None
        return token.strip() or None

    def create_user(self, email: str, full_name: str | None = None) -> BetaUser:
        normalized = email.strip().lower()
        existing = next((item for item in self.store.beta_users.values() if item.email == normalized), None)
        if existing:
            return existing
        user = BetaUser(id=generate_id("usr"), email=normalized, full_name=(full_name or None))
        self.store.beta_users[user.id] = user
        self.audit_service.log(
            household_id="system",
            event_type="beta.user_created",
            entity_id=user.id,
            details={"email": user.email},
        )
        return user

    def issue_token(self, user_id: str, label: str | None = None) -> BetaApiToken:
        if user_id not in self.store.beta_users:
            raise ValueError(f"Unknown user_id '{user_id}'")
        token_value = f"nvk_{generate_id('tok')}"
        token = BetaApiToken(
            id=generate_id("tok"),
            user_id=user_id,
            token=token_value,
            label=(label or "beta"),
            is_active=True,
        )
        self.store.beta_api_tokens[token.id] = token
        self.audit_service.log(
            household_id="system",
            event_type="beta.token_issued",
            entity_id=token.id,
            details={"user_id": user_id, "label": token.label},
        )
        return token

    def add_membership(self, user_id: str, household_id: str, role: str = "member") -> HouseholdMembership:
        if user_id not in self.store.beta_users:
            raise ValueError(f"Unknown user_id '{user_id}'")
        existing = next(
            (
                item
                for item in self.store.household_memberships.values()
                if item.user_id == user_id and item.household_id == household_id and item.is_active
            ),
            None,
        )
        if existing:
            return existing
        membership = HouseholdMembership(
            id=generate_id("mbr"),
            household_id=household_id,
            user_id=user_id,
            role=role,
        )
        self.store.household_memberships[membership.id] = membership
        self.audit_service.log(
            household_id=household_id,
            event_type="beta.membership_added",
            entity_id=membership.id,
            details={"user_id": user_id, "role": role},
        )
        return membership

    def set_household_enabled(self, household_id: str, enabled: bool) -> bool:
        self.store.household_enabled[household_id] = enabled
        self.audit_service.log(
            household_id=household_id,
            event_type="beta.household_status_updated",
            entity_id=household_id,
            details={"enabled": enabled},
        )
        return enabled

    def is_household_enabled(self, household_id: str) -> bool:
        return self.store.household_enabled.get(household_id, True)

    def authenticate(self, bearer_token: str | None) -> str:
        if not self.auth_required:
            return "public"
        if not bearer_token:
            raise ValueError("Missing bearer token")

        bootstrap = self.bootstrap_token
        if bootstrap and bearer_token == bootstrap:
            return "bootstrap_admin"

        token = next(
            (
                item
                for item in self.store.beta_api_tokens.values()
                if item.token == bearer_token and item.is_active
            ),
            None,
        )
        if token is None:
            raise ValueError("Invalid bearer token")
        if token.user_id not in self.store.beta_users:
            raise ValueError("Token user is not active")
        return token.user_id

    def can_access_household(self, user_id: str, household_id: str) -> bool:
        if not self.auth_required:
            return True
        if user_id == "bootstrap_admin":
            return True
        return any(
            item.household_id == household_id and item.user_id == user_id and item.is_active
            for item in self.store.household_memberships.values()
        )

    def membership_for_household(self, user_id: str, household_id: str) -> HouseholdMembership | None:
        for item in self.store.household_memberships.values():
            if item.household_id == household_id and item.user_id == user_id and item.is_active:
                return item
        return None

    def can_write_household(self, user_id: str, household_id: str) -> bool:
        if not self.auth_required:
            return True
        if user_id == "bootstrap_admin":
            return True
        membership = self.membership_for_household(user_id, household_id)
        if membership is None:
            return False
        return membership.role in {"owner", "admin", "member"}

    def ensure_household_access(self, user_id: str, household_id: str, require_write: bool = False) -> None:
        if require_write and not self.can_write_household(user_id, household_id):
            raise ValueError("Write access denied for household")
        if not require_write and not self.can_access_household(user_id, household_id):
            raise ValueError("Access denied for household")
        if not self.is_household_enabled(household_id):
            raise ValueError("Household is disabled")

    def auto_provision_membership_for_new_household(self, user_id: str, household_id: str) -> None:
        if not self.auth_required or user_id in {"public", "bootstrap_admin"}:
            return
        self.add_membership(user_id=user_id, household_id=household_id, role="owner")
