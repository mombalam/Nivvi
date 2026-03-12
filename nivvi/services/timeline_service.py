from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nivvi.domain.models import DeadlineItem
from nivvi.services.utils import generate_id
from nivvi.storage.in_memory import InMemoryStore


class TimelineService:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def _next_nl_tax_deadline(self) -> datetime:
        now = datetime.now(timezone.utc)
        candidate = datetime(year=now.year, month=5, day=1, tzinfo=timezone.utc)
        if candidate < now:
            candidate = datetime(year=now.year + 1, month=5, day=1, tzinfo=timezone.utc)
        return candidate

    def timeline(self, household_id: str, lookahead_days: int = 90) -> list[DeadlineItem]:
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=lookahead_days)

        entries = [
            item
            for item in self.store.deadlines.values()
            if item.household_id == household_id and now <= item.due_at <= until
        ]

        # Always include Dutch annual return as a default guardrail item.
        tax_due = self._next_nl_tax_deadline()
        if now <= tax_due <= until:
            entries.append(
                DeadlineItem(
                    id=generate_id("ddl"),
                    household_id=household_id,
                    source="nl_tax_guard",
                    title="Dutch Income Tax Return Due",
                    jurisdiction="NL",
                    due_at=tax_due,
                    penalty_risk="high",
                    amount=None,
                )
            )

        entries.sort(key=lambda item: item.due_at)
        return entries
