from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from nivvi.domain.models import (
    AccountType,
    ActionType,
    ChatChannel,
    Direction,
    OpportunityDomain,
    PlaybookRunStatus,
    ProviderDomain,
)


class AccountConnectInput(BaseModel):
    institution: str
    account_type: AccountType
    currency: str = "EUR"
    balance: float = Field(default=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectAccountsRequest(BaseModel):
    household_id: str
    household_name: str | None = None
    accounts: list[AccountConnectInput]


class ConnectAccountsResponse(BaseModel):
    household_id: str
    account_ids: list[str]


class ProviderTransactionInput(BaseModel):
    account_id: str
    amount: float
    currency: str = "EUR"
    direction: Direction
    description: str
    category: str
    booked_at: datetime


class DeadlineInput(BaseModel):
    source: str
    title: str
    jurisdiction: str = "NL"
    due_at: datetime
    penalty_risk: str = "medium"
    amount: float | None = None


class ProviderDataIngestRequest(BaseModel):
    household_id: str
    provider_name: str = Field(default="provider_sync", min_length=1, max_length=64)
    transactions: list[ProviderTransactionInput] = Field(default_factory=list)
    deadlines: list[DeadlineInput] = Field(default_factory=list)


class ProviderDataIngestResponse(BaseModel):
    household_id: str
    provider_name: str
    transactions_ingested: int
    deadlines_ingested: int


class CreateActionProposalRequest(BaseModel):
    household_id: str
    action_type: ActionType
    amount: float = Field(gt=0)
    currency: str = "EUR"
    due_at: datetime | None = None
    category: str = "general"
    rationale: list[str] = Field(default_factory=list)


class ApproveActionRequest(BaseModel):
    step: Literal["confirm", "authorize"]


class RejectActionRequest(BaseModel):
    reason: str | None = None


class DispatchExecutionRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key cannot be empty")
        return normalized


class RetryExecutionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    retry_reason: str | None = Field(default=None, max_length=256)

    @field_validator("idempotency_key")
    @classmethod
    def validate_retry_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key cannot be empty")
        return normalized

    @field_validator("retry_reason")
    @classmethod
    def validate_retry_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CreateRuleRequest(BaseModel):
    household_id: str
    scope: str = "global"
    daily_amount_limit: float | None = None
    max_single_action: float | None = None
    blocked_categories: list[str] = Field(default_factory=list)
    blocked_action_types: list[ActionType] = Field(default_factory=list)
    require_approval_always: bool = True
    anomaly_detection_enabled: bool = True
    anomaly_expense_multiplier: float = Field(default=1.75, ge=1.1, le=5.0)
    anomaly_income_multiplier: float = Field(default=2.0, ge=1.1, le=5.0)
    anomaly_min_expense_amount: float = Field(default=150.0, ge=0.0, le=10000.0)
    anomaly_min_income_amount: float = Field(default=300.0, ge=0.0, le=10000.0)
    weekly_planning_enabled: bool = True
    weekly_drift_threshold_percent: float = Field(default=20.0, ge=5.0, le=200.0)
    weekly_min_delta_amount: float = Field(default=50.0, ge=0.0, le=10000.0)
    weekly_cooldown_days: int = Field(default=6, ge=1, le=30)


class UpsertGoalRequest(BaseModel):
    household_id: str
    name: str
    target_amount: float = Field(gt=0)
    target_date: datetime
    recommended_contribution: float = Field(ge=0)
    tradeoffs: list[str] = Field(default_factory=list)
    goal_id: str | None = None


class UpsertPortfolioRecommendationRequest(BaseModel):
    household_id: str
    model_id: str
    target_alloc: dict[str, float] = Field(default_factory=dict)
    delta_orders: list[dict[str, Any]] = Field(default_factory=list)
    suitability_flags: list[str] = Field(default_factory=list)


class UpsertTaxPackageRequest(BaseModel):
    household_id: str
    jurisdiction: str = "NL"
    forms: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    missing_items: list[str] = Field(default_factory=list)
    submission_mode: str = "partner_one_click_submit"


class HouseholdMandateSchema(BaseModel):
    id: str
    household_id: str
    objective: str
    liquidity_floor: float = 0.0
    max_single_action: float | None = None
    blocked_action_types: list[ActionType] = Field(default_factory=list)
    blocked_categories: list[str] = Field(default_factory=list)
    risk_limits: dict[str, Any] = Field(default_factory=dict)
    tax_preferences: dict[str, Any] = Field(default_factory=dict)
    priority_weights: dict[str, float] = Field(default_factory=dict)
    active: bool = True
    created_at: datetime
    updated_at: datetime


class OpportunitySignalSchema(BaseModel):
    id: str
    household_id: str
    domain: OpportunityDomain
    source: str
    title: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: str = "medium"
    estimated_impact_amount: float | None = None
    currency: str = "EUR"
    expires_at: datetime | None = None
    mandate_fit_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PlaybookRunSchema(BaseModel):
    id: str
    household_id: str
    mandate_id: str | None = None
    signal_ids: list[str] = Field(default_factory=list)
    status: PlaybookRunStatus
    selected_strategy: str | None = None
    action_ids: list[str] = Field(default_factory=list)
    expected_impact: dict[str, Any] = Field(default_factory=dict)
    realized_impact: dict[str, Any] = Field(default_factory=dict)
    continuity_mode: bool = False
    continuity_reason: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    updated_at: datetime


class ChatEventRequest(BaseModel):
    household_id: str
    channel: ChatChannel
    user_id: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinkChannelIdentityRequest(BaseModel):
    household_id: str
    channel: ChatChannel
    user_handle: str


class UpsertProviderConnectionRequest(BaseModel):
    household_id: str
    provider_name: str = Field(min_length=1, max_length=64)
    domain: ProviderDomain
    is_primary: bool = True
    is_enabled: bool = True
    credentials_ref: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_name")
    @classmethod
    def validate_provider_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name is required")
        return normalized


class TriggerProviderSyncRequest(BaseModel):
    household_id: str
    domain: ProviderDomain


class CreateProviderSessionRequest(BaseModel):
    household_id: str
    provider_name: str = Field(min_length=1, max_length=64)
    domain: ProviderDomain
    redirect_url: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_in_minutes: int = Field(default=30, ge=5, le=120)

    @field_validator("provider_name")
    @classmethod
    def validate_session_provider_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name is required")
        return normalized


class CompleteProviderSessionRequest(BaseModel):
    success: bool = True
    provider_session_ref: str | None = Field(default=None, max_length=128)
    credentials_ref: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TriggerHouseholdSyncRequest(BaseModel):
    domains: list[ProviderDomain] | None = None


class CreateBetaUserRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    full_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized):
            raise ValueError("email must be valid")
        return normalized


