from __future__ import annotations

import csv
import io
import json
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from nivvi.api.schemas import (
    AgentLoopSimulationRequest,
    AgentRuntimeResponse,
    AgentRuntimeStartRequest,
    AnalyticsEventRequest,
    ApproveActionRequest,
    ChatEventRequest,
    ConnectAccountsRequest,
    ConnectAccountsResponse,
    CreateActionProposalRequest,
    CreateRuleRequest,
    DispatchExecutionRequest,
    CreateBetaUserRequest,
    AddMembershipRequest,
    IssueBetaTokenRequest,
    LedgerResponse,
    LinkChannelIdentityRequest,
    CompleteProviderSessionRequest,
    ProviderDataIngestRequest,
    ProviderDataIngestResponse,
    RejectActionRequest,
    RetryExecutionRequest,
    TriggerHouseholdSyncRequest,
    CreateProviderSessionRequest,
    TriggerProviderSyncRequest,
    UpdateHouseholdStatusRequest,
    UpsertProviderConnectionRequest,
    UpsertPortfolioRecommendationRequest,
    UpsertGoalRequest,
    UpsertTaxPackageRequest,
    WaitlistRequest,
    WaitlistResponse,
)
from nivvi.api.serializers import serialize
from nivvi.domain.models import ActionProposal, ChatChannel, PortfolioRecommendation, ProviderDomain, TaxPackage
from nivvi.services.action_service import ActionService
from nivvi.services.auth_service import AuthService
from nivvi.services.audit_service import AuditService
from nivvi.services.dashboard_service import DashboardService
from nivvi.services.forecast_service import ForecastService
from nivvi.services.household_service import HouseholdService
from nivvi.services.policy_service import PolicyService
from nivvi.services.provider_service import ProviderService
from nivvi.services.timeline_service import TimelineService
from nivvi.services.chat_service import ChatService
from nivvi.services.waitlist_service import WaitlistService
from nivvi.services.webhook_service import WebhookService
from nivvi.storage.in_memory import STORE
from nivvi.storage.relational_persistence import RelationalPersistence
from nivvi.storage.snapshot_persistence import SnapshotPersistence
from nivvi.workflows.orchestrator import AgentOrchestrator
from nivvi.workflows.runtime import AgentRuntime


agent_runtime: AgentRuntime | None = None
CURRENT_USER_ID: ContextVar[str | None] = ContextVar("current_user_id", default=None)
persistence = SnapshotPersistence()
persistence.load_into(STORE)
relational_persistence = RelationalPersistence()
relational_persistence.load_into(STORE)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if agent_runtime is not None:
        await agent_runtime.start()
    try:
        yield
    finally:
        if agent_runtime is not None:
            await agent_runtime.stop()


app = FastAPI(
    title="Nivvi Agentic Personal Finance OS",
    version="0.1.0",
    description="Supervised execution-capable AI money manager.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_context_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/v1"):
        return await call_next(request)

    public_v1_paths = {
        "/v1/waitlist",
        "/v1/analytics/events",
    }
    if path in public_v1_paths:
        return await call_next(request)

    if not auth_service.auth_required:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", maxsplit=1)[1].strip()

    try:
        user_id = auth_service.authenticate(token)
    except ValueError as error:
        return JSONResponse(status_code=401, content={"detail": str(error)})

    if path.startswith("/v1/beta") and user_id != "bootstrap_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Beta operations require bootstrap admin token"},
        )
    if path.startswith("/v1/agent/runtime") and user_id != "bootstrap_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Agent runtime control requires bootstrap admin token"},
        )

    token_ref = CURRENT_USER_ID.set(user_id)
    request.state.user_id = user_id
    try:
        return await call_next(request)
    finally:
        CURRENT_USER_ID.reset(token_ref)


@app.middleware("http")
async def persistence_snapshot_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 500:
        persistence.save(STORE)
    return response


