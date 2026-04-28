"""vdm01_add_to_sof_and_type_columns

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-02-17
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE vessel_delay_types ADD COLUMN IF NOT EXISTS to_sof TEXT')
    op.execute('ALTER TABLE vessel_delay_types ADD COLUMN IF NOT EXISTS type TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE vessel_delay_types DROP COLUMN IF EXISTS to_sof')
    op.execute('ALTER TABLE vessel_delay_types DROP COLUMN IF EXISTS type')
