"""jnpa phase1 - recreate vcn_export_cargo_declaration mirroring vcn_consigners (minus BL)

Export parcels become the same shape as import parcels: they gain the
operational fields (igm_line_no, quantity, consigner_name, importer_name,
pipeline_name, unload_terminal, toll_applicable, toll_reason, equipment_names)
and drop the legacy EGM / customer / UOM / billing-tracking columns. No BL No or
BL Date on export. Legacy export rows are dropped (dev cutover, not migrated).

Revision ID: jnpa35_export_parcel_mirror
Revises: jnpa34_ldud_pilot_pickup_time
Create Date: 2026-07-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa35_export_parcel_mirror'
down_revision: Union[str, None] = 'jnpa34_ldud_pilot_pickup_time'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('DROP TABLE IF EXISTS vcn_export_cargo_declaration CASCADE;')
    op.execute('''
        CREATE TABLE vcn_export_cargo_declaration (
            id              SERIAL PRIMARY KEY,
            vcn_id          INTEGER NOT NULL REFERENCES vcn_header(id) ON DELETE CASCADE,
            parcel_seq      INTEGER,
            parcel_no       TEXT,
            igm_line_no     TEXT,
            cargo_name      TEXT,
            quantity        TEXT,
            consigner_name  TEXT,
            importer_name   TEXT,
            pipeline_name   TEXT,
            unload_terminal TEXT,
            toll_applicable BOOLEAN DEFAULT FALSE,
            toll_reason     TEXT,
            equipment_names TEXT
        );
    ''')


def downgrade() -> None:
    # Best-effort restore of the legacy shape (data is not recoverable).
    op.execute('DROP TABLE IF EXISTS vcn_export_cargo_declaration CASCADE;')
    op.execute('''
        CREATE TABLE vcn_export_cargo_declaration (
            id                       SERIAL PRIMARY KEY,
            vcn_id                   INTEGER NOT NULL REFERENCES vcn_header(id) ON DELETE CASCADE,
            egm_shipping_bill_number TEXT,
            egm_shipping_bill_date   TEXT,
            cargo_name               TEXT,
            customer_name            TEXT,
            bl_no                    TEXT,
            bl_date                  TEXT,
            bl_quantity              REAL,
            quantity_uom             TEXT,
            is_billed                INTEGER DEFAULT 0,
            bill_id                  INTEGER,
            billed_quantity          REAL DEFAULT 0,
            parcel_seq               INTEGER,
            parcel_no                TEXT
        );
    ''')
