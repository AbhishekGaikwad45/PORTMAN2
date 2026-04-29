"""jnpa phase1 - split EV01 agent/tank/consignee, add codes, tank master

Revision ID: jnpa05_ev01_agt_split
Revises: jnpa04_expected_vessels
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa05_ev01_agt_split'
down_revision: Union[str, None] = 'jnpa04_expected_vessels'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE vessel_agents ADD COLUMN IF NOT EXISTS agent_code VARCHAR(20);
        ALTER TABLE vessel_customers ADD COLUMN IF NOT EXISTS customer_code VARCHAR(20);

        ALTER TABLE expected_vessels ADD COLUMN IF NOT EXISTS agents TEXT;
        ALTER TABLE expected_vessels ADD COLUMN IF NOT EXISTS tanks TEXT;
        ALTER TABLE expected_vessels ADD COLUMN IF NOT EXISTS consignees TEXT;
        ALTER TABLE expected_vessels DROP COLUMN IF EXISTS agent_tank_consignee;

        CREATE TABLE IF NOT EXISTS tank_master (
            id SERIAL PRIMARY KEY,
            tank_code VARCHAR(20),
            tank_name TEXT,
            is_active BOOLEAN DEFAULT TRUE
        );
    ''')


def downgrade() -> None:
    op.execute('''
        DROP TABLE IF EXISTS tank_master;

        ALTER TABLE expected_vessels ADD COLUMN IF NOT EXISTS agent_tank_consignee TEXT;
        ALTER TABLE expected_vessels DROP COLUMN IF EXISTS agents;
        ALTER TABLE expected_vessels DROP COLUMN IF EXISTS tanks;
        ALTER TABLE expected_vessels DROP COLUMN IF EXISTS consignees;

        ALTER TABLE vessel_customers DROP COLUMN IF EXISTS customer_code;
        ALTER TABLE vessel_agents DROP COLUMN IF EXISTS agent_code;
    ''')
