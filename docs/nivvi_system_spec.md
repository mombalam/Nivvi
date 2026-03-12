# Nivvi System Spec

**Nivvi** is an agentic, supervised AI money manager for household finances.  
It connects to the financial products a household already uses, identifies what matters most, prepares the right action, and executes only after explicit approval.

This document is the single operational spec for how Nivvi runs end to end.

## How It Works

```text
Provider Connections + Provider Ingest + Chat/Webhooks
            |
            v
API Ingestion Layer (/connect, /providers/ingest, /chat, /providers, /webhooks)
            |
            v
Unified Financial Graph (accounts, liabilities, txns, bills/deadlines, goals, portfolio + tax context, rules, mandates, opportunity signals, playbook runs)
            |
            +--> Forecast + Timeline + Planning Insights + Opportunity Signals
            |
            +--> Mandate + Playbook Engine (priority, constraints, sequencing)
            |
            +--> Agent Runtime Loops (daily, anomaly, weekly, deadline guard)
                           |
                           v
                    Action Proposal (draft)
                           |
                           v
               Preview + Policy + Readiness Gates
                           |
                           v
                  Confirm -> Authorize (required)
                           |
                           v
          Dispatch via Provider Router (primary -> fallback)
                           |
                           v
              Execution Receipt + Attempts + Audit Hash Chain
                           |
                           v
             Chat/App visibility + follow-up interventions
```

## Runtime Model

Nivvi runs as a supervised advisor-to-execution loop:

1. Ingest and normalize household data.
2. Evaluate active household mandate (priorities, constraints, risk posture).
3. Detect risks/opportunities across cash, bills, debt, tax, and investing context.
4. Rank opportunities and run the next playbook with rationale.
5. Draft the next best action with rationale.
6. Require two-step approval before any consequential dispatch.
7. Dispatch through configured provider rails.
8. Log outcomes and adapt subsequent recommendations.

## Business Process Flow

Nivvi business flow is documented in detail in `docs/business_process_flow.md`.

At a high level:

1. Onboard and connect provider rails.
2. Build unified graph and set household mandate.
3. Monitor continuously and detect opportunity signals.
4. Prepare playbook and action preview.
5. Require confirm + authorize.
6. Dispatch through provider router.
7. Reconcile, audit, and adapt.

## Missing-Layer Runtime Objects

The unified graph needs three first-class runtime objects beyond accounts and transactions:

- `HouseholdMandate`: explicit priorities and constraints used to decide what Nivvi should optimize for.
- `OpportunitySignal`: detected risk/opportunity items scored by impact, urgency, confidence, and mandate fit.
- `PlaybookRun`: managed execution wrapper for one prioritized opportunity from detection through outcome.

These are required so Nivvi behaves like a money manager, not a dashboard plus chat wrapper.

## Triggers and Entry Points

Primary triggers:

- User/API ingestion:
  - `POST /v1/connect/accounts`
  - `POST /v1/providers/ingest`
- Chat:
  - `POST /v1/chat/events`
  - `POST /webhooks/whatsapp`
  - `POST /webhooks/telegram`
- Provider orchestration:
  - `POST /v1/providers/connections`
  - `POST /v1/providers/sessions`
  - `POST /v1/providers/sync`
  - `POST /v1/households/{household_id}/sync`
- Runtime cycles:
  - periodic loop (configurable interval)
  - `POST /v1/agent/runtime/run-cycle`

## Agent Loops

The runtime executes these loops per household:

- Daily monitor loop:
  - scans forecast shortfall risk
  - drafts cashflow-protection transfer when needed
- Event anomaly loop:
  - classifies unexpected income/expense shocks from fresh transactions
  - drafts protection/allocation transfer
  - emits intervention message
- Weekly planning loop:
  - computes spend drift vs baseline by category
  - drafts weekly rebalance transfer and intervention
- Deadline guard loop:
  - sends reminder messages for near-term due items
  - throttled to avoid duplicate spam

Loop controls come from household `UserRule` settings.

## Chat Processing Rules

Nivvi chat routing is deterministic-first:

1. Try explicit command map (`today`, `actions`, `approve`, `dispatch`, etc.).
2. If no explicit command, infer intent from natural language.
3. If inference is unclear, return advisor brief fallback.

Identity handling:

- Channels are linked to household IDs using `/v1/chat/identities/link`.
- Unknown inbound webhook identity is not executed; message is unmatched until linked.

## Action Lifecycle and Enforcement

State machine:

`draft -> pending_authorization -> approved -> dispatched`
`draft/pending/approved -> rejected`
`approved -> failed` (if dispatch attempt fails)
`failed -> dispatched` (via retry path)

Approval rules:

- `confirm` is required before `authorize`.
- Dispatch requires `approved` (or `failed` retry flow).
- No dispatch without approval artifacts.

Idempotency rules:

- Same idempotency key + same action returns same receipt (safe replay).
- Same key across different actions is blocked.
- Retrying a failed action requires an idempotency key.

Execution readiness gates:

- Invest actions:
  - require portfolio recommendation
  - blocked when suitability flags include blocking tokens (for example `non_compliant`, `unsuitable`, `restricted`, `fail`)
- Tax submission actions:
  - require tax package
  - blocked while `missing_items` is non-empty

## Playbook Lifecycle

Playbook state machine:

