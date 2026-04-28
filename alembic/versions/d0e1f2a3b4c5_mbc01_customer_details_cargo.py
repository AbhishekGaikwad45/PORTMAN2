"""MBC01: add cargo_name to mbc_customer_details

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-02-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE mbc_customer_details ADD COLUMN IF NOT EXISTS cargo_name VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE mbc_customer_details DROP COLUMN IF EXISTS cargo_name")
