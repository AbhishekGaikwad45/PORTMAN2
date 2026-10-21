"""Month card in the jnpa_* views now follows Report 5, like the dashboard.

Adds jnpa_month_by_category (jnpa_month_totals split by liquid category, the
same split port_overview._month_by_type makes) and points the 'month' period of
jnpa_cargo_throughput at it, so jnpa_cargo_cards' current_month card matches
the Port Overview dashboard. Every other period is unchanged.

Revision ID: jnpa76_month_by_category
Revises: jnpa75_month_totals_view
Create Date: 2026-10-16
"""
import importlib.util
import re
from pathlib import Path
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa76_month_by_category'
down_revision: Union[str, None] = 'jnpa75_month_totals_view'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_MONTH = """    UNION ALL SELECT 'month', l.category, l.quantity FROM logs l, c
              WHERE l.start_ts >= c.month_start AND l.start_ts < c.now_ts
"""
NEW_MONTH = """    UNION ALL SELECT 'month', b.category, b.quantity FROM jnpa_month_by_category b, c
              WHERE b.mon_yy = to_char(c.op_date, 'Mon-YY')
"""

MONTH_BY_CATEGORY = r"""
CREATE OR REPLACE VIEW jnpa_month_by_category AS
WITH mis AS (
    SELECT TRIM(v.month) AS mon_yy,
           jnpa_liquid_category(v.cargo, v.new_cat, v.category1, v.category, m.category) AS category,
           SUM(COALESCE(v.quantity, 0)) AS qty
    FROM mis_vessel_master v
    LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(v.cargo))
    WHERE TRIM(v.month) ~ '^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-[0-9]{2}$'
    GROUP BY 1, 2
),
live AS (
    SELECT to_char(jnpa_ts(h.cast_off_datetime), 'Mon-YY') AS mon_yy,
           jnpa_liquid_category(o.cargo_name, NULL, NULL, NULL, m.category) AS category,
           SUM(l.quantity) AS qty
    FROM lueu_parcel_log l
    JOIN ldud_parcel_ops o ON o.id = l.parcel_op_id
    JOIN ldud_header h ON h.id = o.ldud_id
    LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(o.cargo_name))
    WHERE l.is_deleted IS NOT TRUE AND h.is_deleted IS NOT TRUE
      AND l.is_shortclose IS NOT TRUE AND l.quantity IS NOT NULL
      AND jnpa_ts(h.cast_off_datetime) IS NOT NULL
    GROUP BY 1, 2
),
booked AS (
    SELECT mon_yy, category, qty, 'mis' AS source FROM mis
    UNION ALL
    SELECT mon_yy, category, qty, 'live' FROM live
)
SELECT t.mon_yy, t.month_start, t.fin_year_start, t.source, k.category, k.category_order,
       round(COALESCE(SUM(b.qty), 0), 3) AS quantity
FROM jnpa_month_totals t
CROSS JOIN (VALUES ('Edible Oil', 1), ('Chemical', 2), ('POL', 3), ('Other liquid', 4)) k(category, category_order)
LEFT JOIN booked b ON b.mon_yy = t.mon_yy AND b.source = t.source AND b.category = k.category
GROUP BY t.mon_yy, t.month_start, t.fin_year_start, t.source, k.category, k.category_order;
"""


def _throughput_v74():
    """jnpa_cargo_throughput exactly as jnpa74 created it — reused so this
    migration only swaps the month branch instead of restating the view."""
    path = Path(__file__).with_name('jnpa74_port_overview_views.py')
    spec = importlib.util.spec_from_file_location('jnpa74_port_overview_views', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sql = re.search(r'CREATE OR REPLACE VIEW jnpa_cargo_throughput AS.*?;\n', mod.VIEWS_SQL, re.S).group(0)
    assert OLD_MONTH in sql, 'jnpa74 month branch not found'
    return sql


def upgrade() -> None:
    op.execute(MONTH_BY_CATEGORY)
    op.execute(_throughput_v74().replace(OLD_MONTH, NEW_MONTH))


def downgrade() -> None:
    op.execute(_throughput_v74())
    op.execute("DROP VIEW IF EXISTS jnpa_month_by_category")
