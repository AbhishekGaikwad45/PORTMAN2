"""cargo_declaration_customer

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE vcn_cargo_declaration ADD COLUMN IF NOT EXISTS customer_name TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE vcn_cargo_declaration DROP COLUMN IF EXISTS customer_name')
