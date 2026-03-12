"""create relational execution and audit tables

Revision ID: 0002_execution_audit_relational
Revises: 0001_store_snapshots
Create Date: 2026-03-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_execution_audit_relational"
down_revision = "0001_store_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("rationale_json", sa.Text(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approval_step", sa.Integer(), nullable=False),
        sa.Column("violations_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_action_records"),
    )
    op.create_index("ix_action_records_household_id", "action_records", ["household_id"])

    op.create_table(
        "action_approval_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("approval_step", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_action_approval_records"),
    )
    op.create_index("ix_action_approval_records_action_id", "action_approval_records", ["action_id"])
    op.create_index("ix_action_approval_records_household_id", "action_approval_records", ["household_id"])

    op.create_table(
        "execution_records",
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("partner_ref", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("reversible_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("provider_attempts_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("action_id", name="pk_execution_records"),
    )
    op.create_index("ix_execution_records_household_id", "execution_records", ["household_id"])

    op.create_table(
        "execution_attempt_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("partner_ref", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status_before", sa.Text(), nullable=False),
        sa.Column("status_after", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_execution_attempt_records"),
    )
    op.create_index("ix_execution_attempt_records_action_id", "execution_attempt_records", ["action_id"])
    op.create_index(
        "ix_execution_attempt_records_idempotency_key",
        "execution_attempt_records",
        ["idempotency_key"],
    )

    op.create_table(
        "audit_event_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("household_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.Text(), nullable=True),
        sa.Column("event_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_event_records"),
    )
    op.create_index("ix_audit_event_records_household_id", "audit_event_records", ["household_id"])
    op.create_index("ix_audit_event_records_event_hash", "audit_event_records", ["event_hash"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_records_event_hash", table_name="audit_event_records")
    op.drop_index("ix_audit_event_records_household_id", table_name="audit_event_records")
    op.drop_table("audit_event_records")

    op.drop_index("ix_execution_attempt_records_idempotency_key", table_name="execution_attempt_records")
    op.drop_index("ix_execution_attempt_records_action_id", table_name="execution_attempt_records")
    op.drop_table("execution_attempt_records")

    op.drop_index("ix_execution_records_household_id", table_name="execution_records")
    op.drop_table("execution_records")

    op.drop_index("ix_action_approval_records_household_id", table_name="action_approval_records")
    op.drop_index("ix_action_approval_records_action_id", table_name="action_approval_records")
    op.drop_table("action_approval_records")

    op.drop_index("ix_action_records_household_id", table_name="action_records")
    op.drop_table("action_records")
