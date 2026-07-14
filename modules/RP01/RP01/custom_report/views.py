"""Custom Report Designer — drag-and-drop pivot over continuing datasets:
historical uploads (RP01 vessel-master / MIS history) extended with live rows
built from VCN01 (call + parcels), LDUD01 (SOF timings) and LUEU01 (actual
handled quantity). Each source's two legs share one column set so pivots span
the historical/live boundary seamlessly.

Sources:
  vessel-calls — one row per vessel call (mis_vessel_master + live VCN/LDUD)
  mis-history  — one row per customer/cargo parcel line (mis_history + live
                 VCN parcels; charge columns stay blank on live rows until
                 the billing rebuild feeds them)
"""
from flask import render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from datetime import date, datetime
from decimal import Decimal
import json

from .. import bp
from ..views import get_perms
from database import get_db, get_cursor


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _row_to_dict(row):
    out = {}
    for k, v in row.items():
        if isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif v is None:
            out[k] = ''
        else:
            out[k] = v
    return out


def _parse_dt(v):
    """Parse the app's mixed date-ish text formats; None when blank/unparseable."""
    s = str(v or '').strip()
    if not s:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _diff_days(row, col_from, col_to):
    a, b = _parse_dt(row.get(col_from)), _parse_dt(row.get(col_to))
    if not a or not b:
        return None
    d = (b - a).total_seconds() / 86400
    return round(d, 2) if d >= 0 else None


