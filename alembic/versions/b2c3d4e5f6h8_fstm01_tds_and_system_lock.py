"""FSTM01: add TDS fields, lock cargo handling rows as system

Revision ID: b2c3d4e5f6h8
Revises: a1b2c3d4e5f7
Create Date: 2026-03-06
"""
from alembic import op

revision = 'b2c3d4e5f6h8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add TDS columns
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='finance_service_types' AND column_name='is_tds'
            ) THEN
                ALTER TABLE finance_service_types
                    ADD COLUMN is_tds SMALLINT DEFAULT 0,
                    ADD COLUMN tds_percent NUMERIC(5,2);
            END IF;
        END $$
    """)

    # 2. Mark pre-existing cargo handling rows as system (CHGL01, CHGU01, CARGO_LOAD, CARGO_UNLOAD)
    op.execute("""
        UPDATE finance_service_types
        SET is_system = 1
        WHERE service_code IN ('CHGL01', 'CHGU01', 'CARGO_LOAD', 'CARGO_UNLOAD')
           OR service_name ILIKE '%cargo handling%'
    """)


def downgrade():
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS tds_percent")
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS is_tds")
