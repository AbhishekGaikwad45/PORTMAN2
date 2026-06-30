"""jnpa phase1 - ldud_header gains pilot_pickup_time

SOF time captured between NOR Accepted and Customs Clearance. Stored as TEXT
('YYYY-MM-DDTHH:MM') like the other LDUD datetime fields.

Revision ID: jnpa34_ldud_pilot_pickup_time
Revises: jnpa33_consigner_toll_reason
Create Date: 2026-06-30
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa34_ldud_pilot_pickup_time'
down_revision: Union[str, None] = 'jnpa33_consigner_toll_reason'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE ldud_header ADD COLUMN IF NOT EXISTS pilot_pickup_time TEXT;')


def downgrade() -> None:
    op.execute('ALTER TABLE ldud_header DROP COLUMN IF EXISTS pilot_pickup_time;')
