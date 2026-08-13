"""BPL01: berth_plan draft table.

One row per planned vessel. parcels holds [{cargo, qty, start, rate}] as
JSONB — the plan is always read and written whole, so no child table.

ON DELETE CASCADE is the entire cleanup story: EV01 deletes the
expected_vessels row on move-to-VCN, and the draft plan goes with it.
UNIQUE(ev_id) means a vessel is planned at exactly one berth, so dragging
it to another lane is an UPDATE rather than an insert + delete.

Revision ID: jnpa54_bpl01_berth_plan
Revises: jnpa53_vcg01_cargo_code
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa54_bpl01_berth_plan'
down_revision: Union[str, None] = 'jnpa53_vcg01_cargo_code'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS berth_plan (
            id          SERIAL PRIMARY KEY,
            ev_id       INTEGER UNIQUE REFERENCES expected_vessels(id) ON DELETE CASCADE,
            berth_name  TEXT NOT NULL,
            parcels     JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by  TEXT,
            updated_at  TIMESTAMP DEFAULT now()
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS berth_plan')
