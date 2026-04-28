"""anchorage_master_and_vcn_changes

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create anchorage master table
    op.execute('''
        CREATE TABLE IF NOT EXISTS anchorage_master (
            id SERIAL PRIMARY KEY,
            name TEXT,
            latitude TEXT,
            longitude TEXT
        )
    ''')

    # Add draft fields to vcn_nominations
    op.execute('''
        ALTER TABLE vcn_nominations
        ADD COLUMN IF NOT EXISTS arrival_fore_draft REAL
    ''')
    op.execute('''
        ALTER TABLE vcn_nominations
        ADD COLUMN IF NOT EXISTS arrival_after_draft REAL
    ''')

    # Update vcn_anchorage: add anchorage_name, anchorage_arrival, anchorage_departure
    op.execute('''
        ALTER TABLE vcn_anchorage
        ADD COLUMN IF NOT EXISTS anchorage_name TEXT
    ''')
    op.execute('''
        ALTER TABLE vcn_anchorage
        ADD COLUMN IF NOT EXISTS anchorage_arrival TEXT
    ''')
    op.execute('''
        ALTER TABLE vcn_anchorage
        ADD COLUMN IF NOT EXISTS anchorage_departure TEXT
    ''')

    # Drop old columns from vcn_anchorage
    op.execute('ALTER TABLE vcn_anchorage DROP COLUMN IF EXISTS latitude')
    op.execute('ALTER TABLE vcn_anchorage DROP COLUMN IF EXISTS longitude')
    op.execute('ALTER TABLE vcn_anchorage DROP COLUMN IF EXISTS anchored_time')


def downgrade() -> None:
    # Restore old columns on vcn_anchorage
    op.execute('ALTER TABLE vcn_anchorage ADD COLUMN IF NOT EXISTS latitude TEXT')
    op.execute('ALTER TABLE vcn_anchorage ADD COLUMN IF NOT EXISTS longitude TEXT')
    op.execute('ALTER TABLE vcn_anchorage ADD COLUMN IF NOT EXISTS anchored_time TEXT')

    # Drop new columns from vcn_anchorage
    op.execute('ALTER TABLE vcn_anchorage DROP COLUMN IF EXISTS anchorage_name')
    op.execute('ALTER TABLE vcn_anchorage DROP COLUMN IF EXISTS anchorage_arrival')
    op.execute('ALTER TABLE vcn_anchorage DROP COLUMN IF EXISTS anchorage_departure')

    # Drop draft fields from vcn_nominations
    op.execute('ALTER TABLE vcn_nominations DROP COLUMN IF EXISTS arrival_fore_draft')
    op.execute('ALTER TABLE vcn_nominations DROP COLUMN IF EXISTS arrival_after_draft')

    # Drop anchorage master table
    op.execute('DROP TABLE IF EXISTS anchorage_master')
