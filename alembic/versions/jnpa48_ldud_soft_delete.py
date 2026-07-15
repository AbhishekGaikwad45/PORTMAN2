"""jnpa phase1 - soft delete for ldud_header

VCN01's send-back-to-Expected used to refuse when an LDUD existed, forcing
admins to hard-delete the LDUD first. Now the send-back soft-deletes the
LDUD instead (hidden everywhere, recoverable if the vessel comes back).

Revision ID: jnpa48_ldud_soft_delete
Revises: jnpa47_mis_sr_no
Create Date: 2026-07-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa48_ldud_soft_delete'
down_revision: Union[str, None] = 'jnpa47_mis_sr_no'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_header
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS deleted_by TEXT,
            ADD COLUMN IF NOT EXISTS deleted_date TIMESTAMP;
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_header
            DROP COLUMN IF EXISTS is_deleted,
            DROP COLUMN IF EXISTS deleted_by,
            DROP COLUMN IF EXISTS deleted_date;
    ''')
