"""Add expiry estimate provenance and private recipe snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve existing stock dates and create owner-bound recipe storage."""
    op.add_column("batches", sa.Column("expiry_estimate", sa.JSON(), nullable=True))
    op.create_table(
        "recipes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_recipes_owner_id", "recipes", ["owner_id"])


def downgrade() -> None:
    """Remove the new recipe table and estimate provenance column."""
    op.drop_table("recipes")
    op.drop_column("batches", "expiry_estimate")