class IssueBetaTokenRequest(BaseModel):
    label: str | None = Field(default=None, max_length=64)


class AddMembershipRequest(BaseModel):
    user_id: str
    role: str = Field(default="member", max_length=32)


class UpdateHouseholdStatusRequest(BaseModel):
    enabled: bool


class WaitlistRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    phone_number: str | None = Field(default=None, max_length=32)
    marketing_consent: bool
    source: str | None = Field(default=None, max_length=64)
    utm: dict[str, str] | None = None

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("first_name is required")
        return trimmed

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized):
            raise ValueError("email must be valid")
        return normalized

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if not re.fullmatch(r"^\+?[0-9().\-\s]{7,32}$", trimmed):
            raise ValueError("phone_number must be valid")
        digits = re.sub(r"\D", "", trimmed)
        if not 7 <= len(digits) <= 15:
            raise ValueError("phone_number must be valid")
        return trimmed

    @field_validator("utm")
    @classmethod
    def validate_utm(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        sanitized: dict[str, str] = {}
        for key, raw in value.items():
            safe_key = str(key).strip()[:64]
            safe_val = str(raw).strip()[:256]
            if safe_key:
                sanitized[safe_key] = safe_val
        return sanitized


class WaitlistResponse(BaseModel):
    id: str
    status: Literal["created", "already_exists"]
    created_at: datetime


class AnalyticsEventRequest(BaseModel):
    event_name: Literal[
        "landing_view",
        "cta_click_hero",
        "cta_click_midpage",
        "faq_expand",
        "waitlist_submit_success",
        "waitlist_submit_duplicate",
        "waitlist_submit_error",
    ]
    page: str = Field(default="landing", max_length=40)
    properties: dict[str, str] | None = None


class ChatMessageResponse(BaseModel):
    id: str
    household_id: str
    channel: ChatChannel
    user_id: str | None
    sender: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AgentRuntimeStartRequest(BaseModel):
    interval_seconds: int | None = Field(default=None, ge=10, le=3600)


class AgentRuntimeResponse(BaseModel):
    running: bool
    interval_seconds: int
    cycles_run: int
    last_run_at: str | None = None
    last_error: str | None = None


class AgentLoopSimulationRequest(BaseModel):
    household_id: str
    include_daily_monitor: bool = True
    include_event_anomaly: bool = True
    include_weekly_planning: bool = True


class ForecastResponse(BaseModel):
    household_id: str
    horizon_days: int
    points: list[dict[str, Any]]


class TimelineResponse(BaseModel):
    household_id: str
    items: list[dict[str, Any]]


class LedgerResponse(BaseModel):
    household_id: str
    ledger: dict[str, Any]


class AuditResponse(BaseModel):
    events: list[dict[str, Any]]
