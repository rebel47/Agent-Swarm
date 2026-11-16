"""Persist repository snapshot ownership and preparation state."""

from alembic import op
import sqlalchemy as sa

revision = "c9b38f62a19d"
down_revision = "b73164ec93ac"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "repository_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("location", sa.String(2000), nullable=False),
        sa.Column("ref", sa.String(200), nullable=True),
        sa.Column("revision", sa.String(80), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_repository_sources_owner_id", "repository_sources", ["owner_id"])


def downgrade():
    op.drop_table("repository_sources")
