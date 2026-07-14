"""jnpa phase1 - RP01 custom report designer: saved pivot report configs

Revision ID: jnpa46_saved_pivot_reports
Revises: jnpa45_vcn_run_type
Create Date: 2026-07-14
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa46_saved_pivot_reports'
down_revision: Union[str, None] = 'jnpa45_vcn_run_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS saved_pivot_reports (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            data_source TEXT NOT NULL,
            config      JSONB NOT NULL,
            created_by  INTEGER,
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP DEFAULT NOW()
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS saved_pivot_reports')
