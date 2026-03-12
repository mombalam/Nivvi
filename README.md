# Nivvi AI Money Manager

Execution-capable AI money manager platform for households.

## Product positioning

People juggle multiple accounts, cards, loans, investments, bills, and tax obligations without a single view or plan. They rely on spreadsheets or siloed apps that track spending or handle one task, but cannot coordinate cash flow, deadlines, or goals. The result is missed bills, idle cash, unnecessary fees, under-saving, and too much financial admin.

Nivvi is an agentic, supervised AI money manager for the whole household financial system. It connects to the financial products you already use, builds a unified view of your money, identifies what matters most, prepares the right action across providers, and handles it once you approve. It manages cash flow, bills, debt, taxes, and investing decisions as one system, not five separate problems.

See `docs/positioning.md` for the canonical category definition and language guide.
See `docs/nivvi_system_spec.md` for the canonical end-to-end system architecture, rules, setup, and operations.
See `docs/business_process_flow.md` for the operational business process from onboarding to supervised execution and adaptation.
See `docs/security_policies.md` for the baseline security controls and launch security gate.
See `docs/preseed_investor_deck.md` for the pre-seed investor deck content package.
See `docs/closed_beta_ops.md` for launch-gate and incident runbooks.
See `docs/landing_deploy.md` for deploying the landing/marketing app.

Nivvi is not just Cleo plus open banking. It manages across cash, bills, debt, investing context, and taxes together, then prepares and executes approved actions instead of stopping at chat or categorization.

Business model: subscription-first and alignment-first.

Reliability principle: connectors are useful inputs, not a single point of failure. If a sync is delayed or fails, Nivvi continues from the latest good state and provider failover paths.

Nivvi is not:
- a neobank that primarily offers new bank accounts/cards
- a passive spending tracker or dashboard-only aggregator
- a chatbot that only answers questions without managing execution
- a narrow automation tool that only optimizes one money workflow at a time

Nivvi does:
- unify accounts, liabilities, investments, deadlines, and goals into one financial graph
- continuously plan cash, debt, investing, and tax actions together
- run portfolio opportunity intelligence: detect holding drift/opportunity and draft mandate/risk/tax-aware moves
- prepare concrete action drafts with impact previews
- execute only after explicit user approval, policy checks, and partner-rail dispatch

Category ladder:
- tracker = shows what happened
- advisor = tells you what to do
- money manager = prepares and executes approved actions

## Advisor operating loop

Nivvi follows the same continuous loop a strong financial advisor would run:

1. Understand the current financial state across all connected data.
2. Build and maintain a personalized plan using forecasts and deadlines.
3. Recommend prioritized actions with rationale and expected impact.
4. Execute approved actions through regulated partners.
5. Monitor outcomes, detect drift/anomalies, and adapt the plan.

## What is implemented

- FastAPI backend covering the planned endpoints:
  - marketing routes (`/`, `/waitlist`, `/waitlist/success`, `/legal/privacy`, `/legal/terms`)
  - companion app route (`/app`)
  - waitlist capture (`POST /v1/waitlist`) and marketing analytics ingestion (`POST /v1/analytics/events`)
  - secured waitlist lead read/export (`GET /v1/admin/waitlist/leads`, `GET /v1/admin/waitlist/leads.csv` with `x-admin-key`)
  - account linking and provider-ingested transaction/deadline updates
  - unified ledger retrieval
  - 30/60/90-day probabilistic cashflow forecasting
  - deadline timeline with Netherlands guardrail defaults
  - planning insights endpoint (`GET /v1/planning/insights`)
- action proposal, preview, two-step approval, rejection, and dispatch
  - dispatch includes idempotency-key replay safety and conflict checks
  - execution history endpoint and explicit retry endpoint for failed dispatches
  - rule upsert versioning (`POST /v1/rules`) with active-only policy evaluation
  - rule history retrieval (`GET /v1/rules?include_inactive=true`)
  - policy checks before proposal and dispatch
  - goal plans, invest workspace recommendation object, and tax workspace package object
  - chat command ingestion (`/v1/chat/events`) and chat thread retrieval (`/v1/chat/messages`)
  - provider webhooks for WhatsApp and Telegram
  - provider connection/sync/health endpoints for multi-rail orchestration
  - provider session lifecycle endpoints (initiate + complete) for connector linking
  - household-level sync run endpoints with per-domain status aggregation
  - beta auth and household isolation tooling endpoints
  - background agent runtime control/status endpoints
  - runtime metrics endpoint for loop latency/emissions/dispatch outcomes
  - append-only audit event retrieval
- Agent orchestrator daily monitor loop that can emit cashflow-protection draft actions.
- Event-driven anomaly loop for unexpected income/expense shocks with intervention drafts.
- Weekly planning loop for spend-drift detection and envelope rebalance draft actions.
- Loop thresholds and enable/disable toggles configurable via household safety rules.
- Dry-run loop simulation endpoint (`POST /v1/agent/loops/simulate`) to preview emissions without side effects.
- In-process async runtime that periodically executes agent cycles across all households.
- Optional PostgreSQL snapshot persistence backend (`NIVVI_STORE_BACKEND=postgres`) with Alembic migration baseline.
- Relational Postgres slice for core household + execution + audit entities when `NIVVI_STORE_BACKEND=postgres`.
- Mobile-first companion web app (`/app`) with tabs:
  - `Today`, `Chat`, `Cashflow`, `Actions`, `Goals`, `Accounts`, `Rules & Safety`, `Audit Log`
  - `Invest Workspace`, `Tax Workspace`
