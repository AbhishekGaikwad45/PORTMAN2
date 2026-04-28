"""VC01: add no_of_holds column to vessels table

Revision ID: b5d8f2a4c916
Revises: 9f3a1e7c2b84
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b5d8f2a4c916'
down_revision: Union[str, None] = '9f3a1e7c2b84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE vessels ADD COLUMN IF NOT EXISTS no_of_holds INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE vessels DROP COLUMN IF EXISTS no_of_holds")