def _num(v):
    try:
        return float(str(v).replace(',', '')) if v not in (None, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fin_year_month(dt):
    """('2025-26', 'Jul-25') for a datetime, FY starting April."""
    fy = dt.year if dt.month >= 4 else dt.year - 1
    return f"{fy}-{str(fy + 1)[2:]}", dt.strftime('%b-%y')


# ── Data sources ─────────────────────────────────────────────────────────────

VALID_SOURCES = {'vessel-calls', 'mis-history'}

# Live-leg NOR: LDUD SOF NOR, falling back to the VCN nomination NOR / doc date.
_LIVE_NOR = "NULLIF(COALESCE(l.nor_tendered, v.nor_tendered::TEXT, v.doc_date), '')::TIMESTAMP"
# mis_history has no real date — place rows at the 1st of their JNPT month.
_HIST_MONTH = ("CASE WHEN month_jnpt ~ '^[A-Za-z]{3}-[0-9]{2}$' "
               "THEN TO_DATE(month_jnpt, 'Mon-YY')::TIMESTAMP END")

# date_col key → (historical leg expr, live leg expr); both yield TIMESTAMP/NULL
DATE_COL_FILTERS = {
    'vessel-calls': {
        'nor':              ("NULLIF(nor, '')::TIMESTAMP", _LIVE_NOR),
        'cargo_completion': ("NULLIF(cargo_completion, '')::TIMESTAMP",
                             "NULLIF(l.discharge_completed, '')::TIMESTAMP"),
    },
    'mis-history': {
        'period': (_HIST_MONTH, _LIVE_NOR),
    },
}
DATE_COL_DEFAULTS = {'vessel-calls': 'nor', 'mis-history': 'period'}

# Live-row turnaround KPIs, same column names the vessel-master sheet carries.
# Waiting/non-working splits need delay classification — left blank for live.
_KPI_DEFS = [
    ('Pre-Berthing Waiting (days)', 'NOR', 'First Line'),
    ('Stay at Berth (days)', 'First Line', 'Cast Off'),
    ('Arrive to Comm (days)', 'Alongside', 'Ops Commenced'),
    ('Working Time (days)', 'Ops Commenced', 'Cargo Completion'),
    ('Inward Movement (days)', 'Pilot Pick Up', 'First Line'),
    ('Outward Movement (days)', 'Cast Off', 'Pilot Disembarked'),
]


def _date_where(source, date_col, from_date, to_date):
    """(hist_clause, live_clause, params) for the chosen date column."""
    cols = DATE_COL_FILTERS[source]
    hist_expr, live_expr = cols.get(date_col) or cols[DATE_COL_DEFAULTS[source]]
    from_val = (from_date or '').replace('T', ' ') or '1900-01-01 00:00'
    to_val = (to_date or '').replace('T', ' ') or '2999-12-31 23:59'
    mk = lambda e: f"{e} IS NOT NULL AND {e} BETWEEN %s AND %s"
    return mk(hist_expr), mk(live_expr), (from_val, to_val)


# ── Main page ────────────────────────────────────────────────────────────────

@bp.route('/module/RP01/custom-report/')
@login_required
def custom_report_index():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('custom_report/custom_report.html',
                           username=session.get('username'))


# ── vessel-calls source ──────────────────────────────────────────────────────

def _vessel_calls_rows(cur, hist_where, live_where, params):
    cur.execute(f"""
        SELECT
            'Historical'                          AS "Source",
            COALESCE(fin_year, '')                AS "Fin Year",
            COALESCE(month, '')                   AS "Month",
            COALESCE(vcn_no, '')                  AS "VCN No",
            COALESCE(vessel_name, '')             AS "Vessel Name",
            COALESCE(berth_no, '')                AS "Berth No",
            COALESCE(overseas_coastal, '')        AS "Overseas/Coastal",
            COALESCE(foreign_indian, '')          AS "F/I",
            COALESCE(imo_no, '')                  AS "IMO No",
            COALESCE(flag, '')                    AS "Flag",
            COALESCE(bhc, '')                     AS "BHC",
            COALESCE(port_code, '')               AS "Port Code",
            COALESCE(port_of_loading, '')         AS "Port of Loading",
            grt::float8                           AS "GRT",
            draft::float8                         AS "Draft",
            loa::float8                           AS "LOA",
            COALESCE(import_export, '')           AS "Import/Export",
            COALESCE(agent, '')                   AS "Agent",
            COALESCE(consigner, '')               AS "Consigner",
            COALESCE(unload_pipeline, '')         AS "Unload Pipeline",
            COALESCE(unloading_terminal, '')      AS "Unloading Terminal",
            COALESCE(new_cat, '')                 AS "New Cat",
            COALESCE(category1, '')               AS "Category-1",
            COALESCE(category, '')                AS "Category",
            COALESCE(cargo, '')                   AS "Cargo",
            quantity::float8                      AS "Quantity MT",
            flow_rate::float8                     AS "Flow Rate (MT/hr)",
            COALESCE(nor, '')                     AS "NOR",
            COALESCE(anchorage_time, '')          AS "Anchorage Time",
            COALESCE(pilot_pickup, '')            AS "Pilot Pick Up",
            COALESCE(first_line, '')              AS "First Line",
            COALESCE(alongside, '')               AS "Alongside",
            COALESCE(ops_commenced, '')           AS "Ops Commenced",
            COALESCE(cargo_completion, '')        AS "Cargo Completion",
            COALESCE(sail_cast_off, '')           AS "Sail Cast Off",
            COALESCE(cast_off, '')                AS "Cast Off",
            COALESCE(pilot_board_departure, '')   AS "Pilot Board Departure",
            COALESCE(pilot_disembarked, '')       AS "Pilot Disembarked",
            pre_berthing_waiting::float8          AS "Pre-Berthing Waiting (days)",
            waiting_port::float8                  AS "Waiting Port (days)",
            waiting_non_port::float8              AS "Waiting Non-Port (days)",
            stay_at_berth::float8                 AS "Stay at Berth (days)",
            arrive_to_comm::float8                AS "Arrive to Comm (days)",
            working_time::float8                  AS "Working Time (days)",
            non_working_total::float8             AS "Non-Working Total (days)",
            non_working_port::float8              AS "Non-Working Port (days)",
            non_working_non_port::float8          AS "Non-Working Non-Port (days)",
            inward_movement::float8               AS "Inward Movement (days)",
            outward_movement::float8              AS "Outward Movement (days)",
            ''                                    AS "Status",
            COALESCE(remarks, '')                 AS "Remarks",
            ''                                    AS "_doc_date"
        FROM mis_vessel_master
        WHERE {hist_where}
        ORDER BY id
        LIMIT 100000
    """, params)
    rows = [_row_to_dict(r) for r in cur.fetchall()]

    cur.execute(f"""
        SELECT
            'Live'                                              AS "Source",
            ''                                                  AS "Fin Year",
            ''                                                  AS "Month",
            COALESCE(v.vcn_doc_num, '')                         AS "VCN No",
            COALESCE(v.vessel_name, '')                         AS "Vessel Name",
            COALESCE(v.berth_name, '')                          AS "Berth No",
            COALESCE(v.vessel_run_type, '')                     AS "Overseas/Coastal",
            CASE WHEN vm.nationality ILIKE 'ind%%' THEN 'I'
                 WHEN vm.nationality IS NOT NULL   THEN 'F'
                 ELSE '' END                                    AS "F/I",
            COALESCE(vm.imo_num, '')                            AS "IMO No",
            COALESCE(vm.nationality, '')                        AS "Flag",
            ''                                                  AS "BHC",
            ''                                                  AS "Port Code",
            COALESCE(v.load_port, '')                           AS "Port of Loading",
            vm.gt::float8                                       AS "GRT",
            v.draft::float8                                     AS "Draft",
            v.loa::float8                                       AS "LOA",
            COALESCE(v.operation_type, '')                      AS "Import/Export",
            COALESCE(v.vessel_agent_name, '')                   AS "Agent",
            COALESCE(p.consigners, '')                          AS "Consigner",
            COALESCE(p.pipelines, '')                           AS "Unload Pipeline",
            COALESCE(p.terminals, '')                           AS "Unloading Terminal",
            COALESCE(p.new_cat, '')                             AS "New Cat",
            COALESCE(p.category1, '')                           AS "Category-1",
            COALESCE(p.category, '')                            AS "Category",
            COALESCE(p.cargoes, v.cargo_type, '')               AS "Cargo",
            COALESCE(lu.qty, 0)::float8                         AS "Quantity MT",
            NULL::float8                                        AS "Flow Rate (MT/hr)",
            COALESCE(l.nor_tendered, v.nor_tendered::TEXT, '')  AS "NOR",
            COALESCE(l.anchored_datetime, '')                   AS "Anchorage Time",
            COALESCE(l.pilot_pickup_time, '')                   AS "Pilot Pick Up",
            COALESCE(l.first_line, '')                          AS "First Line",
            COALESCE(l.alongside_datetime, '')                  AS "Alongside",
            COALESCE(l.discharge_commenced, '')                 AS "Ops Commenced",
            COALESCE(l.discharge_completed, '')                 AS "Cargo Completion",
            ''                                                  AS "Sail Cast Off",
            COALESCE(l.cast_off_datetime, '')                   AS "Cast Off",
            COALESCE(l.pilot_board_departure, '')               AS "Pilot Board Departure",
            COALESCE(l.pilot_disembarked, '')                   AS "Pilot Disembarked",
            NULL::float8 AS "Pre-Berthing Waiting (days)",
            NULL::float8 AS "Waiting Port (days)",
            NULL::float8 AS "Waiting Non-Port (days)",
            NULL::float8 AS "Stay at Berth (days)",
            NULL::float8 AS "Arrive to Comm (days)",
            NULL::float8 AS "Working Time (days)",
            NULL::float8 AS "Non-Working Total (days)",
            NULL::float8 AS "Non-Working Port (days)",
            NULL::float8 AS "Non-Working Non-Port (days)",
            NULL::float8 AS "Inward Movement (days)",
            NULL::float8 AS "Outward Movement (days)",
            COALESCE(l.doc_status, v.doc_status, '')            AS "Status",
            COALESCE(v.remarks, '')                             AS "Remarks",
            COALESCE(v.doc_date, '')                            AS "_doc_date"
        FROM vcn_header v
        LEFT JOIN ldud_header l ON l.vcn_id = v.id
        LEFT JOIN vessels vm ON vm.doc_num = SPLIT_PART(v.vessel_master_doc, '/', 1)
        LEFT JOIN LATERAL (
            SELECT STRING_AGG(DISTINCT pr.cargo_name, ', ')          AS cargoes,
                   STRING_AGG(DISTINCT pr.consigner_name, ', ')      AS consigners,
                   STRING_AGG(DISTINCT pr.unload_terminal, ', ')     AS terminals,
                   STRING_AGG(DISTINCT pr.pipeline_name, ', ')       AS pipelines,
                   STRING_AGG(DISTINCT vc.cargo_type, ', ')          AS new_cat,
                   STRING_AGG(DISTINCT vc.cargo_sub_category, ', ')  AS category1,
                   STRING_AGG(DISTINCT vc.cargo_category, ', ')      AS category
            FROM (
                SELECT cargo_name, consigner_name, unload_terminal, pipeline_name
                FROM vcn_consigners WHERE vcn_id = v.id
                UNION ALL
                SELECT cargo_name, consigner_name, unload_terminal, pipeline_name
                FROM vcn_export_cargo_declaration WHERE vcn_id = v.id
            ) pr
            LEFT JOIN vessel_cargo vc ON vc.cargo_name = TRIM(pr.cargo_name)
        ) p ON TRUE
        LEFT JOIN LATERAL (
            SELECT ROUND(SUM(CASE WHEN COALESCE(lg.is_shortclose, FALSE)
                                  THEN 0 ELSE lg.quantity END), 3) AS qty
            FROM lueu_parcel_log lg
            JOIN ldud_parcel_ops po ON po.id = lg.parcel_op_id
            WHERE po.ldud_id = l.id AND lg.is_deleted IS NOT TRUE
        ) lu ON TRUE
        WHERE {live_where}
        ORDER BY v.id DESC
        LIMIT 100000
    """, params)
    live_rows = [_row_to_dict(r) for r in cur.fetchall()]

    # Live rows: derive FY/Month, turnaround KPI days and avg flow rate so they
    # line up with the columns the historical sheet already carries.
    for r in live_rows:
        dt = _parse_dt(r['NOR']) or _parse_dt(r['_doc_date'])
        if dt:
            r['Fin Year'], r['Month'] = _fin_year_month(dt)
        for col, c_from, c_to in _KPI_DEFS:
            d = _diff_days(r, c_from, c_to)
            r[col] = d if d is not None else ''
        wt = _diff_days(r, 'Ops Commenced', 'Cargo Completion')
        qty = r['Quantity MT'] or 0
        r['Flow Rate (MT/hr)'] = round(qty / (wt * 24), 1) if wt and qty else ''

    rows += live_rows
    for r in rows:
        base = r['NOR'] or r['_doc_date']
        r['Year'] = base[:4]
        r['Year-Month'] = base[:7]
        del r['_doc_date']
    return rows


# ── mis-history source ───────────────────────────────────────────────────────

def _parcel_actual_qty(cur, ldud_ids, declared):
    """{(ldud_id, parcel_id): LUEU actual MT}. Non-deleted, non-shortclose log
    quantity per parcel-op; ops merging several parcels are split by declared-
    quantity share (equal split when the declared total is unknown)."""
    if not ldud_ids:
        return {}
    cur.execute('''
        SELECT po.ldud_id, po.parcel_ids,
               COALESCE(SUM(CASE WHEN COALESCE(lg.is_shortclose, FALSE) THEN 0
                                 ELSE lg.quantity END)
                        FILTER (WHERE lg.is_deleted IS NOT TRUE), 0) AS logged
        FROM ldud_parcel_ops po
        LEFT JOIN lueu_parcel_log lg ON lg.parcel_op_id = po.id
        WHERE po.ldud_id = ANY(%s)
        GROUP BY po.id
    ''', (ldud_ids,))
    out = {}
    for r in cur.fetchall():
        ids = [int(x) for x in str(r['parcel_ids'] or '').split(',') if x.strip().isdigit()]
        logged = float(r['logged'] or 0)
        if not ids or not logged:
            continue
        shares = [declared.get((r['ldud_id'], i), 0.0) for i in ids]
        total = sum(shares)
        for i, s in zip(ids, shares):
            part = logged * (s / total) if total > 0 else logged / len(ids)
            key = (r['ldud_id'], i)
            out[key] = out.get(key, 0.0) + part
    return out


def _mis_history_rows(cur, hist_where, live_where, params):
    cur.execute(f"""
        SELECT
            'Historical'                          AS "Source",
            COALESCE(fin_year, '')                AS "Fin Year",
            COALESCE(month_jsw, '')               AS "Month JSW",
            COALESCE(month_jnpt, '')              AS "Month JNPT",
            COALESCE(vcn_no, '')                  AS "VCN No",
            COALESCE(vessel_name, '')             AS "Vessel Name",
            ''                                    AS "Parcel No",
            COALESCE(customer, '')                AS "Customer",
            COALESCE(payment_by, '')              AS "Payment By",
            COALESCE(importer, '')                AS "Importer",
            COALESCE(cargo_type, '')              AS "Cargo Type",
            COALESCE(cargo_category, '')          AS "Cargo Category",
            COALESCE(cargo_category_2, '')        AS "Cargo Category 2",
            COALESCE(cargo_sub_category, '')      AS "Cargo Sub Category",
            COALESCE(cargo_sub_category_2, '')    AS "Cargo Sub Category 2",
            COALESCE(cargo_name, '')              AS "Cargo Name",
            COALESCE(terminal, '')                AS "Terminal",
            quantity::float8                      AS "Quantity MT",
            COALESCE(overseas_coastal, '')        AS "Overseas/Coastal",
            COALESCE(import_export, '')           AS "Import/Export",
            cargo_rate::float8                    AS "Cargo Handling Rate",
            cargo_amount::float8                  AS "Cargo Handling Amount",
            infra_rate::float8                    AS "Infra & Misc Rate",
            infra_amount::float8                  AS "Infra & Misc Amount",
            toll_rate::float8                     AS "Toll Rate",
            toll_amount::float8                   AS "Toll Amount",
            COALESCE(gangway_agent, '')           AS "Gangway Agent",
            gangway_amount::float8                AS "Gangway Amount",
            mla_rate::float8                      AS "MLA Rate",
            mla_amount::float8                    AS "MLA Amount",
            ''                                    AS "Status",
            COALESCE(remarks, '')                 AS "Remarks"
        FROM mis_history
        WHERE {hist_where}
        ORDER BY id
        LIMIT 100000
    """, params)
    rows = [_row_to_dict(r) for r in cur.fetchall()]
    for r in rows:
        dt = _parse_dt_month(r['Month JNPT']) or _parse_dt_month(r['Month JSW'])
        r['Year'] = dt.strftime('%Y') if dt else ''
        r['Year-Month'] = dt.strftime('%Y-%m') if dt else ''

    # Live leg: one row per VCN parcel (import consigners + export declarations)
    cur.execute(f"""
        SELECT
            v.vcn_doc_num, v.vessel_name, v.vessel_run_type, v.operation_type,
            v.doc_date, v.doc_status AS vcn_status,
            l.id AS ldud_id, l.nor_tendered, l.doc_status AS ldud_status,
            p.id AS parcel_id, p.parcel_no, p.cargo_name, p.consigner_name,
            p.importer_name, p.unload_terminal, p.quantity AS declared_qty,
            vc.cargo_type, vc.cargo_category, vc.cargo_category_2,
            vc.cargo_sub_category, vc.cargo_sub_category_2
        FROM vcn_header v
        JOIN (
            SELECT vcn_id, id, parcel_no, cargo_name, consigner_name,
                   importer_name, unload_terminal, quantity
            FROM vcn_consigners
            UNION ALL
            SELECT vcn_id, id, parcel_no, cargo_name, consigner_name,
                   importer_name, unload_terminal, quantity
            FROM vcn_export_cargo_declaration
        ) p ON p.vcn_id = v.id
        LEFT JOIN ldud_header l ON l.vcn_id = v.id
        LEFT JOIN LATERAL (
            SELECT cargo_type, cargo_category, cargo_category_2,
                   cargo_sub_category, cargo_sub_category_2
            FROM vessel_cargo WHERE cargo_name = TRIM(p.cargo_name) LIMIT 1
        ) vc ON TRUE
        WHERE {live_where}
        ORDER BY v.id DESC, p.id
        LIMIT 100000
    """, params)
    parcels = [dict(r) for r in cur.fetchall()]

    # Actual handled qty per parcel from the LUEU01 logbook
    declared = {(p['ldud_id'], p['parcel_id']): _num(p['declared_qty'])
                for p in parcels if p['ldud_id']}
    ldud_ids = sorted({p['ldud_id'] for p in parcels if p['ldud_id']})
    actual = _parcel_actual_qty(cur, ldud_ids, declared)

    for p in parcels:
        dt = _parse_dt(p['nor_tendered']) or _parse_dt(p['doc_date'])
        fin_year, month = _fin_year_month(dt) if dt else ('', '')
        rows.append({
            'Source': 'Live',
            'Fin Year': fin_year,
            'Month JSW': month,
            'Month JNPT': month,
            'VCN No': p['vcn_doc_num'] or '',
            'Vessel Name': p['vessel_name'] or '',
            'Parcel No': p['parcel_no'] or '',
            'Customer': p['consigner_name'] or '',
            'Payment By': p['importer_name'] or '',
            'Importer': p['importer_name'] or '',
            'Cargo Type': p['cargo_type'] or '',
            'Cargo Category': p['cargo_category'] or '',
            'Cargo Category 2': p['cargo_category_2'] or '',
            'Cargo Sub Category': p['cargo_sub_category'] or '',
            'Cargo Sub Category 2': p['cargo_sub_category_2'] or '',
            'Cargo Name': p['cargo_name'] or '',
            'Terminal': p['unload_terminal'] or '',
            'Quantity MT': round(actual.get((p['ldud_id'], p['parcel_id']), 0.0), 3),
            'Overseas/Coastal': p['vessel_run_type'] or '',
            'Import/Export': p['operation_type'] or '',
            'Cargo Handling Rate': '',
            'Cargo Handling Amount': '',
            'Infra & Misc Rate': '',
            'Infra & Misc Amount': '',
            'Toll Rate': '',
            'Toll Amount': '',
            'Gangway Agent': '',
            'Gangway Amount': '',
            'MLA Rate': '',
            'MLA Amount': '',
            'Status': p['ldud_status'] or p['vcn_status'] or '',
            'Remarks': '',
            'Year': dt.strftime('%Y') if dt else '',
            'Year-Month': dt.strftime('%Y-%m') if dt else '',
        })
    return rows


def _parse_dt_month(v):
    """'Nov-24' → datetime(2024, 11, 1); None when blank/unparseable."""
    try:
        return datetime.strptime(str(v or '').strip(), '%b-%y')
    except ValueError:
        return None


# ── Pivot data endpoint ──────────────────────────────────────────────────────

@bp.route('/api/module/RP01/pivot/data/<source>')
@login_required
def pivot_data(source):
    if source not in VALID_SOURCES:
        return jsonify({'error': 'Unknown data source'}), 400

    today = date.today()
    # default: from previous FY start, so the pivot spans the historical/live seam
    fy = today.year - 1 if today.month >= 4 else today.year - 2
    from_date = request.args.get('from_date', f'{fy}-04-01T00:00')
    to_date = request.args.get('to_date', today.strftime('%Y-%m-%dT23:59'))
    date_col = request.args.get('date_col', DATE_COL_DEFAULTS[source])
    hist_where, live_where, params = _date_where(source, date_col, from_date, to_date)

    conn = get_db()
    cur = get_cursor(conn)
    try:
        if source == 'vessel-calls':
            rows = _vessel_calls_rows(cur, hist_where, live_where, params)
        else:
            rows = _mis_history_rows(cur, hist_where, live_where, params)
    finally:
        conn.close()
    return jsonify(rows)


# ── Saved reports CRUD ───────────────────────────────────────────────────────

@bp.route('/api/module/RP01/pivot/saved-reports', methods=['GET'])
@login_required
def saved_reports_list():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("""
        SELECT id, name, description, data_source, config, created_at
        FROM saved_pivot_reports
        ORDER BY updated_at DESC
    """)
    rows = [_row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/api/module/RP01/pivot/saved-reports', methods=['POST'])
@login_required
def saved_reports_create():
    body = request.get_json(force=True) or {}
    name = (body.get('name') or '').strip()
    description = (body.get('description') or '').strip()
    data_source = (body.get('data_source') or '').strip()
    config = body.get('config', {})

    if not name or data_source not in VALID_SOURCES:
        return jsonify({'error': 'name and valid data_source are required'}), 400

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("""
        INSERT INTO saved_pivot_reports (name, description, data_source, config, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (name, description, data_source, json.dumps(config), session.get('user_id')))
    new_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': new_id, 'name': name}), 201


@bp.route('/api/module/RP01/pivot/saved-reports/<int:report_id>', methods=['PUT'])
@login_required
def saved_reports_update(report_id):
    body = request.get_json(force=True) or {}
    name = (body.get('name') or '').strip()
    description = (body.get('description') or '').strip()
    config = body.get('config', {})

    if not name:
        return jsonify({'error': 'name is required'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE saved_pivot_reports
        SET name = %s, description = %s, config = %s, updated_at = NOW()
        WHERE id = %s
    """, (name, description, json.dumps(config), report_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@bp.route('/api/module/RP01/pivot/saved-reports/<int:report_id>', methods=['DELETE'])
@login_required
def saved_reports_delete(report_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM saved_pivot_reports WHERE id = %s", (report_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})
