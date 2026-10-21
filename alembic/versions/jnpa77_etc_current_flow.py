"""jnpa_vessels_on_berth ETC follows the current flow rate, like the dashboard.

Expected completion was start_dt + quantity / cumulative avg rate, so a slow
ramp-up held the ETC days out after the line reached full rate. It is now
LUEU01.current_etc: end of the last real log row + balance / rate of the
latest row that moved cargo. Every other column is unchanged.

Revision ID: jnpa77_etc_current_flow
Revises: jnpa76_month_by_category
Create Date: 2026-10-19
"""
import importlib.util
import re
from pathlib import Path
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa77_etc_current_flow'
down_revision: Union[str, None] = 'jnpa76_month_by_category'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ETC = """    LEFT JOIN lg ON lg.parcel_op_id = po.id
    CROSS JOIN LATERAL (
        SELECT CASE WHEN COALESCE(lg.hrs_all, 0) > 0 AND COALESCE(lg.qty_all, 0) > 0 AND jnpa_ts(po.start_dt) IS NOT NULL
                    THEN jnpa_ts(po.start_dt) + make_interval(secs => (po.quantity / (lg.qty_all / lg.hrs_all) * 3600)::float8)
"""
NEW_ETC = """    LEFT JOIN lg ON lg.parcel_op_id = po.id
    LEFT JOIN LATERAL (
        SELECT MAX(l.start_ts + make_interval(secs => (l.hours * 3600)::float8)) AS end_ts,
               (ARRAY_AGG(l.quantity / l.hours ORDER BY l.entry_date DESC, l.from_time DESC NULLS FIRST, l.log_id DESC)
                    FILTER (WHERE l.quantity > 0 AND l.hours > 0))[1] AS rate
        FROM jnpa_parcel_log l
        WHERE l.parcel_op_id = po.id AND NOT l.is_shortclose
    ) cur ON TRUE
    CROSS JOIN LATERAL (
        SELECT CASE WHEN COALESCE(cur.rate, 0) > 0 AND cur.end_ts IS NOT NULL
                    THEN cur.end_ts + make_interval(secs => ((po.quantity - COALESCE(lg.qty_all, 0)) / cur.rate * 3600)::float8)
"""
OLD_PLANNED = "NOT (COALESCE(lg.hrs_all, 0) > 0 AND COALESCE(lg.qty_all, 0) > 0 AND jnpa_ts(po.start_dt) IS NOT NULL) AS planned"
NEW_PLANNED = "NOT (COALESCE(cur.rate, 0) > 0 AND cur.end_ts IS NOT NULL) AS planned"


def _on_berth_v74():
    """jnpa_vessels_on_berth exactly as jnpa74 created it — reused so this
    migration only swaps the ETC branch instead of restating the view."""
    path = Path(__file__).with_name('jnpa74_port_overview_views.py')
    spec = importlib.util.spec_from_file_location('jnpa74_port_overview_views', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sql = re.search(r'CREATE OR REPLACE VIEW jnpa_vessels_on_berth AS.*?;\n', mod.VIEWS_SQL, re.S).group(0)
    assert OLD_ETC in sql and OLD_PLANNED in sql, 'jnpa74 ETC branch not found'
    return sql


def upgrade() -> None:
    op.execute(_on_berth_v74().replace(OLD_ETC, NEW_ETC).replace(OLD_PLANNED, NEW_PLANNED))


def downgrade() -> None:
    op.execute(_on_berth_v74())
