from __future__ import annotations

import hashlib
import json

from nivvi.domain.models import AuditEvent
from nivvi.services.utils import generate_id
from nivvi.storage.relational_persistence import RelationalPersistence
from nivvi.storage.in_memory import InMemoryStore


class AuditService:
    def __init__(
        self,
        store: InMemoryStore,
        relational_persistence: RelationalPersistence | None = None,
    ) -> None:
        self.store = store
        self.relational_persistence = relational_persistence

    def log(self, household_id: str, event_type: str, entity_id: str, details: dict) -> AuditEvent:
        previous = next(
            (item for item in reversed(self.store.audit_events) if item.household_id == household_id),
            None,
        )
        previous_hash = previous.event_hash if previous is not None else None
        event = AuditEvent(
            id=generate_id("evt"),
            household_id=household_id,
            event_type=event_type,
            entity_id=entity_id,
            details=details,
            previous_hash=previous_hash,
        )
        event.event_hash = self._hash_event(event)
        self.store.audit_events.append(event)
        if self.relational_persistence is not None:
            self.relational_persistence.append_audit_event(event)
        return event

    def list_events(self, household_id: str | None = None) -> list[AuditEvent]:
        if household_id is None:
            return list(self.store.audit_events)
        return [event for event in self.store.audit_events if event.household_id == household_id]

    def verify_integrity(self, household_id: str | None = None) -> dict:
        events = self.list_events(household_id=household_id)
        by_household: dict[str, list[AuditEvent]] = {}
        for event in events:
            by_household.setdefault(event.household_id, []).append(event)

        broken: list[dict[str, str]] = []
        for scope, scoped_events in by_household.items():
            ordered = sorted(scoped_events, key=lambda item: item.created_at)
            previous_hash: str | None = None
            for event in ordered:
                expected_hash = self._hash_event(event)
                if event.previous_hash != previous_hash:
                    broken.append(
                        {
                            "household_id": scope,
                            "event_id": event.id,
                            "reason": "previous_hash_mismatch",
                        }
                    )
                if event.event_hash != expected_hash:
                    broken.append(
                        {
                            "household_id": scope,
                            "event_id": event.id,
                            "reason": "event_hash_mismatch",
                        }
                    )
                previous_hash = event.event_hash

        return {
            "valid": len(broken) == 0,
            "checked_events": len(events),
            "broken_links": broken,
        }

    @staticmethod
    def _hash_event(event: AuditEvent) -> str:
        payload = {
            "id": event.id,
            "household_id": event.household_id,
            "event_type": event.event_type,
            "entity_id": event.entity_id,
            "details": event.details,
            "previous_hash": event.previous_hash,
            "created_at": event.created_at.isoformat(),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
