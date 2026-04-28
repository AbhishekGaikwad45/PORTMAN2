"""Add approval_log table and rename Pending to Draft

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-02-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_log (
            id SERIAL PRIMARY KEY,
            module_code TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            actioned_by TEXT NOT NULL,
            actioned_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("UPDATE vcn_header SET doc_status = 'Draft' WHERE doc_status = 'Pending'")
    op.execute("UPDATE mbc_header SET doc_status = 'Draft' WHERE doc_status = 'Pending'")


def downgrade() -> None:
    op.execute("UPDATE vcn_header SET doc_status = 'Pending' WHERE doc_status = 'Draft'")
    op.execute("UPDATE mbc_header SET doc_status = 'Pending' WHERE doc_status = 'Draft'")
    op.execute("DROP TABLE IF EXISTS approval_log")
