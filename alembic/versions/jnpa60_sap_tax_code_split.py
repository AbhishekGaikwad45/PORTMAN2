"""jnpa phase2 - split sap_api_config.tax_code into igst_tax_code + cgst_tax_code

One SAP tax code cannot serve both transaction types: an inter-state line needs
the IGST code, an intra-state line the CGST/SGST one. sap_builder already picks
by line, so give it two columns to pick from. Both are backfilled from the old
single value; downgrade collapses back onto the intra-state code.

Revision ID: jnpa60_sap_tax_code_split
Revises: jnpa59_financial_year_targets
Create Date: 2026-09-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa60_sap_tax_code_split'
down_revision: Union[str, None] = 'jnpa59_financial_year_targets'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE sap_api_config ADD COLUMN IF NOT EXISTS igst_tax_code TEXT')
    op.execute('ALTER TABLE sap_api_config ADD COLUMN IF NOT EXISTS cgst_tax_code TEXT')
    op.execute('UPDATE sap_api_config SET igst_tax_code = tax_code, cgst_tax_code = tax_code')
    op.execute('ALTER TABLE sap_api_config DROP COLUMN IF EXISTS tax_code')


def downgrade() -> None:
    op.execute('ALTER TABLE sap_api_config ADD COLUMN IF NOT EXISTS tax_code TEXT')
    op.execute('UPDATE sap_api_config SET tax_code = cgst_tax_code')
    op.execute('ALTER TABLE sap_api_config DROP COLUMN IF EXISTS igst_tax_code')
    op.execute('ALTER TABLE sap_api_config DROP COLUMN IF EXISTS cgst_tax_code')
