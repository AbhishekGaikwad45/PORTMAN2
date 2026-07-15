"""jnpa phase1 - sr_no serial column for mis_history + mis_vessel_master

Users asked for the legacy sheet's SN serial back as the first template
column (was excluded on purpose in jnpa42/43).

Revision ID: jnpa47_mis_sr_no
Revises: jnpa46_saved_pivot_reports
Create Date: 2026-07-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa47_mis_sr_no'
down_revision: Union[str, None] = 'jnpa46_saved_pivot_reports'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE mis_history ADD COLUMN IF NOT EXISTS sr_no INTEGER;')
    op.execute('ALTER TABLE mis_vessel_master ADD COLUMN IF NOT EXISTS sr_no INTEGER;')


def downgrade() -> None:
    op.execute('ALTER TABLE mis_history DROP COLUMN IF EXISTS sr_no;')
    op.execute('ALTER TABLE mis_vessel_master DROP COLUMN IF EXISTS sr_no;')
