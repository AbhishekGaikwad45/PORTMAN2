"""VC01: add num_cranes column to vessels table

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'y5z6a7b8c9d0'
down_revision: Union[str, None] = 'x4y5z6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE vessels ADD COLUMN IF NOT EXISTS num_cranes INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE vessels DROP COLUMN IF EXISTS num_cranes")
