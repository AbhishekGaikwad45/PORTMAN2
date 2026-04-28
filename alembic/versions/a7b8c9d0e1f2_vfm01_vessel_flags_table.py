"""VFM01: create vessel_flags table

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
Create Date: 2026-02-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS vessel_flags (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vessel_flags")
