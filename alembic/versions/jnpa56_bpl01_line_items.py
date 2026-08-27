"""BPL01: plans become an ordered list of line items that run back to back.

A vessel's plan reads like the planner's spreadsheet:

    Prior Documentation   (fixed bookend, typed hours)
    ... parcels and delays inserted between ...
    Post Documentation    (fixed bookend, typed hours)

Each item starts when the one before it ends, and each vessel in a berth
starts when the vessel before it ends. A parcel's hours are derived from
qty / flow rate; docs and delays carry typed hours.

parcels -> items, and start_dt is added as the optional anchor for a vessel
whose start the planner pins rather than deriving from the queue.

Existing drafts keep their cargo names, quantities and hours as parcel items
wrapped in the new bookends. The old per-parcel delay lists are dropped:
delays are now their own items in the sequence, and the previous shape had
no position to restore them to.

Revision ID: jnpa56_bpl01_line_items
Revises: jnpa55_bpl01_vcn_and_hours
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa56_bpl01_line_items'
down_revision: Union[str, None] = 'jnpa55_bpl01_vcn_and_hours'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PRIOR = """jsonb_build_object('kind','doc','name','Prior Documentation','hours',4,'fixed',true)"""
_POST = """jsonb_build_object('kind','doc','name','Post Documentation','hours',4,'fixed',true)"""


def upgrade() -> None:
    op.execute('ALTER TABLE berth_plan ADD COLUMN IF NOT EXISTS start_dt TIMESTAMP')
    op.execute('ALTER TABLE berth_plan RENAME COLUMN parcels TO items')
    op.execute(f'''
        UPDATE berth_plan SET items =
            jsonb_build_array({_PRIOR})
            || COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'kind', 'parcel',
                    'name', p->>'cargo',
                    'qty', p->'qty',
                    'pipeline', NULL,
                    'rate', NULL,
                    'hours', p->'hours'
                ))
                FROM jsonb_array_elements(items) p
            ), '[]'::jsonb)
            || jsonb_build_array({_POST})
    ''')


def downgrade() -> None:
    op.execute('''
        UPDATE berth_plan SET items = COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'cargo', p->>'name', 'qty', p->'qty',
                'start', NULL, 'hours', p->'hours', 'delays', '[]'::jsonb))
            FROM jsonb_array_elements(items) p
            WHERE p->>'kind' = 'parcel'
        ), '[]'::jsonb)
    ''')
    op.execute('ALTER TABLE berth_plan RENAME COLUMN items TO parcels')
    op.execute('ALTER TABLE berth_plan DROP COLUMN IF EXISTS start_dt')
