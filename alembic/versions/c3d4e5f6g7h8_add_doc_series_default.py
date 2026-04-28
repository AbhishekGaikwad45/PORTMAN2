"""add_doc_series_default

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE vessel_call_doc_series
        ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE
    ''')
    op.execute('''
        ALTER TABLE mbc_doc_series
        ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE
    ''')
    op.execute('''
        ALTER TABLE vex_doc_series
        ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE vessel_call_doc_series DROP COLUMN IF EXISTS is_default')
    op.execute('ALTER TABLE mbc_doc_series DROP COLUMN IF EXISTS is_default')
    op.execute('ALTER TABLE vex_doc_series DROP COLUMN IF EXISTS is_default')
