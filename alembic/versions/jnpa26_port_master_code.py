"""jnpa phase1 - port_master gains port_code

Revision ID: jnpa26_port_master_code
Revises: jnpa25_vcn_cargo_quota
Create Date: 2026-06-19
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa26_port_master_code'
down_revision: Union[str, None] = 'jnpa25_vcn_cargo_quota'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE port_master ADD COLUMN IF NOT EXISTS port_code TEXT;')


def downgrade() -> None:
    op.execute('ALTER TABLE port_master DROP COLUMN IF EXISTS port_code;')
