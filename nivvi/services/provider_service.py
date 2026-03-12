from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
from typing import Any

from nivvi.domain.models import (
    ActionProposal,
    ActionType,
    HouseholdSyncRun,
    HouseholdSyncRunStatus,
    ProviderConnection,
    ProviderConnectionStatus,
    ProviderDomain,
    ProviderSession,
    ProviderSessionStatus,
    ProviderSyncJob,
    ProviderSyncStatus,
)
from nivvi.services.audit_service import AuditService
from nivvi.services.utils import generate_id, utc_now
from nivvi.storage.in_memory import InMemoryStore
from nivvi.storage.relational_persistence import RelationalPersistence


@dataclass
class ProviderDispatchResult:
    provider_name: str
    result: str
    partner_ref: str
    message: str
    fallback_used: bool = False
    provider_attempts: list[str] | None = None


class ProviderAdapter:
    def __init__(self, provider_name: str, domain: ProviderDomain) -> None:
        self.provider_name = provider_name
        self.domain = domain

    def sync(self, household_id: str, connection: ProviderConnection) -> dict[str, Any]:
        del household_id, connection
        return {"records": 1, "message": "sync complete"}

    def execute(
        self,
        household_id: str,
        action: ActionProposal,
        connection: ProviderConnection | None,
        idempotency_key: str | None,
    ) -> ProviderDispatchResult:
        del household_id
        partner_ref = f"{self.provider_name}_{idempotency_key or generate_id('partner')}"
        metadata = connection.metadata if connection else {}
        if metadata.get("simulate_fail"):
            return ProviderDispatchResult(
                provider_name=self.provider_name,
                result="failed",
                partner_ref=partner_ref,
                message="Simulated provider failure",
            )

        if action.amount >= 100_000:
            return ProviderDispatchResult(
                provider_name=self.provider_name,
                result="failed",
                partner_ref=partner_ref,
                message="Amount exceeds provider sandbox threshold",
            )

        return ProviderDispatchResult(
            provider_name=self.provider_name,
            result="success",
            partner_ref=partner_ref,
            message="Dispatched to provider",
        )

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "checked_at": utc_now().isoformat()}


