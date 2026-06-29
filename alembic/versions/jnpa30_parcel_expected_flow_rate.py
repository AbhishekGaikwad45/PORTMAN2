"""jnpa phase1 - ldud_parcel_ops gains expected_flow_rate

Expected (planned) flow rate per parcel (MT/Hr), entered in LUEU01 alongside
the expected start. Used to compute the planned ETC; the actual ETC stays
driven by logged averages.

Revision ID: jnpa30_parcel_expected_flow_rate
Revises: jnpa29_ldud_ts_to_text
Create Date: 2026-06-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa30_parcel_expected_flow_rate'
down_revision: Union[str, None] = 'jnpa29_ldud_ts_to_text'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE ldud_parcel_ops ADD COLUMN IF NOT EXISTS expected_flow_rate NUMERIC;')


def downgrade() -> None:
    op.execute('ALTER TABLE ldud_parcel_ops DROP COLUMN IF EXISTS expected_flow_rate;')
