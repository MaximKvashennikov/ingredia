"""Create accounts, private stock and administrative audit."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a frozen initial schema without runtime model imports."""
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3)),
        sa.Column("unit", sa.String(8)),
        sa.Column("expiry", sa.Date()),
        sa.Column("expiry_source", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity IS NULL OR quantity > 0"),
    )
    op.create_index("ix_batches_owner_id", "batches", ["owner_id"])
    op.create_table(
        "administrative_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_administrative_audit_target_id", "administrative_audit", ["target_id"])


def downgrade() -> None:
    """Remove the objects introduced by this revision."""
    op.drop_table("administrative_audit")
    op.drop_table("batches")
    op.drop_table("accounts")
