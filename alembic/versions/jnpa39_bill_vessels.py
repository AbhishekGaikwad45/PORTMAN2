"""jnpa phase1 - bill_vessels mapping (a bill can span multiple VCNs)

Revision ID: jnpa39_bill_vessels
Revises: jnpa38_parcel_charge_billed
Create Date: 2026-07-02
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa39_bill_vessels'
down_revision: Union[str, None] = 'jnpa38_parcel_charge_billed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS bill_vessels (
            id      SERIAL PRIMARY KEY,
            bill_id INTEGER NOT NULL REFERENCES bill_header(id) ON DELETE CASCADE,
            vcn_id  INTEGER NOT NULL REFERENCES vcn_header(id)
        );
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_bill_vessels_bill ON bill_vessels (bill_id);')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS bill_vessels;')