- Demo bootstrap flow in the UI for quick end-to-end interaction.

## Safety model

- Per-action explicit approval is required (`confirm` then `authorize`).
- Policy checks run during proposal and again before dispatch.
- Investment dispatch is blocked when suitability flags indicate non-compliance.
- Tax-submission dispatch is blocked until tax package `missing_items` is empty.
- Dispatch goes through partner-rail simulation and records immutable audit events.
- Failed dispatch retries require an idempotency key for safe replay semantics.
- Execution rails support provider failover (primary -> fallback) when configured.
- Household-level access isolation is available via optional token auth (`NIVVI_REQUIRE_AUTH=true`).
- Role-aware household permissions are enforced when auth is enabled (`owner/admin/member` write, `viewer` read-only).
- Beta operations can be restricted to bootstrap operator token (`NIVVI_BOOTSTRAP_TOKEN`).
- Provider-level execution kill switch is available via `NIVVI_DISABLED_EXECUTION_PROVIDERS`.
- Audit events are hash-chained and verifiable through integrity checks.
- Action lifecycle artifacts are dual-written to relational tables in Postgres mode.
- Core household data (households, accounts, transactions, deadlines, goals, rules, chat, provider artifacts) is dual-written to relational tables in Postgres mode.

## Agent runtime and chat commands

- Runtime endpoints:
  - `GET /v1/agent/runtime`
  - `GET /v1/agent/runtime/metrics`
  - `POST /v1/agent/runtime/start`
  - `POST /v1/agent/runtime/stop`
  - `POST /v1/agent/runtime/run-cycle`
  - cycle output now includes `emitted_by_loop` and `interventions_sent`.
- Agent simulation endpoint:
  - `POST /v1/agent/loops/simulate`
- Chat endpoints:
  - `POST /v1/chat/events`
  - `GET /v1/chat/messages`
  - `POST /v1/chat/identities/link`
  - `GET /v1/chat/identities`
- Provider webhook endpoints:
  - `GET /webhooks/whatsapp` (Meta verification challenge)
  - `POST /webhooks/whatsapp`
  - `POST /webhooks/telegram`
- Supported chat commands:
  - natural language prompts are supported (for example: `What should I prioritize this week?`, `Please execute act_...`)
  - `brief` / `status` / `summary`
  - `today`
  - `actions`
  - `preview <action_id>`
  - `approve <action_id>` (smart step: confirm then authorize)
  - `confirm <action_id>`
  - `authorize <action_id>`
  - `reject <action_id> [reason]`
  - `dispatch <action_id>`
  - `dispatch <action_id> <idempotency_key>` (optional key for safe retries/replays)
  - `help`

Execution endpoints:
- `GET /v1/executions/{action_id}`
- `POST /v1/executions/{action_id}/dispatch`
- `POST /v1/executions/{action_id}/retry`

Audit endpoints:
- `GET /v1/audit/events`
- `GET /v1/audit/integrity`

Provider integration endpoints:
- `POST /v1/providers/ingest`
- `POST /v1/providers/connections`
- `GET /v1/providers/connections`
- `POST /v1/providers/sessions`
- `GET /v1/providers/sessions`
- `POST /v1/providers/sessions/{session_id}/complete`
- `POST /v1/providers/sync`
- `GET /v1/providers/sync/{sync_id}`
- `GET /v1/providers/health`
- `POST /v1/households/{household_id}/sync`
- `GET /v1/households/{household_id}/sync/{run_id}`

Closed beta operations endpoints:
- `POST /v1/beta/users`
- `POST /v1/beta/users/{user_id}/tokens`
- `POST /v1/beta/households/{household_id}/memberships`
- `POST /v1/beta/households/{household_id}/status`
- `GET /v1/beta/households/{household_id}/diagnostics`
- `GET /v1/beta/launch-gate`

## Webhook configuration

- `WHATSAPP_VERIFY_TOKEN`: required for `GET /webhooks/whatsapp` verification.
- `WHATSAPP_APP_SECRET`: optional but recommended; when set, `POST /webhooks/whatsapp` requires valid `X-Hub-Signature-256`.
- `TELEGRAM_WEBHOOK_SECRET`: optional but recommended; when set, `POST /webhooks/telegram` requires matching `X-Telegram-Bot-Api-Secret-Token`.
- `NIVVI_BOOTSTRAP_TOKEN`: optional bootstrap operator token for protected beta-ops endpoints when auth is enabled.
- `NIVVI_DISABLED_EXECUTION_PROVIDERS`: optional comma-separated provider names blocked from dispatch.

## Run locally

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

Then open:
- Marketing landing: <http://127.0.0.1:8000/>
- Marketing docs: <http://127.0.0.1:8000/docs>
- Product companion app: <http://127.0.0.1:8001/app>
- Product API docs: <http://127.0.0.1:8001/docs>

## Notes

- Storage is in-memory for MVP scaffolding.
- For PostgreSQL-backed snapshots:
- For PostgreSQL mode (snapshots + relational execution/audit slice):
  - `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname`
  - `NIVVI_STORE_BACKEND=postgres`
  - `alembic upgrade head`
- Multi-currency support is modeled at the data layer; FX conversion in forecasts is currently simplified.
- Investment execution is constrained to supervised approvals and simulated partner dispatch.
