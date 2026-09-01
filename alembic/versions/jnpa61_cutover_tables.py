"""jnpa phase2 - go-live cutover: numbering seeds + audit trail

At go-live PORTMAN2 must continue document numbering from wherever the legacy
system stopped, and must never re-bill cargo the legacy system already
invoiced. `cutover_seed` holds the numbering floor per (type, series, FY);
`cutover_audit` records every cutover action, including the lock/unlock that
freezes the whole feature once go-live data is final.

Revision ID: jnpa61_cutover_tables
Revises: jnpa60_sap_tax_code_split
Create Date: 2026-09-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa61_cutover_tables'
down_revision: Union[str, None] = 'jnpa60_sap_tax_code_split'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS cutover_seed (
            id             SERIAL PRIMARY KEY,
            seed_type      TEXT NOT NULL,
            doc_series     TEXT NOT NULL DEFAULT '',
            financial_year TEXT NOT NULL DEFAULT '',
            start_seq      INTEGER NOT NULL,
            created_by     TEXT,
            updated_by     TEXT,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    op.execute('''CREATE UNIQUE INDEX IF NOT EXISTS ux_cutover_seed_key
                  ON cutover_seed (seed_type, doc_series, financial_year);''')
    op.execute('''
        CREATE TABLE IF NOT EXISTS cutover_audit (
            id            SERIAL PRIMARY KEY,
            action        TEXT NOT NULL,
            details       TEXT,
            performed_by  TEXT,
            performed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_cutover_audit_action ON cutover_audit (action);')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS cutover_audit;')
    op.execute('DROP TABLE IF EXISTS cutover_seed;')
