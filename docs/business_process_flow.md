# Nivvi Business Process Flow

This document describes how Nivvi operates as a supervised AI money manager from onboarding through execution and continuous adaptation.

## End-to-End Flow

```text
User onboarding + provider linking
            |
            v
Unified financial graph build
            |
            v
Mandate and policy setup
            |
            v
Continuous monitoring (loops + provider sync)
            |
            v
Opportunity detection and ranking
            |
            v
Action preparation + impact preview
            |
            v
Two-step user approval (confirm -> authorize)
            |
            v
Provider dispatch (primary -> fallback)
            |
            v
Receipt, reconciliation, audit logging
            |
            v
Outcome scoring and plan adaptation
```

## Process Stages

### 1) Onboard and connect

- Create user and household context.
- Link provider connections across aggregation and execution rails.
- Trigger initial provider ingest and baseline sync.
- Build first unified graph snapshot.

### 2) Define mandate and safety envelope

- Capture priorities (liquidity safety, debt reduction, growth, tax timing, deadline protection).
- Capture constraints (risk limits, blocked actions/categories, max action sizes).
- Persist user rules and approval requirements.
- Store mandate as the optimization reference.

### 3) Monitor continuously

- Run daily monitor, anomaly, weekly planning, and deadline-guard loops.
- Refresh balances, transactions, deadlines, and provider health.
- Detect drift, shocks, due-risk windows, and opportunity signals.
- Maintain continuity using fallback providers and last-good-state planning.

### 4) Prioritize and prepare

- Score opportunities by impact, urgency, confidence, and mandate fit.
- Select next-best playbook run.
- Draft one or more action proposals with rationale and expected impact.
- Generate preview artifacts for cash, fee, goal, and deadline effects.

### 5) Supervised approval

- Require explicit two-step approval:
  - confirm
  - authorize
- Block dispatch if policy gates fail.
- Block domain-specific execution when readiness gates fail (for example suitability/completeness blockers).

### 6) Execute through provider rails

- Dispatch approved action through provider router (primary then fallback).
- Enforce idempotency and replay safety.
- Persist execution attempts and final receipt.
- Capture provider references and dispatch metadata.

### 7) Reconcile, log, and adapt

- Reconcile result into the financial graph and household timeline.
- Append hash-chained audit events for proposal, approval, dispatch, and outcome.
- Compare expected vs realized impact.
- Update playbook quality and future prioritization.

## Exception and Recovery Flows

### Provider sync degraded

- Mark provider/domain health state.
- Continue planning with last-good-state and partial continuity.
- Trigger fallback provider sync path.
- Emit user-facing status intervention when continuity risk is material.

### Dispatch failed

- Transition action to `failed`.
- Persist failure class and provider attempt history.
- Offer retry with idempotency key and policy re-checks.
- Keep full audit trail for support and reconstruction.

### Approval timeout or rejection

- Keep action in non-dispatched state.
- Optionally propose revised action if context changed.
- Log rejection reason when provided.

## Operating Roles

- User: sets mandate, approves actions, reviews outcomes.
- Agent Runtime: detects, ranks, drafts, and follows up.
- Policy/Risk Engine: enforces limits and readiness gates.
- Execution Gateway: dispatches and retries safely.
- Provider Adapters: sync/execute through external rails.
- Support/Ops: manage incidents, diagnostics, and cohort controls.

## Closed Beta Process Guardrails

- No consequential action executes without valid confirm+authorize artifacts.
- Every execution path is auditable end-to-end.
- Provider degradation cannot silently collapse household planning.
- Household isolation and authorization boundaries remain enforced.
