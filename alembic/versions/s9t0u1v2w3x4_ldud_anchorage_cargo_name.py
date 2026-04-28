"""add cargo_name to ldud_anchorage

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-02-18

"""
from alembic import op
import sqlalchemy as sa

revision = 's9t0u1v2w3x4'
down_revision = 'r8s9t0u1v2w3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ldud_anchorage', sa.Column('cargo_name', sa.String(200), nullable=True))


def downgrade():
    op.drop_column('ldud_anchorage', 'cargo_name')
