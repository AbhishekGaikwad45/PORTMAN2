"""SAP sandbox log — every payload sent from Admin > SAP Sandbox and what SAP
returned. Kept apart from integration_logs so test sends never mix with the
real invoice posting log.

Revision ID: jnpa78_sap_sandbox_log
Revises: jnpa77_etc_current_flow
Create Date: 2026-10-19
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa78_sap_sandbox_log'
down_revision: Union[str, None] = 'jnpa77_etc_current_flow'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sap_sandbox_log (
            id            SERIAL PRIMARY KEY,
            sent_at       TIMESTAMP NOT NULL DEFAULT now(),
            sent_by       TEXT,
            environment   TEXT,
            request_url   TEXT,
            reference     TEXT,
            request_body  JSONB,
            http_status   INTEGER,
            response_body JSONB,         -- non-JSON replies stored as {"raw": "..."}
            status        TEXT,          -- Success / Error
            error_message TEXT,
            duration_ms   INTEGER
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sap_sandbox_log")
