"""add mbc export load port lines and customer details tables, rename columns

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-02-24
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'w3x4y5z6a7b8'
down_revision: Union[str, None] = 'v2w3x4y5z6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Export Load Port Details - separate table from Import load port
    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_export_load_port_lines (
            id SERIAL PRIMARY KEY,
            mbc_id INTEGER NOT NULL,
            arrived_at_port TEXT,
            alongside_at_berth TEXT,
            loading_commenced TEXT,
            loading_completed TEXT,
            cast_off_from_berth TEXT,
            sailed_out_from_port TEXT,
            eta_at_gull_island TEXT,
            unloaded_by TEXT,
            berth_master TEXT,
            FOREIGN KEY (mbc_id) REFERENCES mbc_header(id) ON DELETE CASCADE
        )
    ''')

    # Customer Details sub-table
    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_customer_details (
            id SERIAL PRIMARY KEY,
            mbc_id INTEGER NOT NULL,
            customer_name TEXT,
            bill_of_coastal_goods_no TEXT,
            quantity REAL,
            material_po TEXT,
            FOREIGN KEY (mbc_id) REFERENCES mbc_header(id) ON DELETE CASCADE
        )
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS mbc_customer_details CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_export_load_port_lines CASCADE')
