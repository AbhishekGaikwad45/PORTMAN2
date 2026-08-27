"""BPL01: per-vessel simultaneous-discharge switch.

Some vessels cannot work two lines at once however many pipelines the berth
offers — the constraint is the ship's own pumps and manifold, not the shore
side. Turning this off makes every line on that vessel queue, ignoring which
pipeline each names.

Defaults TRUE: the pipeline-aware schedule stays the norm, and this is the
exception a planner ticks off for the vessels that need it.

Revision ID: jnpa57_bpl01_simultaneous
Revises: jnpa56_bpl01_line_items
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa57_bpl01_simultaneous'
down_revision: Union[str, None] = 'jnpa56_bpl01_line_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE berth_plan ADD COLUMN IF NOT EXISTS '
               'simultaneous BOOLEAN NOT NULL DEFAULT TRUE')


def downgrade() -> None:
    op.execute('ALTER TABLE berth_plan DROP COLUMN IF EXISTS simultaneous')
