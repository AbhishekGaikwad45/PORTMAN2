"""jnpa phase1 - VC01/EV01 field changes

VC01 (vessels):
  - drop vessel_type_name, no_of_holds, num_cranes (not applicable to liquid berths)
  - rename dwt -> displacement
  - add pbl (Parallel Body Length) and remarks (max 200 chars)
EV01 (expected_vessels):
  - add remarks (max 200 chars); terminal_name already exists
VHO01 (Vessel Hold Master): module removed — drop vessel_holds table + perms

Revision ID: jnpa13_vc01_ev01_fields
Revises: jnpa12_consigner_igm_lines
Create Date: 2026-06-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa13_vc01_ev01_fields'
down_revision: Union[str, None] = 'jnpa12_consigner_igm_lines'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE vessels DROP COLUMN IF EXISTS vessel_type_name;
        ALTER TABLE vessels DROP COLUMN IF EXISTS no_of_holds;
        ALTER TABLE vessels DROP COLUMN IF EXISTS num_cranes;

        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS displacement NUMERIC;
        UPDATE vessels SET displacement = dwt WHERE displacement IS NULL AND dwt IS NOT NULL;
        ALTER TABLE vessels DROP COLUMN IF EXISTS dwt;

        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS pbl NUMERIC(10,2);
        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS remarks VARCHAR(200);

        ALTER TABLE expected_vessels ADD COLUMN IF NOT EXISTS remarks VARCHAR(200);

        DROP TABLE IF EXISTS vessel_holds CASCADE;
        DELETE FROM module_permissions WHERE module_code = 'VHO01';
        DELETE FROM module_config WHERE module_code = 'VHO01';
    ''')


def downgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_holds (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE
        );

        ALTER TABLE expected_vessels DROP COLUMN IF EXISTS remarks;

        ALTER TABLE vessels DROP COLUMN IF EXISTS remarks;
        ALTER TABLE vessels DROP COLUMN IF EXISTS pbl;

        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS dwt NUMERIC;
        UPDATE vessels SET dwt = displacement WHERE dwt IS NULL AND displacement IS NOT NULL;
        ALTER TABLE vessels DROP COLUMN IF EXISTS displacement;

        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS vessel_type_name TEXT;
        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS no_of_holds INTEGER;
        ALTER TABLE vessels ADD COLUMN IF NOT EXISTS num_cranes INTEGER;
    ''')


