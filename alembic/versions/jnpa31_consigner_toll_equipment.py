"""jnpa phase1 - vcn_consigners gains toll_applicable + equipment_names

Per-parcel (consigner line) flags entered in VCN01: a Toll Applicable checkbox
and a multi-select Equipment list (comma-separated names from the equipment
master).

Revision ID: jnpa31_consigner_toll_equipment
Revises: jnpa30_parcel_expected_flow_rate
Create Date: 2026-06-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa31_consigner_toll_equipment'
down_revision: Union[str, None] = 'jnpa30_parcel_expected_flow_rate'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS toll_applicable BOOLEAN DEFAULT FALSE;')
    op.execute('ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS equipment_names TEXT;')


def downgrade() -> None:
    op.execute('ALTER TABLE vcn_consigners DROP COLUMN IF EXISTS equipment_names;')
    op.execute('ALTER TABLE vcn_consigners DROP COLUMN IF EXISTS toll_applicable;')
