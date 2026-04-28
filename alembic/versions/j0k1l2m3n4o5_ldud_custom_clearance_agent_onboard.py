"""ldud_custom_clearance_and_agent_onboard

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE ldud_header ADD COLUMN IF NOT EXISTS custom_clearance TIMESTAMP')
    op.execute('ALTER TABLE ldud_header ADD COLUMN IF NOT EXISTS agent_stevedore_onboard TIMESTAMP')


def downgrade() -> None:
    op.execute('ALTER TABLE ldud_header DROP COLUMN IF EXISTS custom_clearance')
    op.execute('ALTER TABLE ldud_header DROP COLUMN IF EXISTS agent_stevedore_onboard')