audit_service = AuditService(STORE, relational_persistence=relational_persistence)
auth_service = AuthService(STORE, audit_service)
policy_service = PolicyService(STORE)
household_service = HouseholdService(STORE, audit_service, relational_persistence=relational_persistence)
forecast_service = ForecastService(STORE)
timeline_service = TimelineService(STORE)
provider_service = ProviderService(STORE, audit_service, relational_persistence=relational_persistence)
action_service = ActionService(
    STORE,
    policy_service,
    audit_service,
    provider_service=provider_service,
    relational_persistence=relational_persistence,
)
dashboard_service = DashboardService(STORE, forecast_service, timeline_service, policy_service=policy_service)
orchestrator = AgentOrchestrator(forecast_service, action_service, audit_service)
chat_service = ChatService(
    STORE,
    action_service,
    dashboard_service,
    audit_service,
    relational_persistence=relational_persistence,
)
webhook_service = WebhookService(
    STORE,
    chat_service,
    audit_service,
    relational_persistence=relational_persistence,
)
waitlist_service = WaitlistService(STORE, audit_service)
agent_runtime = AgentRuntime(
    STORE,
    orchestrator,
    timeline_service,
    audit_service,
    interval_seconds=int(os.getenv("NIVVI_AGENT_INTERVAL_SECONDS", "120")),
    on_cycle_complete=lambda: persistence.save(STORE),
)


@app.get("/health")
def health() -> dict:
    if agent_runtime is None:
        return {"status": "ok", "agent_runtime": None}
    status = agent_runtime.status()
    return {
        "status": "ok",
        "agent_runtime": {
            "running": status.running,
            "interval_seconds": status.interval_seconds,
            "cycles_run": status.cycles_run,
            "last_run_at": status.last_run_at,
            "last_error": status.last_error,
        },
    }


