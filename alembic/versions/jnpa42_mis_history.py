"""jnpa phase1 - mis_history base table for reports

Holds the legacy monthly MIS (JJLTPL) data, one row per customer/cargo
parcel line. Loaded via the RP01 wizard as a full replace (delete +
insert, never upsert) so future reports can use it as their base.

Revision ID: jnpa42_mis_history
Revises: jnpa41_invoice_sap_date_types
Create Date: 2026-07-07
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa42_mis_history'
down_revision: Union[str, None] = 'jnpa41_invoice_sap_date_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS mis_history (
            id               SERIAL PRIMARY KEY,
            fin_year         TEXT,           -- '2024-25'
            month_jsw        TEXT,           -- 'Nov-24'
            month_jnpt       TEXT,           -- 'Nov-24' (differs from JSW when ops cross month end)
            vcn_no           TEXT,
            vessel_name      TEXT,
            customer         TEXT,           -- billed party ('Company' in the MIS sheet)
            payment_by       TEXT,
            category         TEXT,           -- Category0 (Edible Oil / Chemical / POL / Other Liquid)
            sub_category1    TEXT,           -- Category1
            sub_category2    TEXT,           -- extra classification level
            cargo_class      TEXT,           -- 'Cargo'  (Edible Oil / Other Liquid / Ph.Acid / POL)
            cargo_name       TEXT,           -- 'Cargo1' (CPO, CDSBO, Acetic Acid, ...)
            terminal         TEXT,
            quantity         NUMERIC(14,3),
            overseas_coastal TEXT,
            import_export    TEXT,
            cargo_rate       NUMERIC(12,2),  -- (A) cargo handling
            cargo_amount     NUMERIC(14,2),
            infra_rate       NUMERIC(12,2),  -- (B) infrastructure & misc
            infra_amount     NUMERIC(14,2),
            toll_rate        NUMERIC(12,2),  -- (C) toll
            toll_amount      NUMERIC(14,2),
            gangway_agent    TEXT,           -- (D) shipping agent, first row of vessel only
            gangway_amount   NUMERIC(14,2),
            mla_rate         NUMERIC(12,2),  -- (E) MLA handling
            mla_amount       NUMERIC(14,2),
            remarks          TEXT,
            importer         TEXT,
            uploaded_by      TEXT,
            uploaded_at      TIMESTAMP DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_mis_history_vcn   ON mis_history (vcn_no);
        CREATE INDEX IF NOT EXISTS idx_mis_history_month ON mis_history (month_jnpt);
        CREATE INDEX IF NOT EXISTS idx_mis_history_fy    ON mis_history (fin_year);
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS mis_history;')
