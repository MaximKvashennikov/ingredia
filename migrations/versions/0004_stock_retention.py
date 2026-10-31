"""Index expiry cleanup and retain minimal deduplication keys after deletion."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the cleanup index and an event-key ledger without product payloads."""
    op.create_index("ix_batches_expiry", "batches", ["expiry"])
    op.create_table(
        "removed_stock_events",
        sa.Column("event_key", sa.String(100), primary_key=True),
        sa.Column(
            "removed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    """Remove maintenance metadata without recreating already deleted products."""
    op.drop_table("removed_stock_events")
    op.drop_index("ix_batches_expiry", table_name="batches")
