"""create store snapshots table

Revision ID: 0001_store_snapshots
Revises:
Create Date: 2026-03-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_store_snapshots"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_store_snapshots"),
    )


def downgrade() -> None:
    op.drop_table("store_snapshots")

