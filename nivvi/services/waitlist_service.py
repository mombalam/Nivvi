from __future__ import annotations

from dataclasses import dataclass

from nivvi.domain.models import WaitlistLead
from nivvi.services.audit_service import AuditService
from nivvi.services.utils import generate_id
from nivvi.storage.in_memory import InMemoryStore


@dataclass
class WaitlistResult:
    lead: WaitlistLead
    created: bool


class WaitlistService:
    def __init__(self, store: InMemoryStore, audit: AuditService) -> None:
        self.store = store
        self.audit = audit

    def upsert_lead(
        self,
        first_name: str,
        last_name: str | None,
        email: str,
        phone_number: str | None,
        marketing_consent: bool,
        source: str | None,
        utm: dict[str, str] | None,
    ) -> WaitlistResult:
        normalized_email = email.strip().lower()
        normalized_last_name = (last_name or "").strip() or None
        normalized_phone_number = (phone_number or "").strip() or None
        if not marketing_consent:
            raise ValueError("marketing_consent must be true")

        existing = self.store.waitlist_leads.get(normalized_email)
        if existing:
            self.audit.log(
                household_id="system",
                event_type="waitlist.duplicate",
                entity_id=existing.id,
                details={"email": normalized_email, "source": source},
            )
            return WaitlistResult(lead=existing, created=False)

        lead = WaitlistLead(
            id=generate_id("lead"),
            first_name=first_name.strip(),
            last_name=normalized_last_name,
            email=normalized_email,
            phone_number=normalized_phone_number,
            marketing_consent=True,
            source=(source or "landing_hero")[:64],
            utm=utm or {},
        )
        self.store.waitlist_leads[normalized_email] = lead
        self.audit.log(
            household_id="system",
            event_type="waitlist.created",
            entity_id=lead.id,
            details={
                "email": normalized_email,
                "source": lead.source,
                "has_last_name": bool(lead.last_name),
                "has_phone_number": bool(lead.phone_number),
                "utm": lead.utm,
            },
        )
        return WaitlistResult(lead=lead, created=True)
