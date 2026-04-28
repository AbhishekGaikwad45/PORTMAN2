"""MBC01: add arrived_yellow_crane column to mbc_discharge_port_lines

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'z6a7b8c9d0e1'
down_revision: Union[str, None] = 'y5z6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE mbc_discharge_port_lines ADD COLUMN IF NOT EXISTS arrived_yellow_crane TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE mbc_discharge_port_lines DROP COLUMN IF EXISTS arrived_yellow_crane")
