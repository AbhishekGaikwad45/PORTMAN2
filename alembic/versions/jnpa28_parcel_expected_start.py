"""jnpa phase1 - ldud_parcel_ops gains expected_start

Expected (planned) start time per parcel, entered in LUEU01 alongside the
actual Start/End.

Revision ID: jnpa28_parcel_expected_start
Revises: jnpa27_ldud_first_line
Create Date: 2026-06-19
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa28_parcel_expected_start'
down_revision: Union[str, None] = 'jnpa27_ldud_first_line'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE ldud_parcel_ops ADD COLUMN IF NOT EXISTS expected_start TEXT;')


def downgrade() -> None:
    op.execute('ALTER TABLE ldud_parcel_ops DROP COLUMN IF EXISTS expected_start;')
