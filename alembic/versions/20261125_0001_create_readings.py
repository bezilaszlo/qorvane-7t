"""create readings

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "readings",
        sa.Column("sensor_id", sa.Text, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Double, nullable=False),
        sa.PrimaryKeyConstraint("sensor_id", "metric", "ts"),
    )


def downgrade() -> None:
    op.drop_table("readings")
