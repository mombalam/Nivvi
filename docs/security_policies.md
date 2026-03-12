# Nivvi Security Policies (Baseline)

This is the baseline security policy set for closed beta and production hardening of Nivvi as a supervised AI money manager.

## 1) Identity and Authentication

- Require authenticated access for protected `/v1/*` endpoints in non-public environments.
- Use short-lived bearer tokens with revocation support.
- Bind tokens to explicit user identity and household membership.
- Protect operator/bootstrap controls separately from end-user tokens.

## 2) Authorization and Household Isolation

- Enforce least-privilege role model (`owner/admin/member/viewer`).
- Scope every read/write operation by `household_id` membership.
- Reject cross-household data access by default.
- Require explicit role checks for mutating actions and dispatch paths.

## 3) Supervised Execution Integrity

- Enforce two-step approval (`confirm -> authorize`) for consequential actions.
- Bind approval artifacts to action ID, actor, timestamp, and channel context.
- Re-validate policy/risk gates at dispatch time.
- Reject dispatch attempts without valid approval artifacts.

## 4) API and Webhook Security

- Validate webhook authenticity:
  - WhatsApp signature verification (`X-Hub-Signature-256`)
  - Telegram secret token verification
- Enforce strict request validation and schema constraints.
- Apply rate limits and abuse controls to public-facing ingestion routes.
- Standardize structured error responses without leaking internal secrets.

## 5) Data Protection

- Encrypt data in transit (TLS 1.2+ minimum).
- Encrypt data at rest for databases, backups, and file/object storage.
- Classify sensitive financial and identity fields; mask where possible in logs.
- Store only necessary data; avoid retaining raw provider payloads longer than needed.

## 6) Secrets and Key Management

- Keep secrets in managed secret stores, never in source control.
- Rotate API keys, webhook secrets, and service credentials on schedule and incident.
- Use environment-specific credentials and strict separation of duties.
- Restrict secret access to required services and operators only.

## 7) Provider and Rail Security

- Maintain explicit provider allowlist and domain-scoped adapter permissions.
- Isolate provider credentials per environment and per integration.
- Capture provider request/response metadata needed for audit and incident triage.
- Apply provider kill switches and failover controls without bypassing approval policy.

## 8) Idempotency, Replay, and Fraud Controls

- Require idempotency keys on retry/replay-sensitive execution endpoints.
- Block idempotency-key reuse across different actions.
- Detect anomalous repeated dispatch attempts and escalate for review.
- Keep immutable attempt history for replay and fraud investigation.

## 9) Auditability and Tamper Evidence

- Record append-only audit events for proposal, approval, dispatch, and outcome.
- Hash-chain audit events for tamper evidence and integrity checks.
- Preserve actor identity and event provenance for every consequential action.
- Provide integrity verification endpoints or internal verification jobs.

## 10) Monitoring, Alerting, and Incident Response

- Monitor auth failures, policy denials, provider failures, and dispatch error classes.
- Alert on unusual approval/dispatch patterns and repeated failed execution attempts.
- Maintain incident playbooks for:
  - provider downtime
  - delayed sync
  - failed dispatch recovery
  - suspected account compromise
- Require incident postmortems and corrective action tracking.

## 11) Secure Development Lifecycle

- Require code review for security-sensitive paths (auth, policy, dispatch, webhooks).
- Use dependency scanning and patch critical vulnerabilities on defined SLA.
- Enforce test coverage for approval bypass, household isolation, and idempotency semantics.
- Keep environment parity between staging and production for security controls.

## 12) Privacy, Compliance, and Retention

- Maintain clear data-processing disclosures and user rights handling workflow.
- Apply retention schedules for logs, chat artifacts, and provider metadata.
- Support deletion/export flows aligned with legal obligations.
- Use regulated partner rails for licensed execution domains.

## 13) Business Continuity

- Maintain tested backup and restore procedures for core financial/audit data.
- Define recovery objectives (RPO/RTO) for critical services.
- Ensure degraded-mode continuity when provider connectors fail.
- Validate disaster-recovery runbooks during beta and before scale-up.

## Minimum Launch Security Gate

Closed beta should not launch unless all of the following are true:

- Household isolation is enforced in authenticated mode.
- Approval artifacts are mandatory and verified before dispatch.
- Webhook verification is enabled for connected chat channels.
- Audit hash-chain integrity checks pass.
- Provider failover and execution kill switches are operational.
- Incident escalation and recovery playbooks are documented and test-run.
