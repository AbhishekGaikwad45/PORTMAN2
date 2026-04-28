"""ldud_vessel_operations_and_barge_cleaning_lines

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-02-17
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Vessel Operations sub-table (hold-wise discharge)
    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_vessel_operations (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER NOT NULL,
            hold_name TEXT,
            start_time TEXT,
            end_time TEXT,
            cargo_name TEXT,
            quantity NUMERIC,
            FOREIGN KEY (ldud_id) REFERENCES ldud_header(id) ON DELETE CASCADE
        )
    ''')

    # Barge Cleaning Lines sub-table
    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_barge_cleaning (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER NOT NULL,
            barge_name TEXT,
            payloader_name TEXT,
            hmr_start NUMERIC,
            hmr_end NUMERIC,
            diesel_start TEXT,
            diesel_end TEXT,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY (ldud_id) REFERENCES ldud_header(id) ON DELETE CASCADE
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS ldud_barge_cleaning')
    op.execute('DROP TABLE IF EXISTS ldud_vessel_operations')