`detected -> prepared -> awaiting_approval -> approved -> executing -> completed`
`detected/prepared/awaiting_approval -> dismissed`
`approved/executing -> failed`
`failed -> retry_pending -> executing` (with idempotency and policy checks)

Lifecycle rules:

- A playbook run references one or more opportunity signals.
- The playbook may generate one or more action proposals, but no dispatch can occur before confirm+authorize.
- If an upstream provider is degraded, the playbook remains open with continuity status rather than hard-failing the full plan.
- Final run outcome stores expected vs realized impact for future ranking quality.

## Provider Routing and Resilience

Provider dispatch router behavior:

- Action domain map:
  - `transfer -> payments`
  - `invest -> investing`
  - `tax_submission -> tax_submission`
- Connections are ordered primary then fallback.
- Disabled providers (`NIVVI_DISABLED_EXECUTION_PROVIDERS`) are skipped.
- First success wins, receipt captures fallback usage and attempts.
- If all attempts fail, action moves to `failed`.

Important current state:

- Default adapters are `sandbox_primary` and `sandbox_fallback`.
- `ProviderAdapter` is the integration contract (`sync`, `execute`, `health`).
- Live providers (for example Yapily) must be implemented and registered via that adapter contract.

## Data Integrity and Auditability

Nivvi persists and traces every consequential step:

- `ActionProposal` record
- approval artifacts (confirm/authorize)
- `ExecutionReceipt`
- `ExecutionAttempt` history
- append-only `AuditEvent`

Audit events are hash-chained:

- each event stores `previous_hash`
- each event stores computed `event_hash`
- integrity can be verified with `GET /v1/audit/integrity`

## Storage Model

Two persistence layers are supported:

- Snapshot persistence (default memory mode)
- Relational persistence (Postgres mode) for core entities

Postgres mode:

- set `NIVVI_STORE_BACKEND=postgres`
- set `DATABASE_URL=postgresql+psycopg://...`
- run `alembic upgrade head`

## Security and Isolation

When auth mode is enabled:

- `NIVVI_REQUIRE_AUTH=true` enforces bearer token auth on `/v1/*` (except waitlist/analytics).
- Household access is role-based:
  - `owner/admin/member`: read/write
  - `viewer`: read-only
- Bootstrap token can gate beta operator endpoints:
  - `NIVVI_BOOTSTRAP_TOKEN`

Security baseline policy set is documented in detail in `docs/security_policies.md`.

## Environment Variables

| Variable | Purpose |
|---|---|
| `NIVVI_REQUIRE_AUTH` | Enable auth-required mode for `/v1/*` endpoints |
| `NIVVI_BOOTSTRAP_TOKEN` | Bootstrap operator token for beta/runtime admin controls |
| `NIVVI_AGENT_INTERVAL_SECONDS` | Runtime loop interval |
| `NIVVI_EXECUTION_ENABLED_TRANSFER` | Enable/disable transfer dispatch |
| `NIVVI_EXECUTION_ENABLED_INVEST` | Enable/disable invest dispatch |
| `NIVVI_EXECUTION_ENABLED_TAX` | Enable/disable tax dispatch |
| `NIVVI_DISABLED_EXECUTION_PROVIDERS` | Comma-separated provider kill switch |
| `WHATSAPP_VERIFY_TOKEN` | WhatsApp webhook verification token |
| `WHATSAPP_APP_SECRET` | WhatsApp signature verification secret |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram webhook secret token |
| `NIVVI_STORE_BACKEND` | `memory` or `postgres` |
| `DATABASE_URL` | Postgres connection URL when Postgres mode is used |

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run landing-first marketing app:

```bash
uvicorn marketing:app --reload --port 8000
```

Run product app (companion + full `/v1/*` runtime):

```bash
uvicorn product:app --reload --port 8001
```

Run both in Postgres mode:

```bash
export NIVVI_STORE_BACKEND=postgres
export DATABASE_URL='postgresql+psycopg://user:pass@host:5432/dbname'
alembic upgrade head
uvicorn marketing:app --reload --port 8000
uvicorn product:app --reload --port 8001
```

Open:

- Landing: `http://127.0.0.1:8000/`
- Marketing docs: `http://127.0.0.1:8000/docs`
- Companion app: `http://127.0.0.1:8001/app`
- Product API docs: `http://127.0.0.1:8001/docs`

## Beta Readiness Checks

Before closed beta go-live:

1. Dispatch cannot bypass confirm+authorize.
2. Idempotency replay/collision behavior passes.
3. Failed dispatch retry path is healthy.
4. Provider failure degrades to fallback and last-good-state continuity.
5. Loop emissions are non-duplicative across repeated cycles.
6. Audit integrity endpoint reports valid hash chain.
7. Household isolation and role controls are enforced in auth mode.

## Test and Debug Commands

Run all tests:

```bash
pytest -q
```

Target key suites:

```bash
pytest -q tests/test_api_contract.py
pytest -q tests/test_agent_runtime_chat.py
pytest -q tests/test_mvp_foundation.py
pytest -q tests/test_webhooks.py
```

## Implementation Notes

- Nivvi is execution-capable, but supervision is non-negotiable.
- Connectors are useful inputs, not a single point of failure.
- Provider adapters are intentionally pluggable; current defaults are sandbox rails.
