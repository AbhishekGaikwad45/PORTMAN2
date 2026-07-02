"""jnpa phase1 - parcel_charge_billed ledger

Records which parcel x service has been billed, on which bill, and for how much.
One row per parcel x service x bill. This is the billed-status store for the AR
engine: is_vcn_billed() and billed_qty() read it, the bill generator writes it,
and bill cancellation voids it.

Revision ID: jnpa38_parcel_charge_billed
Revises: jnpa37_seed_finance_services
Create Date: 2026-07-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa38_parcel_charge_billed'
down_revision: Union[str, None] = 'jnpa37_seed_finance_services'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS parcel_charge_billed (
            id                SERIAL PRIMARY KEY,
            cargo_source_type TEXT NOT NULL,      -- 'VCN_IMPORT' | 'VCN_EXPORT'
            cargo_source_id   INTEGER NOT NULL,   -- parcel id (vcn_consigners / vcn_export_cargo_declaration)
            service_type_id   INTEGER,
            service_code      TEXT,
            bill_id           INTEGER,
            billed_quantity   NUMERIC,
            billed_date       TEXT,
            created_by        TEXT
        );
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_pcb_source ON parcel_charge_billed (cargo_source_type, cargo_source_id);')
    op.execute('CREATE INDEX IF NOT EXISTS ix_pcb_bill ON parcel_charge_billed (bill_id);')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS parcel_charge_billed;')
