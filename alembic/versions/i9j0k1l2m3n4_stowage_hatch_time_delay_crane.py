"""stowage_hatch_completion_time_and_delay_crane_number

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE vcn_stowage_plan ADD COLUMN IF NOT EXISTS hatch_completion_time TIMESTAMP')
    op.execute('ALTER TABLE ldud_delays ADD COLUMN IF NOT EXISTS crane_number TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE vcn_stowage_plan DROP COLUMN IF EXISTS hatch_completion_time')
    op.execute('ALTER TABLE ldud_delays DROP COLUMN IF EXISTS crane_number')
