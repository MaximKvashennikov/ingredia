"""Store owner-bound stock removal confirmations and known stock entry dates."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve legacy unknown entry dates and create confirmation storage."""
    op.add_column("batches", sa.Column("added_on", sa.Date(), nullable=True))
    op.create_table(
        "stock_removal_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stock_removal_drafts_owner_id", "stock_removal_drafts", ["owner_id"])


def downgrade() -> None:
    """Remove action drafts and entry-date metadata without restoring deleted stock."""
    op.drop_table("stock_removal_drafts")
    op.drop_column("batches", "added_on")
