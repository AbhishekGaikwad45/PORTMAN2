"""BPL01: plan VCN vessels too, and schedule parcels by hours + delay lines.

Two changes to berth_plan:

1. vcn_id alongside ev_id, so a plan can hang off either an EV01 expected
   vessel or a VCN. Both cascade, and a CHECK enforces exactly one — a plan
   row is one vessel, never two.

2. Parcels move from a flow rate to the hours the planner expects the parcel
   to take, plus delay line items ({name, hours}) drawn from the same delay
   master LUEU01 picks from. end = start + hours + delay hours.

Existing draft rows are converted rather than wiped: hours = qty / rate where
a usable rate was set, NULL otherwise.

Revision ID: jnpa55_bpl01_vcn_and_hours
Revises: jnpa54_bpl01_berth_plan
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa55_bpl01_vcn_and_hours'
down_revision: Union[str, None] = 'jnpa54_bpl01_berth_plan'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE berth_plan
        ADD COLUMN IF NOT EXISTS vcn_id INTEGER UNIQUE
            REFERENCES vcn_header(id) ON DELETE CASCADE
    ''')
    # rate -> hours, and every parcel gains an empty delays list
    op.execute('''
        UPDATE berth_plan SET parcels = COALESCE((
            SELECT jsonb_agg(
                (p - 'rate') || jsonb_build_object(
                    'hours', CASE
                        WHEN NULLIF(p->>'rate', '')::numeric > 0
                         AND NULLIF(p->>'qty', '') IS NOT NULL
                        THEN round((p->>'qty')::numeric / (p->>'rate')::numeric, 2)
                        ELSE NULL END,
                    'delays', COALESCE(p->'delays', '[]'::jsonb)
                )
            )
            FROM jsonb_array_elements(parcels) p
        ), '[]'::jsonb)
    ''')
    # a plan is one vessel: exactly one source, never both, never neither
    op.execute('''
        ALTER TABLE berth_plan
        ADD CONSTRAINT berth_plan_one_source CHECK (
            (ev_id IS NOT NULL AND vcn_id IS NULL)
         OR (ev_id IS NULL AND vcn_id IS NOT NULL)
        )
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE berth_plan DROP CONSTRAINT IF EXISTS berth_plan_one_source')
    op.execute('DELETE FROM berth_plan WHERE vcn_id IS NOT NULL')
    op.execute('ALTER TABLE berth_plan DROP COLUMN IF EXISTS vcn_id')
    op.execute('''
        UPDATE berth_plan SET parcels = COALESCE((
            SELECT jsonb_agg((p - 'hours' - 'delays') || jsonb_build_object(
                'rate', CASE
                    WHEN NULLIF(p->>'hours', '')::numeric > 0
                     AND NULLIF(p->>'qty', '') IS NOT NULL
                    THEN round((p->>'qty')::numeric / (p->>'hours')::numeric, 2)
                    ELSE NULL END))
            FROM jsonb_array_elements(parcels) p
        ), '[]'::jsonb)
    ''')
