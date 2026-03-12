from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from nivvi.domain.models import (
    Account,
    BetaApiToken,
    BetaUser,
    ExecutionAttempt,
    ActionProposal,
    AuditEvent,
    ChatMessage,
    DeadlineItem,
    ExecutionReceipt,
    GoalPlan,
    Household,
    HouseholdSyncRun,
    PortfolioRecommendation,
    ProviderConnection,
    ProviderSession,
    ProviderSyncJob,
    RuntimeCycleMetric,
    TaxPackage,
    Transaction,
    HouseholdMembership,
    UserRule,
    WaitlistLead,
)


@dataclass
class InMemoryStore:
    households: dict[str, Household] = field(default_factory=dict)
    accounts: dict[str, Account] = field(default_factory=dict)
    transactions: dict[str, Transaction] = field(default_factory=dict)
    deadlines: dict[str, DeadlineItem] = field(default_factory=dict)
    goals: dict[str, GoalPlan] = field(default_factory=dict)
    actions: dict[str, ActionProposal] = field(default_factory=dict)
    executions: dict[str, ExecutionReceipt] = field(default_factory=dict)
    execution_attempts: dict[str, list[ExecutionAttempt]] = field(default_factory=lambda: defaultdict(list))
    execution_idempotency_keys: dict[str, str] = field(default_factory=dict)
    rules: dict[str, list[UserRule]] = field(default_factory=lambda: defaultdict(list))
    audit_events: list[AuditEvent] = field(default_factory=list)
    portfolio_recommendations: dict[str, PortfolioRecommendation] = field(default_factory=dict)
    tax_packages: dict[str, TaxPackage] = field(default_factory=dict)
    chat_messages: list[ChatMessage] = field(default_factory=list)
    channel_identities: dict[str, str] = field(default_factory=dict)
    waitlist_leads: dict[str, WaitlistLead] = field(default_factory=dict)
    anomaly_processed_transactions: set[str] = field(default_factory=set)
    last_anomaly_scan_at: dict[str, datetime] = field(default_factory=dict)
    last_weekly_planning_at: dict[str, datetime] = field(default_factory=dict)
    provider_connections: dict[str, ProviderConnection] = field(default_factory=dict)
    provider_sync_jobs: dict[str, ProviderSyncJob] = field(default_factory=dict)
    provider_sessions: dict[str, ProviderSession] = field(default_factory=dict)
    household_sync_runs: dict[str, HouseholdSyncRun] = field(default_factory=dict)
    household_enabled: dict[str, bool] = field(default_factory=dict)
    beta_users: dict[str, BetaUser] = field(default_factory=dict)
    household_memberships: dict[str, HouseholdMembership] = field(default_factory=dict)
    beta_api_tokens: dict[str, BetaApiToken] = field(default_factory=dict)
    runtime_cycle_metrics: list[RuntimeCycleMetric] = field(default_factory=list)


STORE = InMemoryStore()
