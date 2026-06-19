"""jnpa phase1 - LDUD parcel_ops gains quantity + terminal_name

Each parcel-ops row now captures a quantity and a terminal (sourced from the
VCN parcel's unload_terminal). The same parcel may appear on several rows
(one per terminal), so the multi-parcel merge is retired in the UI — these
columns are per single-parcel row.

Revision ID: jnpa20_parcel_ops_qty_term
Revises: jnpa19_lueu_parcel_logbook
Create Date: 2026-06-19
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa20_parcel_ops_qty_term'
down_revision: Union[str, None] = 'jnpa19_lueu_parcel_logbook'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_parcel_ops ADD COLUMN IF NOT EXISTS quantity NUMERIC;
        ALTER TABLE ldud_parcel_ops ADD COLUMN IF NOT EXISTS terminal_name TEXT;
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_parcel_ops DROP COLUMN IF EXISTS terminal_name;
        ALTER TABLE ldud_parcel_ops DROP COLUMN IF EXISTS quantity;
    ''')
