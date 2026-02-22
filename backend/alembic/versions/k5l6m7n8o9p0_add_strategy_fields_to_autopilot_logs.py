"""add strategy fields to autopilot_logs

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("autopilot_logs", sa.Column("strategy_id", sa.Integer(), nullable=True))
    op.add_column("autopilot_logs", sa.Column("strategy_name", sa.String(100), nullable=True))
    op.add_column("autopilot_logs", sa.Column("signal_raw", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("autopilot_logs", "signal_raw")
    op.drop_column("autopilot_logs", "strategy_name")
    op.drop_column("autopilot_logs", "strategy_id")
