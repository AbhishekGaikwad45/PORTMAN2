"""jnpa phase1 - add terminal, pipeline, and pipeline-terminal mapping tables

Revision ID: jnpa03_terminal_pipeline
Revises: jnpa02_drop_stowage
Create Date: 2026-04-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa03_terminal_pipeline'
down_revision: Union[str, None] = 'jnpa02_drop_stowage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS terminal_master (
            id SERIAL PRIMARY KEY,
            terminal_name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS pipeline_master (
            id SERIAL PRIMARY KEY,
            pipeline_name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS pipeline_terminal_mapping (
            id SERIAL PRIMARY KEY,
            pipeline_id INTEGER NOT NULL REFERENCES pipeline_master(id),
            terminal_id INTEGER NOT NULL REFERENCES terminal_master(id),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(pipeline_id, terminal_id)
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS pipeline_terminal_mapping CASCADE')
    op.execute('DROP TABLE IF EXISTS pipeline_master CASCADE')
    op.execute('DROP TABLE IF EXISTS terminal_master CASCADE')
