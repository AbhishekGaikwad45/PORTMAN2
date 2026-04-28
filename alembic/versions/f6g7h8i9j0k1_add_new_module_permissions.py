"""add_new_module_permissions

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Grant permissions for new master modules (VANM01, VPM01) to all existing users
    # Approvers/admins get full access, regular users get read-only
    new_modules = ['VANM01', 'VPM01']
    for module in new_modules:
        # Give all users with existing permissions on other master modules the same level of access
        op.execute(f'''
            INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete)
            SELECT DISTINCT u.id, '{module}',
                1,
                CASE WHEN u.is_admin = 1 THEN 1 ELSE 0 END,
                CASE WHEN u.is_admin = 1 THEN 1 ELSE 0 END,
                CASE WHEN u.is_admin = 1 THEN 1 ELSE 0 END
            FROM users u
            ON CONFLICT (user_id, module_code) DO NOTHING
        ''')
        # Also grant full access to users who are approvers (have full access on other master modules)
        op.execute(f'''
            UPDATE module_permissions
            SET can_read = 1, can_add = 1, can_edit = 1, can_delete = 1
            WHERE module_code = '{module}'
            AND user_id IN (
                SELECT DISTINCT user_id FROM module_permissions
                WHERE can_delete = 1 AND module_code IN ('VTM01', 'VCM01', 'GM01')
            )
        ''')


def downgrade() -> None:
    op.execute("DELETE FROM module_permissions WHERE module_code IN ('VANM01', 'VPM01')")
