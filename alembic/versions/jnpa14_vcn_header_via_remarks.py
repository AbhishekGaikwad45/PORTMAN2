"""jnpa phase1 - VCN01: VIA number + remarks on header; vessel agent off consigner lines

Revision ID: jnpa14_vcn_via_remarks
Revises: jnpa13_vc01_ev01_fields
Create Date: 2026-06-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa14_vcn_via_remarks'
down_revision: Union[str, None] = 'jnpa13_vc01_ev01_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE vcn_header ADD COLUMN IF NOT EXISTS via_number TEXT;
        ALTER TABLE vcn_header ADD COLUMN IF NOT EXISTS remarks VARCHAR(200);

        -- vessel agent now lives only on the header (vessel_agent_name)
        ALTER TABLE vcn_consigners DROP COLUMN IF EXISTS agent_name;
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS agent_name TEXT;

        ALTER TABLE vcn_header DROP COLUMN IF EXISTS via_number;
        ALTER TABLE vcn_header DROP COLUMN IF EXISTS remarks;
    ''')
