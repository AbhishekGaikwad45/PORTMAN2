"""PLM01: hydro test validity on pipeline_master.

A pipeline may only be picked on a VCN while its hydro test is still valid.
NULL means "no hydro test recorded" and stays selectable, so existing
pipelines keep working until someone fills the date in.

Revision ID: jnpa58_plm01_hydro_test
Revises: jnpa57_bpl01_simultaneous
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa58_plm01_hydro_test'
down_revision: Union[str, None] = 'jnpa57_bpl01_simultaneous'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE pipeline_master ADD COLUMN IF NOT EXISTS '
               'hydro_test_valid_until TIMESTAMPTZ')


def downgrade() -> None:
    op.execute('ALTER TABLE pipeline_master DROP COLUMN IF EXISTS hydro_test_valid_until')
