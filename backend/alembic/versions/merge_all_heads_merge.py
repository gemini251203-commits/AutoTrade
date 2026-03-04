"""merge 3 heads into single migration chain

Merges:
- f1u2n3d4i5n6 (add funding fee fields)
- u1n2i3f4y5f6 (unify fee field names)
- p0f1x2p3r4c5 (fix float to numeric precision)

Revision ID: merge_all_heads
Revises: f1u2n3d4i5n6, u1n2i3f4y5f6, p0f1x2p3r4c5
Create Date: 2026-03-04
"""
from alembic import op

revision = 'merge_all_heads'
down_revision = ('f1u2n3d4i5n6', 'u1n2i3f4y5f6', 'p0f1x2p3r4c5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
