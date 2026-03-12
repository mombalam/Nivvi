from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AccountType(str, Enum):
    BANK = "bank"
    CARD = "card"
    LOAN = "loan"
    PENSION = "pension"
    INVESTMENT = "investment"


class Direction(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class ActionType(str, Enum):
    TRANSFER = "transfer"
    INVEST = "invest"
    TAX_SUBMISSION = "tax_submission"


class ActionStatus(str, Enum):
    DRAFT = "draft"
    PENDING_AUTHORIZATION = "pending_authorization"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class ChatChannel(str, Enum):
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"


class ProviderDomain(str, Enum):
    AGGREGATION = "aggregation"
    PAYMENTS = "payments"
    INVESTING = "investing"
    TAX_SUBMISSION = "tax_submission"


class ProviderConnectionStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProviderSyncStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ProviderSessionStatus(str, Enum):
    CREATED = "created"
    EXCHANGED = "exchanged"
    FAILED = "failed"
    EXPIRED = "expired"


class HouseholdSyncRunStatus(str, Enum):
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCESS = "success"
    FAILED = "failed"


class DeadlineStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    MISSED = "missed"


class OpportunityDomain(str, Enum):
    CASHFLOW = "cashflow"
    BILLS = "bills"
    DEBT = "debt"
    INVESTING = "investing"
    TAX = "tax"
    CROSS_DOMAIN = "cross_domain"


class PlaybookRunStatus(str, Enum):
    DETECTED = "detected"
    PREPARED = "prepared"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    FAILED = "failed"
    RETRY_PENDING = "retry_pending"


@dataclass
class Household:
    id: str
    name: str
    base_currency: str = "EUR"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Account:
    id: str
    household_id: str
    institution: str
    account_type: AccountType
    currency: str
    balance: float
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Transaction:
    id: str
    household_id: str
    account_id: str
    amount: float
    currency: str
    direction: Direction
    description: str
    category: str
    booked_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DeadlineItem:
    id: str
    household_id: str
    source: str
    title: str
    jurisdiction: str
    due_at: datetime
    penalty_risk: str
    amount: float | None = None
    status: DeadlineStatus = DeadlineStatus.PENDING


@dataclass
class GoalPlan:
    goal_id: str
    household_id: str
    name: str
    target_amount: float
    target_date: datetime
    recommended_contribution: float
    tradeoffs: list[str] = field(default_factory=list)


@dataclass
class HouseholdMandate:
    id: str
    household_id: str
    objective: str = "balanced_growth"
    liquidity_floor: float = 0.0
    max_single_action: float | None = None
    blocked_action_types: list[ActionType] = field(default_factory=list)
    blocked_categories: list[str] = field(default_factory=list)
    risk_limits: dict[str, Any] = field(default_factory=dict)
    tax_preferences: dict[str, Any] = field(default_factory=dict)
    priority_weights: dict[str, float] = field(default_factory=dict)
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OpportunitySignal:
    id: str
    household_id: str
    domain: OpportunityDomain
    source: str
    title: str
    summary: str
    confidence: float
    urgency: str = "medium"
    estimated_impact_amount: float | None = None
    currency: str = "EUR"
    expires_at: datetime | None = None
    mandate_fit_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PlaybookRun:
    id: str
    household_id: str
    mandate_id: str | None = None
    signal_ids: list[str] = field(default_factory=list)
    status: PlaybookRunStatus = PlaybookRunStatus.DETECTED
    selected_strategy: str | None = None
    action_ids: list[str] = field(default_factory=list)
    expected_impact: dict[str, Any] = field(default_factory=dict)
    realized_impact: dict[str, Any] = field(default_factory=dict)
    continuity_mode: bool = False
    continuity_reason: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ForecastPoint:
    date: datetime
    p10_balance: float
    p50_balance: float
    p90_balance: float
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class ActionProposal:
    id: str
    household_id: str
    action_type: ActionType
    amount: float
    currency: str
    due_at: datetime | None
    category: str
    rationale: list[str]
    risk_score: float
    requires_approval: bool
    status: ActionStatus = ActionStatus.DRAFT
    approval_step: int = 0
    violations: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ActionPreview:
    action_id: str
    projected_balance_after: float
    fee_impact: float
    goal_impact: str
    deadline_impact: str
    notes: list[str] = field(default_factory=list)


@dataclass
class ExecutionReceipt:
    action_id: str
    partner_ref: str
    submitted_at: datetime
    result: str
    reversible_until: datetime | None
    message: str
    provider_name: str | None = None
    fallback_used: bool = False
    provider_attempts: list[str] = field(default_factory=list)


@dataclass
class ExecutionAttempt:
    action_id: str
    attempt_number: int
    idempotency_key: str | None
    partner_ref: str
    result: str
    message: str
    status_before: ActionStatus
    status_after: ActionStatus
    provider_name: str | None = None
    attempted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class UserRule:
    rule_id: str
    household_id: str
    scope: str
    version: int = 1
    is_active: bool = True
    superseded_at: datetime | None = None
    superseded_by_rule_id: str | None = None
    daily_amount_limit: float | None = None
    max_single_action: float | None = None
    blocked_categories: list[str] = field(default_factory=list)
    blocked_action_types: list[ActionType] = field(default_factory=list)
    require_approval_always: bool = True
    anomaly_detection_enabled: bool = True
    anomaly_expense_multiplier: float = 1.75
    anomaly_income_multiplier: float = 2.0
    anomaly_min_expense_amount: float = 150.0
    anomaly_min_income_amount: float = 300.0
    weekly_planning_enabled: bool = True
    weekly_drift_threshold_percent: float = 20.0
    weekly_min_delta_amount: float = 50.0
    weekly_cooldown_days: int = 6
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PortfolioRecommendation:
    household_id: str
    model_id: str
    target_alloc: dict[str, float]
    delta_orders: list[dict[str, Any]]
    suitability_flags: list[str]


@dataclass
class TaxPackage:
    household_id: str
    jurisdiction: str
    forms: list[str]
    inputs: dict[str, Any]
    missing_items: list[str]
    submission_mode: str


@dataclass
class AuditEvent:
    id: str
    household_id: str
    event_type: str
    entity_id: str
    details: dict[str, Any]
    previous_hash: str | None = None
    event_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ChatMessage:
    id: str
    household_id: str
    channel: ChatChannel
    user_id: str | None
    sender: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WaitlistLead:
    id: str
    first_name: str
    last_name: str | None
    email: str
    phone_number: str | None
    marketing_consent: bool
    source: str | None
    utm: dict[str, str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProviderConnection:
    id: str
    household_id: str
    provider_name: str
    domain: ProviderDomain
    is_primary: bool = True
    status: ProviderConnectionStatus = ProviderConnectionStatus.ACTIVE
    credentials_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProviderSyncJob:
    id: str
    household_id: str
    domain: ProviderDomain
    status: ProviderSyncStatus = ProviderSyncStatus.PENDING
    provider_attempts: list[str] = field(default_factory=list)
    synced_records: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


@dataclass
class ProviderSession:
    id: str
    household_id: str
    provider_name: str
    domain: ProviderDomain
    status: ProviderSessionStatus = ProviderSessionStatus.CREATED
    redirect_url: str | None = None
    expires_at: datetime | None = None
    provider_session_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HouseholdSyncRun:
    id: str
    household_id: str
    domains: list[ProviderDomain]
    status: HouseholdSyncRunStatus = HouseholdSyncRunStatus.RUNNING
    job_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


@dataclass
class RuntimeCycleMetric:
    id: str
    run_at: datetime
    duration_ms: int
    processed_households: int
    emitted_actions: int
    emitted_by_loop: dict[str, int]
    interventions_sent: int
    dispatch_successes: int
    dispatch_failures: int
    provider_failures: int


@dataclass
class BetaUser:
    id: str
    email: str
    full_name: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HouseholdMembership:
    id: str
    household_id: str
    user_id: str
    role: str = "member"
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BetaApiToken:
    id: str
    user_id: str
    token: str
    label: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HouseholdLedger:
    household: Household
    accounts: list[Account]
    transactions: list[Transaction]
    deadlines: list[DeadlineItem]
    goals: list[GoalPlan]


def to_dict(model: Any) -> dict[str, Any]:
    """Convert domain dataclass model to primitive dict for API serialization."""
    data = asdict(model)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data
