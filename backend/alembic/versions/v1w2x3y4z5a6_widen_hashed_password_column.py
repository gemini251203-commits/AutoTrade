"""widen hashed_password column from 100 to 255

Argon2 hashes can exceed 100 characters, causing registration failures.

Revision ID: v1w2x3y4z5a6
Revises: t1o2l3s4p5e6
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'v1w2x3y4z5a6'
down_revision = 't1o2l3s4p5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.String(100),
        type_=sa.String(255),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.String(255),
        type_=sa.String(100),
        existing_nullable=False,
    )
