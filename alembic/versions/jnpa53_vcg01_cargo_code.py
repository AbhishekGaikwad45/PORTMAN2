"""VCG01: cargo_code on vessel_cargo.

Free-text code entered/uploaded alongside the cargo name. No backfill.

Revision ID: jnpa53_vcg01_cargo_code
Revises: jnpa52_pbm01_image_position
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'jnpa53_vcg01_cargo_code'
down_revision: Union[str, None] = 'jnpa52_pbm01_image_position'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE vessel_cargo ADD COLUMN IF NOT EXISTS cargo_code TEXT')


def downgrade() -> None:
    op.execute('ALTER TABLE vessel_cargo DROP COLUMN IF EXISTS cargo_code')
