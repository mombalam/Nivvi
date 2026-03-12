from __future__ import annotations

from dataclasses import MISSING, fields
from datetime import datetime, timezone
import os
import pickle
from threading import Lock
from typing import Any

from nivvi.storage.in_memory import InMemoryStore


class SnapshotPersistence:
    """Optional persistence layer that snapshots the full in-memory store into PostgreSQL."""

    def __init__(self, database_url: str | None = None, backend: str | None = None) -> None:
        self.backend = (backend or os.getenv("NIVVI_STORE_BACKEND", "memory")).strip().lower()
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.enabled = self.backend == "postgres" and bool(self.database_url)
        self._lock = Lock()
        self._engine: Any | None = None
        self._text = None
        self._initialized = False

        if self.enabled:
            try:
                from sqlalchemy import create_engine, text
            except ImportError as error:  # pragma: no cover - exercised when postgres backend is configured
                raise RuntimeError(
                    "PostgreSQL snapshot backend requires sqlalchemy. "
                    "Install project dependencies with SQLAlchemy support."
                ) from error

            self._engine = create_engine(str(self.database_url), future=True, pool_pre_ping=True)
            self._text = text
            self._init_schema()

    def _init_schema(self) -> None:
        if not self.enabled or self._initialized:
            return
        assert self._engine is not None
        assert self._text is not None
        with self._engine.begin() as conn:
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS store_snapshots (
                      id INTEGER PRIMARY KEY,
                      payload BYTEA NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
        self._initialized = True

    def load_into(self, store: InMemoryStore) -> bool:
        if not self.enabled:
            return False
        assert self._engine is not None
        assert self._text is not None

        self._init_schema()
        with self._engine.connect() as conn:
            row = conn.execute(self._text("SELECT payload FROM store_snapshots WHERE id = 1")).mappings().first()
        if not row:
            return False

        payload = row["payload"]
        restored = pickle.loads(payload)
        if not isinstance(restored, InMemoryStore):
            return False
        _copy_store_values(store, restored)
        return True

    def save(self, store: InMemoryStore) -> None:
        if not self.enabled:
            return
        assert self._engine is not None
        assert self._text is not None

        payload = pickle.dumps(store, protocol=pickle.HIGHEST_PROTOCOL)
        now = datetime.now(timezone.utc)
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        """
                        INSERT INTO store_snapshots (id, payload, updated_at)
                        VALUES (1, :payload, :updated_at)
                        ON CONFLICT (id) DO UPDATE
                        SET payload = EXCLUDED.payload,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {"payload": payload, "updated_at": now},
                )


def _copy_store_values(target: InMemoryStore, source: InMemoryStore) -> None:
    for item in fields(InMemoryStore):
        if hasattr(source, item.name):
            setattr(target, item.name, getattr(source, item.name))
            continue
        setattr(target, item.name, _default_value_for_field(item))

    # Backfill fields for snapshots created before newer audit integrity fields existed.
    for event in getattr(target, "audit_events", []):
        if not hasattr(event, "previous_hash"):
            setattr(event, "previous_hash", None)
        if not hasattr(event, "event_hash"):
            setattr(event, "event_hash", "")

    for lead in getattr(target, "waitlist_leads", {}).values():
        if not hasattr(lead, "last_name"):
            setattr(lead, "last_name", None)
        if not hasattr(lead, "phone_number"):
            setattr(lead, "phone_number", None)


def _default_value_for_field(field: Any) -> Any:
    if field.default is not MISSING:
        return field.default
    if field.default_factory is not MISSING:  # type: ignore[comparison-overlap]
        return field.default_factory()
    return None
