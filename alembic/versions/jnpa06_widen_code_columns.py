"""jnpa phase1 - widen agent_code and customer_code to TEXT

Revision ID: jnpa06_widen_code_columns
Revises: jnpa05_ev01_agt_split
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa06_widen_code_columns'
down_revision: Union[str, None] = 'jnpa05_ev01_agt_split'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE vessel_agents   ALTER COLUMN agent_code    TYPE TEXT;
        ALTER TABLE vessel_customers ALTER COLUMN customer_code TYPE TEXT;
        ALTER TABLE tank_master      ALTER COLUMN tank_code     TYPE TEXT;
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE vessel_agents   ALTER COLUMN agent_code    TYPE VARCHAR(20) USING agent_code::VARCHAR(20);
        ALTER TABLE vessel_customers ALTER COLUMN customer_code TYPE VARCHAR(20) USING customer_code::VARCHAR(20);
        ALTER TABLE tank_master      ALTER COLUMN tank_code     TYPE VARCHAR(20) USING tank_code::VARCHAR(20);
    ''')
