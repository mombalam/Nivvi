"""create core household relational tables

Revision ID: 0003_core_household_relational
Revises: 0002_execution_audit_relational
Create Date: 2026-03-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_core_household_relational"
down_revision = "0002_execution_audit_relational"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "household_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_currency", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_household_records"),
    )

    op.create_table(
        "account_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("institution", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_account_records"),
    )
    op.create_index("ix_account_records_household_id", "account_records", ["household_id"])

    op.create_table(
        "transaction_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transaction_records"),
    )
    op.create_index("ix_transaction_records_household_id", "transaction_records", ["household_id"])
    op.create_index("ix_transaction_records_account_id", "transaction_records", ["account_id"])

    op.create_table(
        "deadline_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("penalty_risk", sa.Text(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_deadline_records"),
    )
    op.create_index("ix_deadline_records_household_id", "deadline_records", ["household_id"])

    op.create_table(
        "goal_records",
        sa.Column("goal_id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("target_amount", sa.Float(), nullable=False),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recommended_contribution", sa.Float(), nullable=False),
        sa.Column("tradeoffs_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("goal_id", name="pk_goal_records"),
    )
    op.create_index("ix_goal_records_household_id", "goal_records", ["household_id"])

    op.create_table(
        "rule_records",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_rule_id", sa.Text(), nullable=True),
        sa.Column("daily_amount_limit", sa.Float(), nullable=True),
        sa.Column("max_single_action", sa.Float(), nullable=True),
        sa.Column("blocked_categories_json", sa.Text(), nullable=False),
        sa.Column("blocked_action_types_json", sa.Text(), nullable=False),
        sa.Column("require_approval_always", sa.Boolean(), nullable=False),
        sa.Column("anomaly_detection_enabled", sa.Boolean(), nullable=False),
        sa.Column("anomaly_expense_multiplier", sa.Float(), nullable=False),
        sa.Column("anomaly_income_multiplier", sa.Float(), nullable=False),
        sa.Column("anomaly_min_expense_amount", sa.Float(), nullable=False),
        sa.Column("anomaly_min_income_amount", sa.Float(), nullable=False),
        sa.Column("weekly_planning_enabled", sa.Boolean(), nullable=False),
        sa.Column("weekly_drift_threshold_percent", sa.Float(), nullable=False),
        sa.Column("weekly_min_delta_amount", sa.Float(), nullable=False),
        sa.Column("weekly_cooldown_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("rule_id", name="pk_rule_records"),
    )
    op.create_index("ix_rule_records_household_id", "rule_records", ["household_id"])

    op.create_table(
        "chat_message_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chat_message_records"),
    )
    op.create_index("ix_chat_message_records_household_id", "chat_message_records", ["household_id"])

    op.create_table(
        "channel_identity_records",
        sa.Column("identity_key", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("user_handle", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("identity_key", name="pk_channel_identity_records"),
    )
    op.create_index("ix_channel_identity_records_household_id", "channel_identity_records", ["household_id"])

    op.create_table(
        "provider_connection_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("credentials_ref", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_provider_connection_records"),
    )
    op.create_index("ix_provider_connection_records_household_id", "provider_connection_records", ["household_id"])

    op.create_table(
        "provider_session_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("redirect_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_session_ref", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_provider_session_records"),
    )
    op.create_index("ix_provider_session_records_household_id", "provider_session_records", ["household_id"])

    op.create_table(
        "provider_sync_job_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_attempts_json", sa.Text(), nullable=False),
        sa.Column("synced_records", sa.Integer(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_provider_sync_job_records"),
    )
    op.create_index("ix_provider_sync_job_records_household_id", "provider_sync_job_records", ["household_id"])

    op.create_table(
        "household_sync_run_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("domains_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("job_ids_json", sa.Text(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_household_sync_run_records"),
    )
    op.create_index("ix_household_sync_run_records_household_id", "household_sync_run_records", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_household_sync_run_records_household_id", table_name="household_sync_run_records")
    op.drop_table("household_sync_run_records")

    op.drop_index("ix_provider_sync_job_records_household_id", table_name="provider_sync_job_records")
    op.drop_table("provider_sync_job_records")

    op.drop_index("ix_provider_session_records_household_id", table_name="provider_session_records")
    op.drop_table("provider_session_records")

    op.drop_index("ix_provider_connection_records_household_id", table_name="provider_connection_records")
    op.drop_table("provider_connection_records")

    op.drop_index("ix_channel_identity_records_household_id", table_name="channel_identity_records")
    op.drop_table("channel_identity_records")

    op.drop_index("ix_chat_message_records_household_id", table_name="chat_message_records")
    op.drop_table("chat_message_records")

    op.drop_index("ix_rule_records_household_id", table_name="rule_records")
    op.drop_table("rule_records")

    op.drop_index("ix_goal_records_household_id", table_name="goal_records")
    op.drop_table("goal_records")

    op.drop_index("ix_deadline_records_household_id", table_name="deadline_records")
    op.drop_table("deadline_records")

    op.drop_index("ix_transaction_records_account_id", table_name="transaction_records")
    op.drop_index("ix_transaction_records_household_id", table_name="transaction_records")
    op.drop_table("transaction_records")

    op.drop_index("ix_account_records_household_id", table_name="account_records")
    op.drop_table("account_records")

    op.drop_table("household_records")
