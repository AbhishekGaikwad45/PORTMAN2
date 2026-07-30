"""PBM01: image_position JSONB on port_berth_master.

Stores {cx, cy, w, h, angle} in static/img/jjltpljetty.png pixel space,
set via the PBM01 image position picker. No backfill: JNPA berths have
not been positioned on the jetty image yet.

Revision ID: jnpa52_pbm01_image_position
Revises: jnpa51_pdm01_delay_classes
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa52_pbm01_image_position'
down_revision: Union[str, None] = 'jnpa51_pdm01_delay_classes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE port_berth_master ADD COLUMN IF NOT EXISTS image_position JSONB')


def downgrade() -> None:
    op.execute('ALTER TABLE port_berth_master DROP COLUMN IF EXISTS image_position')
