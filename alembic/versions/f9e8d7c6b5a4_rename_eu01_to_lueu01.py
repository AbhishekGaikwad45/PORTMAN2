"""rename eu01 to lueu01: eu_lines -> lueu_lines, module_permissions EU01 -> LUEU01

Revision ID: f9e8d7c6b5a4
Revises: d8f1a3b5c7e9
Create Date: 2026-02-26

"""
from alembic import op

revision = 'f9e8d7c6b5a4'
down_revision = 'd8f1a3b5c7e9'
branch_labels = None
depends_on = None


def upgrade():
    # Rename only if eu_lines exists (skip if already renamed or created as lueu_lines)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'eu_lines') THEN
                ALTER TABLE eu_lines RENAME TO lueu_lines;
            END IF;
        END $$
    """)
    op.execute("UPDATE module_permissions SET module_code = 'LUEU01' WHERE module_code = 'EU01'")


def downgrade():
    op.execute('ALTER TABLE lueu_lines RENAME TO eu_lines')
    op.execute("UPDATE module_permissions SET module_code = 'EU01' WHERE module_code = 'LUEU01'")
