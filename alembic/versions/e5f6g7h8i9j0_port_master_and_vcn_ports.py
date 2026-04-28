"""port_master_and_vcn_ports

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_master (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('ALTER TABLE vcn_header ADD COLUMN IF NOT EXISTS load_port TEXT')
    op.execute('ALTER TABLE vcn_header ADD COLUMN IF NOT EXISTS discharge_port TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE vcn_header DROP COLUMN IF EXISTS load_port')
    op.execute('ALTER TABLE vcn_header DROP COLUMN IF EXISTS discharge_port')
    op.execute('DROP TABLE IF EXISTS port_master')
