"""Add durable purchase confirmation previews."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a preview table with ownership, event identity and expiry."""
    op.create_table(
        "purchase_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("event_key", sa.String(100), unique=True, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_purchase_drafts_owner_id", "purchase_drafts", ["owner_id"])


def downgrade() -> None:
    """Remove only the purchase preview table."""
    op.drop_table("purchase_drafts")
