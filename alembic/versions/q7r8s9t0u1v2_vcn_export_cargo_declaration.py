"""vcn_export_cargo_declaration

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-02-18
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'q7r8s9t0u1v2'
down_revision: Union[str, None] = 'p6q7r8s9t0u1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_export_cargo_declaration (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            egm_shipping_bill_number TEXT,
            egm_shipping_bill_date TEXT,
            cargo_name TEXT,
            customer_name TEXT,
            bl_no TEXT,
            bl_date TEXT,
            bl_quantity REAL,
            quantity_uom TEXT,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS vcn_export_cargo_declaration CASCADE')
