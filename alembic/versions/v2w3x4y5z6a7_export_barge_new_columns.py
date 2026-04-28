"""add export barge line columns for gull island empty and cast off loading berth

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-02-23
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'v2w3x4y5z6a7'
down_revision: Union[str, None] = 'u1v2w3x4y5z6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS cast_off_loading_berth TEXT')
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS anchored_gull_island_empty TEXT')
    op.execute('ALTER TABLE ldud_barge_lines ADD COLUMN IF NOT EXISTS aweigh_gull_island_empty TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS cast_off_loading_berth')
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS anchored_gull_island_empty')
    op.execute('ALTER TABLE ldud_barge_lines DROP COLUMN IF EXISTS aweigh_gull_island_empty')
