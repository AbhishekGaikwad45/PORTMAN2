"""VFM01: add flag_type column to vessel_flags

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-02-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE vessel_flags ADD COLUMN IF NOT EXISTS flag_type VARCHAR(5)")


def downgrade() -> None:
    op.execute("ALTER TABLE vessel_flags DROP COLUMN IF EXISTS flag_type")
