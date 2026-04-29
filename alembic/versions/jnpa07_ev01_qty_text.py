"""jnpa phase1 - change expected_vessels.quantity to TEXT for per-cargo quantities

Revision ID: jnpa07_ev01_qty_text
Revises: jnpa06_widen_code_columns
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa07_ev01_qty_text'
down_revision: Union[str, None] = 'jnpa06_widen_code_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE expected_vessels ALTER COLUMN quantity TYPE TEXT USING quantity::TEXT;
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE expected_vessels ALTER COLUMN quantity TYPE NUMERIC(15,3)
            USING CASE WHEN quantity ~ '^[0-9.]+$' THEN quantity::NUMERIC ELSE NULL END;
    ''')
