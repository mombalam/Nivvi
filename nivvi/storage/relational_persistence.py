from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from threading import Lock
from typing import Any

from nivvi.domain.models import (
    Account,
    AccountType,
    ActionProposal,
    ActionStatus,
    ActionType,
    AuditEvent,
    ChatChannel,
    ChatMessage,
    DeadlineItem,
    DeadlineStatus,
    Direction,
    ExecutionAttempt,
    ExecutionReceipt,
    GoalPlan,
    Household,
    HouseholdSyncRun,
    HouseholdSyncRunStatus,
    ProviderConnection,
    ProviderConnectionStatus,
    ProviderDomain,
    ProviderSession,
    ProviderSessionStatus,
    ProviderSyncJob,
    ProviderSyncStatus,
    Transaction,
    UserRule,
)
from nivvi.storage.in_memory import InMemoryStore


class RelationalPersistence:
    """Optional relational persistence for core execution/audit entities."""

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
            except ImportError as error:  # pragma: no cover - only hit when postgres mode is enabled
                raise RuntimeError(
                    "Relational persistence requires sqlalchemy when NIVVI_STORE_BACKEND=postgres"
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
                    CREATE TABLE IF NOT EXISTS action_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      action_type TEXT NOT NULL,
                      amount DOUBLE PRECISION NOT NULL,
                      currency TEXT NOT NULL,
                      due_at TIMESTAMPTZ NULL,
                      category TEXT NOT NULL,
                      rationale_json TEXT NOT NULL,
                      risk_score DOUBLE PRECISION NOT NULL,
                      requires_approval BOOLEAN NOT NULL,
                      status TEXT NOT NULL,
                      approval_step INTEGER NOT NULL,
                      violations_json TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS action_approval_records (
                      id TEXT PRIMARY KEY,
                      action_id TEXT NOT NULL,
                      household_id TEXT NOT NULL,
                      step TEXT NOT NULL,
                      approval_step INTEGER NOT NULL,
                      status TEXT NOT NULL,
                      actor_user_id TEXT NULL,
                      created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS execution_records (
                      action_id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      partner_ref TEXT NOT NULL,
                      submitted_at TIMESTAMPTZ NOT NULL,
                      result TEXT NOT NULL,
                      reversible_until TIMESTAMPTZ NULL,
                      message TEXT NOT NULL,
                      provider_name TEXT NULL,
                      fallback_used BOOLEAN NOT NULL,
                      provider_attempts_json TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS execution_attempt_records (
                      id TEXT PRIMARY KEY,
                      action_id TEXT NOT NULL,
                      household_id TEXT NOT NULL,
                      attempt_number INTEGER NOT NULL,
                      idempotency_key TEXT NULL,
                      partner_ref TEXT NOT NULL,
                      result TEXT NOT NULL,
                      message TEXT NOT NULL,
                      status_before TEXT NOT NULL,
                      status_after TEXT NOT NULL,
                      provider_name TEXT NULL,
                      attempted_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS audit_event_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      event_type TEXT NOT NULL,
                      entity_id TEXT NOT NULL,
                      details_json TEXT NOT NULL,
                      previous_hash TEXT NULL,
                      event_hash TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS household_records (
                      id TEXT PRIMARY KEY,
                      name TEXT NOT NULL,
                      base_currency TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS account_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      institution TEXT NOT NULL,
                      account_type TEXT NOT NULL,
                      currency TEXT NOT NULL,
                      balance DOUBLE PRECISION NOT NULL,
                      metadata_json TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS transaction_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      account_id TEXT NOT NULL,
                      amount DOUBLE PRECISION NOT NULL,
                      currency TEXT NOT NULL,
                      direction TEXT NOT NULL,
                      description TEXT NOT NULL,
                      category TEXT NOT NULL,
                      booked_at TIMESTAMPTZ NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS deadline_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      source TEXT NOT NULL,
                      title TEXT NOT NULL,
                      jurisdiction TEXT NOT NULL,
                      due_at TIMESTAMPTZ NOT NULL,
                      penalty_risk TEXT NOT NULL,
                      amount DOUBLE PRECISION NULL,
                      status TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS goal_records (
                      goal_id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      name TEXT NOT NULL,
                      target_amount DOUBLE PRECISION NOT NULL,
                      target_date TIMESTAMPTZ NOT NULL,
                      recommended_contribution DOUBLE PRECISION NOT NULL,
                      tradeoffs_json TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS rule_records (
                      rule_id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      scope TEXT NOT NULL,
                      version INTEGER NOT NULL,
                      is_active BOOLEAN NOT NULL,
                      superseded_at TIMESTAMPTZ NULL,
                      superseded_by_rule_id TEXT NULL,
                      daily_amount_limit DOUBLE PRECISION NULL,
                      max_single_action DOUBLE PRECISION NULL,
                      blocked_categories_json TEXT NOT NULL,
                      blocked_action_types_json TEXT NOT NULL,
                      require_approval_always BOOLEAN NOT NULL,
                      anomaly_detection_enabled BOOLEAN NOT NULL,
                      anomaly_expense_multiplier DOUBLE PRECISION NOT NULL,
                      anomaly_income_multiplier DOUBLE PRECISION NOT NULL,
                      anomaly_min_expense_amount DOUBLE PRECISION NOT NULL,
                      anomaly_min_income_amount DOUBLE PRECISION NOT NULL,
                      weekly_planning_enabled BOOLEAN NOT NULL,
                      weekly_drift_threshold_percent DOUBLE PRECISION NOT NULL,
                      weekly_min_delta_amount DOUBLE PRECISION NOT NULL,
                      weekly_cooldown_days INTEGER NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_message_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      channel TEXT NOT NULL,
                      user_id TEXT NULL,
                      sender TEXT NOT NULL,
                      text TEXT NOT NULL,
                      metadata_json TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS channel_identity_records (
                      identity_key TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      channel TEXT NOT NULL,
                      user_handle TEXT NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS provider_connection_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      provider_name TEXT NOT NULL,
                      domain TEXT NOT NULL,
                      is_primary BOOLEAN NOT NULL,
                      status TEXT NOT NULL,
                      credentials_ref TEXT NULL,
                      metadata_json TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS provider_session_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      provider_name TEXT NOT NULL,
                      domain TEXT NOT NULL,
                      status TEXT NOT NULL,
                      redirect_url TEXT NULL,
                      expires_at TIMESTAMPTZ NULL,
                      provider_session_ref TEXT NULL,
                      metadata_json TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL,
                      updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS provider_sync_job_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      domain TEXT NOT NULL,
                      status TEXT NOT NULL,
                      provider_attempts_json TEXT NOT NULL,
                      synced_records INTEGER NOT NULL,
                      errors_json TEXT NOT NULL,
                      started_at TIMESTAMPTZ NOT NULL,
                      completed_at TIMESTAMPTZ NULL
                    )
                    """
                )
            )
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS household_sync_run_records (
                      id TEXT PRIMARY KEY,
                      household_id TEXT NOT NULL,
                      domains_json TEXT NOT NULL,
                      status TEXT NOT NULL,
                      job_ids_json TEXT NOT NULL,
                      errors_json TEXT NOT NULL,
                      started_at TIMESTAMPTZ NOT NULL,
                      completed_at TIMESTAMPTZ NULL
                    )
                    """
                )
            )
        self._initialized = True

    def load_into(self, store: InMemoryStore) -> bool:
        if not self.enabled:
            return False
        self._init_schema()
        assert self._engine is not None
        assert self._text is not None

        with self._engine.connect() as conn:
            count_row = conn.execute(
                self._text(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM household_records) AS household_count,
                      (SELECT COUNT(*) FROM account_records) AS account_count,
                      (SELECT COUNT(*) FROM transaction_records) AS transaction_count,
                      (SELECT COUNT(*) FROM deadline_records) AS deadline_count,
                      (SELECT COUNT(*) FROM goal_records) AS goal_count,
                      (SELECT COUNT(*) FROM rule_records) AS rule_count,
                      (SELECT COUNT(*) FROM chat_message_records) AS chat_count,
                      (SELECT COUNT(*) FROM channel_identity_records) AS identity_count,
                      (SELECT COUNT(*) FROM provider_connection_records) AS provider_connection_count,
                      (SELECT COUNT(*) FROM provider_session_records) AS provider_session_count,
                      (SELECT COUNT(*) FROM provider_sync_job_records) AS provider_sync_job_count,
                      (SELECT COUNT(*) FROM household_sync_run_records) AS household_sync_run_count,
                      (SELECT COUNT(*) FROM action_records) AS action_count,
                      (SELECT COUNT(*) FROM execution_records) AS execution_count,
                      (SELECT COUNT(*) FROM audit_event_records) AS audit_count
                    """
                )
            ).mappings().first()
            if not count_row:
                return False

            has_data = sum(int(value) for value in count_row.values()) > 0
            if not has_data:
                return False
            has_households = int(count_row["household_count"]) > 0
            has_accounts = int(count_row["account_count"]) > 0
            has_transactions = int(count_row["transaction_count"]) > 0
            has_deadlines = int(count_row["deadline_count"]) > 0
            has_goals = int(count_row["goal_count"]) > 0
            has_rules = int(count_row["rule_count"]) > 0
            has_chat = int(count_row["chat_count"]) > 0
            has_identities = int(count_row["identity_count"]) > 0
            has_provider_connections = int(count_row["provider_connection_count"]) > 0
            has_provider_sessions = int(count_row["provider_session_count"]) > 0
            has_provider_sync_jobs = int(count_row["provider_sync_job_count"]) > 0
            has_household_sync_runs = int(count_row["household_sync_run_count"]) > 0
            has_actions = int(count_row["action_count"]) > 0
            has_executions = int(count_row["execution_count"]) > 0
            has_audit = int(count_row["audit_count"]) > 0

            household_rows = conn.execute(self._text("SELECT * FROM household_records")).mappings().all()
            account_rows = conn.execute(self._text("SELECT * FROM account_records")).mappings().all()
            transaction_rows = conn.execute(
                self._text("SELECT * FROM transaction_records ORDER BY booked_at ASC")
            ).mappings().all()
            deadline_rows = conn.execute(self._text("SELECT * FROM deadline_records")).mappings().all()
            goal_rows = conn.execute(self._text("SELECT * FROM goal_records")).mappings().all()
            rule_rows = conn.execute(self._text("SELECT * FROM rule_records")).mappings().all()
            chat_rows = conn.execute(
                self._text("SELECT * FROM chat_message_records ORDER BY created_at ASC")
            ).mappings().all()
            identity_rows = conn.execute(self._text("SELECT * FROM channel_identity_records")).mappings().all()
            provider_connection_rows = conn.execute(
                self._text("SELECT * FROM provider_connection_records")
            ).mappings().all()
            provider_session_rows = conn.execute(
                self._text("SELECT * FROM provider_session_records")
            ).mappings().all()
            provider_sync_job_rows = conn.execute(
                self._text("SELECT * FROM provider_sync_job_records")
            ).mappings().all()
            household_sync_run_rows = conn.execute(
                self._text("SELECT * FROM household_sync_run_records")
            ).mappings().all()
            action_rows = conn.execute(self._text("SELECT * FROM action_records")).mappings().all()
            execution_rows = conn.execute(self._text("SELECT * FROM execution_records")).mappings().all()
            attempt_rows = conn.execute(
                self._text("SELECT * FROM execution_attempt_records ORDER BY attempted_at ASC")
            ).mappings().all()
            audit_rows = conn.execute(
                self._text("SELECT * FROM audit_event_records ORDER BY created_at ASC")
            ).mappings().all()

        if has_households:
            store.households = {}
            for row in household_rows:
                household = Household(
                    id=row["id"],
                    name=row["name"],
                    base_currency=row["base_currency"],
                    created_at=row["created_at"],
                )
                store.households[household.id] = household

        if has_accounts:
            store.accounts = {}
            for row in account_rows:
                account = Account(
                    id=row["id"],
                    household_id=row["household_id"],
                    institution=row["institution"],
                    account_type=AccountType(row["account_type"]),
                    currency=row["currency"],
                    balance=float(row["balance"]),
                    metadata=_json_loads_dict(row["metadata_json"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                store.accounts[account.id] = account

        if has_transactions:
            store.transactions = {}
            for row in transaction_rows:
                transaction = Transaction(
                    id=row["id"],
                    household_id=row["household_id"],
                    account_id=row["account_id"],
                    amount=float(row["amount"]),
                    currency=row["currency"],
                    direction=Direction(row["direction"]),
                    description=row["description"],
                    category=row["category"],
                    booked_at=row["booked_at"],
                    created_at=row["created_at"],
                )
                store.transactions[transaction.id] = transaction

        if has_deadlines:
            store.deadlines = {}
            for row in deadline_rows:
                deadline = DeadlineItem(
                    id=row["id"],
                    household_id=row["household_id"],
                    source=row["source"],
                    title=row["title"],
                    jurisdiction=row["jurisdiction"],
                    due_at=row["due_at"],
                    penalty_risk=row["penalty_risk"],
                    amount=row["amount"],
                    status=DeadlineStatus(row["status"]),
                )
                store.deadlines[deadline.id] = deadline

        if has_goals:
            store.goals = {}
            for row in goal_rows:
                goal = GoalPlan(
                    goal_id=row["goal_id"],
                    household_id=row["household_id"],
                    name=row["name"],
                    target_amount=float(row["target_amount"]),
                    target_date=row["target_date"],
                    recommended_contribution=float(row["recommended_contribution"]),
                    tradeoffs=_json_loads_list(row["tradeoffs_json"]),
                )
                store.goals[goal.goal_id] = goal

        if has_rules:
            store.rules = defaultdict(list)
            for row in rule_rows:
                rule = UserRule(
                    rule_id=row["rule_id"],
                    household_id=row["household_id"],
                    scope=row["scope"],
                    version=int(row["version"]),
                    is_active=bool(row["is_active"]),
                    superseded_at=row["superseded_at"],
                    superseded_by_rule_id=row["superseded_by_rule_id"],
                    daily_amount_limit=row["daily_amount_limit"],
                    max_single_action=row["max_single_action"],
                    blocked_categories=_json_loads_list(row["blocked_categories_json"]),
                    blocked_action_types=[ActionType(item) for item in _json_loads_list(row["blocked_action_types_json"])],
                    require_approval_always=bool(row["require_approval_always"]),
                    anomaly_detection_enabled=bool(row["anomaly_detection_enabled"]),
                    anomaly_expense_multiplier=float(row["anomaly_expense_multiplier"]),
                    anomaly_income_multiplier=float(row["anomaly_income_multiplier"]),
                    anomaly_min_expense_amount=float(row["anomaly_min_expense_amount"]),
                    anomaly_min_income_amount=float(row["anomaly_min_income_amount"]),
                    weekly_planning_enabled=bool(row["weekly_planning_enabled"]),
                    weekly_drift_threshold_percent=float(row["weekly_drift_threshold_percent"]),
                    weekly_min_delta_amount=float(row["weekly_min_delta_amount"]),
                    weekly_cooldown_days=int(row["weekly_cooldown_days"]),
                    created_at=row["created_at"],
                )
                store.rules[rule.household_id].append(rule)

        if has_chat:
            store.chat_messages = []
            for row in chat_rows:
                message = ChatMessage(
                    id=row["id"],
                    household_id=row["household_id"],
                    channel=ChatChannel(row["channel"]),
                    user_id=row["user_id"],
                    sender=row["sender"],
                    text=row["text"],
                    metadata=_json_loads_dict(row["metadata_json"]),
                    created_at=row["created_at"],
                )
                store.chat_messages.append(message)

        if has_identities:
            store.channel_identities = {}
            for row in identity_rows:
                store.channel_identities[row["identity_key"]] = row["household_id"]

        if has_provider_connections:
            store.provider_connections = {}
            for row in provider_connection_rows:
                connection = ProviderConnection(
                    id=row["id"],
                    household_id=row["household_id"],
                    provider_name=row["provider_name"],
                    domain=ProviderDomain(row["domain"]),
                    is_primary=bool(row["is_primary"]),
                    status=ProviderConnectionStatus(row["status"]),
                    credentials_ref=row["credentials_ref"],
                    metadata=_json_loads_dict(row["metadata_json"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                store.provider_connections[connection.id] = connection

        if has_provider_sessions:
            store.provider_sessions = {}
            for row in provider_session_rows:
                session = ProviderSession(
                    id=row["id"],
                    household_id=row["household_id"],
                    provider_name=row["provider_name"],
                    domain=ProviderDomain(row["domain"]),
                    status=ProviderSessionStatus(row["status"]),
                    redirect_url=row["redirect_url"],
                    expires_at=row["expires_at"],
                    provider_session_ref=row["provider_session_ref"],
                    metadata=_json_loads_dict(row["metadata_json"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                store.provider_sessions[session.id] = session

        if has_provider_sync_jobs:
            store.provider_sync_jobs = {}
            for row in provider_sync_job_rows:
                sync_job = ProviderSyncJob(
                    id=row["id"],
                    household_id=row["household_id"],
                    domain=ProviderDomain(row["domain"]),
                    status=ProviderSyncStatus(row["status"]),
                    provider_attempts=_json_loads_list(row["provider_attempts_json"]),
                    synced_records=int(row["synced_records"]),
                    errors=_json_loads_list(row["errors_json"]),
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                )
                store.provider_sync_jobs[sync_job.id] = sync_job

        if has_household_sync_runs:
            store.household_sync_runs = {}
            for row in household_sync_run_rows:
                run = HouseholdSyncRun(
                    id=row["id"],
                    household_id=row["household_id"],
                    domains=[ProviderDomain(item) for item in _json_loads_list(row["domains_json"])],
                    status=HouseholdSyncRunStatus(row["status"]),
                    job_ids=_json_loads_list(row["job_ids_json"]),
                    errors=_json_loads_list(row["errors_json"]),
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                )
                store.household_sync_runs[run.id] = run

        if has_actions:
            store.actions = {}
            for row in action_rows:
                action = ActionProposal(
                    id=row["id"],
                    household_id=row["household_id"],
                    action_type=ActionType(row["action_type"]),
                    amount=float(row["amount"]),
                    currency=row["currency"],
                    due_at=row["due_at"],
                    category=row["category"],
                    rationale=_json_loads_list(row["rationale_json"]),
                    risk_score=float(row["risk_score"]),
                    requires_approval=bool(row["requires_approval"]),
                    status=ActionStatus(row["status"]),
                    approval_step=int(row["approval_step"]),
                    violations=_json_loads_list(row["violations_json"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                store.actions[action.id] = action

        if has_executions:
            store.executions = {}
            for row in execution_rows:
                receipt = ExecutionReceipt(
                    action_id=row["action_id"],
                    partner_ref=row["partner_ref"],
                    submitted_at=row["submitted_at"],
                    result=row["result"],
                    reversible_until=row["reversible_until"],
                    message=row["message"],
                    provider_name=row["provider_name"],
                    fallback_used=bool(row["fallback_used"]),
                    provider_attempts=_json_loads_list(row["provider_attempts_json"]),
                )
                store.executions[receipt.action_id] = receipt

        if attempt_rows:
            store.execution_attempts = defaultdict(list)
            store.execution_idempotency_keys = {}
            for row in attempt_rows:
                attempt = ExecutionAttempt(
                    action_id=row["action_id"],
                    attempt_number=int(row["attempt_number"]),
                    idempotency_key=row["idempotency_key"],
                    partner_ref=row["partner_ref"],
                    result=row["result"],
                    message=row["message"],
                    status_before=ActionStatus(row["status_before"]),
                    status_after=ActionStatus(row["status_after"]),
                    provider_name=row["provider_name"],
                    attempted_at=row["attempted_at"],
                )
                store.execution_attempts[attempt.action_id].append(attempt)
                if attempt.idempotency_key:
                    store.execution_idempotency_keys[attempt.idempotency_key] = attempt.action_id

        if has_audit:
            store.audit_events = []
            for row in audit_rows:
                event = AuditEvent(
                    id=row["id"],
                    household_id=row["household_id"],
                    event_type=row["event_type"],
                    entity_id=row["entity_id"],
                    details=_json_loads_dict(row["details_json"]),
                    previous_hash=row["previous_hash"],
                    event_hash=row["event_hash"],
                    created_at=row["created_at"],
                )
                store.audit_events.append(event)
        return True

    def upsert_action(self, action: ActionProposal) -> None:
        if not self.enabled:
            return
        assert self._engine is not None
        assert self._text is not None
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        """
                        INSERT INTO action_records (
                          id, household_id, action_type, amount, currency, due_at, category,
                          rationale_json, risk_score, requires_approval, status, approval_step,
                          violations_json, created_at, updated_at
                        ) VALUES (
                          :id, :household_id, :action_type, :amount, :currency, :due_at, :category,
                          :rationale_json, :risk_score, :requires_approval, :status, :approval_step,
                          :violations_json, :created_at, :updated_at
                        )
                        ON CONFLICT (id) DO UPDATE SET
                          household_id = EXCLUDED.household_id,
                          action_type = EXCLUDED.action_type,
                          amount = EXCLUDED.amount,
                          currency = EXCLUDED.currency,
                          due_at = EXCLUDED.due_at,
                          category = EXCLUDED.category,
                          rationale_json = EXCLUDED.rationale_json,
                          risk_score = EXCLUDED.risk_score,
                          requires_approval = EXCLUDED.requires_approval,
                          status = EXCLUDED.status,
                          approval_step = EXCLUDED.approval_step,
                          violations_json = EXCLUDED.violations_json,
                          updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": action.id,
                        "household_id": action.household_id,
                        "action_type": action.action_type.value,
                        "amount": action.amount,
                        "currency": action.currency,
                        "due_at": action.due_at,
                        "category": action.category,
                        "rationale_json": json.dumps(action.rationale),
                        "risk_score": action.risk_score,
                        "requires_approval": action.requires_approval,
                        "status": action.status.value,
                        "approval_step": action.approval_step,
                        "violations_json": json.dumps(action.violations),
                        "created_at": action.created_at,
                        "updated_at": action.updated_at,
                    },
                )

    def record_approval(
        self,
        approval_id: str,
        action_id: str,
        household_id: str,
        step: str,
        approval_step: int,
        status: str,
        actor_user_id: str | None,
        created_at: Any,
    ) -> None:
        if not self.enabled:
            return
        assert self._engine is not None
        assert self._text is not None
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        """
                        INSERT INTO action_approval_records (
                          id, action_id, household_id, step, approval_step, status, actor_user_id, created_at
                        ) VALUES (
                          :id, :action_id, :household_id, :step, :approval_step, :status, :actor_user_id, :created_at
                        )
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": approval_id,
                        "action_id": action_id,
                        "household_id": household_id,
                        "step": step,
                        "approval_step": approval_step,
                        "status": status,
                        "actor_user_id": actor_user_id,
                        "created_at": created_at,
                    },
                )

    def upsert_execution(self, household_id: str, receipt: ExecutionReceipt) -> None:
        if not self.enabled:
            return
        assert self._engine is not None
        assert self._text is not None
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        """
                        INSERT INTO execution_records (
                          action_id, household_id, partner_ref, submitted_at, result, reversible_until,
                          message, provider_name, fallback_used, provider_attempts_json
                        ) VALUES (
                          :action_id, :household_id, :partner_ref, :submitted_at, :result, :reversible_until,
                          :message, :provider_name, :fallback_used, :provider_attempts_json
                        )
                        ON CONFLICT (action_id) DO UPDATE SET
                          household_id = EXCLUDED.household_id,
                          partner_ref = EXCLUDED.partner_ref,
                          submitted_at = EXCLUDED.submitted_at,
                          result = EXCLUDED.result,
                          reversible_until = EXCLUDED.reversible_until,
                          message = EXCLUDED.message,
                          provider_name = EXCLUDED.provider_name,
                          fallback_used = EXCLUDED.fallback_used,
                          provider_attempts_json = EXCLUDED.provider_attempts_json
                        """
                    ),
                    {
                        "action_id": receipt.action_id,
                        "household_id": household_id,
                        "partner_ref": receipt.partner_ref,
                        "submitted_at": receipt.submitted_at,
                        "result": receipt.result,
                        "reversible_until": receipt.reversible_until,
                        "message": receipt.message,
                        "provider_name": receipt.provider_name,
                        "fallback_used": receipt.fallback_used,
                        "provider_attempts_json": json.dumps(receipt.provider_attempts),
                    },
                )

    def append_execution_attempt(self, attempt_id: str, household_id: str, attempt: ExecutionAttempt) -> None:
        if not self.enabled:
            return
        assert self._engine is not None
        assert self._text is not None
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        """
                        INSERT INTO execution_attempt_records (
                          id, action_id, household_id, attempt_number, idempotency_key, partner_ref,
                          result, message, status_before, status_after, provider_name, attempted_at
                        ) VALUES (
                          :id, :action_id, :household_id, :attempt_number, :idempotency_key, :partner_ref,
                          :result, :message, :status_before, :status_after, :provider_name, :attempted_at
                        )
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": attempt_id,
                        "action_id": attempt.action_id,
                        "household_id": household_id,
                        "attempt_number": attempt.attempt_number,
                        "idempotency_key": attempt.idempotency_key,
                        "partner_ref": attempt.partner_ref,
                        "result": attempt.result,
                        "message": attempt.message,
                        "status_before": attempt.status_before.value,
                        "status_after": attempt.status_after.value,
                        "provider_name": attempt.provider_name,
                        "attempted_at": attempt.attempted_at,
                    },
                )

    def append_audit_event(self, event: AuditEvent) -> None:
        if not self.enabled:
            return
        assert self._engine is not None
        assert self._text is not None
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        """
                        INSERT INTO audit_event_records (
                          id, household_id, event_type, entity_id, details_json,
                          previous_hash, event_hash, created_at
                        ) VALUES (
                          :id, :household_id, :event_type, :entity_id, :details_json,
                          :previous_hash, :event_hash, :created_at
                        )
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": event.id,
                        "household_id": event.household_id,
                        "event_type": event.event_type,
                        "entity_id": event.entity_id,
                        "details_json": json.dumps(event.details),
                        "previous_hash": event.previous_hash,
                        "event_hash": event.event_hash,
                        "created_at": event.created_at,
                    },
                )

    def upsert_household(self, household: Household) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO household_records (id, name, base_currency, created_at)
            VALUES (:id, :name, :base_currency, :created_at)
            ON CONFLICT (id) DO UPDATE SET
              name = EXCLUDED.name,
              base_currency = EXCLUDED.base_currency
            """,
            {
                "id": household.id,
                "name": household.name,
                "base_currency": household.base_currency,
                "created_at": household.created_at,
            },
        )

    def upsert_account(self, account: Account) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO account_records (
              id, household_id, institution, account_type, currency, balance, metadata_json, created_at, updated_at
            ) VALUES (
              :id, :household_id, :institution, :account_type, :currency, :balance, :metadata_json, :created_at, :updated_at
            )
            ON CONFLICT (id) DO UPDATE SET
              institution = EXCLUDED.institution,
              account_type = EXCLUDED.account_type,
              currency = EXCLUDED.currency,
              balance = EXCLUDED.balance,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = EXCLUDED.updated_at
            """,
            {
                "id": account.id,
                "household_id": account.household_id,
                "institution": account.institution,
                "account_type": account.account_type.value,
                "currency": account.currency,
                "balance": account.balance,
                "metadata_json": _json_dumps(account.metadata),
                "created_at": account.created_at,
                "updated_at": account.updated_at,
            },
        )

    def upsert_transaction(self, transaction: Transaction) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO transaction_records (
              id, household_id, account_id, amount, currency, direction, description, category, booked_at, created_at
            ) VALUES (
              :id, :household_id, :account_id, :amount, :currency, :direction, :description, :category, :booked_at, :created_at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": transaction.id,
                "household_id": transaction.household_id,
                "account_id": transaction.account_id,
                "amount": transaction.amount,
                "currency": transaction.currency,
                "direction": transaction.direction.value,
                "description": transaction.description,
                "category": transaction.category,
                "booked_at": transaction.booked_at,
                "created_at": transaction.created_at,
            },
        )

    def upsert_deadline(self, deadline: DeadlineItem) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO deadline_records (
              id, household_id, source, title, jurisdiction, due_at, penalty_risk, amount, status
            ) VALUES (
              :id, :household_id, :source, :title, :jurisdiction, :due_at, :penalty_risk, :amount, :status
            )
            ON CONFLICT (id) DO UPDATE SET
              source = EXCLUDED.source,
              title = EXCLUDED.title,
              jurisdiction = EXCLUDED.jurisdiction,
              due_at = EXCLUDED.due_at,
              penalty_risk = EXCLUDED.penalty_risk,
              amount = EXCLUDED.amount,
              status = EXCLUDED.status
            """,
            {
                "id": deadline.id,
                "household_id": deadline.household_id,
                "source": deadline.source,
                "title": deadline.title,
                "jurisdiction": deadline.jurisdiction,
                "due_at": deadline.due_at,
                "penalty_risk": deadline.penalty_risk,
                "amount": deadline.amount,
                "status": deadline.status.value,
            },
        )

    def upsert_goal(self, goal: GoalPlan) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO goal_records (
              goal_id, household_id, name, target_amount, target_date, recommended_contribution, tradeoffs_json
            ) VALUES (
              :goal_id, :household_id, :name, :target_amount, :target_date, :recommended_contribution, :tradeoffs_json
            )
            ON CONFLICT (goal_id) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              name = EXCLUDED.name,
              target_amount = EXCLUDED.target_amount,
              target_date = EXCLUDED.target_date,
              recommended_contribution = EXCLUDED.recommended_contribution,
              tradeoffs_json = EXCLUDED.tradeoffs_json
            """,
            {
                "goal_id": goal.goal_id,
                "household_id": goal.household_id,
                "name": goal.name,
                "target_amount": goal.target_amount,
                "target_date": goal.target_date,
                "recommended_contribution": goal.recommended_contribution,
                "tradeoffs_json": _json_dumps(goal.tradeoffs),
            },
        )

    def upsert_rule(self, rule: UserRule) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO rule_records (
              rule_id, household_id, scope, version, is_active, superseded_at, superseded_by_rule_id,
              daily_amount_limit, max_single_action, blocked_categories_json, blocked_action_types_json,
              require_approval_always, anomaly_detection_enabled, anomaly_expense_multiplier,
              anomaly_income_multiplier, anomaly_min_expense_amount, anomaly_min_income_amount,
              weekly_planning_enabled, weekly_drift_threshold_percent, weekly_min_delta_amount,
              weekly_cooldown_days, created_at
            ) VALUES (
              :rule_id, :household_id, :scope, :version, :is_active, :superseded_at, :superseded_by_rule_id,
              :daily_amount_limit, :max_single_action, :blocked_categories_json, :blocked_action_types_json,
              :require_approval_always, :anomaly_detection_enabled, :anomaly_expense_multiplier,
              :anomaly_income_multiplier, :anomaly_min_expense_amount, :anomaly_min_income_amount,
              :weekly_planning_enabled, :weekly_drift_threshold_percent, :weekly_min_delta_amount,
              :weekly_cooldown_days, :created_at
            )
            ON CONFLICT (rule_id) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              scope = EXCLUDED.scope,
              version = EXCLUDED.version,
              is_active = EXCLUDED.is_active,
              superseded_at = EXCLUDED.superseded_at,
              superseded_by_rule_id = EXCLUDED.superseded_by_rule_id,
              daily_amount_limit = EXCLUDED.daily_amount_limit,
              max_single_action = EXCLUDED.max_single_action,
              blocked_categories_json = EXCLUDED.blocked_categories_json,
              blocked_action_types_json = EXCLUDED.blocked_action_types_json,
              require_approval_always = EXCLUDED.require_approval_always,
              anomaly_detection_enabled = EXCLUDED.anomaly_detection_enabled,
              anomaly_expense_multiplier = EXCLUDED.anomaly_expense_multiplier,
              anomaly_income_multiplier = EXCLUDED.anomaly_income_multiplier,
              anomaly_min_expense_amount = EXCLUDED.anomaly_min_expense_amount,
              anomaly_min_income_amount = EXCLUDED.anomaly_min_income_amount,
              weekly_planning_enabled = EXCLUDED.weekly_planning_enabled,
              weekly_drift_threshold_percent = EXCLUDED.weekly_drift_threshold_percent,
              weekly_min_delta_amount = EXCLUDED.weekly_min_delta_amount,
              weekly_cooldown_days = EXCLUDED.weekly_cooldown_days
            """,
            {
                "rule_id": rule.rule_id,
                "household_id": rule.household_id,
                "scope": rule.scope,
                "version": rule.version,
                "is_active": rule.is_active,
                "superseded_at": rule.superseded_at,
                "superseded_by_rule_id": rule.superseded_by_rule_id,
                "daily_amount_limit": rule.daily_amount_limit,
                "max_single_action": rule.max_single_action,
                "blocked_categories_json": _json_dumps(rule.blocked_categories),
                "blocked_action_types_json": _json_dumps([item.value for item in rule.blocked_action_types]),
                "require_approval_always": rule.require_approval_always,
                "anomaly_detection_enabled": rule.anomaly_detection_enabled,
                "anomaly_expense_multiplier": rule.anomaly_expense_multiplier,
                "anomaly_income_multiplier": rule.anomaly_income_multiplier,
                "anomaly_min_expense_amount": rule.anomaly_min_expense_amount,
                "anomaly_min_income_amount": rule.anomaly_min_income_amount,
                "weekly_planning_enabled": rule.weekly_planning_enabled,
                "weekly_drift_threshold_percent": rule.weekly_drift_threshold_percent,
                "weekly_min_delta_amount": rule.weekly_min_delta_amount,
                "weekly_cooldown_days": rule.weekly_cooldown_days,
                "created_at": rule.created_at,
            },
        )

    def upsert_chat_message(self, message: ChatMessage) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO chat_message_records (
              id, household_id, channel, user_id, sender, text, metadata_json, created_at
            ) VALUES (
              :id, :household_id, :channel, :user_id, :sender, :text, :metadata_json, :created_at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": message.id,
                "household_id": message.household_id,
                "channel": message.channel.value,
                "user_id": message.user_id,
                "sender": message.sender,
                "text": message.text,
                "metadata_json": _json_dumps(message.metadata),
                "created_at": message.created_at,
            },
        )

    def upsert_channel_identity(
        self,
        identity_key: str,
        household_id: str,
        channel: str,
        user_handle: str,
    ) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO channel_identity_records (
              identity_key, household_id, channel, user_handle, updated_at
            ) VALUES (
              :identity_key, :household_id, :channel, :user_handle, :updated_at
            )
            ON CONFLICT (identity_key) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              channel = EXCLUDED.channel,
              user_handle = EXCLUDED.user_handle,
              updated_at = EXCLUDED.updated_at
            """,
            {
                "identity_key": identity_key,
                "household_id": household_id,
                "channel": channel,
                "user_handle": user_handle,
                "updated_at": _now_utc(),
            },
        )

    def upsert_provider_connection(self, connection: ProviderConnection) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO provider_connection_records (
              id, household_id, provider_name, domain, is_primary, status, credentials_ref, metadata_json, created_at, updated_at
            ) VALUES (
              :id, :household_id, :provider_name, :domain, :is_primary, :status, :credentials_ref, :metadata_json, :created_at, :updated_at
            )
            ON CONFLICT (id) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              provider_name = EXCLUDED.provider_name,
              domain = EXCLUDED.domain,
              is_primary = EXCLUDED.is_primary,
              status = EXCLUDED.status,
              credentials_ref = EXCLUDED.credentials_ref,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = EXCLUDED.updated_at
            """,
            {
                "id": connection.id,
                "household_id": connection.household_id,
                "provider_name": connection.provider_name,
                "domain": connection.domain.value,
                "is_primary": connection.is_primary,
                "status": connection.status.value,
                "credentials_ref": connection.credentials_ref,
                "metadata_json": _json_dumps(connection.metadata),
                "created_at": connection.created_at,
                "updated_at": connection.updated_at,
            },
        )

    def upsert_provider_session(self, session: ProviderSession) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO provider_session_records (
              id, household_id, provider_name, domain, status, redirect_url, expires_at,
              provider_session_ref, metadata_json, created_at, updated_at
            ) VALUES (
              :id, :household_id, :provider_name, :domain, :status, :redirect_url, :expires_at,
              :provider_session_ref, :metadata_json, :created_at, :updated_at
            )
            ON CONFLICT (id) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              provider_name = EXCLUDED.provider_name,
              domain = EXCLUDED.domain,
              status = EXCLUDED.status,
              redirect_url = EXCLUDED.redirect_url,
              expires_at = EXCLUDED.expires_at,
              provider_session_ref = EXCLUDED.provider_session_ref,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = EXCLUDED.updated_at
            """,
            {
                "id": session.id,
                "household_id": session.household_id,
                "provider_name": session.provider_name,
                "domain": session.domain.value,
                "status": session.status.value,
                "redirect_url": session.redirect_url,
                "expires_at": session.expires_at,
                "provider_session_ref": session.provider_session_ref,
                "metadata_json": _json_dumps(session.metadata),
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            },
        )

    def upsert_provider_sync_job(self, sync_job: ProviderSyncJob) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO provider_sync_job_records (
              id, household_id, domain, status, provider_attempts_json, synced_records, errors_json, started_at, completed_at
            ) VALUES (
              :id, :household_id, :domain, :status, :provider_attempts_json, :synced_records, :errors_json, :started_at, :completed_at
            )
            ON CONFLICT (id) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              domain = EXCLUDED.domain,
              status = EXCLUDED.status,
              provider_attempts_json = EXCLUDED.provider_attempts_json,
              synced_records = EXCLUDED.synced_records,
              errors_json = EXCLUDED.errors_json,
              completed_at = EXCLUDED.completed_at
            """,
            {
                "id": sync_job.id,
                "household_id": sync_job.household_id,
                "domain": sync_job.domain.value,
                "status": sync_job.status.value,
                "provider_attempts_json": _json_dumps(sync_job.provider_attempts),
                "synced_records": sync_job.synced_records,
                "errors_json": _json_dumps(sync_job.errors),
                "started_at": sync_job.started_at,
                "completed_at": sync_job.completed_at,
            },
        )

    def upsert_household_sync_run(self, run: HouseholdSyncRun) -> None:
        if not self.enabled:
            return
        self._execute(
            """
            INSERT INTO household_sync_run_records (
              id, household_id, domains_json, status, job_ids_json, errors_json, started_at, completed_at
            ) VALUES (
              :id, :household_id, :domains_json, :status, :job_ids_json, :errors_json, :started_at, :completed_at
            )
            ON CONFLICT (id) DO UPDATE SET
              household_id = EXCLUDED.household_id,
              domains_json = EXCLUDED.domains_json,
              status = EXCLUDED.status,
              job_ids_json = EXCLUDED.job_ids_json,
              errors_json = EXCLUDED.errors_json,
              completed_at = EXCLUDED.completed_at
            """,
            {
                "id": run.id,
                "household_id": run.household_id,
                "domains_json": _json_dumps([item.value for item in run.domains]),
                "status": run.status.value,
                "job_ids_json": _json_dumps(run.job_ids),
                "errors_json": _json_dumps(run.errors),
                "started_at": run.started_at,
                "completed_at": run.completed_at,
            },
        )

    def _execute(self, statement: str, params: dict[str, Any]) -> None:
        assert self._engine is not None
        assert self._text is not None
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(self._text(statement), params)


def _json_loads_list(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    return []


def _json_loads_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
