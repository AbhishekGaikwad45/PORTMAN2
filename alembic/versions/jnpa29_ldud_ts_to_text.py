"""jnpa phase1 - convert LDUD timestamp cols to TEXT (ISO)

custom_clearance / agent_stevedore_onboard were 'timestamp without time zone',
serialized to the UI as RFC822 ('Fri, 26 Jun 2026 18:30:00 GMT'), which the
text-based datetime editor couldn't parse — clicking the cell blanked it.
Convert to TEXT in 'YYYY-MM-DDTHH:MM' form to match every other datetime field.

Revision ID: jnpa29_ldud_ts_to_text
Revises: jnpa28_parcel_expected_start
Create Date: 2026-06-19
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa29_ldud_ts_to_text'
down_revision: Union[str, None] = 'jnpa28_parcel_expected_start'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_header ALTER COLUMN custom_clearance TYPE TEXT
            USING to_char(custom_clearance, 'YYYY-MM-DD"T"HH24:MI');
        ALTER TABLE ldud_header ALTER COLUMN agent_stevedore_onboard TYPE TEXT
            USING to_char(agent_stevedore_onboard, 'YYYY-MM-DD"T"HH24:MI');
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_header ALTER COLUMN custom_clearance TYPE timestamp
            USING NULLIF(custom_clearance, '')::timestamp;
        ALTER TABLE ldud_header ALTER COLUMN agent_stevedore_onboard TYPE timestamp
            USING NULLIF(agent_stevedore_onboard, '')::timestamp;
    ''')
