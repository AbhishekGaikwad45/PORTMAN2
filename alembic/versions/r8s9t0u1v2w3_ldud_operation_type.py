"""add operation_type to ldud_header

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-02-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'r8s9t0u1v2w3'
down_revision = 'q7r8s9t0u1v2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ldud_header', sa.Column('operation_type', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('ldud_header', 'operation_type')
