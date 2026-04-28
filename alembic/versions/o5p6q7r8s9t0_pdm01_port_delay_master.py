"""pdm01_port_delay_master

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-02-17
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'o5p6q7r8s9t0'
down_revision: Union[str, None] = 'n4o5p6q7r8s9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create port_delay_types table (same structure as vessel_delay_types)
    op.execute('''
        CREATE TABLE IF NOT EXISTS port_delay_types (
            id SERIAL PRIMARY KEY,
            name TEXT,
            to_sof TEXT,
            type TEXT
        )
    ''')

    # Grant PDM01 permissions to all existing users
    op.execute('''
        INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete)
        SELECT u.id, 'PDM01', 1, 0, 0, 0
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM module_permissions mp WHERE mp.user_id = u.id AND mp.module_code = 'PDM01'
        )
    ''')

    # Grant full access to users who have delete on other master modules
    op.execute('''
        UPDATE module_permissions
        SET can_read = 1, can_add = 1, can_edit = 1, can_delete = 1
        WHERE module_code = 'PDM01'
        AND user_id IN (
            SELECT DISTINCT user_id FROM module_permissions
            WHERE can_delete = 1 AND module_code IN ('VTM01', 'VCM01', 'GM01')
        )
    ''')


def downgrade() -> None:
    op.execute("DELETE FROM module_permissions WHERE module_code = 'PDM01'")
    op.execute('DROP TABLE IF EXISTS port_delay_types')