class ProviderService:
    """Provider connection, sync orchestration, and execution routing service."""

    ACTION_DOMAIN_MAP = {
        ActionType.TRANSFER: ProviderDomain.PAYMENTS,
        ActionType.INVEST: ProviderDomain.INVESTING,
        ActionType.TAX_SUBMISSION: ProviderDomain.TAX_SUBMISSION,
    }

    DOMAIN_FLAGS = {
        ProviderDomain.PAYMENTS: "NIVVI_EXECUTION_ENABLED_TRANSFER",
        ProviderDomain.INVESTING: "NIVVI_EXECUTION_ENABLED_INVEST",
        ProviderDomain.TAX_SUBMISSION: "NIVVI_EXECUTION_ENABLED_TAX",
    }

    def __init__(
        self,
        store: InMemoryStore,
        audit_service: AuditService,
        relational_persistence: RelationalPersistence | None = None,
    ) -> None:
        self.store = store
        self.audit_service = audit_service
        self.relational_persistence = relational_persistence
        self.adapters: dict[tuple[str, ProviderDomain], ProviderAdapter] = {}
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        domains = (
            ProviderDomain.AGGREGATION,
            ProviderDomain.PAYMENTS,
            ProviderDomain.INVESTING,
            ProviderDomain.TAX_SUBMISSION,
        )
        for domain in domains:
            self.register_adapter(ProviderAdapter(provider_name="sandbox_primary", domain=domain))
            self.register_adapter(ProviderAdapter(provider_name="sandbox_fallback", domain=domain))

    def register_adapter(self, adapter: ProviderAdapter) -> None:
        self.adapters[(adapter.provider_name, adapter.domain)] = adapter

    def is_execution_enabled(self, action_type: ActionType) -> bool:
        domain = self.ACTION_DOMAIN_MAP[action_type]
        flag = self.DOMAIN_FLAGS[domain]
        return str(os.getenv(flag, "true")).strip().lower() not in {"0", "false", "no", "off"}

    def disabled_execution_providers(self) -> set[str]:
        raw = str(os.getenv("NIVVI_DISABLED_EXECUTION_PROVIDERS", "")).strip().lower()
        if not raw:
            return set()
        return {item.strip() for item in raw.split(",") if item.strip()}

    def upsert_connection(
        self,
        household_id: str,
        provider_name: str,
        domain: ProviderDomain,
        is_primary: bool = True,
        is_enabled: bool = True,
        credentials_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderConnection:
        existing = self._find_connection(household_id, provider_name, domain)
        status = ProviderConnectionStatus.ACTIVE if is_enabled else ProviderConnectionStatus.DISABLED
        now = utc_now()
        if existing:
            existing.is_primary = is_primary
            existing.status = status
            existing.credentials_ref = credentials_ref
            existing.metadata = metadata or {}
            existing.updated_at = now
            connection = existing
        else:
            connection = ProviderConnection(
                id=generate_id("conn"),
                household_id=household_id,
                provider_name=provider_name,
                domain=domain,
                is_primary=is_primary,
                status=status,
                credentials_ref=credentials_ref,
                metadata=metadata or {},
            )
            self.store.provider_connections[connection.id] = connection
        self._persist_provider_connection(connection)

        if is_primary:
            for item in self.list_connections(household_id=household_id, domain=domain):
                if item.id != connection.id:
                    item.is_primary = False
                    item.updated_at = now
                    self._persist_provider_connection(item)

        self.audit_service.log(
            household_id,
            "provider.connection_upserted",
            connection.id,
            {
                "provider_name": provider_name,
                "domain": domain.value,
                "is_primary": connection.is_primary,
                "status": connection.status.value,
            },
        )
        return connection

    def create_session(
        self,
        household_id: str,
        provider_name: str,
        domain: ProviderDomain,
        redirect_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        expires_in_minutes: int = 30,
    ) -> ProviderSession:
        now = utc_now()
        session = ProviderSession(
            id=generate_id("psess"),
            household_id=household_id,
            provider_name=provider_name,
            domain=domain,
            status=ProviderSessionStatus.CREATED,
            redirect_url=redirect_url,
            expires_at=now + timedelta(minutes=max(5, expires_in_minutes)),
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self.store.provider_sessions[session.id] = session
        self._persist_provider_session(session)
        self.audit_service.log(
            household_id,
            "provider.session_created",
            session.id,
            {
                "provider_name": provider_name,
                "domain": domain.value,
                "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            },
        )
        return session

    def complete_session(
        self,
        session_id: str,
        success: bool,
        provider_session_ref: str | None = None,
        credentials_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderSession:
        session = self.store.provider_sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id '{session_id}'")
        now = utc_now()
        if session.expires_at and session.expires_at <= now and success:
            success = False
            session.status = ProviderSessionStatus.EXPIRED
        elif success:
            session.status = ProviderSessionStatus.EXCHANGED
        else:
            session.status = ProviderSessionStatus.FAILED

        session.provider_session_ref = provider_session_ref
        if metadata:
            session.metadata.update(metadata)
        session.updated_at = now
        self._persist_provider_session(session)

        if session.status == ProviderSessionStatus.EXCHANGED:
            existing_in_domain = self.list_connections(
                household_id=session.household_id,
                domain=session.domain,
            )
            self.upsert_connection(
                household_id=session.household_id,
                provider_name=session.provider_name,
                domain=session.domain,
                is_primary=not existing_in_domain,
                is_enabled=True,
                credentials_ref=credentials_ref,
                metadata={"linked_via_session_id": session.id},
            )

        self.audit_service.log(
            session.household_id,
            "provider.session_completed",
            session.id,
            {
                "status": session.status.value,
                "provider_name": session.provider_name,
                "domain": session.domain.value,
            },
        )
        return session

    def list_sessions(self, household_id: str | None = None) -> list[ProviderSession]:
        items = list(self.store.provider_sessions.values())
        if household_id is not None:
            items = [item for item in items if item.household_id == household_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def get_session(self, session_id: str) -> ProviderSession | None:
        return self.store.provider_sessions.get(session_id)

    def list_connections(
        self,
        household_id: str | None = None,
        domain: ProviderDomain | None = None,
    ) -> list[ProviderConnection]:
        items = list(self.store.provider_connections.values())
        if household_id is not None:
            items = [item for item in items if item.household_id == household_id]
        if domain is not None:
            items = [item for item in items if item.domain == domain]
        return sorted(items, key=lambda item: (item.household_id, item.domain.value, not item.is_primary, item.provider_name))

    def trigger_sync(self, household_id: str, domain: ProviderDomain) -> ProviderSyncJob:
        job = ProviderSyncJob(
            id=generate_id("sync"),
            household_id=household_id,
            domain=domain,
            status=ProviderSyncStatus.RUNNING,
            started_at=utc_now(),
        )
        self.store.provider_sync_jobs[job.id] = job
        connections = self._active_connections_for(household_id, domain)
        if not connections:
            fallback = ProviderConnection(
                id=generate_id("conn"),
                household_id=household_id,
                provider_name="sandbox_primary",
                domain=domain,
                is_primary=True,
            )
            connections = [fallback]

        for connection in connections:
            job.provider_attempts.append(connection.provider_name)
            adapter = self._resolve_adapter(connection.provider_name, domain)
            try:
                result = adapter.sync(household_id, connection)
            except Exception as error:  # noqa: BLE001
                job.errors.append(f"{connection.provider_name}: {error}")
                continue

            job.synced_records += int(result.get("records", 0))
            job.status = ProviderSyncStatus.SUCCESS
            job.completed_at = utc_now()
            self.audit_service.log(
                household_id,
                "provider.sync_completed",
                job.id,
                {
                    "domain": domain.value,
                    "provider": connection.provider_name,
                    "records": job.synced_records,
                },
            )
            self._persist_provider_sync_job(job)
            return job

        job.status = ProviderSyncStatus.FAILED
        job.completed_at = utc_now()
        self.audit_service.log(
            household_id,
            "provider.sync_failed",
            job.id,
            {"domain": domain.value, "errors": job.errors},
        )
        self._persist_provider_sync_job(job)
        return job

    def get_sync_job(self, sync_id: str) -> ProviderSyncJob | None:
        return self.store.provider_sync_jobs.get(sync_id)

    def trigger_household_sync(
        self,
        household_id: str,
        domains: list[ProviderDomain] | None = None,
    ) -> HouseholdSyncRun:
        domain_list = domains or list(ProviderDomain)
        run = HouseholdSyncRun(
            id=generate_id("hsync"),
            household_id=household_id,
            domains=domain_list,
            status=HouseholdSyncRunStatus.RUNNING,
            started_at=utc_now(),
        )
        self.store.household_sync_runs[run.id] = run

        statuses: list[ProviderSyncStatus] = []
        for domain in domain_list:
            job = self.trigger_sync(household_id=household_id, domain=domain)
            run.job_ids.append(job.id)
            statuses.append(job.status)
            if job.status == ProviderSyncStatus.FAILED and job.errors:
                run.errors.extend(job.errors)

        if statuses and all(item == ProviderSyncStatus.SUCCESS for item in statuses):
            run.status = HouseholdSyncRunStatus.SUCCESS
        elif statuses and any(item == ProviderSyncStatus.SUCCESS for item in statuses):
            run.status = HouseholdSyncRunStatus.PARTIAL
        else:
            run.status = HouseholdSyncRunStatus.FAILED
        run.completed_at = utc_now()

        self.audit_service.log(
            household_id,
            "provider.household_sync_completed",
            run.id,
            {
                "status": run.status.value,
                "domains": [item.value for item in run.domains],
                "job_ids": run.job_ids,
                "errors": run.errors,
            },
        )
        self._persist_household_sync_run(run)
        return run

    def get_household_sync_run(self, run_id: str) -> HouseholdSyncRun | None:
        return self.store.household_sync_runs.get(run_id)

    def health(self, household_id: str | None = None) -> list[dict[str, Any]]:
        report: list[dict[str, Any]] = []
        connections = self.list_connections(household_id=household_id)
        seen: set[tuple[str, ProviderDomain]] = set()
        disabled_providers = self.disabled_execution_providers()

        for connection in connections:
            key = (connection.provider_name, connection.domain)
            if key in seen:
                continue
            seen.add(key)
            adapter = self._resolve_adapter(connection.provider_name, connection.domain)
            check = adapter.health()
            report.append(
                {
                    "provider_name": connection.provider_name,
                    "domain": connection.domain.value,
                    "status": check.get("status", "unknown"),
                    "checked_at": check.get("checked_at", utc_now().isoformat()),
                    "household_id": connection.household_id,
                    "execution_disabled": connection.provider_name in disabled_providers,
                }
            )

        if not report:
            for domain in ProviderDomain:
                adapter = self._resolve_adapter("sandbox_primary", domain)
                check = adapter.health()
                report.append(
                    {
                        "provider_name": "sandbox_primary",
                        "domain": domain.value,
                        "status": check.get("status", "healthy"),
                        "checked_at": check.get("checked_at", utc_now().isoformat()),
                        "household_id": household_id,
                        "execution_disabled": "sandbox_primary" in disabled_providers,
                    }
                )

        return report

    def dispatch_action(
        self,
        household_id: str,
        action: ActionProposal,
        idempotency_key: str | None = None,
    ) -> ProviderDispatchResult:
        domain = self.ACTION_DOMAIN_MAP[action.action_type]
        if not self.is_execution_enabled(action.action_type):
            raise ValueError(f"Execution disabled for action type '{action.action_type.value}'")

        connections = self._active_connections_for(household_id, domain)
        if not connections:
            connections = [
                ProviderConnection(
                    id=generate_id("conn"),
                    household_id=household_id,
                    provider_name="sandbox_primary",
                    domain=domain,
                    is_primary=True,
                ),
                ProviderConnection(
                    id=generate_id("conn"),
                    household_id=household_id,
                    provider_name="sandbox_fallback",
                    domain=domain,
                    is_primary=False,
                ),
            ]

        disabled_providers = self.disabled_execution_providers()
        attempts: list[str] = []
        for index, connection in enumerate(connections):
            if connection.provider_name in disabled_providers:
                attempts.append(f"{connection.provider_name}(disabled)")
                continue
            attempts.append(connection.provider_name)
            adapter = self._resolve_adapter(connection.provider_name, domain)
            result = adapter.execute(
                household_id=household_id,
                action=action,
                connection=connection,
                idempotency_key=idempotency_key,
            )
            if result.result == "success":
                result.fallback_used = index > 0
                result.provider_attempts = attempts
                return result

        if disabled_providers and not [item for item in attempts if "(disabled)" not in item]:
            return ProviderDispatchResult(
                provider_name="disabled",
                result="failed",
                partner_ref=f"disabled_{idempotency_key or generate_id('partner')}",
                message="All execution providers are disabled by kill switch",
                fallback_used=False,
                provider_attempts=attempts,
            )

        final = ProviderDispatchResult(
            provider_name=attempts[-1] if attempts else "unknown",
            result="failed",
            partner_ref=f"failed_{idempotency_key or generate_id('partner')}",
            message="All provider attempts failed",
            fallback_used=len(attempts) > 1,
            provider_attempts=attempts,
        )
        return final

    def _active_connections_for(self, household_id: str, domain: ProviderDomain) -> list[ProviderConnection]:
        connections = [
            item
            for item in self.list_connections(household_id=household_id, domain=domain)
            if item.status == ProviderConnectionStatus.ACTIVE
        ]
        return sorted(connections, key=lambda item: (not item.is_primary, item.updated_at))

    def _find_connection(
        self,
        household_id: str,
        provider_name: str,
        domain: ProviderDomain,
    ) -> ProviderConnection | None:
        for item in self.store.provider_connections.values():
            if (
                item.household_id == household_id
                and item.provider_name == provider_name
                and item.domain == domain
            ):
                return item
        return None

    def _resolve_adapter(self, provider_name: str, domain: ProviderDomain) -> ProviderAdapter:
        adapter = self.adapters.get((provider_name, domain))
        if adapter is not None:
            return adapter
        fallback = self.adapters.get(("sandbox_primary", domain))
        if fallback is None:
            fallback = ProviderAdapter(provider_name="sandbox_primary", domain=domain)
            self.register_adapter(fallback)
        return fallback

    def _persist_provider_connection(self, connection: ProviderConnection) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_provider_connection(connection)

    def _persist_provider_session(self, session: ProviderSession) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_provider_session(session)

    def _persist_provider_sync_job(self, sync_job: ProviderSyncJob) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_provider_sync_job(sync_job)

    def _persist_household_sync_run(self, run: HouseholdSyncRun) -> None:
        if self.relational_persistence is None:
            return
        self.relational_persistence.upsert_household_sync_run(run)
