"""add new columns to ldud_barge_lines for import restructuring

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-02-23
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'u1v2w3x4y5z6'
down_revision: Union[str, None] = 't0u1v2w3x4y5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS crane_loaded_from TEXT')
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS trip_start TEXT')
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS amf_at_port TEXT')
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS cast_off_port TEXT')
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS port_crane TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS crane_loaded_from')
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS trip_start')
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS amf_at_port')
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS cast_off_port')
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS port_crane')
