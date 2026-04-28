"""billing redesign: is_system on service types, ref_source on service_records

Revision ID: a1b2c3d4e5f7
Revises: f9e8d7c6b5a4
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = ('f9e8d7c6b5a4', 'f2a3b4c5d6e7')
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add is_system flag to finance_service_types
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='finance_service_types' AND column_name='is_system'
            ) THEN
                ALTER TABLE finance_service_types ADD COLUMN is_system SMALLINT DEFAULT 0;
            END IF;
        END $$
    """)

    # 2. Seed the two hardcoded cargo handling service types
    op.execute("""
        INSERT INTO finance_service_types
            (service_code, service_name, service_category, uom, is_billable, is_active, is_system)
        VALUES
            ('CARGO_LOAD',   'Cargo Handling Loading',   'Cargo Handling', 'MT', 1, 1, 1),
            ('CARGO_UNLOAD', 'Cargo Handling Unloading', 'Cargo Handling', 'MT', 1, 1, 1)
        ON CONFLICT (service_code) DO UPDATE SET is_system = 1
    """)

    # 3. Add optional VCN/MBC reference columns to service_records
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='service_records' AND column_name='ref_source_type'
            ) THEN
                ALTER TABLE service_records
                    ADD COLUMN ref_source_type VARCHAR(10),
                    ADD COLUMN ref_source_id INTEGER,
                    ADD COLUMN ref_source_display VARCHAR(255);
            END IF;
        END $$
    """)


def downgrade():
    op.execute("ALTER TABLE service_records DROP COLUMN IF EXISTS ref_source_display")
    op.execute("ALTER TABLE service_records DROP COLUMN IF EXISTS ref_source_id")
    op.execute("ALTER TABLE service_records DROP COLUMN IF EXISTS ref_source_type")
    op.execute("""
        DELETE FROM finance_service_types
        WHERE service_code IN ('CARGO_LOAD', 'CARGO_UNLOAD')
    """)
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS is_system")
