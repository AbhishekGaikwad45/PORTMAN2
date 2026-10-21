"""Read-only jnpa_* views that reproduce the RP01 Port Overview dashboard.

A third party given SELECT on these views alone (no base tables) can rebuild
the same dashboard. Access is granted outside migrations. Each view mirrors the
Python it stands in for (named in its comment), including that code's quirks,
so the numbers match the live dashboard.

Panel -> view:
  header clock / FY countdown   jnpa_clock
  jetty image + berth boxes     jnpa_berths            (static/img/jjltpljetty.png, 540x808)
  tankers on berth + card       jnpa_vessels_on_berth, jnpa_parcels
  waiting / expected overlay    jnpa_waiting_vessels
  cargo cards                   jnpa_cargo_cards (jnpa_cargo_throughput, jnpa_fy_targets)
  pipelines panel               jnpa_pipelines, jnpa_pipeline_live
  top delays                    jnpa_delays_today
  tide strip                    jnpa_tide
  weather card                  jnpa_weather
  shift in-charge               jnpa_shift_incharge
  raw operational log           jnpa_parcel_log

Helper views (jnpa_cargo_category_map, jnpa_vcn_parcels, jnpa_parcel_op_sources,
jnpa_parcel_targets) feed the ones above and carry consignee names the
dashboard never shows — no need to share them.

Time-based views evaluate "now" in Asia/Kolkata whatever the session time zone;
the operational day runs 07:00 -> 07:00 like the DPR.

Revision ID: jnpa74_port_overview_views
Revises: jnpa73_weather_cache
Create Date: 2026-10-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa74_port_overview_views'
down_revision: Union[str, None] = 'jnpa73_weather_cache'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Drop order (dependents first).
ALL_VIEWS = [
    'jnpa_shift_incharge', 'jnpa_weather', 'jnpa_tide', 'jnpa_delays_today',
    'jnpa_pipelines', 'jnpa_pipeline_live', 'jnpa_cargo_cards', 'jnpa_fy_targets',
    'jnpa_cargo_throughput', 'jnpa_waiting_vessels', 'jnpa_vessels_on_berth',
    'jnpa_parcels', 'jnpa_parcel_log', 'jnpa_parcel_targets', 'jnpa_parcel_op_sources',
    'jnpa_vcn_parcels', 'jnpa_berths', 'jnpa_clock', 'jnpa_cargo_category_map',
]
FUNCTIONS = [
    'jnpa_liquid_category(text, text, text, text, text)', 'jnpa_name_category(text)',
    'jnpa_master_category(text, text)', 'jnpa_explicit_category(text)',
    'jnpa_distinct_csv(text)', 'jnpa_hours(text, text)', 'jnpa_log_ts(text, text)', 'jnpa_time(text)',
    'jnpa_ts(text)', 'jnpa_num(text)',
]


FUNCTIONS_SQL = r"""
-- LDUD01._qty / LUEU01 float(): text quantity with thousands separators; NULL when unparsable.
CREATE OR REPLACE FUNCTION jnpa_num(v text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN NULLIF(TRIM(REPLACE(v, ',', '')), '')::numeric;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

-- dpr._parse_entry_dt: the TEXT datetimes used across LDUD/LUEU/TM01.
CREATE OR REPLACE FUNCTION jnpa_ts(v text) RETURNS timestamp
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE t time;
BEGIN
    v := NULLIF(TRIM(v), '');
    IF v IS NULL THEN RETURN NULL; END IF;
    t := COALESCE(substring(substr(v, 11) from '(\d{1,2}:\d{2})')::time, '00:00'::time);
    IF v ~ '^\d{4}-\d{2}-\d{2}' THEN
        RETURN to_date(substr(v, 1, 10), 'YYYY-MM-DD') + t;
    ELSIF v ~ '^\d{4}/\d{2}/\d{2}' THEN
        RETURN to_date(substr(v, 1, 10), 'YYYY/MM/DD') + t;
    ELSIF v ~ '^\d{2}[-/.]\d{2}[-/.]\d{4}' THEN
        RETURN to_date(translate(substr(v, 1, 10), '/.', '--'), 'DD-MM-YYYY') + t;
    END IF;
    RETURN NULL;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION jnpa_time(v text) RETURNS time
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN substring(v from '^\s*(\d{1,2}:\d{2})')::time;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

-- LUEU log interval start: entry date + from_time (dpr._parse_entry_dt with from_time).
CREATE OR REPLACE FUNCTION jnpa_log_ts(d text, f text) RETURNS timestamp
LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(jnpa_ts(d)::date + jnpa_time(f), jnpa_ts(d))
$$;

-- LUEU01._hours: 'HH:MM' -> 'HH:MM' in hours, wrapping past midnight; 0 when unparsable.
CREATE OR REPLACE FUNCTION jnpa_hours(f text, t text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE fm int; tm int;
BEGIN
    fm := split_part(TRIM(f), ':', 1)::int * 60 + split_part(TRIM(f), ':', 2)::int;
    tm := split_part(TRIM(t), ':', 1)::int * 60 + split_part(TRIM(t), ':', 2)::int;
    RETURN (((tm - fm) % 1440 + 1440) % 1440) / 60.0;
EXCEPTION WHEN others THEN RETURN 0;
END $$;

-- LUEU01.get_started_parcels._distinct: 'a, b,a , c' -> 'a, b, c' (first-seen order).
CREATE OR REPLACE FUNCTION jnpa_distinct_csv(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT STRING_AGG(val, ', ' ORDER BY pos)
    FROM (SELECT TRIM(x) AS val, MIN(pos) AS pos
          FROM unnest(string_to_array(v, ',')) WITH ORDINALITY AS u(x, pos)
          WHERE TRIM(x) <> '' GROUP BY TRIM(x)) d
$$;

-- dpr._categorize_cargo step 1: an explicit category field.
CREATE OR REPLACE FUNCTION jnpa_explicit_category(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN TRIM(COALESCE(v, '')) = '' THEN NULL
        WHEN UPPER(v) LIKE '%EDIBLE%' THEN 'Edible Oil'
        WHEN UPPER(v) LIKE '%CHEM%'   THEN 'Chemical'
        WHEN UPPER(v) LIKE '%POL%'    THEN 'POL'
        WHEN UPPER(v) LIKE '%FARM%' OR UPPER(v) LIKE '%OTHER%' THEN 'Other liquid'
    END
$$;

-- dpr._load_vessel_cargo_map.resolve_category (note: POL is tested before CHEM here).
CREATE OR REPLACE FUNCTION jnpa_master_category(v text, fallback text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN s LIKE '%EDIBLE%' THEN 'Edible Oil'
        WHEN s LIKE '%POL%'    THEN 'POL'
        WHEN s LIKE '%CHEM%'   THEN 'Chemical'
        ELSE 'Other liquid'
    END
    FROM (SELECT COALESCE(NULLIF(UPPER(TRIM(v)), ''), UPPER(TRIM(COALESCE(fallback, '')))) AS s) x
$$;

-- dpr._categorize_cargo step 3: cargo-name keywords.
CREATE OR REPLACE FUNCTION jnpa_name_category(n text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN s ~ '(EDIBLE|PALM|SOYA|SUNFLOWER|CPO|CDSBO)' THEN 'Edible Oil'
        WHEN s ~ '(POL|MOTOR SPIRIT|HSD|NAPHTHA|DIESEL|PETROL)' THEN 'POL'
        WHEN s ~ '(CHEM|BENZENE|HEXANE|METHANOL|ETHANOL|ACETONE)' THEN 'Chemical'
        ELSE 'Other liquid'
    END
    FROM (SELECT UPPER(TRIM(COALESCE(n, ''))) AS s) x
$$;

-- dpr._categorize_cargo: explicit fields, then the master map (passed in by
-- the caller's join to jnpa_cargo_category_map), then name keywords.
CREATE OR REPLACE FUNCTION jnpa_liquid_category(name text, sub2 text, cat text, sub text, mapped text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(jnpa_explicit_category(sub2), jnpa_explicit_category(cat),
                    jnpa_explicit_category(sub), mapped, jnpa_name_category(name))
$$;
"""


VIEWS_SQL = r"""
-- dpr._load_vessel_cargo_map: vessel_cargo (last row wins) > mis_vessel_master > mis_history (first wins).
CREATE OR REPLACE VIEW jnpa_cargo_category_map AS
SELECT DISTINCT ON (norm_name) norm_name, category
FROM (
    SELECT 1 AS pri, -id AS ord, LOWER(TRIM(cargo_name)) AS norm_name,
           jnpa_master_category(COALESCE(NULLIF(cargo_sub_category_2, ''), NULLIF(cargo_category, ''), cargo_type),
                                LOWER(TRIM(cargo_name))) AS category
    FROM vessel_cargo WHERE TRIM(COALESCE(cargo_name, '')) <> ''
    UNION ALL
    SELECT 2, id, LOWER(TRIM(cargo)),
           jnpa_master_category(COALESCE(NULLIF(new_cat, ''), NULLIF(category1, ''), category), LOWER(TRIM(cargo)))
    FROM mis_vessel_master WHERE TRIM(COALESCE(cargo, '')) <> ''
    UNION ALL
    SELECT 3, id, LOWER(TRIM(cargo_name)),
           jnpa_master_category(COALESCE(NULLIF(cargo_sub_category_2, ''), NULLIF(cargo_category, ''), cargo_type),
                                LOWER(TRIM(cargo_name)))
    FROM mis_history WHERE TRIM(COALESCE(cargo_name, '')) <> ''
) s
ORDER BY norm_name, pri, ord;

-- Dashboard clock: 07:00 operational day, month, FY windows.
CREATE OR REPLACE VIEW jnpa_clock AS
SELECT n.now_ts,
       d.op_day_start,
       d.op_date,
       date_trunc('month', d.op_date::timestamp) + interval '7 hours' AS month_start,
       f.fy_start_year,
       f.fy_start_year || '-' || lpad(((f.fy_start_year + 1) % 100)::text, 2, '0') AS fy_label,
       (f.fy_start_year - 1) || '-' || lpad((f.fy_start_year % 100)::text, 2, '0') AS fy_prev_label,
       (f.fy_start_year - 2) || '-' || lpad(((f.fy_start_year - 1) % 100)::text, 2, '0') AS fy_prev2_label,
       make_timestamp(f.fy_start_year, 7, 1, 7, 0, 0) AS fy_live_start,
       make_date(f.fy_start_year + 1, 3, 31) AS fy_end,
       (date_trunc('month', d.op_date::timestamp) + interval '1 month')::date - d.op_date AS month_days_left,
       make_date(f.fy_start_year + 1, 3, 31) - d.op_date + 1 AS fy_days_left,
       to_char(d.op_date, 'Mon') AS month_abbr
FROM (SELECT (now() AT TIME ZONE 'Asia/Kolkata')::timestamp(0) AS now_ts) n
CROSS JOIN LATERAL (
    SELECT date_trunc('day', n.now_ts - interval '7 hours') + interval '7 hours' AS op_day_start,
           (n.now_ts - interval '7 hours')::date AS op_date
) d
CROSS JOIN LATERAL (
    SELECT CASE WHEN extract(month FROM d.op_date) >= 4 THEN extract(year FROM d.op_date)::int
                ELSE extract(year FROM d.op_date)::int - 1 END AS fy_start_year
) f;

-- port_overview._load_berth_layout: PBM01 positions in jjltpljetty.png pixel space.
-- The dashboard draws only berths whose cx is not null.
CREATE OR REPLACE VIEW jnpa_berths AS
SELECT b.id AS berth_id, b.berth_name, b.berth_location,
       (b.image_position->>'cx')::numeric AS cx,
       (b.image_position->>'cy')::numeric AS cy,
       (b.image_position->>'w')::numeric AS w,
       (b.image_position->>'h')::numeric AS h,
       COALESCE((b.image_position->>'angle')::numeric, 0) AS angle,
       'static/img/jjltpljetty.png'::text AS image_file,
       540 AS image_width, 808 AS image_height
FROM port_berth_master b;

-- VCN parcels from the operation type's table (LDUD01.parcel_source_table).
CREATE OR REPLACE VIEW jnpa_vcn_parcels AS
SELECT 'vcn_consigners'::text AS source_table, c.id, c.vcn_id, c.parcel_no, c.cargo_name,
       c.quantity AS quantity_text, c.consigner_name, c.pipeline_name, c.unload_terminal,
       c.equipment_names, COALESCE(c.is_removed, FALSE) AS is_removed, c.removed_reason
FROM vcn_consigners c JOIN vcn_header vh ON vh.id = c.vcn_id
WHERE vh.operation_type IS DISTINCT FROM 'Export'
UNION ALL
SELECT 'vcn_export_cargo_declaration', e.id, e.vcn_id, e.parcel_no, e.cargo_name,
       e.quantity, e.consigner_name, e.pipeline_name, e.unload_terminal,
       e.equipment_names, COALESCE(e.is_removed, FALSE), e.removed_reason
FROM vcn_export_cargo_declaration e JOIN vcn_header vh ON vh.id = e.vcn_id
WHERE vh.operation_type = 'Export';

-- ldud_parcel_ops.parcel_ids (CSV) resolved to VCN parcels, in CSV order.
CREATE OR REPLACE VIEW jnpa_parcel_op_sources AS
SELECT po.id AS parcel_op_id, ids.ord, ids.pid, vp.id AS source_id, vp.parcel_no, vp.quantity_text,
       vp.pipeline_name, vp.unload_terminal, vp.equipment_names, vp.is_removed, vp.removed_reason
FROM ldud_parcel_ops po
JOIN ldud_header lh ON lh.id = po.ldud_id
CROSS JOIN LATERAL (
    SELECT TRIM(x)::int AS pid, ord
    FROM unnest(string_to_array(po.parcel_ids, ',')) WITH ORDINALITY AS u(x, ord)
    WHERE TRIM(x) ~ '^\d+$'
) ids
LEFT JOIN jnpa_vcn_parcels vp ON vp.id = ids.pid AND vp.vcn_id = lh.vcn_id;

-- LDUD01.effective_target + LUEU01.get_started_parcels labels/pipelines/terminals per parcel op.
CREATE OR REPLACE VIEW jnpa_parcel_targets AS
SELECT po.id AS parcel_op_id,
       CASE WHEN COUNT(s.source_id) > 0
            THEN SUM(CASE WHEN s.is_removed THEN 0 ELSE COALESCE(jnpa_num(s.quantity_text), 0) END)
                 FILTER (WHERE s.source_id IS NOT NULL)
            ELSE COALESCE(po.quantity, 0) END
         + COALESCE(po.additional_qty, 0) AS target_qty,
       COUNT(s.pid) > 0 AND bool_and(COALESCE(s.is_removed, FALSE)) AS is_removed,
       MIN(s.removed_reason) FILTER (WHERE s.is_removed) AS removed_reason,
       COALESCE(STRING_AGG(COALESCE(NULLIF(s.parcel_no, ''), '#' || s.pid), ', ' ORDER BY s.ord), '—') AS parcel_no,
       jnpa_distinct_csv(STRING_AGG(s.pipeline_name, ',' ORDER BY s.ord)) AS pipeline_name,
       COALESCE(jnpa_distinct_csv(STRING_AGG(s.unload_terminal, ',' ORDER BY s.ord)),
                po.terminal_name, '') AS terminal_name,
       jnpa_distinct_csv(STRING_AGG(s.equipment_names, ',' ORDER BY s.ord)) AS equipment_names
FROM ldud_parcel_ops po
LEFT JOIN jnpa_parcel_op_sources s ON s.parcel_op_id = po.id
GROUP BY po.id;

-- Every live LUEU parcel log row (deleted rows and deleted LDUDs excluded).
--   excluded_from_throughput: DPR day/month rule (short-close flag or 'short' in remarks)
--   counts_toward_target:     LUEU01 completion cap — rows after the parcel reached
--                             its target are ignored for logged qty / run hours
CREATE OR REPLACE VIEW jnpa_parcel_log AS
SELECT l.id AS log_id, l.parcel_op_id, po.ldud_id, lh.vcn_id, vh.vcn_doc_num, lh.vessel_name,
       vh.berth_name AS vcn_berth_name, l.berth_name AS log_berth_name,
       po.cargo_name,
       jnpa_liquid_category(po.cargo_name, NULL, NULL, NULL, m.category) AS liquid_category,
       t.pipeline_name,
       l.entry_date, l.from_time, l.to_time,
       jnpa_log_ts(l.entry_date, l.from_time) AS start_ts,
       jnpa_hours(l.from_time, l.to_time) AS hours,
       COALESCE(l.quantity, 0) AS quantity, l.quantity_uom, l.medium, l.pressure,
       l.equipment_name, NULLIF(TRIM(l.delay_name), '') AS delay_name,
       l.shift, l.operator_name, l.shift_incharge, l.remarks,
       COALESCE(l.is_shortclose, FALSE) AS is_shortclose,
       (COALESCE(l.is_shortclose, FALSE) OR LOWER(COALESCE(l.remarks, '')) LIKE '%short%') AS excluded_from_throughput,
       NOT (t.target_qty > 0 AND COALESCE(SUM(COALESCE(l.quantity, 0)) OVER (
                PARTITION BY l.parcel_op_id ORDER BY l.entry_date, l.from_time NULLS LAST, l.id
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) >= t.target_qty - 0.000001
           ) AS counts_toward_target
FROM lueu_parcel_log l
JOIN ldud_parcel_ops po ON po.id = l.parcel_op_id
JOIN ldud_header lh ON lh.id = po.ldud_id
LEFT JOIN vcn_header vh ON vh.id = lh.vcn_id
LEFT JOIN jnpa_parcel_targets t ON t.parcel_op_id = po.id
LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(po.cargo_name))
WHERE l.is_deleted IS NOT TRUE AND lh.is_deleted IS NOT TRUE;

-- LUEU01.get_started_parcels: one row per parcel op (the vessel card's parcel list).
CREATE OR REPLACE VIEW jnpa_parcels AS
SELECT po.id AS parcel_op_id, po.ldud_id, lh.vcn_id, vh.vcn_doc_num, vh.vessel_name, vh.berth_name,
       vh.operation_type, t.parcel_no, po.cargo_name,
       jnpa_liquid_category(po.cargo_name, NULL, NULL, NULL, m.category) AS liquid_category,
       t.pipeline_name, t.terminal_name, t.equipment_names,
       round(t.target_qty, 3) AS target_qty,
       round(COALESCE(a.real_qty, 0) + COALESCE(a.sc_qty, 0), 3) AS logged_qty,
       round(t.target_qty - COALESCE(a.real_qty, 0) - COALESCE(a.sc_qty, 0), 3) AS remaining_qty,
       round(COALESCE(a.hours, 0), 2) AS run_hours,
       CASE WHEN COALESCE(a.hours, 0) > 0 THEN round(a.real_qty / a.hours, 2) ELSE 0 END AS avg_rate,
       COALESCE(a.sc_qty, 0) > 0.000001 AS is_shortclosed,
       COALESCE(po.additional_qty, 0) AS additional_qty, po.additional_reason,
       t.is_removed, t.removed_reason,
       po.expected_start, po.expected_flow_rate, po.start_dt, po.end_dt,
       CASE WHEN t.is_removed THEN 'Removed'
            WHEN NULLIF(TRIM(po.end_dt), '') IS NOT NULL THEN 'Completed'
            WHEN NULLIF(TRIM(po.start_dt), '') IS NOT NULL THEN 'Pumping'
            ELSE 'Not Started' END AS state
FROM ldud_parcel_ops po
JOIN ldud_header lh ON lh.id = po.ldud_id
JOIN vcn_header vh ON vh.id = lh.vcn_id
JOIN jnpa_parcel_targets t ON t.parcel_op_id = po.id
LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(po.cargo_name))
LEFT JOIN (
    SELECT parcel_op_id,
           SUM(quantity) FILTER (WHERE NOT is_shortclose) AS real_qty,
           SUM(quantity) FILTER (WHERE is_shortclose) AS sc_qty,
           SUM(hours) FILTER (WHERE NOT is_shortclose) AS hours
    FROM jnpa_parcel_log WHERE counts_toward_target
    GROUP BY parcel_op_id
) a ON a.parcel_op_id = po.id
WHERE lh.is_deleted IS NOT TRUE;

-- Berth_plan.get_berthed_vessels + _enrich_vessel as of now: latest alongside,
-- not-yet-sailed vessel per PBM01 berth.
CREATE OR REPLACE VIEW jnpa_vessels_on_berth AS
WITH c AS (SELECT now_ts, op_day_start FROM jnpa_clock),
hdr AS (
    SELECT DISTINCT ON (vh.berth_name)
           vh.id AS vcn_id, lh.id AS ldud_id, vh.vcn_doc_num, vh.via_number, vh.vessel_name,
           vh.loa, vh.draft, vh.vessel_agent_name AS agent, vh.cargo_type, vh.berth_name,
           vh.operation_type, v.imo_num, v.nationality,
           jnpa_ts(lh.alongside_datetime) AS alongside_at
    FROM ldud_header lh
    JOIN vcn_header vh ON vh.id = lh.vcn_id
    LEFT JOIN vessels v ON UPPER(REPLACE(TRIM(v.vessel_name), 'MT ', '')) = UPPER(REPLACE(TRIM(vh.vessel_name), 'MT ', ''))
    CROSS JOIN c
    WHERE lh.is_deleted IS NOT TRUE
      AND vh.berth_name IN (SELECT berth_name FROM port_berth_master)
      AND jnpa_ts(lh.alongside_datetime) < c.now_ts
      AND (jnpa_ts(lh.cast_off_datetime) IS NULL OR jnpa_ts(lh.cast_off_datetime) >= c.now_ts)
    ORDER BY vh.berth_name, jnpa_ts(lh.alongside_datetime) DESC
),
-- _cumulative_as_of / last-24h: real (non-short-close) log, no completion cap
lg AS (
    SELECT l.ldud_id, l.parcel_op_id,
           SUM(l.quantity) FILTER (WHERE l.start_ts < c.now_ts) AS qty_asof,
           SUM(l.hours)    FILTER (WHERE l.start_ts < c.now_ts) AS hrs_asof,
           SUM(l.quantity) FILTER (WHERE l.start_ts >= c.op_day_start AND l.start_ts < c.now_ts) AS qty_today,
           SUM(l.quantity) AS qty_all, SUM(l.hours) AS hrs_all
    FROM jnpa_parcel_log l CROSS JOIN c
    WHERE NOT l.is_shortclose AND l.ldud_id IN (SELECT ldud_id FROM hdr)
    GROUP BY l.ldud_id, l.parcel_op_id
),
asof AS (
    SELECT ldud_id, SUM(COALESCE(qty_asof, 0)) AS done_qty, MAX(COALESCE(hrs_asof, 0)) AS max_hrs,
           SUM(COALESCE(qty_today, 0)) AS today_qty
    FROM lg GROUP BY ldud_id
),
-- _per_parcel_completion: ETC per parcel op on its snapshot quantity
op_etc AS (
    SELECT po.ldud_id, x.etc, x.planned
    FROM ldud_parcel_ops po
    LEFT JOIN lg ON lg.parcel_op_id = po.id
    CROSS JOIN LATERAL (
        SELECT CASE WHEN COALESCE(lg.hrs_all, 0) > 0 AND COALESCE(lg.qty_all, 0) > 0 AND jnpa_ts(po.start_dt) IS NOT NULL
                    THEN jnpa_ts(po.start_dt) + make_interval(secs => (po.quantity / (lg.qty_all / lg.hrs_all) * 3600)::float8)
                    WHEN COALESCE(po.expected_flow_rate, 0) > 0 AND jnpa_ts(po.expected_start) IS NOT NULL AND COALESCE(po.quantity, 0) <> 0
                    THEN jnpa_ts(po.expected_start) + make_interval(secs => (po.quantity / po.expected_flow_rate * 3600)::float8)
               END AS etc,
               NOT (COALESCE(lg.hrs_all, 0) > 0 AND COALESCE(lg.qty_all, 0) > 0 AND jnpa_ts(po.start_dt) IS NOT NULL) AS planned
    ) x
    WHERE po.ldud_id IN (SELECT ldud_id FROM hdr)
      AND COALESCE(po.quantity, 0) - COALESCE(lg.qty_all, 0) > 0
),
etc AS (
    SELECT DISTINCT ON (ldud_id) ldud_id, etc, planned
    FROM op_etc WHERE etc IS NOT NULL ORDER BY ldud_id, etc DESC
),
-- _enrich_vessel._planned_etc: rate of the parcel with the latest planned ETC
planned AS (
    SELECT DISTINCT ON (p.vcn_id) p.vcn_id, p.expected_flow_rate AS best_rate
    FROM jnpa_parcels p
    WHERE COALESCE(p.expected_flow_rate, 0) > 0 AND jnpa_ts(p.expected_start) IS NOT NULL AND p.target_qty <> 0
    ORDER BY p.vcn_id, jnpa_ts(p.expected_start) + make_interval(secs => (p.target_qty / p.expected_flow_rate * 3600)::float8) DESC
),
tot AS (SELECT vcn_id, SUM(target_qty) AS total_qty FROM jnpa_parcels GROUP BY vcn_id),
ops AS (
    SELECT ldud_id, MIN(jnpa_ts(start_dt)) AS ops_commenced,
           MAX(jnpa_ts(end_dt)) AS cargo_completion
    FROM ldud_parcel_ops GROUP BY ldud_id
),
-- _enrich_vessel remarks: last remark of in-progress parcels, else latest
-- short-close remark, else the last parcel's last remark
pr AS (
    SELECT po.ldud_id, po.id,
           COALESCE(po.quantity, 0) - COALESCE(lg.qty_all, 0) > 0 AS in_progress,
           (SELECT NULLIF(r.remarks, '') FROM lueu_parcel_log r
             WHERE r.parcel_op_id = po.id AND r.is_deleted IS NOT TRUE
             ORDER BY jnpa_ts(r.entry_date)::date DESC, jnpa_time(r.to_time) DESC, r.id DESC LIMIT 1) AS last_remark,
           (SELECT NULLIF(r.remarks, '') FROM lueu_parcel_log r
             WHERE r.parcel_op_id = po.id AND r.is_deleted IS NOT TRUE AND r.is_shortclose IS TRUE
             ORDER BY jnpa_ts(r.entry_date)::date DESC, jnpa_time(r.to_time) DESC, r.id DESC LIMIT 1) AS sc_remark
    FROM ldud_parcel_ops po
    LEFT JOIN lg ON lg.parcel_op_id = po.id
    WHERE po.ldud_id IN (SELECT ldud_id FROM hdr)
),
rem AS (
    SELECT ldud_id,
           COALESCE(STRING_AGG(last_remark, ', ' ORDER BY id) FILTER (WHERE in_progress),
                    (ARRAY_AGG(sc_remark ORDER BY id DESC) FILTER (WHERE sc_remark IS NOT NULL))[1],
                    (ARRAY_AGG(last_remark ORDER BY id DESC))[1]) AS remarks
    FROM pr GROUP BY ldud_id
),
src AS (
    SELECT vp.vcn_id,
           STRING_AGG(DISTINCT COALESCE(NULLIF(TRIM(cu.customer_code), ''), TRIM(vp.consigner_name)), ', ')
               FILTER (WHERE TRIM(COALESCE(vp.consigner_name, '')) <> '') AS consigner,
           STRING_AGG(DISTINCT COALESCE(NULLIF(TRIM(vc.cargo_code), ''),
                                        NULLIF(TRIM(REGEXP_REPLACE(vp.cargo_name, '\s*\[.*\]', '')), ''),
                                        TRIM(vp.cargo_name)), ', ')
               FILTER (WHERE TRIM(COALESCE(vp.cargo_name, '')) <> '') AS cargo,
           STRING_AGG(DISTINCT NULLIF(TRIM(vp.pipeline_name), ''), ', ') AS pipeline,
           STRING_AGG(DISTINCT NULLIF(TRIM(vp.unload_terminal), ''), ', ') AS terminal
    FROM jnpa_vcn_parcels vp
    LEFT JOIN vessel_customers cu
           ON UPPER(TRIM(cu.name)) = UPPER(TRIM(vp.consigner_name))
           OR UPPER(TRIM(cu.customer_code)) = UPPER(TRIM(vp.consigner_name))
    LEFT JOIN vessel_cargo vc
           ON UPPER(TRIM(vc.cargo_name)) = UPPER(TRIM(vp.cargo_name))
           OR UPPER(TRIM(vc.cargo_code)) = UPPER(TRIM(vp.cargo_name))
           OR UPPER(TRIM(vc.cargo_name)) = UPPER(TRIM(REGEXP_REPLACE(vp.cargo_name, '\s*\[.*\]', '')))
           OR UPPER(TRIM(vc.cargo_code)) = UPPER(TRIM(REGEXP_REPLACE(vp.cargo_name, '\s*\[.*\]', '')))
    WHERE vp.vcn_id IN (SELECT vcn_id FROM hdr)
    GROUP BY vp.vcn_id
)
SELECT h.berth_name, h.vcn_id, h.ldud_id, h.vcn_doc_num, h.via_number, h.vessel_name,
       h.imo_num, h.nationality, h.loa, h.draft, h.agent, h.operation_type,
       COALESCE(s.cargo, h.cargo_type) AS cargo,
       s.consigner, s.pipeline, s.terminal,
       h.alongside_at, o.ops_commenced, o.cargo_completion,
       round(COALESCE(tot.total_qty, 0), 3) AS total_qty,
       round(COALESCE(a.done_qty, 0), 3) AS handled_qty,
       round(COALESCE(tot.total_qty, 0) - COALESCE(a.done_qty, 0), 3) AS balance_qty,
       round(COALESCE(a.today_qty, 0), 3) AS today_qty,
       r.rate AS flow_rate,
       (NOT r.has_actual AND COALESCE(pl.best_rate, 0) > 0) OR COALESCE(e.planned, FALSE) AS flow_rate_is_planned,
       e.etc AS expected_completion,
       rm.remarks,
       CASE WHEN o.ops_commenced IS NULL THEN 'Awaiting Ops'
            WHEN COALESCE(tot.total_qty, 0) - COALESCE(a.done_qty, 0) <= 0 THEN 'Ops Completed'
            ELSE 'Under Operation' END AS status
FROM hdr h
LEFT JOIN asof a ON a.ldud_id = h.ldud_id
LEFT JOIN tot ON tot.vcn_id = h.vcn_id
LEFT JOIN etc e ON e.ldud_id = h.ldud_id
LEFT JOIN planned pl ON pl.vcn_id = h.vcn_id
LEFT JOIN ops o ON o.ldud_id = h.ldud_id
LEFT JOIN rem rm ON rm.ldud_id = h.ldud_id
LEFT JOIN src s ON s.vcn_id = h.vcn_id
CROSS JOIN LATERAL (
    SELECT CASE WHEN COALESCE(a.max_hrs, 0) > 0 THEN round(a.done_qty / a.max_hrs, 2) ELSE 0 END AS present
) pf
CROSS JOIN LATERAL (
    SELECT pf.present > 0 AND COALESCE(a.max_hrs, 0) >= 4 AS has_actual,
           CASE WHEN pf.present > 0 AND COALESCE(a.max_hrs, 0) >= 4 THEN pf.present
                ELSE COALESCE(NULLIF(pl.best_rate, 0), pf.present) END AS rate
) r;

-- Berth_plan.get_expected_waiting_vessels: VCNs whose latest LDUD has no alongside time.
CREATE OR REPLACE VIEW jnpa_waiting_vessels AS
SELECT vh.id AS vcn_id, vh.vcn_doc_num, vh.vessel_name, vh.via_number, vh.loa, vh.draft,
       vh.vessel_agent_name AS agent, vh.berth_name, vh.doc_date, vh.load_port,
       vh.cargo_type AS cargo,
       q.total_quantity, q.terminals,
       jnpa_ts(ld.anchored_datetime) AS anchored_at,
       jnpa_ts(ld.nor_accepted) AS nor_accepted_at,
       CASE WHEN jnpa_ts(ld.anchored_datetime) IS NOT NULL THEN 'At Anchorage' ELSE 'Expected' END AS state
FROM vcn_header vh
LEFT JOIN LATERAL (
    SELECT alongside_datetime, anchored_datetime, nor_accepted
    FROM ldud_header WHERE vcn_id = vh.id AND is_deleted IS NOT TRUE
    ORDER BY id DESC LIMIT 1
) ld ON TRUE
LEFT JOIN LATERAL (
    SELECT SUM(jnpa_num(p.quantity)) AS total_quantity,
           STRING_AGG(DISTINCT NULLIF(TRIM(p.unload_terminal), ''), ', ') AS terminals
    FROM (SELECT quantity, unload_terminal FROM vcn_consigners WHERE vcn_id = vh.id
          UNION ALL
          SELECT quantity, unload_terminal FROM vcn_export_cargo_declaration WHERE vcn_id = vh.id) p
) q ON TRUE
WHERE TRIM(COALESCE(ld.alongside_datetime, '')) = '';

-- dpr._get_section_b as the dashboard calls it: one row per period x liquid category.
--   balance_on_board  vessels alongside LB/03/04 now: parcel-op qty minus logged
--   today / yesterday / month   LUEU log by interval start (07:00 day)
--   fy                mis_vessel_master(current FY) + live vessels cast off since 1 Jul 07:00
--   fy_prev / fy_prev2   mis_history for the two prior FYs
--   cumulative        fy + fy_prev + fy_prev2
CREATE OR REPLACE VIEW jnpa_cargo_throughput AS
WITH c AS (SELECT * FROM jnpa_clock),
cats(category, sort_order) AS (VALUES ('Edible Oil', 1), ('Chemical', 2), ('POL', 3), ('Other liquid', 4)),
logs AS (
    SELECT l.liquid_category AS category, l.quantity, l.start_ts
    FROM jnpa_parcel_log l WHERE NOT l.excluded_from_throughput AND l.start_ts IS NOT NULL
),
bob AS (
    SELECT jnpa_liquid_category(COALESCE(po.cargo_name, vh.cargo_type, ''), vc.cargo_category,
                                vc.cargo_sub_category, vc.cargo_sub_category_2, m.category) AS category,
           GREATEST(COALESCE(po.quantity, 0) - COALESCE((
               SELECT SUM(COALESCE(g.quantity, 0)) FROM lueu_parcel_log g
               WHERE g.parcel_op_id = po.id AND g.is_deleted IS NOT TRUE AND g.is_shortclose IS NOT TRUE
                 AND LOWER(COALESCE(g.remarks, '')) NOT LIKE '%short%close%'), 0), 0) AS qty
    FROM ldud_parcel_ops po
    JOIN ldud_header lh ON lh.id = po.ldud_id
    JOIN vcn_header vh ON vh.id = lh.vcn_id
    LEFT JOIN vessel_cargo vc ON LOWER(TRIM(COALESCE(po.cargo_name, ''))) = LOWER(TRIM(vc.cargo_name))
    LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(COALESCE(po.cargo_name, vh.cargo_type, '')))
    CROSS JOIN c
    WHERE lh.is_deleted IS NOT TRUE
      AND (vh.berth_name LIKE '%LB%' OR vh.berth_name LIKE '%03%' OR vh.berth_name LIKE '%04%')
      AND jnpa_ts(lh.alongside_datetime) <= c.now_ts
      AND (jnpa_ts(lh.cast_off_datetime) IS NULL OR jnpa_ts(lh.cast_off_datetime) > c.now_ts)
),
live_fy AS (
    SELECT jnpa_liquid_category(g.cargo_name, g.cargo_sub_category_2, g.cargo_category, g.cargo_type, m.category) AS category,
           g.qty
    FROM (
        SELECT po.cargo_name, vc.cargo_sub_category_2, vc.cargo_category, vc.cargo_type,
               lh.cast_off_datetime, SUM(COALESCE(l.quantity, 0)) AS qty
        FROM ldud_header lh
        JOIN ldud_parcel_ops po ON po.ldud_id = lh.id
        JOIN lueu_parcel_log l ON l.parcel_op_id = po.id
        LEFT JOIN vessel_cargo vc ON LOWER(TRIM(vc.cargo_name)) = LOWER(TRIM(po.cargo_name))
        WHERE TRIM(COALESCE(lh.cast_off_datetime, '')) <> ''
          AND l.is_deleted IS NOT TRUE AND l.is_shortclose IS NOT TRUE
          AND LOWER(COALESCE(l.remarks, '')) NOT LIKE '%short%'
          AND lh.is_deleted IS NOT TRUE
        GROUP BY lh.id, lh.vessel_name, lh.cast_off_datetime, po.cargo_name,
                 vc.cargo_sub_category_2, vc.cargo_category, vc.cargo_type
    ) g
    LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(g.cargo_name))
    CROSS JOIN c
    WHERE jnpa_ts(g.cast_off_datetime) BETWEEN c.fy_live_start AND c.now_ts AND g.qty > 0
),
mis_fy AS (
    SELECT jnpa_liquid_category(v.cargo, v.new_cat, v.category1, v.category, m.category) AS category,
           SUM(COALESCE(v.quantity, 0)) AS qty
    FROM mis_vessel_master v
    LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(v.cargo))
    WHERE v.fin_year = (SELECT fy_label FROM c)
    GROUP BY v.cargo, v.new_cat, v.category1, v.category, m.category
),
hist AS (
    SELECT h.fin_year,
           jnpa_liquid_category(h.cargo_name, h.cargo_sub_category_2, h.cargo_category, h.cargo_type, m.category) AS category,
           SUM(COALESCE(h.quantity, 0)) AS qty
    FROM mis_history h
    LEFT JOIN jnpa_cargo_category_map m ON m.norm_name = LOWER(TRIM(h.cargo_name))
    WHERE h.fin_year IN (SELECT fy_prev_label FROM c UNION ALL SELECT fy_prev2_label FROM c)
    GROUP BY h.fin_year, h.cargo_name, h.cargo_sub_category_2, h.cargo_category, h.cargo_type, m.category
),
raw AS (
    SELECT 'balance_on_board' AS period, category, qty FROM bob
    UNION ALL SELECT 'today', l.category, l.quantity FROM logs l, c
              WHERE l.start_ts >= c.op_day_start AND l.start_ts < c.now_ts
    UNION ALL SELECT 'yesterday', l.category, l.quantity FROM logs l, c
              WHERE l.start_ts >= c.op_day_start - interval '1 day' AND l.start_ts < c.op_day_start
    UNION ALL SELECT 'month', l.category, l.quantity FROM logs l, c
              WHERE l.start_ts >= c.month_start AND l.start_ts < c.now_ts
    UNION ALL SELECT 'fy', category, qty FROM mis_fy
    UNION ALL SELECT 'fy', category, qty FROM live_fy
    UNION ALL SELECT CASE WHEN h.fin_year = c.fy_prev_label THEN 'fy_prev' ELSE 'fy_prev2' END, h.category, h.qty
              FROM hist h, c
),
periods(period, sort_order) AS (VALUES ('balance_on_board', 0), ('today', 1), ('yesterday', 2), ('month', 3),
                                       ('fy', 4), ('fy_prev', 5), ('fy_prev2', 6), ('cumulative', 7)),
summed AS (
    SELECT p.period, p.sort_order AS period_order, k.category, k.sort_order AS category_order,
           COALESCE((SELECT SUM(r.qty) FROM raw r
                      WHERE r.category = k.category
                        AND (r.period = p.period
                             OR (p.period = 'cumulative' AND r.period IN ('fy', 'fy_prev', 'fy_prev2')))), 0) AS qty
    FROM periods p CROSS JOIN cats k
)
SELECT s.period, s.period_order, s.category, s.category_order, round(s.qty, 3) AS qty,
       CASE s.period WHEN 'fy' THEN c.fy_label WHEN 'fy_prev' THEN c.fy_prev_label
                     WHEN 'fy_prev2' THEN c.fy_prev2_label END AS fin_year
FROM summed s CROSS JOIN c;

-- financial_year_targets (budget report) expanded: Outlook overrides Target when set.
CREATE OR REPLACE VIEW jnpa_fy_targets AS
SELECT f.financial_year, item->>'name' AS item_name, TRIM(md->>'month') AS month,
       x.target, x.outlook,
       CASE WHEN x.outlook <> 0 THEN x.outlook ELSE x.target END AS effective_target
FROM financial_year_targets f
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(f.targets->'targets') = 'array' THEN f.targets->'targets' ELSE '[]'::jsonb END) item
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(item->'monthly_data') = 'array' THEN item->'monthly_data' ELSE '[]'::jsonb END) md
CROSS JOIN LATERAL (
    SELECT COALESCE(NULLIF(jnpa_num(md->>'target'), 0), NULLIF(jnpa_num(md->>'budget_quantity'), 0), 0) AS target,
           COALESCE(jnpa_num(md->>'outlook'), 0) AS outlook
) x;

-- port_overview_data cargo_cards: the five KPI cards, categories pivoted.
CREATE OR REPLACE VIEW jnpa_cargo_cards AS
WITH c AS (SELECT * FROM jnpa_clock),
tg AS (
    SELECT COALESCE(SUM(t.effective_target), 0) AS fy_target,
           COALESCE(SUM(t.effective_target) FILTER (WHERE t.month = c.month_abbr), 0) AS month_target
    FROM c LEFT JOIN jnpa_fy_targets t ON t.financial_year = c.fy_label
    GROUP BY c.month_abbr
),
cards(card, card_order, period) AS (VALUES ('today', 1, 'today'), ('yesterday', 2, 'yesterday'),
                                           ('current_month', 3, 'month'), ('current_fy', 4, 'fy'),
                                           ('all_time', 5, 'cumulative')),
p AS (
    SELECT period, SUM(qty) AS total,
           SUM(qty) FILTER (WHERE category = 'Edible Oil') AS edible_oil,
           SUM(qty) FILTER (WHERE category = 'Chemical') AS chemical,
           SUM(qty) FILTER (WHERE category = 'POL') AS pol,
           SUM(qty) FILTER (WHERE category = 'Other liquid') AS other_liquid
    FROM jnpa_cargo_throughput GROUP BY period
)
SELECT k.card, k.card_order,
       CASE k.card WHEN 'today' THEN 'Today' WHEN 'yesterday' THEN 'Yesterday'
                   WHEN 'current_month' THEN to_char(c.op_date, 'Mon YYYY')
                   WHEN 'current_fy' THEN 'FY ' || c.fy_label ELSE 'Cumulative' END AS label,
       round(p.total, 2) AS total_qty,
       round(p.edible_oil, 2) AS edible_oil, round(p.chemical, 2) AS chemical,
       round(p.pol, 2) AS pol, round(p.other_liquid, 2) AS other_liquid,
       t.target,
       CASE WHEN t.target > 0 THEN round(p.total / t.target * 100) END AS pct_achieved,
       CASE WHEN t.target > 0 THEN round(t.target - p.total, 2) END AS shortfall,
       CASE WHEN t.target > 0 THEN round(GREATEST(t.target - p.total, 0) / NULLIF(t.days_left, 0), 2) END AS required_daily
FROM cards k
JOIN p ON p.period = k.period
CROSS JOIN c CROSS JOIN tg
CROSS JOIN LATERAL (
    SELECT CASE k.card WHEN 'current_month' THEN tg.month_target WHEN 'current_fy' THEN tg.fy_target END AS target,
           CASE k.card WHEN 'current_month' THEN c.month_days_left WHEN 'current_fy' THEN c.fy_days_left END AS days_left
) t;

-- Parcels pumping right now on a berthed vessel, one row per pipeline they use.
CREATE OR REPLACE VIEW jnpa_pipeline_live AS
SELECT TRIM(x) AS pipeline_name, v.berth_name, p.vessel_name, p.vcn_id, p.parcel_op_id, p.parcel_no,
       p.cargo_name, p.avg_rate, p.remaining_qty
FROM jnpa_parcels p
JOIN jnpa_vessels_on_berth v ON v.vcn_id = p.vcn_id
CROSS JOIN LATERAL unnest(string_to_array(p.pipeline_name, ',')) x
WHERE p.state = 'Pumping' AND TRIM(x) <> '';

-- port_overview._pipelines: PLM01 + PLTM01 terminals, live use, month throughput, hydro test.
-- A parcel declared on two pipelines counts its full log on both (same as the dashboard).
CREATE OR REPLACE VIEW jnpa_pipelines AS
WITH c AS (SELECT * FROM jnpa_clock),
month_qty AS (
    SELECT s.pipe, SUM(l.quantity) AS qty
    FROM jnpa_parcel_log l
    CROSS JOIN c
    CROSS JOIN LATERAL (
        SELECT DISTINCT UPPER(TRIM(x)) AS pipe
        FROM jnpa_parcel_op_sources o, unnest(string_to_array(o.pipeline_name, ',')) x
        WHERE o.parcel_op_id = l.parcel_op_id AND TRIM(x) <> ''
    ) s
    WHERE NOT l.is_shortclose AND l.start_ts >= c.month_start
    GROUP BY s.pipe
),
live AS (
    SELECT UPPER(pipeline_name) AS pipe, COUNT(*) AS n,
           STRING_AGG(vessel_name || ' · ' || COALESCE(cargo_name, '') ||
                      CASE WHEN avg_rate > 0 THEN ' · ' || round(avg_rate) || ' MT/h' ELSE '' END, '; ') AS detail
    FROM jnpa_pipeline_live GROUP BY UPPER(pipeline_name)
),
term AS (
    SELECT m.pipeline_id, STRING_AGG(t.terminal_name, ', ' ORDER BY t.terminal_name) AS terminals
    FROM pipeline_terminal_mapping m JOIN terminal_master t ON t.id = m.terminal_id
    WHERE m.is_active IS NOT FALSE GROUP BY m.pipeline_id
)
SELECT p.id AS pipeline_id, p.pipeline_name, p.is_active IS NOT FALSE AS is_active,
       CASE WHEN COALESCE(lv.n, 0) > 0 THEN 'pumping' WHEN p.is_active IS NOT FALSE THEN 'idle' ELSE 'inactive' END AS state,
       COALESCE(lv.n, 0) AS live_parcels, lv.detail AS live_detail,
       COALESCE(tm.terminals, '') AS terminals,
       round(COALESCE(mq.qty, 0), 2) AS month_qty,
       (p.hydro_test_valid_until AT TIME ZONE 'Asia/Kolkata')::date AS hydro_test_valid_until,
       (p.hydro_test_valid_until AT TIME ZONE 'Asia/Kolkata')::date - c.op_date AS hydro_days_left,
       CASE WHEN p.hydro_test_valid_until IS NULL THEN NULL
            WHEN (p.hydro_test_valid_until AT TIME ZONE 'Asia/Kolkata')::date < c.op_date THEN 'expired'
            WHEN (p.hydro_test_valid_until AT TIME ZONE 'Asia/Kolkata')::date - c.op_date <= 30 THEN 'due'
            ELSE 'ok' END AS hydro_status
FROM pipeline_master p
CROSS JOIN c
LEFT JOIN term tm ON tm.pipeline_id = p.id
LEFT JOIN month_qty mq ON mq.pipe = UPPER(TRIM(p.pipeline_name))
LEFT JOIN live lv ON lv.pipe = UPPER(TRIM(p.pipeline_name));

-- port_overview._top_delays: delay-tagged log time in the current operational day.
CREATE OR REPLACE VIEW jnpa_delays_today AS
SELECT l.vessel_name, l.equipment_name, l.delay_name,
       CASE WHEN TRIM(COALESCE(l.vessel_name, '')) || TRIM(COALESCE(l.equipment_name, '')) = '' THEN l.delay_name
            ELSE concat_ws(' · ', NULLIF(TRIM(l.vessel_name), ''), NULLIF(TRIM(l.equipment_name), '')) || ' — ' || l.delay_name
       END AS label,
       floor(SUM(l.hours * 60))::int AS minutes
FROM jnpa_parcel_log l CROSS JOIN jnpa_clock c
WHERE l.delay_name IS NOT NULL AND l.start_ts >= c.op_day_start AND l.start_ts < c.now_ts
GROUP BY l.vessel_name, l.equipment_name, l.delay_name
HAVING floor(SUM(l.hours * 60)) > 0;

-- port_overview._tide: TM01 readings typed HW/LW against the next (else previous) reading.
-- The dashboard shows the first 6 rows with is_upcoming, ordered by tide_at.
CREATE OR REPLACE VIEW jnpa_tide AS
SELECT t.tide_at, round(t.m, 2) AS height_m,
       CASE WHEN t.m > COALESCE(LEAD(t.m) OVER w, LAG(t.m) OVER w, t.m) THEN 'HW' ELSE 'LW' END AS tide_type,
       t.tide_at >= c.now_ts AS is_upcoming
FROM (SELECT jnpa_ts(tide_datetime) AS tide_at, COALESCE(tide_meters, 0) AS m FROM tide_master) t
CROSS JOIN jnpa_clock c
WHERE t.tide_at IS NOT NULL
WINDOW w AS (ORDER BY t.tide_at);

-- weather_service.get_weather: WeatherAPI forecast.json payload; stale after 6 hours.
CREATE OR REPLACE VIEW jnpa_weather AS
SELECT w.cache_key, w.fetched_at, w.fetched_at >= c.now_ts - interval '6 hours' AS is_fresh,
       (w.data->'current'->>'temp_c')::numeric AS temp_c,
       (w.data->'current'->>'feelslike_c')::numeric AS feelslike_c,
       w.data->'current'->'condition'->>'text' AS condition_text,
       w.data->'current'->'condition'->>'icon' AS condition_icon,
       (w.data->'current'->>'wind_kph')::numeric AS wind_kph,
       w.data->'current'->>'wind_dir' AS wind_dir,
       (w.data->'current'->>'gust_kph')::numeric AS gust_kph,
       (w.data->'current'->>'humidity')::numeric AS humidity,
       (w.data->'current'->>'pressure_mb')::numeric AS pressure_mb,
       (w.data->'current'->>'vis_km')::numeric AS vis_km,
       w.data->'current'->>'last_updated' AS last_updated,
       w.data AS payload
FROM weather_cache w CROSS JOIN jnpa_clock c;

-- port_overview._shift_incharge: latest named shift in-charge logged today.
CREATE OR REPLACE VIEW jnpa_shift_incharge AS
SELECT l.shift_incharge, l.shift, l.entry_date
FROM lueu_parcel_log l CROSS JOIN jnpa_clock c
WHERE l.is_deleted IS NOT TRUE AND TRIM(COALESCE(l.shift_incharge, '')) <> ''
  AND l.entry_date >= to_char(c.op_date, 'YYYY-MM-DD')
ORDER BY l.entry_date DESC, l.id DESC
LIMIT 1;
"""


def upgrade() -> None:
    op.execute(FUNCTIONS_SQL)
    op.execute(VIEWS_SQL)


def downgrade() -> None:
    for v in ALL_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {v}")
    for f in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
