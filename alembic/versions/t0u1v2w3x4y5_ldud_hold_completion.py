"""ldud_hold_completion table

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-02-23
"""
from typing import Sequence, Union
from alembic import op

revision: str = 't0u1v2w3x4y5'
down_revision: Union[str, None] = 's9t0u1v2w3x4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_hold_completion (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER NOT NULL,
            hold_name TEXT,
            commenced TEXT,
            completed TEXT,
            FOREIGN KEY (ldud_id) REFERENCES ldud_header(id) ON DELETE CASCADE
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS ldud_hold_completion')
