# Alembic Migrations

Run migrations with:

```bash
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname alembic upgrade head
```

Current migration scope:
- `store_snapshots` table for full-state snapshot fallback.
- Relational execution/audit slice:
  - `action_records`
  - `action_approval_records`
  - `execution_records`
  - `execution_attempt_records`
  - `audit_event_records`
- Relational core household/provider/chat slice:
  - `household_records`
  - `account_records`
  - `transaction_records`
  - `deadline_records`
  - `goal_records`
  - `rule_records`
  - `chat_message_records`
  - `channel_identity_records`
  - `provider_connection_records`
  - `provider_session_records`
  - `provider_sync_job_records`
  - `household_sync_run_records`
