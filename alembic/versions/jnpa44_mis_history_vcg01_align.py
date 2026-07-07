"""jnpa phase1 - normalize mis_history to VCG01-aligned cargo columns

jnpa42 was edited in place during development, so environments may hold any
of its historical shapes:
  v1: operation_start/end + category, sub_category, cargo_class, cargo_name
  v2: v1 without operation_start/end
  v3: v2 with sub_category1 + sub_category2 instead of sub_category
  v4 (current file): cargo_type, cargo_category, cargo_category_2,
      cargo_sub_category, cargo_sub_category_2, cargo_name

Every step below is guarded, and classification columns are RENAMED (not
dropped), so existing data is preserved. On a v4 database this is a no-op.

Revision ID: jnpa44_mis_history_vcg01_align
Revises: jnpa43_mis_vessel_master
Create Date: 2026-07-07
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa44_mis_history_vcg01_align'
down_revision: Union[str, None] = 'jnpa43_mis_vessel_master'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_if_exists(old, new):
    return f'''
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'mis_history' AND column_name = '{old}')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'mis_history' AND column_name = '{new}') THEN
            ALTER TABLE mis_history RENAME COLUMN {old} TO {new};
        END IF;
    '''


UPGRADE_SQL = f'''
    ALTER TABLE mis_history DROP COLUMN IF EXISTS operation_start;
    ALTER TABLE mis_history DROP COLUMN IF EXISTS operation_end;
    DO $$
    BEGIN
        {_rename_if_exists('category', 'cargo_type')}
        {_rename_if_exists('sub_category', 'cargo_category')}
        {_rename_if_exists('sub_category1', 'cargo_category')}
        {_rename_if_exists('sub_category2', 'cargo_category_2')}
        {_rename_if_exists('cargo_class', 'cargo_sub_category')}
    END $$;
    ALTER TABLE mis_history ADD COLUMN IF NOT EXISTS cargo_category_2 TEXT;
    ALTER TABLE mis_history ADD COLUMN IF NOT EXISTS cargo_sub_category TEXT;
    ALTER TABLE mis_history ADD COLUMN IF NOT EXISTS cargo_sub_category_2 TEXT;
'''


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    # Back to the v2 shape (op-time columns are not restorable — their data
    # was dropped on upgrade).
    op.execute('''
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'mis_history' AND column_name = 'cargo_type') THEN
                ALTER TABLE mis_history RENAME COLUMN cargo_type TO category;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'mis_history' AND column_name = 'cargo_category') THEN
                ALTER TABLE mis_history RENAME COLUMN cargo_category TO sub_category;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'mis_history' AND column_name = 'cargo_sub_category') THEN
                ALTER TABLE mis_history RENAME COLUMN cargo_sub_category TO cargo_class;
            END IF;
        END $$;
        ALTER TABLE mis_history DROP COLUMN IF EXISTS cargo_category_2;
        ALTER TABLE mis_history DROP COLUMN IF EXISTS cargo_sub_category_2;
    ''')
