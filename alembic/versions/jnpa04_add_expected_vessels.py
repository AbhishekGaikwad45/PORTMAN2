"""jnpa phase1 - add expected_vessels table

Revision ID: jnpa04_expected_vessels
Revises: jnpa03_terminal_pipeline
Create Date: 2026-04-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa04_expected_vessels'
down_revision: Union[str, None] = 'jnpa03_terminal_pipeline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS expected_vessels (
            id SERIAL PRIMARY KEY,
            terminal_name TEXT,
            vessel_name TEXT,
            via_number TEXT,
            loa NUMERIC(10,2),
            draft NUMERIC(10,2),
            agent_tank_consignee TEXT,
            cargo_name TEXT,
            mla TEXT,
            quantity NUMERIC(15,3),
            ddp DATE,
            dop DATE,
            eta TIMESTAMPTZ,
            ata TIMESTAMPTZ,
            lpc TIMESTAMPTZ,
            doc TIMESTAMPTZ,
            nor TIMESTAMPTZ,
            berth_name TEXT,
            vcn_id INTEGER,
            doc_status TEXT DEFAULT 'Pending',
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS expected_vessels CASCADE')
