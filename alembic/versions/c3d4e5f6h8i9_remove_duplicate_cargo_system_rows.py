"""Remove duplicate CARGO_LOAD/CARGO_UNLOAD system rows (CHGL01/CHGU01 are canonical)

Revision ID: c3d4e5f6h8i9
Revises: b2c3d4e5f6h8
Create Date: 2026-03-06
"""
from alembic import op

revision = 'c3d4e5f6h8i9'
down_revision = 'b2c3d4e5f6h8'
branch_labels = None
depends_on = None


def upgrade():
    # CARGO_LOAD and CARGO_UNLOAD were seeded by the billing_redesign migration
    # but CHGL01 and CHGU01 are the pre-existing canonical rows for the same purpose.
    # Remove the duplicates.
    op.execute("""
        DELETE FROM finance_service_types
        WHERE service_code IN ('CARGO_LOAD', 'CARGO_UNLOAD')
    """)


def downgrade():
    op.execute("""
        INSERT INTO finance_service_types
            (service_code, service_name, service_category, uom, is_billable, is_active, is_system)
        VALUES
            ('CARGO_LOAD',   'Cargo Handling Loading',   'Cargo Handling', 'MT', 1, 1, 1),
            ('CARGO_UNLOAD', 'Cargo Handling Unloading', 'Cargo Handling', 'MT', 1, 1, 1)
        ON CONFLICT (service_code) DO NOTHING
    """)
