"""ppl01_port_payloaders_mbc_cleaning_details_eta

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-02-17
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Port Payloader Master table
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_payloaders (
            id SERIAL PRIMARY KEY,
            name TEXT,
            make TEXT
        )
    ''')

    # Add ETA to load port lines
    op.execute('ALTER TABLE mbc_load_port_lines ADD COLUMN IF NOT EXISTS eta TEXT')

    # Add cleaning_completed to discharge port lines
    op.execute('ALTER TABLE mbc_discharge_port_lines ADD COLUMN IF NOT EXISTS cleaning_completed TEXT')

    # MBC Cleaning Details sub-table
    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_cleaning_details (
            id SERIAL PRIMARY KEY,
            mbc_id INTEGER NOT NULL,
            payloader_name TEXT,
            hmr_start TEXT,
            hmr_end TEXT,
            diesel_start TEXT,
            diesel_end TEXT,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY (mbc_id) REFERENCES mbc_header(id) ON DELETE CASCADE
        )
    ''')

    # Grant PPL01 permissions to all existing users
    op.execute('''
        INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete)
        SELECT DISTINCT u.id, 'PPL01',
            1,
            CASE WHEN u.is_admin = 1 THEN 1 ELSE 0 END,
            CASE WHEN u.is_admin = 1 THEN 1 ELSE 0 END,
            CASE WHEN u.is_admin = 1 THEN 1 ELSE 0 END
        FROM users u
        ON CONFLICT (user_id, module_code) DO NOTHING
    ''')
    op.execute('''
        UPDATE module_permissions
        SET can_read = 1, can_add = 1, can_edit = 1, can_delete = 1
        WHERE module_code = 'PPL01'
        AND user_id IN (
            SELECT DISTINCT user_id FROM module_permissions
            WHERE can_delete = 1 AND module_code IN ('VTM01', 'VCM01', 'GM01')
        )
    ''')


def downgrade() -> None:
    op.execute("DELETE FROM module_permissions WHERE module_code = 'PPL01'")
    op.execute('DROP TABLE IF EXISTS mbc_cleaning_details')
    op.execute('ALTER TABLE mbc_discharge_port_lines DROP COLUMN IF EXISTS cleaning_completed')
    op.execute('ALTER TABLE mbc_load_port_lines DROP COLUMN IF EXISTS eta')
    op.execute('DROP TABLE IF EXISTS port_payloaders')
