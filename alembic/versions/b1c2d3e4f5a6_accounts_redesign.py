"""accounts redesign: SAP/GST integration, virtual accounts, EU line split, credit notes, integration logs

Revision ID: b1c2d3e4f5a6
Revises: f9e8d7c6b5a4
Create Date: 2026-02-26

"""
from alembic import op

revision = 'b1c2d3e4f5a6'
down_revision = 'f9e8d7c6b5a4'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Modified tables ────────────────────────────────────────────────────

    # vessel_agents – add billing + SAP fields
    op.execute("""
        ALTER TABLE vessel_agents
          ADD COLUMN IF NOT EXISTS sap_customer_code TEXT,
          ADD COLUMN IF NOT EXISTS company_code TEXT,
          ADD COLUMN IF NOT EXISTS gl_code TEXT,
          ADD COLUMN IF NOT EXISTS gstin TEXT,
          ADD COLUMN IF NOT EXISTS gst_state_code TEXT,
          ADD COLUMN IF NOT EXISTS gst_state_name TEXT,
          ADD COLUMN IF NOT EXISTS pan TEXT,
          ADD COLUMN IF NOT EXISTS billing_address TEXT,
          ADD COLUMN IF NOT EXISTS city TEXT,
          ADD COLUMN IF NOT EXISTS pincode TEXT,
          ADD COLUMN IF NOT EXISTS contact_person TEXT,
          ADD COLUMN IF NOT EXISTS contact_email TEXT,
          ADD COLUMN IF NOT EXISTS contact_phone TEXT,
          ADD COLUMN IF NOT EXISTS default_currency TEXT DEFAULT 'INR',
          ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1
    """)

    # vessel_customers – SAP customer code + inter-company code
    op.execute("""
        ALTER TABLE vessel_customers
          ADD COLUMN IF NOT EXISTS sap_customer_code TEXT,
          ADD COLUMN IF NOT EXISTS company_code TEXT
    """)

    # vessel_importer_exporters – same
    op.execute("""
        ALTER TABLE vessel_importer_exporters
          ADD COLUMN IF NOT EXISTS sap_customer_code TEXT,
          ADD COLUMN IF NOT EXISTS company_code TEXT
    """)

    # finance_service_types – SAP GL/tax/profit/cost fields
    op.execute("""
        ALTER TABLE finance_service_types
          ADD COLUMN IF NOT EXISTS sap_gl_account TEXT,
          ADD COLUMN IF NOT EXISTS sap_tax_code TEXT,
          ADD COLUMN IF NOT EXISTS sap_profit_center TEXT,
          ADD COLUMN IF NOT EXISTS sap_cost_center TEXT
    """)

    # bill_lines – SAP tax code for traceability
    op.execute("""
        ALTER TABLE bill_lines
          ADD COLUMN IF NOT EXISTS sap_tax_code TEXT
    """)

    # invoice_lines – SAP tax code for SAP payload builder
    op.execute("""
        ALTER TABLE invoice_lines
          ADD COLUMN IF NOT EXISTS sap_tax_code TEXT
    """)

    # lueu_lines – EU line split tracking
    op.execute("""
        ALTER TABLE lueu_lines
          ADD COLUMN IF NOT EXISTS is_split INTEGER DEFAULT 0,
          ADD COLUMN IF NOT EXISTS parent_line_id INTEGER,
          ADD COLUMN IF NOT EXISTS split_quantity REAL,
          ADD COLUMN IF NOT EXISTS split_remark TEXT
    """)

    # gst_api_config – audit columns
    op.execute("""
        ALTER TABLE gst_api_config
          ADD COLUMN IF NOT EXISTS updated_by TEXT,
          ADD COLUMN IF NOT EXISTS updated_date TEXT
    """)

    # ── 2. New tables ─────────────────────────────────────────────────────────

    # customer_virtual_accounts
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_virtual_accounts (
            id SERIAL PRIMARY KEY,
            party_type TEXT NOT NULL,
            party_id INTEGER NOT NULL,
            party_name TEXT,
            account_number TEXT NOT NULL,
            ifsc_code TEXT NOT NULL,
            bank_name TEXT,
            branch_name TEXT,
            account_holder_name TEXT,
            account_type TEXT DEFAULT 'Current',
            purpose TEXT,
            is_active INTEGER DEFAULT 1,
            effective_from TEXT,
            effective_to TEXT,
            gl_account_code TEXT,
            remarks TEXT,
            created_by TEXT,
            created_date TEXT
        )
    """)

    # sap_api_config
    op.execute("""
        CREATE TABLE IF NOT EXISTS sap_api_config (
            id SERIAL PRIMARY KEY,
            environment TEXT NOT NULL,
            base_url TEXT NOT NULL,
            client_id TEXT NOT NULL,
            client_secret TEXT NOT NULL,
            company_code TEXT NOT NULL,
            default_payment_term TEXT DEFAULT '51',
            access_token TEXT,
            token_expiry TEXT,
            is_active INTEGER DEFAULT 0,
            created_date TEXT,
            updated_by TEXT,
            updated_date TEXT
        )
    """)

    # Seed SAP config with known environments (inactive by default)
    op.execute("""
        INSERT INTO sap_api_config
            (environment, base_url, client_id, client_secret, company_code,
             default_payment_term, is_active, created_date)
        VALUES
            ('development', 'https://sapapidev.jsw.in:50001', 'jsw_api',
             'k1A_6gvcfIXc3ev-UpuXsfGYXFUW610ZJzPrbIi4Ogc', '5171', '51', 0,
             CURRENT_DATE::TEXT),
            ('quality', 'https://sapapiqas.jsw.in:52401', 'jsw_api',
             'fL6GOT9zuiY3LtiJHSr8R0w5CeQObG6Gy2J4f832i5I', '5171', '51', 0,
             CURRENT_DATE::TEXT),
            ('production', 'https://sapapi.jsw.in:54001', 'jsw_steel',
             'mHJgvipjDPcAiO4H0PZZQXj-aZ4KRq4yXpbFr7jn1BM', '5171', '51', 0,
             CURRENT_DATE::TEXT)
    """)

    # integration_logs
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_logs (
            id SERIAL PRIMARY KEY,
            integration_type TEXT NOT NULL,
            source_type TEXT,
            source_id INTEGER,
            source_reference TEXT,
            request_url TEXT,
            request_method TEXT DEFAULT 'POST',
            request_headers TEXT,
            request_body TEXT,
            response_status_code INTEGER,
            response_body TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            duration_ms INTEGER,
            created_by TEXT,
            created_date TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_intlogs_source ON integration_logs(source_type, source_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_intlogs_type ON integration_logs(integration_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_intlogs_date ON integration_logs(created_date)")

    # credit_note_header
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_note_header (
            id SERIAL PRIMARY KEY,
            credit_note_number TEXT UNIQUE NOT NULL,
            credit_note_date TEXT NOT NULL,
            financial_year TEXT NOT NULL,
            original_invoice_id INTEGER REFERENCES invoice_header(id),
            original_invoice_number TEXT,
            party_type TEXT NOT NULL,
            party_id INTEGER NOT NULL,
            party_name TEXT,
            party_gstin TEXT,
            party_gst_state_code TEXT,
            currency_code TEXT DEFAULT 'INR',
            exchange_rate REAL DEFAULT 1.0,
            subtotal REAL DEFAULT 0,
            cgst_amount REAL DEFAULT 0,
            sgst_amount REAL DEFAULT 0,
            igst_amount REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            reason TEXT NOT NULL,
            credit_note_status TEXT DEFAULT 'Draft',
            sap_document_number TEXT,
            sap_posting_date TEXT,
            gst_irn TEXT,
            gst_ack_number TEXT,
            gst_ack_date TEXT,
            created_by TEXT,
            created_date TEXT,
            approved_by TEXT,
            approved_date TEXT,
            remarks TEXT
        )
    """)

    # credit_note_lines
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_note_lines (
            id SERIAL PRIMARY KEY,
            credit_note_id INTEGER NOT NULL REFERENCES credit_note_header(id) ON DELETE CASCADE,
            original_invoice_line_id INTEGER REFERENCES invoice_lines(id),
            line_number INTEGER,
            service_name TEXT,
            service_description TEXT,
            quantity REAL,
            uom TEXT,
            rate REAL,
            line_amount REAL NOT NULL,
            cgst_rate REAL DEFAULT 0,
            sgst_rate REAL DEFAULT 0,
            igst_rate REAL DEFAULT 0,
            cgst_amount REAL DEFAULT 0,
            sgst_amount REAL DEFAULT 0,
            igst_amount REAL DEFAULT 0,
            line_total REAL NOT NULL,
            gl_code TEXT,
            sac_code TEXT
        )
    """)

    # advance_receipts
    op.execute("""
        CREATE TABLE IF NOT EXISTS advance_receipts (
            id SERIAL PRIMARY KEY,
            receipt_number TEXT UNIQUE NOT NULL,
            party_type TEXT NOT NULL,
            party_id INTEGER NOT NULL,
            party_name TEXT,
            receipt_date TEXT NOT NULL,
            amount REAL NOT NULL,
            currency_code TEXT DEFAULT 'INR',
            exchange_rate REAL DEFAULT 1.0,
            virtual_account_id INTEGER REFERENCES customer_virtual_accounts(id),
            utr_number TEXT,
            payment_method TEXT,
            sap_document_number TEXT,
            sap_posting_date TEXT,
            status TEXT DEFAULT 'Pending',
            adjusted_against TEXT,
            created_by TEXT,
            created_date TEXT,
            remarks TEXT
        )
    """)

    # customer_incoming_payments
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_incoming_payments (
            id SERIAL PRIMARY KEY,
            payment_number TEXT UNIQUE NOT NULL,
            party_type TEXT NOT NULL,
            party_id INTEGER NOT NULL,
            party_name TEXT,
            payment_date TEXT NOT NULL,
            amount REAL NOT NULL,
            currency_code TEXT DEFAULT 'INR',
            exchange_rate REAL DEFAULT 1.0,
            virtual_account_id INTEGER REFERENCES customer_virtual_accounts(id),
            utr_number TEXT,
            payment_method TEXT,
            sap_document_number TEXT,
            sap_clearing_date TEXT,
            invoices_cleared TEXT,
            status TEXT DEFAULT 'Pending',
            created_by TEXT,
            created_date TEXT,
            remarks TEXT
        )
    """)

    # gl_journal_vouchers
    op.execute("""
        CREATE TABLE IF NOT EXISTS gl_journal_vouchers (
            id SERIAL PRIMARY KEY,
            jv_number TEXT UNIQUE NOT NULL,
            jv_date TEXT NOT NULL,
            financial_year TEXT,
            jv_type TEXT DEFAULT 'JV',
            original_jv_id INTEGER,
            narration TEXT,
            total_debit REAL DEFAULT 0,
            total_credit REAL DEFAULT 0,
            jv_status TEXT DEFAULT 'Pending',
            sap_document_number TEXT,
            sap_posting_date TEXT,
            created_by TEXT,
            created_date TEXT
        )
    """)
    op.execute("""
        ALTER TABLE gl_journal_vouchers
          ADD CONSTRAINT fk_jv_original FOREIGN KEY (original_jv_id)
          REFERENCES gl_journal_vouchers(id)
    """)

    # gl_jv_lines
    op.execute("""
        CREATE TABLE IF NOT EXISTS gl_jv_lines (
            id SERIAL PRIMARY KEY,
            jv_id INTEGER NOT NULL REFERENCES gl_journal_vouchers(id) ON DELETE CASCADE,
            line_number INTEGER,
            gl_account TEXT NOT NULL,
            gl_description TEXT,
            cost_center TEXT,
            profit_center TEXT,
            debit_amount REAL DEFAULT 0,
            credit_amount REAL DEFAULT 0,
            tax_code TEXT,
            line_narration TEXT
        )
    """)

    # ── 3. Module permissions for new modules ─────────────────────────────────
    op.execute("""
        INSERT INTO module_permissions (module_code, user_id, can_read, can_add, can_edit, can_delete)
        SELECT 'FCN01', u.id, 0, 0, 0, 0 FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM module_permissions WHERE module_code = 'FCN01' AND user_id = u.id
        )
    """)
    op.execute("""
        INSERT INTO module_permissions (module_code, user_id, can_read, can_add, can_edit, can_delete)
        SELECT 'FSAP01', u.id, 0, 0, 0, 0 FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM module_permissions WHERE module_code = 'FSAP01' AND user_id = u.id
        )
    """)
    op.execute("""
        INSERT INTO module_permissions (module_code, user_id, can_read, can_add, can_edit, can_delete)
        SELECT 'FLOG01', u.id, 0, 0, 0, 0 FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM module_permissions WHERE module_code = 'FLOG01' AND user_id = u.id
        )
    """)


