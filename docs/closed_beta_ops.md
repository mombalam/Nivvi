# Nivvi Closed Beta Operations Playbook

## Purpose
Operational runbook for the 12-week closed beta launch gate. This defines incident handling for provider issues and execution failures while preserving supervised controls and auditability.

## Core Principles
- No consequential action dispatches without `confirm + authorize`.
- Connector degradation must preserve planning continuity.
- Provider failures are retried safely with idempotency keys only.
- Every intervention and execution attempt must remain reconstructable from audit logs.
- Household access follows role-based controls; `viewer` can inspect but not execute.

## Incident Playbooks

### 1) Provider downtime (execution rails unavailable)
- Trigger condition:
  - Provider health transitions to non-healthy or dispatch failures spike.
- Immediate actions:
  - Disable affected provider(s) using `NIVVI_DISABLED_EXECUTION_PROVIDERS`.
  - Confirm fallback provider routes are active via `/v1/providers/health`.
  - Notify beta support channel with impacted domain and expected mitigation window.
- Recovery:
  - Re-enable provider only after health checks pass and one controlled dispatch succeeds.

### 2) Sync delay / aggregation drift
- Trigger condition:
  - Provider sync jobs repeatedly fail or produce stale windows.
- Immediate actions:
  - Trigger household sync: `POST /v1/households/{id}/sync`.
  - If still degraded, continue planning from last-good synchronized state while provider retries run.
  - Keep forecast/timeline active under degraded connector conditions.
- Recovery:
  - Validate successful sync run + expected record volume before closing incident.

### 3) Failed dispatch recovery
- Trigger condition:
  - Execution receipt result = `failed`.
- Immediate actions:
  - Inspect latest attempt: `GET /v1/executions/{action_id}`.
  - Confirm policy/readiness gates are still valid.
  - Retry with new idempotency key (`POST /v1/executions/{action_id}/retry`).
- Recovery:
  - Ensure one successful receipt exists and audit trail includes failure + retry chain.

## Launch Gate Checklist
- Data integrity: restart-safe state and reconstructable action/audit/chat timelines.
- Supervised execution: no dispatch path bypasses confirm+authorize.
- Idempotency: replay and collision protections pass for all action domains.
- Provider resilience: primary failure falls back or degrades gracefully.
- Loop safety: no duplicate anomaly/weekly interventions after repeated cycles.
- Compliance gates: suitability + tax completeness block in API and chat-driven flows.
- Isolation/security: household access controls enforced under auth-required mode.
- Cross-channel consistency: statuses match across API, app, and chat threads.

## Operator Endpoints
- Provider:
  - `GET /v1/providers/health`
  - `POST /v1/providers/sync`
  - `POST /v1/households/{household_id}/sync`
- Execution:
  - `POST /v1/executions/{action_id}/dispatch`
  - `POST /v1/executions/{action_id}/retry`
  - `GET /v1/executions/{action_id}`
- Beta ops:
  - `POST /v1/beta/households/{household_id}/status`
  - `GET /v1/beta/households/{household_id}/diagnostics`
- Runtime observability:
  - `GET /v1/agent/runtime`
  - `GET /v1/agent/runtime/metrics`
- Audit integrity:
  - `GET /v1/audit/events`
  - `GET /v1/audit/integrity`
