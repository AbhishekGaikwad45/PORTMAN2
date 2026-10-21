"""weather_cache: JSONB cache for WeatherAPI responses (Port Overview weather card)

Revision ID: jnpa73_weather_cache
Revises: jnpa72_invoice_series_seq_width
Create Date: 2026-10-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa73_weather_cache'
down_revision: Union[str, None] = 'jnpa72_invoice_series_seq_width'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS weather_cache (
            cache_key  TEXT PRIMARY KEY,
            data       JSONB NOT NULL,
            fetched_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weather_cache")
