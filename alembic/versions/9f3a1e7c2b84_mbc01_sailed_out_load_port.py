"""MBC01: add sailed_out_load_port column to mbc_discharge_port_lines

Revision ID: 9f3a1e7c2b84
Revises: z6a7b8c9d0e1
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = '9f3a1e7c2b84'
down_revision: Union[str, None] = 'z6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE mbc_discharge_port_lines ADD COLUMN IF NOT EXISTS sailed_out_load_port TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE mbc_discharge_port_lines DROP COLUMN IF EXISTS sailed_out_load_port")
