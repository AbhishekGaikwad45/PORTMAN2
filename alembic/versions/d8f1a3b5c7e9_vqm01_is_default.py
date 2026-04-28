"""VQM01: add is_default column to quantity_uom table

Revision ID: d8f1a3b5c7e9
Revises: c7e9f1a3b5d2
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'd8f1a3b5c7e9'
down_revision: Union[str, None] = 'c7e9f1a3b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE quantity_uom ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE quantity_uom DROP COLUMN IF EXISTS is_default")
