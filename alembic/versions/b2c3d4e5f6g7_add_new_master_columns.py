"""add_new_master_columns

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-13
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Add equipment_type to vessel_importer_exporters (VIEM01) ===
    op.execute('''
        ALTER TABLE vessel_importer_exporters
        ADD COLUMN IF NOT EXISTS equipment_type TEXT
    ''')

    # === Add barge_owner_name, barge_owner_email to barges (VBM01) ===
    op.execute('''
        ALTER TABLE barges
        ADD COLUMN IF NOT EXISTS barge_owner_name TEXT
    ''')
    op.execute('''
        ALTER TABLE barges
        ADD COLUMN IF NOT EXISTS barge_owner_email TEXT
    ''')

    # === Add mbc_owner_name to mbc_master (MBCM01) ===
    op.execute('''
        ALTER TABLE mbc_master
        ADD COLUMN IF NOT EXISTS mbc_owner_name TEXT
    ''')

    # === Add call_sign, nationality, mmsi_num, dwt, no_of_hatches, no_of_holds to vessels (VC01) ===
    op.execute('''
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS call_sign TEXT
    ''')
    op.execute('''
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS nationality TEXT
    ''')
    op.execute('''
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS mmsi_num TEXT
    ''')
    op.execute('''
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS dwt NUMERIC
    ''')
    op.execute('''
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS no_of_hatches INTEGER
    ''')
    op.execute('''
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS no_of_holds INTEGER
    ''')

    # === Add cargo_category_2, cargo_sub_category, cargo_sub_category_2 to vessel_cargo (VCG01) ===
    op.execute('''
        ALTER TABLE vessel_cargo
        ADD COLUMN IF NOT EXISTS cargo_category_2 TEXT
    ''')
    op.execute('''
        ALTER TABLE vessel_cargo
        ADD COLUMN IF NOT EXISTS cargo_sub_category TEXT
    ''')
    op.execute('''
        ALTER TABLE vessel_cargo
        ADD COLUMN IF NOT EXISTS cargo_sub_category_2 TEXT
    ''')


def downgrade() -> None:
    op.execute('ALTER TABLE vessel_importer_exporters DROP COLUMN IF EXISTS equipment_type')
    op.execute('ALTER TABLE barges DROP COLUMN IF EXISTS barge_owner_name')
    op.execute('ALTER TABLE barges DROP COLUMN IF EXISTS barge_owner_email')
    op.execute('ALTER TABLE mbc_master DROP COLUMN IF EXISTS mbc_owner_name')
    op.execute('ALTER TABLE vessels DROP COLUMN IF EXISTS call_sign')
    op.execute('ALTER TABLE vessels DROP COLUMN IF EXISTS nationality')
    op.execute('ALTER TABLE vessels DROP COLUMN IF EXISTS mmsi_num')
    op.execute('ALTER TABLE vessels DROP COLUMN IF EXISTS dwt')
    op.execute('ALTER TABLE vessels DROP COLUMN IF EXISTS no_of_hatches')
    op.execute('ALTER TABLE vessels DROP COLUMN IF EXISTS no_of_holds')
    op.execute('ALTER TABLE vessel_cargo DROP COLUMN IF EXISTS cargo_category_2')
    op.execute('ALTER TABLE vessel_cargo DROP COLUMN IF EXISTS cargo_sub_category')
    op.execute('ALTER TABLE vessel_cargo DROP COLUMN IF EXISTS cargo_sub_category_2')
