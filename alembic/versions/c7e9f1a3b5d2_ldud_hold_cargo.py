"""LDUD01: add ldud_hold_cargo table for per-hold cargo config

Revision ID: c7e9f1a3b5d2
Revises: b5d8f2a4c916
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'c7e9f1a3b5d2'
down_revision: Union[str, None] = 'b5d8f2a4c916'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ldud_hold_cargo (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER NOT NULL,
            hold_name VARCHAR(100) NOT NULL,
            cargo_name VARCHAR(200),
            UNIQUE(ldud_id, hold_name)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ldud_hold_cargo")
