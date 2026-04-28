"""EU01 revamp: add new master tables (port_systems, port_shift_incharge, port_shift_operators) and new lueu_lines columns

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-02-24
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'x4y5z6a7b8c9'
down_revision: Union[str, None] = 'w3x4y5z6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Port System Master
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_systems (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    # Port Shift Incharge Master
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_shift_incharge (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    # Port Shift Operator Master
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_shift_operators (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    # Add new columns to lueu_lines
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS shift TEXT")
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS from_time TEXT")
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS to_time TEXT")
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS system_name TEXT")
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS berth_name TEXT")
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS shift_incharge TEXT")
    op.execute("ALTER TABLE lueu_lines ADD COLUMN IF NOT EXISTS remarks TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS shift")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS from_time")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS to_time")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS system_name")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS berth_name")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS shift_incharge")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS remarks")
    op.execute('DROP TABLE IF EXISTS port_shift_operators CASCADE')
    op.execute('DROP TABLE IF EXISTS port_shift_incharge CASCADE')
    op.execute('DROP TABLE IF EXISTS port_systems CASCADE')
