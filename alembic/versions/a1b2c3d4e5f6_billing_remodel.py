"""billing_remodel

Revision ID: a1b2c3d4e5f6
Revises: 745e51f340e0
Create Date: 2026-02-10
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '745e51f340e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Add has_custom_fields flag to finance_service_types ===
    op.execute('''
        ALTER TABLE finance_service_types
        ADD COLUMN IF NOT EXISTS has_custom_fields INTEGER DEFAULT 0
    ''')

    # === Add agreement_id to bill_header ===
    op.execute('''
        ALTER TABLE bill_header
        ADD COLUMN IF NOT EXISTS agreement_id INTEGER REFERENCES customer_agreements(id)
    ''')

    # === Add service_record_id to bill_lines ===
    op.execute('''
        ALTER TABLE bill_lines
        ADD COLUMN IF NOT EXISTS service_record_id INTEGER
    ''')

    # === Service field definitions (EAV schema) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS service_field_definitions (
            id SERIAL PRIMARY KEY,
            service_type_id INTEGER NOT NULL REFERENCES finance_service_types(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            field_label TEXT NOT NULL,
            field_type TEXT NOT NULL,
            field_options TEXT,
            calculation_formula TEXT,
            calculation_result_type TEXT,
            is_required INTEGER DEFAULT 0,
            is_billable_qty INTEGER DEFAULT 0,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_date TEXT
        )
    ''')

    # === Service records header ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS service_records (
            id SERIAL PRIMARY KEY,
            record_number TEXT UNIQUE NOT NULL,
            service_type_id INTEGER NOT NULL REFERENCES finance_service_types(id),
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            source_display TEXT,
            record_date TEXT,
            billable_quantity REAL,
            billable_uom TEXT,
            doc_status TEXT DEFAULT 'Pending',
            is_billed INTEGER DEFAULT 0,
            bill_id INTEGER,
            created_by TEXT,
            created_date TEXT,
            approved_by TEXT,
            approved_date TEXT,
            remarks TEXT
        )
    ''')

    # === Service record values (EAV data) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS service_record_values (
            id SERIAL PRIMARY KEY,
            service_record_id INTEGER NOT NULL REFERENCES service_records(id) ON DELETE CASCADE,
            field_definition_id INTEGER NOT NULL REFERENCES service_field_definitions(id),
            field_value TEXT,
            UNIQUE(service_record_id, field_definition_id)
        )
    ''')

    # === Add FK for bill_lines.service_record_id ===
    op.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_bill_lines_service_record'
            ) THEN
                ALTER TABLE bill_lines
                ADD CONSTRAINT fk_bill_lines_service_record
                FOREIGN KEY (service_record_id) REFERENCES service_records(id);
            END IF;
        END $$;
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE bill_lines DROP CONSTRAINT IF EXISTS fk_bill_lines_service_record')
    op.execute('DROP TABLE IF EXISTS service_record_values CASCADE')
    op.execute('DROP TABLE IF EXISTS service_records CASCADE')
    op.execute('DROP TABLE IF EXISTS service_field_definitions CASCADE')
    op.execute('ALTER TABLE bill_lines DROP COLUMN IF EXISTS service_record_id')
    op.execute('ALTER TABLE bill_header DROP COLUMN IF EXISTS agreement_id')
    op.execute('ALTER TABLE finance_service_types DROP COLUMN IF EXISTS has_custom_fields')
