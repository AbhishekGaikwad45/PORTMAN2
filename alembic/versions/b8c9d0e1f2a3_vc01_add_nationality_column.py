"""VC01: add nationality column to vessels table

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-02-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE vessels ADD COLUMN IF NOT EXISTS nationality VARCHAR(100)")


def downgrade() -> None:
    op.execute("ALTER TABLE vessels DROP COLUMN IF EXISTS nationality")
