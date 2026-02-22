"""add trend schemes and snapshots tables

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

revision = "l6m7n8o9p0q1"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trend_schemes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config_yaml", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("is_preset", sa.Boolean(), default=False),
        sa.Column("last_result", sa.JSON(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trend_schemes_user_active", "trend_schemes", ["user_id", "is_active"])

    op.create_table(
        "trend_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("trend_schemes.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("direction_score", sa.Float(), default=0),
        sa.Column("strength", sa.String(20), nullable=False),
        sa.Column("strength_score", sa.Float(), default=0),
        sa.Column("volatility", sa.String(20), nullable=False),
        sa.Column("momentum", sa.String(20), nullable=False),
        sa.Column("regime", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), default=0),
        sa.Column("suitable_strategies", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trend_snapshots_scheme_time", "trend_snapshots", ["scheme_id", "created_at"])


def downgrade():
    op.drop_table("trend_snapshots")
    op.drop_table("trend_schemes")