@app.post("/v1/waitlist", response_model=WaitlistResponse)
def create_waitlist_lead(payload: WaitlistRequest) -> WaitlistResponse:
    try:
        result = waitlist_service.upsert_lead(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone_number=payload.phone_number,
            marketing_consent=payload.marketing_consent,
            source=payload.source,
            utm=payload.utm,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return WaitlistResponse(
        id=result.lead.id,
        status="created" if result.created else "already_exists",
        created_at=result.lead.created_at,
    )


@app.post("/v1/analytics/events")
def ingest_analytics_event(payload: AnalyticsEventRequest) -> dict:
    audit_service.log(
        household_id="system",
        event_type=f"analytics.{payload.event_name}",
        entity_id=payload.page,
        details={"page": payload.page, "properties": payload.properties or {}},
    )
    return {"status": "ok"}


def _require_marketing_admin_key(request: Request) -> None:
    expected_key = os.getenv("NIVVI_ADMIN_KEY", "").strip()
    if not expected_key:
        raise HTTPException(status_code=503, detail="Admin key is not configured")

    provided_key = request.headers.get("x-admin-key", "").strip()
    if not provided_key or provided_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _serialize_waitlist_lead(lead) -> dict:
    full_name = " ".join(part for part in [lead.first_name, lead.last_name] if part).strip()
    return {
        "id": lead.id,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "full_name": full_name,
        "email": lead.email,
        "phone_number": lead.phone_number,
        "marketing_consent": lead.marketing_consent,
        "source": lead.source,
        "utm": lead.utm,
        "created_at": lead.created_at.isoformat(),
    }


@app.get("/v1/admin/waitlist/leads")
def list_waitlist_leads(
    request: Request,
    limit: int = Query(default=200, ge=1, le=5000),
    source: str | None = Query(default=None, max_length=64),
) -> dict:
    _require_marketing_admin_key(request)

    leads = sorted(
        STORE.waitlist_leads.values(),
        key=lambda item: item.created_at,
        reverse=True,
    )
    if source:
        leads = [lead for lead in leads if lead.source == source]

    rows = [_serialize_waitlist_lead(lead) for lead in leads[:limit]]
    return {"total_count": len(leads), "returned_count": len(rows), "items": rows}


@app.get("/v1/admin/waitlist/leads.csv")
def export_waitlist_leads_csv(
    request: Request,
    source: str | None = Query(default=None, max_length=64),
) -> Response:
    _require_marketing_admin_key(request)

    leads = sorted(
        STORE.waitlist_leads.values(),
        key=lambda item: item.created_at,
        reverse=True,
    )
    if source:
        leads = [lead for lead in leads if lead.source == source]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone_number",
            "marketing_consent",
            "source",
            "utm_json",
            "created_at",
        ]
    )
    for lead in leads:
        full_name = " ".join(part for part in [lead.first_name, lead.last_name] if part).strip()
        writer.writerow(
            [
                lead.id,
                lead.first_name,
                lead.last_name or "",
                full_name,
                lead.email,
                lead.phone_number or "",
                "true" if lead.marketing_consent else "false",
                lead.source or "",
                json.dumps(lead.utm, separators=(",", ":"), sort_keys=True),
                lead.created_at.isoformat(),
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nivvi-waitlist-leads.csv"'},
    )


@app.post("/v1/connect/accounts", response_model=ConnectAccountsResponse)
def connect_accounts(payload: ConnectAccountsRequest) -> ConnectAccountsResponse:
    current_user = CURRENT_USER_ID.get()
    household_exists = payload.household_id in STORE.households
    if household_exists:
        _ensure_household(payload.household_id, require_write=True)
    household_service.create_or_get_household(payload.household_id, payload.household_name)
    if not household_exists and auth_service.auth_required and current_user:
        auth_service.auto_provision_membership_for_new_household(current_user, payload.household_id)
    account_ids: list[str] = []

    for account in payload.accounts:
        created = household_service.connect_account(
            household_id=payload.household_id,
            institution=account.institution,
            account_type=account.account_type,
            currency=account.currency,
            balance=account.balance,
            metadata=account.metadata,
        )
        account_ids.append(created.id)

    return ConnectAccountsResponse(household_id=payload.household_id, account_ids=account_ids)


@app.post("/v1/providers/ingest", response_model=ProviderDataIngestResponse)
def ingest_provider_data(payload: ProviderDataIngestRequest) -> ProviderDataIngestResponse:
    _ensure_household(payload.household_id, require_write=True)

    tx_count = 0
    for tx in payload.transactions:
        account = STORE.accounts.get(tx.account_id)
        if not account or account.household_id != payload.household_id:
            raise HTTPException(status_code=404, detail=f"Account {tx.account_id} not found for household")

        household_service.import_transaction(
            household_id=payload.household_id,
            account_id=tx.account_id,
            amount=tx.amount,
            currency=tx.currency,
            direction=tx.direction,
            description=tx.description,
            category=tx.category,
            booked_at=tx.booked_at,
        )
        tx_count += 1

    deadline_count = 0
    for deadline in payload.deadlines:
        household_service.import_deadline(
            household_id=payload.household_id,
            source=deadline.source,
            title=deadline.title,
            jurisdiction=deadline.jurisdiction,
            due_at=deadline.due_at,
            penalty_risk=deadline.penalty_risk,
            amount=deadline.amount,
        )
        deadline_count += 1

    audit_service.log(
        payload.household_id,
        "provider.data_ingested",
        payload.household_id,
        {
            "provider_name": payload.provider_name,
            "transactions_ingested": tx_count,
            "deadlines_ingested": deadline_count,
        },
    )

    return ProviderDataIngestResponse(
        household_id=payload.household_id,
        provider_name=payload.provider_name,
        transactions_ingested=tx_count,
        deadlines_ingested=deadline_count,
    )


@app.get("/v1/households/{household_id}/ledger", response_model=LedgerResponse)
def get_ledger(household_id: str) -> LedgerResponse:
    _ensure_household(household_id)
    ledger = household_service.get_ledger(household_id)
    return LedgerResponse(household_id=household_id, ledger=serialize(ledger))


@app.get("/v1/households/{household_id}/forecast")
def get_forecast(household_id: str, horizon: int = Query(default=30, alias="horizon")) -> dict:
    _ensure_household(household_id)
    if horizon not in {30, 60, 90}:
        raise HTTPException(status_code=400, detail="horizon must be one of 30, 60, 90")
    points = forecast_service.forecast(household_id, horizon)
    return {
        "household_id": household_id,
        "horizon_days": horizon,
        "points": serialize(points),
    }


@app.get("/v1/households/{household_id}/timeline")
def get_timeline(household_id: str) -> dict:
    _ensure_household(household_id)
    items = timeline_service.timeline(household_id, 90)
    return {"household_id": household_id, "items": serialize(items)}


@app.get("/v1/dashboard/today")
def get_today_dashboard(household_id: str, run_monitor: bool = True) -> dict:
    _ensure_household(household_id, require_write=run_monitor)
    emitted_actions: list[str] = []
    if run_monitor:
        emitted_actions = orchestrator.run_daily_monitor(household_id)
    dashboard = dashboard_service.today(household_id)
    dashboard["orchestrator_emitted_action_ids"] = emitted_actions
    return dashboard


@app.get("/v1/planning/insights")
def get_planning_insights(household_id: str) -> dict:
    _ensure_household(household_id)
    return dashboard_service.planning_insights(household_id)


@app.post("/v1/actions/proposals")
def create_action(payload: CreateActionProposalRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    proposal = action_service.create_proposal(
        household_id=payload.household_id,
        action_type=payload.action_type,
        amount=payload.amount,
        currency=payload.currency,
        due_at=payload.due_at,
        category=payload.category,
        rationale=payload.rationale,
    )
    return serialize(proposal)


@app.get("/v1/actions")
def list_actions(household_id: str) -> dict:
    _ensure_household(household_id)
    actions = action_service.list_actions(household_id)
    return {"items": serialize(sorted(actions, key=lambda item: item.created_at, reverse=True))}


@app.get("/v1/actions/{action_id}/preview")
def get_action_preview(action_id: str) -> dict:
    action = _ensure_action(action_id)
    preview = action_service.preview(action.id)
    return serialize(preview)


@app.post("/v1/actions/{action_id}/approve")
def approve_action(action_id: str, payload: ApproveActionRequest) -> dict:
    _ensure_action(action_id, require_write=True)
    try:
        action = action_service.approve(action_id, payload.step)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return serialize(action)


@app.post("/v1/actions/{action_id}/reject")
def reject_action(action_id: str, payload: RejectActionRequest) -> dict:
    _ensure_action(action_id, require_write=True)
    action = action_service.reject(action_id, payload.reason)
    return serialize(action)


@app.post("/v1/executions/{action_id}/dispatch")
def dispatch_action(action_id: str, payload: DispatchExecutionRequest) -> dict:
    _ensure_action(action_id, require_write=True)
    try:
        receipt = action_service.dispatch(action_id, idempotency_key=payload.idempotency_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return serialize(receipt)


@app.get("/v1/executions/{action_id}")
def get_execution(action_id: str) -> dict:
    _ensure_action(action_id, require_write=False)
    receipt = action_service.get_execution(action_id)
    attempts = action_service.list_execution_attempts(action_id)
    return {
        "action_id": action_id,
        "latest": serialize(receipt) if receipt else None,
        "attempts": serialize(attempts),
    }


@app.post("/v1/executions/{action_id}/retry")
def retry_execution(action_id: str, payload: RetryExecutionRequest) -> dict:
    _ensure_action(action_id, require_write=True)
    try:
        receipt = action_service.retry_dispatch(
            action_id=action_id,
            idempotency_key=payload.idempotency_key,
            retry_reason=payload.retry_reason,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return serialize(receipt)


@app.get("/v1/goals")
def list_goals(household_id: str) -> dict:
    _ensure_household(household_id)
    goals = [goal for goal in STORE.goals.values() if goal.household_id == household_id]
    goals = sorted(goals, key=lambda item: item.target_date)
    return {"items": serialize(goals)}


@app.post("/v1/goals")
def upsert_goal(payload: UpsertGoalRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    goal = household_service.upsert_goal(
        household_id=payload.household_id,
        name=payload.name,
        target_amount=payload.target_amount,
        target_date=payload.target_date,
        recommended_contribution=payload.recommended_contribution,
        tradeoffs=payload.tradeoffs,
        goal_id=payload.goal_id,
    )
    return serialize(goal)


@app.get("/v1/invest/recommendation")
def get_portfolio_recommendation(household_id: str) -> dict:
    _ensure_household(household_id)
    rec = STORE.portfolio_recommendations.get(household_id)
    return {"item": serialize(rec) if rec else None}


@app.post("/v1/invest/recommendation")
def upsert_portfolio_recommendation(payload: UpsertPortfolioRecommendationRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    rec = PortfolioRecommendation(
        household_id=payload.household_id,
        model_id=payload.model_id,
        target_alloc=payload.target_alloc,
        delta_orders=payload.delta_orders,
        suitability_flags=payload.suitability_flags,
    )
    STORE.portfolio_recommendations[payload.household_id] = rec
    audit_service.log(
        payload.household_id,
        "invest.recommendation_upserted",
        payload.household_id,
        {
            "model_id": payload.model_id,
            "suitability_flags": payload.suitability_flags,
            "order_count": len(payload.delta_orders),
        },
    )
    return {"item": serialize(rec)}


@app.get("/v1/tax/package")
def get_tax_package(household_id: str) -> dict:
    _ensure_household(household_id)
    package = STORE.tax_packages.get(household_id)
    return {"item": serialize(package) if package else None}


@app.post("/v1/tax/package")
def upsert_tax_package(payload: UpsertTaxPackageRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    package = TaxPackage(
        household_id=payload.household_id,
        jurisdiction=payload.jurisdiction,
        forms=payload.forms,
        inputs=payload.inputs,
        missing_items=payload.missing_items,
        submission_mode=payload.submission_mode,
    )
    STORE.tax_packages[payload.household_id] = package
    audit_service.log(
        payload.household_id,
        "tax.package_upserted",
        payload.household_id,
        {
            "jurisdiction": payload.jurisdiction,
            "forms": payload.forms,
            "missing_items": payload.missing_items,
        },
    )
    return {"item": serialize(package)}


@app.get("/v1/audit/events")
def list_audit_events(household_id: str | None = None) -> dict:
    if household_id is not None:
        _ensure_household(household_id)
    events = audit_service.list_events(household_id)
    return {"events": serialize(events)}


@app.get("/v1/audit/integrity")
def audit_integrity(household_id: str | None = None) -> dict:
    if household_id is not None:
        _ensure_household(household_id)
        return audit_service.verify_integrity(household_id=household_id)
    if auth_service.auth_required:
        _ensure_beta_operator()
    return audit_service.verify_integrity(household_id=None)


@app.post("/v1/rules")
def create_rule(payload: CreateRuleRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    rule = household_service.add_rule(
        household_id=payload.household_id,
        scope=payload.scope,
        daily_amount_limit=payload.daily_amount_limit,
        max_single_action=payload.max_single_action,
        blocked_categories=payload.blocked_categories,
        blocked_action_types=payload.blocked_action_types,
        require_approval_always=payload.require_approval_always,
        anomaly_detection_enabled=payload.anomaly_detection_enabled,
        anomaly_expense_multiplier=payload.anomaly_expense_multiplier,
        anomaly_income_multiplier=payload.anomaly_income_multiplier,
        anomaly_min_expense_amount=payload.anomaly_min_expense_amount,
        anomaly_min_income_amount=payload.anomaly_min_income_amount,
        weekly_planning_enabled=payload.weekly_planning_enabled,
        weekly_drift_threshold_percent=payload.weekly_drift_threshold_percent,
        weekly_min_delta_amount=payload.weekly_min_delta_amount,
        weekly_cooldown_days=payload.weekly_cooldown_days,
    )
    return serialize(rule)


@app.get("/v1/rules")
def list_rules(household_id: str, include_inactive: bool = Query(default=False)) -> dict:
    _ensure_household(household_id)
    rules = household_service.list_rules(household_id=household_id, include_inactive=include_inactive)
    return {"items": serialize(rules)}


@app.post("/v1/providers/connections")
def upsert_provider_connection(payload: UpsertProviderConnectionRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    connection = provider_service.upsert_connection(
        household_id=payload.household_id,
        provider_name=payload.provider_name,
        domain=payload.domain,
        is_primary=payload.is_primary,
        is_enabled=payload.is_enabled,
        credentials_ref=payload.credentials_ref,
        metadata=payload.metadata,
    )
    return {"item": serialize(connection)}


@app.get("/v1/providers/connections")
def list_provider_connections(household_id: str | None = None, domain: ProviderDomain | None = None) -> dict:
    if household_id:
        _ensure_household(household_id)
    items = provider_service.list_connections(household_id=household_id, domain=domain)
    return {"items": serialize(items)}


@app.post("/v1/providers/sessions")
def create_provider_session(payload: CreateProviderSessionRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    session = provider_service.create_session(
        household_id=payload.household_id,
        provider_name=payload.provider_name,
        domain=payload.domain,
        redirect_url=payload.redirect_url,
        metadata=payload.metadata,
        expires_in_minutes=payload.expires_in_minutes,
    )
    return {"item": serialize(session)}


@app.get("/v1/providers/sessions")
def list_provider_sessions(household_id: str | None = None) -> dict:
    if household_id:
        _ensure_household(household_id)
    items = provider_service.list_sessions(household_id=household_id)
    return {"items": serialize(items)}


@app.post("/v1/providers/sessions/{session_id}/complete")
def complete_provider_session(session_id: str, payload: CompleteProviderSessionRequest) -> dict:
    session = provider_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Provider session '{session_id}' not found")
    _ensure_household(session.household_id, require_write=True)
    updated = provider_service.complete_session(
        session_id=session_id,
        success=payload.success,
        provider_session_ref=payload.provider_session_ref,
        credentials_ref=payload.credentials_ref,
        metadata=payload.metadata,
    )
    return {"item": serialize(updated)}


@app.post("/v1/providers/sync")
def trigger_provider_sync(payload: TriggerProviderSyncRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    job = provider_service.trigger_sync(household_id=payload.household_id, domain=payload.domain)
    return {"item": serialize(job)}


@app.get("/v1/providers/sync/{sync_id}")
def get_provider_sync(sync_id: str) -> dict:
    job = provider_service.get_sync_job(sync_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Sync job '{sync_id}' not found")
    _ensure_household(job.household_id)
    return {"item": serialize(job)}


@app.get("/v1/providers/health")
def get_provider_health(household_id: str | None = None) -> dict:
    if household_id:
        _ensure_household(household_id)
    report = provider_service.health(household_id=household_id)
    return {"items": report}


@app.post("/v1/households/{household_id}/sync")
def trigger_household_sync(household_id: str, payload: TriggerHouseholdSyncRequest | None = None) -> dict:
    _ensure_household(household_id, require_write=True)
    domains = payload.domains if payload else None
    run = provider_service.trigger_household_sync(household_id=household_id, domains=domains)
    jobs = [provider_service.get_sync_job(sync_id) for sync_id in run.job_ids]
    return {"item": serialize(run), "jobs": serialize([job for job in jobs if job is not None])}


@app.get("/v1/households/{household_id}/sync/{run_id}")
def get_household_sync(household_id: str, run_id: str) -> dict:
    _ensure_household(household_id)
    run = provider_service.get_household_sync_run(run_id)
    if run is None or run.household_id != household_id:
        raise HTTPException(status_code=404, detail=f"Household sync run '{run_id}' not found")
    jobs = [provider_service.get_sync_job(sync_id) for sync_id in run.job_ids]
    return {"item": serialize(run), "jobs": serialize([job for job in jobs if job is not None])}


@app.post("/v1/beta/users")
def create_beta_user(payload: CreateBetaUserRequest) -> dict:
    _ensure_beta_operator()
    user = auth_service.create_user(email=payload.email, full_name=payload.full_name)
    return {"item": serialize(user)}


@app.post("/v1/beta/users/{user_id}/tokens")
def issue_beta_token(user_id: str, payload: IssueBetaTokenRequest) -> dict:
    _ensure_beta_operator()
    token = auth_service.issue_token(user_id=user_id, label=payload.label)
    return {"item": serialize(token)}


@app.post("/v1/beta/households/{household_id}/memberships")
def add_household_membership(household_id: str, payload: AddMembershipRequest) -> dict:
    _ensure_beta_operator()
    _ensure_household_exists(household_id)
    membership = auth_service.add_membership(user_id=payload.user_id, household_id=household_id, role=payload.role)
    return {"item": serialize(membership)}


@app.post("/v1/beta/households/{household_id}/status")
def update_household_status(household_id: str, payload: UpdateHouseholdStatusRequest) -> dict:
    _ensure_beta_operator()
    _ensure_household_exists(household_id)
    enabled = auth_service.set_household_enabled(household_id=household_id, enabled=payload.enabled)
    return {"household_id": household_id, "enabled": enabled}


@app.get("/v1/beta/households/{household_id}/diagnostics")
def household_diagnostics(household_id: str) -> dict:
    _ensure_beta_operator()
    _ensure_household(household_id)
    connections = provider_service.list_connections(household_id=household_id)
    sync_jobs = [job for job in STORE.provider_sync_jobs.values() if job.household_id == household_id]
    sync_jobs = sorted(sync_jobs, key=lambda item: item.started_at, reverse=True)[:10]
    recent_audit = [event for event in STORE.audit_events if event.household_id == household_id][-20:]
    return {
        "household_id": household_id,
        "enabled": auth_service.is_household_enabled(household_id),
        "provider_connections": serialize(connections),
        "recent_sync_jobs": serialize(sync_jobs),
        "recent_audit_events": serialize(recent_audit),
        "pending_actions": len(
            [
                item
                for item in STORE.actions.values()
                if item.household_id == household_id and item.status.value in {"draft", "pending_authorization", "approved"}
            ]
        ),
    }


@app.get("/v1/beta/launch-gate")
def launch_gate_status(household_id: str | None = None) -> dict:
    _ensure_beta_operator()
    if household_id is not None:
        _ensure_household_exists(household_id)

    active_connections = provider_service.list_connections(household_id=household_id)
    active_connections = [item for item in active_connections if item.status.value == "active"]
    domains = {item.domain for item in active_connections}
    execution_domains = {ProviderDomain.PAYMENTS, ProviderDomain.INVESTING, ProviderDomain.TAX_SUBMISSION}
    missing_execution_domains = sorted(item.value for item in execution_domains - domains)

    metrics = _runtime().metrics(limit=20)
    failed_actions = [
        item
        for item in STORE.actions.values()
        if (household_id is None or item.household_id == household_id) and item.status.value == "failed"
    ]

    checks = {
        "runtime_available": agent_runtime is not None,
        "runtime_recent_cycle": metrics["summary"]["count"] > 0,
        "execution_domains_connected": len(missing_execution_domains) == 0,
        "no_unresolved_failed_actions": len(failed_actions) == 0,
        "auth_required_enabled": auth_service.auth_required,
    }
    gate_pass = all(checks.values())

    return {
        "household_scope": household_id or "global",
        "pass": gate_pass,
        "checks": checks,
        "details": {
            "missing_execution_domains": missing_execution_domains,
            "active_connections": len(active_connections),
            "failed_actions": len(failed_actions),
            "runtime_metrics_count": metrics["summary"]["count"],
        },
    }


@app.post("/v1/chat/events")
def process_chat_event(payload: ChatEventRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    reply = chat_service.handle_event(
        household_id=payload.household_id,
        channel=payload.channel,
        user_id=payload.user_id,
        message=payload.message,
        metadata=payload.metadata,
    )
    return {"inbound": serialize(reply.inbound), "outbound": serialize(reply.outbound)}


@app.post("/v1/chat/identities/link")
def link_chat_identity(payload: LinkChannelIdentityRequest) -> dict:
    _ensure_household(payload.household_id, require_write=True)
    linked = webhook_service.link_identity(
        household_id=payload.household_id,
        channel=payload.channel,
        user_handle=payload.user_handle,
    )
    return {"item": linked}


@app.get("/v1/chat/identities")
def list_chat_identities(household_id: str | None = None) -> dict:
    if household_id is not None:
        _ensure_household(household_id)
    return {"items": webhook_service.list_identities(household_id=household_id)}


@app.get("/v1/chat/messages")
def list_chat_messages(household_id: str, channel: str | None = None) -> dict:
    _ensure_household(household_id)
    parsed_channel = None
    if channel:
        try:
            parsed_channel = ChatChannel(channel)
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail="channel must be one of: whatsapp, telegram"
            ) from error
    messages = chat_service.list_messages(household_id=household_id, channel=parsed_channel)
    return {"items": serialize(messages)}


@app.get("/webhooks/whatsapp", response_model=None)
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    expected_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if not expected_verify_token:
        raise HTTPException(status_code=503, detail="WHATSAPP_VERIFY_TOKEN is not configured")
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="hub.mode must be subscribe")
    if hub_verify_token != expected_verify_token:
        raise HTTPException(status_code=403, detail="Verification token mismatch")
    return PlainTextResponse(hub_challenge)


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {error}") from error

    signature_header = request.headers.get("x-hub-signature-256")
    is_valid = webhook_service.verify_meta_signature(
        raw_body=raw_body,
        signature_header=signature_header,
        app_secret=os.getenv("WHATSAPP_APP_SECRET"),
    )
    if not is_valid:
        raise HTTPException(status_code=403, detail="Invalid Meta webhook signature")

    result = webhook_service.process_whatsapp_payload(payload)
    return {
        "status": "received",
        "processed": result.processed,
        "ignored": result.ignored,
        "unmatched": result.unmatched,
        "responses": result.responses,
    }


@app.post("/webhooks/telegram")
async def telegram_webhook(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {error}") from error

    secret_header = request.headers.get("x-telegram-bot-api-secret-token")
    is_valid = webhook_service.verify_telegram_secret(
        secret_header=secret_header,
        expected_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET"),
    )
    if not is_valid:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    result = webhook_service.process_telegram_payload(payload)
    return {
        "ok": True,
        "processed": result.processed,
        "ignored": result.ignored,
        "unmatched": result.unmatched,
        "responses": result.responses,
    }


@app.get("/v1/agent/runtime", response_model=AgentRuntimeResponse)
def get_agent_runtime() -> AgentRuntimeResponse:
    return AgentRuntimeResponse(**serialize(_runtime().status()))


@app.get("/v1/agent/runtime/metrics")
def get_agent_runtime_metrics(limit: int = Query(default=20, ge=1, le=500)) -> dict:
    runtime = _runtime()
    metrics = runtime.metrics(limit=limit)
    return {"items": serialize(metrics["items"]), "summary": metrics["summary"]}


@app.post("/v1/agent/runtime/start", response_model=AgentRuntimeResponse)
async def start_agent_runtime(payload: AgentRuntimeStartRequest | None = None) -> AgentRuntimeResponse:
    runtime = _runtime()
    if payload and payload.interval_seconds:
        runtime.interval_seconds = payload.interval_seconds
    await runtime.start()
    return AgentRuntimeResponse(**serialize(runtime.status()))


@app.post("/v1/agent/runtime/stop", response_model=AgentRuntimeResponse)
async def stop_agent_runtime() -> AgentRuntimeResponse:
    runtime = _runtime()
    await runtime.stop()
    return AgentRuntimeResponse(**serialize(runtime.status()))


@app.post("/v1/agent/runtime/run-cycle")
async def run_agent_cycle() -> dict:
    runtime = _runtime()
    result = await runtime.run_cycle()
    return {"result": result, "status": serialize(runtime.status())}


@app.post("/v1/agent/loops/simulate")
def simulate_agent_loops(payload: AgentLoopSimulationRequest) -> dict:
    _ensure_household(payload.household_id)
    result = orchestrator.simulate_loops(
        household_id=payload.household_id,
        include_daily_monitor=payload.include_daily_monitor,
        include_event_anomaly=payload.include_event_anomaly,
        include_weekly_planning=payload.include_weekly_planning,
    )
    return result


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", response_model=None)
def root():
    landing = WEB_DIR / "landing.html"
    if landing.exists():
        return FileResponse(landing)
    return {"message": "Nivvi API running"}


@app.get("/app", response_model=None)
def app_shell():
    app_entry = WEB_DIR / "index.html"
    if app_entry.exists():
        return FileResponse(app_entry)
    return {"message": "Companion app not found"}


@app.get("/waitlist", response_model=None)
def waitlist_page():
    page = WEB_DIR / "waitlist.html"
    if page.exists():
        return FileResponse(page)
    return {"message": "Waitlist page not found"}


@app.get("/waitlist/success", response_model=None)
def waitlist_success_page():
    page = WEB_DIR / "waitlist-success.html"
    if page.exists():
        return FileResponse(page)
    return {"message": "Waitlist success page not found"}


@app.get("/legal/privacy", response_model=None)
def privacy_page():
    page = WEB_DIR / "privacy.html"
    if page.exists():
        return FileResponse(page)
    return {"message": "Privacy policy page not found"}


@app.get("/legal/terms", response_model=None)
def terms_page():
    page = WEB_DIR / "terms.html"
    if page.exists():
        return FileResponse(page)
    return {"message": "Terms page not found"}


def _ensure_beta_operator() -> None:
    if not auth_service.auth_required:
        return
    user_id = CURRENT_USER_ID.get()
    if user_id != "bootstrap_admin":
        raise HTTPException(status_code=403, detail="Beta operations require bootstrap admin token")


def _ensure_household(household_id: str, require_write: bool = False) -> None:
    _ensure_household_exists(household_id)
    if not auth_service.is_household_enabled(household_id):
        raise HTTPException(status_code=403, detail=f"Household '{household_id}' is disabled")
    user_id = CURRENT_USER_ID.get()
    if auth_service.auth_required:
        if not user_id:
            raise HTTPException(status_code=401, detail="Missing authenticated user context")
        try:
            auth_service.ensure_household_access(user_id, household_id, require_write=require_write)
        except ValueError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error


def _ensure_household_exists(household_id: str) -> None:
    if household_id not in STORE.households:
        raise HTTPException(status_code=404, detail=f"Household '{household_id}' not found")


def _runtime() -> AgentRuntime:
    if agent_runtime is None:
        raise HTTPException(status_code=503, detail="Agent runtime unavailable")
    return agent_runtime


def _ensure_action(action_id: str, require_write: bool = False) -> ActionProposal:
    action = STORE.actions.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")
    _ensure_household(action.household_id, require_write=require_write)
    return action
