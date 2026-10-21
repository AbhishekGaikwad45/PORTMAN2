"""jnpa_month_totals: Report 5's month total, one row per month.

Mirrors report5.fetch_month_figures:
  - months before CUTOVER_DATE (1 Jul 2026): mis_vessel_master for 'Mon-YY'
  - later months already in mis_vessel_master: the same MIS total (finalised)
  - later months not yet in MIS: lueu_parcel_log quantities of vessels whose
    ldud_header.cast_off_datetime falls in that calendar month (log rows and
    headers not deleted, short-close rows excluded, null quantities skipped);
    vessel_count is the ldud_header count by cast-off month
    (fetch_vessel_count_from_ldud_header).

The Port Overview month card reads mon_yy + quantity; the other columns are
for checking figures against Report 5.

Revision ID: jnpa75_month_totals_view
Revises: jnpa74_port_overview_views
Create Date: 2026-10-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa75_month_totals_view'
down_revision: Union[str, None] = 'jnpa74_port_overview_views'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE VIEW jnpa_month_totals AS
        WITH mis AS (
            -- report5.fetch_from_mis_vessel_master; month is stored like 'Sep-26'
            SELECT TRIM(month) AS mon_yy,
                   SUM(COALESCE(quantity, 0)) AS quantity,
                   COUNT(DISTINCT vessel_name) AS vessel_count
            FROM mis_vessel_master
            WHERE TRIM(month) ~ '^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-[0-9]{2}$'
            GROUP BY TRIM(month)
        ),
        live_qty AS (
            -- report5.fetch_quantity_from_parcel_log
            SELECT to_char(jnpa_ts(h.cast_off_datetime), 'Mon-YY') AS mon_yy,
                   SUM(l.quantity) AS quantity
            FROM lueu_parcel_log l
            JOIN ldud_parcel_ops o ON o.id = l.parcel_op_id
            JOIN ldud_header h ON h.id = o.ldud_id
            WHERE l.is_deleted IS NOT TRUE AND h.is_deleted IS NOT TRUE
              AND l.is_shortclose IS NOT TRUE AND l.quantity IS NOT NULL
              AND jnpa_ts(h.cast_off_datetime) IS NOT NULL
            GROUP BY 1
        ),
        live_vessels AS (
            -- report5.fetch_vessel_count_from_ldud_header
            SELECT to_char(jnpa_ts(cast_off_datetime), 'Mon-YY') AS mon_yy,
                   COUNT(DISTINCT vessel_name) AS vessel_count
            FROM ldud_header
            WHERE is_deleted IS NOT TRUE AND jnpa_ts(cast_off_datetime) IS NOT NULL
            GROUP BY 1
        ),
        months AS (
            SELECT mon_yy FROM mis
            UNION SELECT mon_yy FROM live_qty
            UNION SELECT mon_yy FROM live_vessels
        )
        SELECT m.mon_yy,
               d.month_start,
               CASE WHEN extract(month FROM d.month_start) >= 4 THEN extract(year FROM d.month_start)::int
                    ELSE extract(year FROM d.month_start)::int - 1 END AS fin_year_start,
               s.source,
               round(CASE WHEN s.source = 'mis' THEN COALESCE(mis.quantity, 0)
                          ELSE COALESCE(lq.quantity, 0) END, 3) AS quantity,
               CASE WHEN s.source = 'mis' THEN COALESCE(mis.vessel_count, 0)
                    ELSE COALESCE(lv.vessel_count, 0) END AS vessel_count
        FROM months m
        CROSS JOIN LATERAL (SELECT to_date('01-' || m.mon_yy, 'DD-Mon-YY') AS month_start) d
        LEFT JOIN mis ON mis.mon_yy = m.mon_yy
        LEFT JOIN live_qty lq ON lq.mon_yy = m.mon_yy
        LEFT JOIN live_vessels lv ON lv.mon_yy = m.mon_yy
        -- report5.CUTOVER_DATE = 2026-07-01
        CROSS JOIN LATERAL (
            SELECT CASE WHEN d.month_start < DATE '2026-07-01' OR mis.mon_yy IS NOT NULL
                        THEN 'mis' ELSE 'live' END AS source
        ) s
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS jnpa_month_totals")
