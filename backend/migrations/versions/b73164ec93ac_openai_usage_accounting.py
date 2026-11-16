"""OpenAI usage metadata and immutable pricing snapshots.

Revision ID: b73164ec93ac
Revises: af87f7d9d383
"""

from alembic import op
import sqlalchemy as sa

revision = "b73164ec93ac"
down_revision = "af87f7d9d383"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("model_allocation", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("inferences", sa.Column("usage_details", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("inferences", sa.Column("pricing", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("inferences", sa.Column("purpose", sa.String(30), nullable=False, server_default="routine"))
    op.add_column("inferences", sa.Column("response_id", sa.String(200), nullable=True))
    op.add_column("inferences", sa.Column("reported_model", sa.String(200), nullable=True))


def downgrade():
    op.drop_column("jobs", "model_allocation")
    for name in ("reported_model", "response_id", "purpose", "pricing", "usage_details"):
        op.drop_column("inferences", name)
