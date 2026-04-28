"""merge_igm_into_cargo_declaration

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-02-18
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'p6q7r8s9t0u1'
down_revision: Union[str, None] = 'o5p6q7r8s9t0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add IGM fields to vcn_cargo_declaration
    op.execute('ALTER TABLE vcn_cargo_declaration ADD COLUMN IF NOT EXISTS igm_number TEXT')
    op.execute('ALTER TABLE vcn_cargo_declaration ADD COLUMN IF NOT EXISTS igm_manual_number TEXT')
    op.execute('ALTER TABLE vcn_cargo_declaration ADD COLUMN IF NOT EXISTS igm_date TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE vcn_cargo_declaration DROP COLUMN IF EXISTS igm_date')
    op.execute('ALTER TABLE vcn_cargo_declaration DROP COLUMN IF EXISTS igm_manual_number')
    op.execute('ALTER TABLE vcn_cargo_declaration DROP COLUMN IF EXISTS igm_number')
