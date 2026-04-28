"""invoice_doc_series table, vessel fields on invoice_header, virtual account + admin bank extras

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6h8i9
Create Date: 2026-03-06
"""
from alembic import op

revision = 'd1e2f3a4b5c6'
down_revision = 'c3d4e5f6h8i9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Invoice doc series master ──────────────────────────────────────────
    op.execute('''
        CREATE TABLE IF NOT EXISTS invoice_doc_series (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            prefix TEXT NOT NULL,
            is_default BOOLEAN DEFAULT FALSE
        )
    ''')

    # ── 2. invoice_header — vessel / operational fields ────────────────────────
    op.execute('''
        ALTER TABLE invoice_header
            ADD COLUMN IF NOT EXISTS doc_series TEXT,
            ADD COLUMN IF NOT EXISTS doc_series_seq INTEGER,
            ADD COLUMN IF NOT EXISTS vessel_name TEXT,
            ADD COLUMN IF NOT EXISTS vessel_call_no TEXT,
            ADD COLUMN IF NOT EXISTS commodity TEXT,
            ADD COLUMN IF NOT EXISTS date_of_berthing TEXT,
            ADD COLUMN IF NOT EXISTS date_of_sailing TEXT,
            ADD COLUMN IF NOT EXISTS grt_of_vessel TEXT,
            ADD COLUMN IF NOT EXISTS no_of_days REAL,
            ADD COLUMN IF NOT EXISTS cargo_quantity REAL,
            ADD COLUMN IF NOT EXISTS no_of_hrs REAL,
            ADD COLUMN IF NOT EXISTS is_cancelled INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS cancelled_at TEXT,
            ADD COLUMN IF NOT EXISTS ship_to_name TEXT,
            ADD COLUMN IF NOT EXISTS ship_to_address TEXT,
            ADD COLUMN IF NOT EXISTS ship_to_gstin TEXT,
            ADD COLUMN IF NOT EXISTS ship_to_state_code TEXT
    ''')

    # ── 3. port_bank_accounts — create if missing, then ensure extra columns ──
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_bank_accounts (
            id SERIAL PRIMARY KEY,
            bank_name TEXT,
            account_number TEXT,
            ifsc_code TEXT,
            account_holder_name TEXT,
            branch_name TEXT,
            pan TEXT,
            cin TEXT,
            corporate_office_address TEXT
        )
    ''')
    op.execute('ALTER TABLE port_bank_accounts ADD COLUMN IF NOT EXISTS pan TEXT')
    op.execute('ALTER TABLE port_bank_accounts ADD COLUMN IF NOT EXISTS cin TEXT')
    op.execute('ALTER TABLE port_bank_accounts ADD COLUMN IF NOT EXISTS corporate_office_address TEXT')

    # ── 4. vessel_customers — virtual account number ───────────────────────────
    op.execute('''
        ALTER TABLE vessel_customers
            ADD COLUMN IF NOT EXISTS virtual_account_number TEXT
    ''')

    # ── 5. vessel_agents — virtual account number ─────────────────────────────
    op.execute('''
        ALTER TABLE vessel_agents
            ADD COLUMN IF NOT EXISTS virtual_account_number TEXT
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE vessel_agents DROP COLUMN IF EXISTS virtual_account_number')
    op.execute('ALTER TABLE vessel_customers DROP COLUMN IF EXISTS virtual_account_number')
    op.execute('DROP TABLE IF EXISTS port_bank_accounts CASCADE')
    op.execute('''
        ALTER TABLE invoice_header
            DROP COLUMN IF EXISTS doc_series,
            DROP COLUMN IF EXISTS doc_series_seq,
            DROP COLUMN IF EXISTS vessel_name,
            DROP COLUMN IF EXISTS vessel_call_no,
            DROP COLUMN IF EXISTS commodity,
            DROP COLUMN IF EXISTS date_of_berthing,
            DROP COLUMN IF EXISTS date_of_sailing,
            DROP COLUMN IF EXISTS grt_of_vessel,
            DROP COLUMN IF EXISTS no_of_days,
            DROP COLUMN IF EXISTS cargo_quantity,
            DROP COLUMN IF EXISTS no_of_hrs,
            DROP COLUMN IF EXISTS is_cancelled,
            DROP COLUMN IF EXISTS cancelled_at,
            DROP COLUMN IF EXISTS ship_to_name,
            DROP COLUMN IF EXISTS ship_to_address,
            DROP COLUMN IF EXISTS ship_to_gstin,
            DROP COLUMN IF EXISTS ship_to_state_code
    ''')
    op.execute('DROP TABLE IF EXISTS invoice_doc_series CASCADE')
