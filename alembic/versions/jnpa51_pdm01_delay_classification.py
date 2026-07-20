"""Rename PDM01 classifications and add description.

Revision ID: jnpa51_pdm01_delay_classification
Revises: jnpa50_pdm01_type_3_type_4
Create Date: 2026-07-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa51_pdm01_delay_classification'
down_revision: Union[str, None] = 'jnpa50_pdm01_type_3_type_4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE port_delay_types ADD COLUMN IF NOT EXISTS description TEXT')
    op.execute('ALTER TABLE port_delay_types RENAME COLUMN type_2 TO delay_type')
    op.execute('ALTER TABLE port_delay_types RENAME COLUMN type_3 TO particular')
    op.execute('ALTER TABLE port_delay_types RENAME COLUMN type_4 TO responsibility')


def downgrade() -> None:
    op.execute('ALTER TABLE port_delay_types RENAME COLUMN responsibility TO type_4')
    op.execute('ALTER TABLE port_delay_types RENAME COLUMN particular TO type_3')
    op.execute('ALTER TABLE port_delay_types RENAME COLUMN delay_type TO type_2')
    op.execute('ALTER TABLE port_delay_types DROP COLUMN IF EXISTS description')