def downgrade():
    # Remove module permissions
    op.execute("DELETE FROM module_permissions WHERE module_code IN ('FCN01', 'FSAP01', 'FLOG01')")

    # Drop new tables
    op.execute("DROP TABLE IF EXISTS gl_jv_lines")
    op.execute("ALTER TABLE gl_journal_vouchers DROP CONSTRAINT IF EXISTS fk_jv_original")
    op.execute("DROP TABLE IF EXISTS gl_journal_vouchers")
    op.execute("DROP TABLE IF EXISTS customer_incoming_payments")
    op.execute("DROP TABLE IF EXISTS advance_receipts")
    op.execute("DROP TABLE IF EXISTS credit_note_lines")
    op.execute("DROP TABLE IF EXISTS credit_note_header")
    op.execute("DROP INDEX IF EXISTS idx_intlogs_source")
    op.execute("DROP INDEX IF EXISTS idx_intlogs_type")
    op.execute("DROP INDEX IF EXISTS idx_intlogs_date")
    op.execute("DROP TABLE IF EXISTS integration_logs")
    op.execute("DELETE FROM sap_api_config")
    op.execute("DROP TABLE IF EXISTS sap_api_config")
    op.execute("DROP TABLE IF EXISTS customer_virtual_accounts")

    # Revert gst_api_config
    op.execute("ALTER TABLE gst_api_config DROP COLUMN IF EXISTS updated_by")
    op.execute("ALTER TABLE gst_api_config DROP COLUMN IF EXISTS updated_date")

    # Revert lueu_lines
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS is_split")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS parent_line_id")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS split_quantity")
    op.execute("ALTER TABLE lueu_lines DROP COLUMN IF EXISTS split_remark")

    # Revert invoice_lines / bill_lines
    op.execute("ALTER TABLE invoice_lines DROP COLUMN IF EXISTS sap_tax_code")
    op.execute("ALTER TABLE bill_lines DROP COLUMN IF EXISTS sap_tax_code")

    # Revert finance_service_types
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS sap_gl_account")
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS sap_tax_code")
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS sap_profit_center")
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS sap_cost_center")

    # Revert customer masters
    op.execute("ALTER TABLE vessel_importer_exporters DROP COLUMN IF EXISTS sap_customer_code")
    op.execute("ALTER TABLE vessel_importer_exporters DROP COLUMN IF EXISTS company_code")
    op.execute("ALTER TABLE vessel_customers DROP COLUMN IF EXISTS sap_customer_code")
    op.execute("ALTER TABLE vessel_customers DROP COLUMN IF EXISTS company_code")

    # Revert vessel_agents
    op.execute("""
        ALTER TABLE vessel_agents
          DROP COLUMN IF EXISTS sap_customer_code,
          DROP COLUMN IF EXISTS company_code,
          DROP COLUMN IF EXISTS gl_code,
          DROP COLUMN IF EXISTS gstin,
          DROP COLUMN IF EXISTS gst_state_code,
          DROP COLUMN IF EXISTS gst_state_name,
          DROP COLUMN IF EXISTS pan,
          DROP COLUMN IF EXISTS billing_address,
          DROP COLUMN IF EXISTS city,
          DROP COLUMN IF EXISTS pincode,
          DROP COLUMN IF EXISTS contact_person,
          DROP COLUMN IF EXISTS contact_email,
          DROP COLUMN IF EXISTS contact_phone,
          DROP COLUMN IF EXISTS default_currency,
          DROP COLUMN IF EXISTS is_active
    """)
