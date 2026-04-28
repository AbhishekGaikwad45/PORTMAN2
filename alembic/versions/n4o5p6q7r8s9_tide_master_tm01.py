"""tide_master_tm01

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-02-17
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'n4o5p6q7r8s9'
down_revision: Union[str, None] = 'm3n4o5p6q7r8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS tide_master (
            id SERIAL PRIMARY KEY,
            tide_datetime TEXT,
            tide_meters NUMERIC
        )
    ''')

    # Grant TM01 permissions to all existing users
    op.execute('''
        INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete)
        SELECT DISTINCT u.id, 'TM01',
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
        WHERE module_code = 'TM01'
        AND user_id IN (
            SELECT DISTINCT user_id FROM module_permissions
            WHERE can_delete = 1 AND module_code IN ('VTM01', 'VCM01', 'GM01')
        )
    ''')


def downgrade() -> None:
    op.execute("DELETE FROM module_permissions WHERE module_code = 'TM01'")
    op.execute('DROP TABLE IF EXISTS tide_master')
