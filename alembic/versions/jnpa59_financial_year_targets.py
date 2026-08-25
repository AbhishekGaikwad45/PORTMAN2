"""Add financial_year_targets table for budget targets

Revision ID: jnpa59_financial_year_targets
Revises: jnpa58_plm01_hydro_test
Create Date: 2026-08-25
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa59_financial_year_targets'
down_revision: Union[str, None] = 'jnpa58_plm01_hydro_test'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS financial_year_targets (
            id BIGSERIAL PRIMARY KEY,
            financial_year TEXT NOT NULL UNIQUE,
            targets JSONB NOT NULL DEFAULT '{"targets": []}'::jsonb,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financial_year_targets;")
