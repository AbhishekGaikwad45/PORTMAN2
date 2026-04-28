"""ldud_anchorage_recording

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_anchorage (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER REFERENCES ldud_header(id) ON DELETE CASCADE,
            anchorage_name TEXT,
            anchored TIMESTAMP,
            discharge_started TIMESTAMP,
            discharge_commenced TIMESTAMP,
            anchor_aweigh TIMESTAMP,
            cargo_quantity NUMERIC(12,2)
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS ldud_anchorage')
