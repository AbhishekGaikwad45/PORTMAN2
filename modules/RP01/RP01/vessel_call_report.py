"""Vessel Call Report — the legacy Vessel Call Master and the live system in one sheet.

The two sources do not overlap in time: the uploaded master covers vessel calls up
to the go-live cut-off, the system covers everything after it. So this is a UNION,
not a join — same columns, master rows first, then actual rows. A 'Source' column
says which side a row came from.

Actual rows come from VCN01 (vcn_header + parcels) + LDUD01 (SOF timings, parcel
ops) + VC01 (vessels). Every VCN vessel is listed whatever its state — the LDUD
join is outer, so a call with no LDUD yet still gets a row with its timings blank.
The VCN Status / LDUD Status columns say how far along each one is.
"""
from flask import render_template, session, redirect, url_for, jsonify
from functools import wraps

import excel_export
from . import bp
from database import get_db, get_cursor

MODULE_CODE = 'RP01'

# Reported for information on the summary chips only — the sheet itself lists
# every VCN vessel regardless of status.
CLOSED_STATUSES = ('Closed', 'Partial Close')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────────────────────────
#  Column spec — Vessel Call Master order, so the sheet reads like the
#  one the users already know. 'dt:' fields split into Date + Time.
#  Master-only and system-only columns stay blank on the other side.
# ──────────────────────────────────────────────────────────────────
COLS = [
    ('Sr No',                   'sr_no'),
    ('Source',                  'source'),
    ('Fin Year',                'fin_year'),
    ('Month JSW',               'month_jsw'),
    ('Month JNPT',              'month_jnpt'),
    ('Berth No',                'berth_no'),
    ('VCN No',                  'vcn_no'),
    ('Vessel Name',             'vessel_name'),
    ('Overseas/Coastal',        'overseas_coastal'),
    ('F/I',                     'foreign_indian'),
    ('IMO No',                  'imo_no'),
    ('Flag',                    'flag'),
    ('Port Code',               'port_code'),
    ('Port of Loading',         'port_of_loading'),
    ('GRT',                     'grt'),
    ('Draft',                   'draft'),
    ('LOA',                     'loa'),
    ('Import/Export',           'import_export'),
    ('Agent',                   'agent'),
    ('Unload Pipeline',         'unload_pipeline'),
    ('Consigner',               'consigner'),
    ('Unloading Terminal',      'unloading_terminal'),
    ('New Cat',                 'new_cat'),
    ('Category-1',              'category1'),
    ('Category',                'category'),
    ('Cargo',                   'cargo'),
    ('NOR',                     'nor'),
    ('Anchorage Time',          'anchorage_time'),
    ('Pilot Pick Up',           'pilot_pickup'),
    ('First Line',              'first_line'),
    ('Alongside',               'alongside'),
    ('Ops Commenced',           'ops_commenced'),
    ('Cargo Completion',        'cargo_completion'),
    ('Sail Cast Off',           'sail_cast_off'),        # actual rows report cast off here
    ('Cast Off',                'cast_off'),             # master only
    ('Pilot Board Departure',   'pilot_board_departure'),
    ('Pilot Disembarked',       'pilot_disembarked'),
    ('Quantity MT',             'quantity'),
    ('Declared Qty MT',         'declared_qty'),         # actual rows only
    ('Short-Closed MT',         'shortclose_qty'),       # actual rows only
    ('Flow Rate (MT/hr)',       'flow_rate'),
    ('Remarks',                 'remarks'),
    ('PORTMAN VCN Doc',         'vcn_doc_num'),          # actual rows only
    ('VCN Status',              'vcn_status'),           # actual rows only
    ('LDUD Doc',                'ldud_doc_num'),         # actual rows only
    ('LDUD Status',             'ldud_status'),          # actual rows only
]

# Timings are stored 'YYYY-MM-DDTHH:MM' on both sides and reported as one
# merged 'DD-MM-YYYY HH:MM' cell, the way the legacy sheet shows them.
_TIME_COLS = ('nor', 'anchorage_time', 'pilot_pickup', 'first_line', 'alongside',
              'ops_commenced', 'cargo_completion', 'sail_cast_off', 'cast_off',
              'pilot_board_departure', 'pilot_disembarked')


def _datetime_cell(val):
    date, time = excel_export.split_datetime(val)
    return ' '.join(p for p in (date, time) if p) or None


# Day-count KPIs (pre-berthing waiting, stay at berth, working time, …) are
# deliberately out: the system stores none of them and the derived-vs-stored
# comparison was descoped. ponytail: add them to COLS + a derive step when asked.


def _fin_year(vcn_doc_num, doc_date):
    """'2025-26' from a PORTMAN doc number 'VCN-2526-001', else from doc_date
    (FY starts in April)."""
    parts = str(vcn_doc_num or '').split('-')
    if len(parts) >= 2 and len(parts[1]) == 4 and parts[1].isdigit():
        return f'20{parts[1][:2]}-{parts[1][2:]}'
    d = str(doc_date or '')
    if len(d) >= 7 and d[:4].isdigit() and d[5:7].isdigit():
        year, month = int(d[:4]), int(d[5:7])
        start = year if month >= 4 else year - 1
        return f'{start}-{str(start + 1)[2:]}'
    return ''


def _vcn_seq(vcn_doc_num):
    """Sr No for a system row: the running number out of 'VCN-2627-199'.

    PORTMAN's VCN numbering was seeded to carry on from the last master row, so
    these continue the master's Sr No instead of restarting at 1.
    ponytail: VCN01 restarts that counter every financial year, so next FY these
    will collide with the master's low numbers — switch to a global running
    number here if that becomes a problem.
    """
    parts = str(vcn_doc_num or '').split('-')
    return int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None


_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def _month(*candidates):
    """'Nov-24' from the first usable 'YYYY-MM-DD…' string given."""
    for v in candidates:
        d = str(v or '')
        if len(d) >= 7 and d[:4].isdigit() and d[5:7].isdigit():
            m = int(d[5:7])
            if 1 <= m <= 12:
                return f'{_MONTHS[m - 1]}-{d[2:4]}'
    return ''


# ──────────────────────────────────────────────────────────────────
#  Source 1: the uploaded Vessel Call Master.
#  Month JSW / Month JNPT are per-parcel in the MIS history sheet — take them
#  from there by VCN No, falling back to the master's own single Month.
# ──────────────────────────────────────────────────────────────────
_MASTER_SQL = '''
    SELECT m.sr_no, 'Master' AS source, m.fin_year,
           COALESCE(h.month_jsw,  m.month) AS month_jsw,
           COALESCE(h.month_jnpt, m.month) AS month_jnpt,
           m.berth_no, m.vcn_no, m.vessel_name, m.overseas_coastal, m.foreign_indian,
           m.imo_no, m.flag, m.port_code, m.port_of_loading, m.grt, m.draft, m.loa,
           m.import_export, m.agent, m.unload_pipeline, m.consigner, m.unloading_terminal,
           m.new_cat, m.category1, m.category, m.cargo,
           m.nor, m.anchorage_time, m.pilot_pickup, m.first_line, m.alongside,
           m.ops_commenced, m.cargo_completion, m.sail_cast_off, m.cast_off,
           m.pilot_board_departure, m.pilot_disembarked,
           m.quantity, m.flow_rate, m.remarks
    FROM mis_vessel_master m
    LEFT JOIN (SELECT vcn_no, MAX(month_jsw) AS month_jsw, MAX(month_jnpt) AS month_jnpt
               FROM mis_history GROUP BY vcn_no) h ON h.vcn_no = m.vcn_no
    ORDER BY m.sr_no NULLS LAST, m.id
'''

# ──────────────────────────────────────────────────────────────────
#  Source 2: the live system.
#  Parcels: import lives in vcn_consigners, export in vcn_export_cargo_declaration
#  — same shape, so union them. Quantity is TEXT on both ('12,000.000').
#  Ops start/end are owned by LUEU01 on ldud_parcel_ops; the legacy
#  ldud_header.discharge_commenced/_completed died with the parcel migration.
#  Timings are TEXT 'YYYY-MM-DDTHH:MM', so MIN/MAX sort correctly as text.
# ──────────────────────────────────────────────────────────────────
_ACTUAL_SQL = f'''
    WITH parcels AS (
        SELECT vcn_id, cargo_name, consigner_name, unload_terminal, pipeline_name,
               NULLIF(regexp_replace(COALESCE(quantity, ''), '[^0-9.]', '', 'g'), '')::numeric AS qty
        FROM vcn_consigners
        UNION ALL
        SELECT vcn_id, cargo_name, consigner_name, unload_terminal, pipeline_name,
               NULLIF(regexp_replace(COALESCE(quantity, ''), '[^0-9.]', '', 'g'), '')::numeric
        FROM vcn_export_cargo_declaration
    ),
    pagg AS (
        SELECT p.vcn_id,
               SUM(p.qty)                                    AS declared_qty,
               string_agg(DISTINCT p.cargo_name,      ', ')   AS cargo,
               string_agg(DISTINCT p.consigner_name,  ', ')   AS consigner,
               string_agg(DISTINCT p.unload_terminal, ', ')   AS unloading_terminal,
               string_agg(DISTINCT p.pipeline_name,   ', ')   AS unload_pipeline,
               string_agg(DISTINCT c.cargo_type,       ', ')  AS new_cat,
               string_agg(DISTINCT c.cargo_category_2, ', ')  AS category1,
               string_agg(DISTINCT c.cargo_category,   ', ')  AS category
        FROM parcels p
        LEFT JOIN vessel_cargo c ON c.cargo_name = p.cargo_name
        GROUP BY p.vcn_id
    ),
    ops AS (
        SELECT ldud_id,
               MIN(NULLIF(start_dt, '')) AS ops_commenced,
               MAX(NULLIF(end_dt, ''))   AS cargo_completion
        FROM ldud_parcel_ops GROUP BY ldud_id
    ),
    act AS (
        SELECT po.ldud_id,
               SUM(CASE WHEN COALESCE(lg.is_shortclose, FALSE) THEN 0 ELSE lg.quantity END) AS actual_qty,
               SUM(CASE WHEN COALESCE(lg.is_shortclose, FALSE) THEN lg.quantity ELSE 0 END) AS shortclose_qty
        FROM lueu_parcel_log lg
        JOIN ldud_parcel_ops po ON po.id = lg.parcel_op_id
        WHERE lg.is_deleted IS NOT TRUE
        GROUP BY po.ldud_id
    )
    SELECT 'Actual' AS source,
           v.vcn_doc_num, v.doc_date, v.doc_status AS vcn_status,
           l.doc_num AS ldud_doc_num, l.doc_status AS ldud_status,
           v.berth_name       AS berth_no,
           v.via_number       AS vcn_no,
           v.vessel_name,
           v.vessel_run_type  AS overseas_coastal,
           ves.imo_num        AS imo_no,
           ves.nationality    AS flag,
           v.load_port        AS port_of_loading,
           ves.gt             AS grt,
           v.draft,
           COALESCE(v.loa, ves.loa) AS loa,
           v.operation_type   AS import_export,
           v.vessel_agent_name AS agent,
           pagg.unload_pipeline, pagg.consigner, pagg.unloading_terminal,
           pagg.new_cat, pagg.category1, pagg.category,
           COALESCE(pagg.cargo, v.cargo_type) AS cargo,
           l.nor_tendered         AS nor,
           l.anchored_datetime    AS anchorage_time,
           l.pilot_pickup_time    AS pilot_pickup,
           l.first_line,
           l.alongside_datetime   AS alongside,
           ops.ops_commenced, ops.cargo_completion,
           -- The system's single cast off is reported as Sail Cast Off; the plain
           -- Cast Off column stays blank on actual rows (master rows carry both).
           l.cast_off_datetime    AS sail_cast_off,
           l.pilot_board_departure, l.pilot_disembarked,
           act.actual_qty, act.shortclose_qty, pagg.declared_qty
    FROM vcn_header v
    LEFT JOIN ldud_header l ON l.vcn_id = v.id AND l.is_deleted IS NOT TRUE
    LEFT JOIN vessels ves ON ves.doc_num = split_part(COALESCE(v.vessel_master_doc, ''), '/', 1)
    LEFT JOIN pagg ON pagg.vcn_id = v.id
    LEFT JOIN ops  ON ops.ldud_id = l.id
    LEFT JOIN act  ON act.ldud_id = l.id
    ORDER BY v.vcn_doc_num
'''


# Terminal / pipeline / equipment are themselves comma-separated multi-value
# cells ('P1, P2'), so aggregating them across parcels double-lists the shared
# ones ('P1' + 'P1, P2' -> 'P1, P1, P2'). Split and dedupe on the way out.
_MULTI_COLS = ('consigner', 'unloading_terminal', 'unload_pipeline',
               'cargo', 'new_cat', 'category1', 'category')


def _dedupe_csv(val):
    seen = []
    for part in str(val or '').split(','):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return ', '.join(seen) or None


def _hours(start, end):
    """Whole hours between two 'YYYY-MM-DDTHH:MM' strings; None if unusable."""
    from datetime import datetime
    try:
        a = datetime.strptime(str(start)[:16], '%Y-%m-%dT%H:%M')
        b = datetime.strptime(str(end)[:16], '%Y-%m-%dT%H:%M')
    except (ValueError, TypeError):
        return None
    secs = (b - a).total_seconds()
    return secs / 3600 if secs > 0 else None


def report_rows():
    """Master rows then actual rows, both shaped to COLS."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(_MASTER_SQL)
    rows = [dict(r) for r in cur.fetchall()]
    cur.execute(_ACTUAL_SQL)
    actuals = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in actuals:
        for col in _MULTI_COLS:
            r[col] = _dedupe_csv(r.get(col))
        r['sr_no'] = _vcn_seq(r.get('vcn_doc_num'))
        r['fin_year'] = _fin_year(r.get('vcn_doc_num'), r.get('doc_date'))
        # ponytail: both months off the same anchor (cargo completion → alongside →
        # VCN doc date). The real JSW/JNPT cut-off rule differs; change here when known.
        month = _month(r.get('cargo_completion'), r.get('alongside'), r.get('doc_date'))
        r['month_jsw'] = r['month_jnpt'] = month
        # Reported quantity is what was actually handled; fall back to the declared
        # parcel total when nothing has been logged in LUEU01.
        qty = r.pop('actual_qty', None)
        r['quantity'] = qty if qty is not None else r.get('declared_qty')
        hrs = _hours(r.get('ops_commenced'), r.get('cargo_completion'))
        r['flow_rate'] = round(float(r['quantity']) / hrs, 2) if (hrs and r.get('quantity')) else None
        r.pop('doc_date', None)

    rows += actuals
    # Last — _month/_hours above read the raw ISO values.
    for r in rows:
        for col in _TIME_COLS:
            r[col] = _datetime_cell(r.get(col))
    return rows


@bp.route('/module/RP01/vessel-call-report/')
@login_required
def vcr_page():
    from database import get_user_permissions
    perms = ({'can_read': 1} if session.get('is_admin')
             else get_user_permissions(session.get('user_id'), MODULE_CODE))
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('vessel_call_report.html')


@bp.route('/api/module/RP01/vessel-call-report/summary')
@login_required
def vcr_summary():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT COUNT(*) AS c FROM mis_vessel_master')
    master = cur.fetchone()['c']
    cur.execute('SELECT COUNT(*) AS c FROM vcn_header')
    actual = cur.fetchone()['c']
    cur.execute('''SELECT COUNT(*) AS c FROM ldud_header l JOIN vcn_header v ON v.id = l.vcn_id
                   WHERE l.is_deleted IS NOT TRUE AND l.doc_status IN %s''', (CLOSED_STATUSES,))
    closed = cur.fetchone()['c']
    conn.close()
    return jsonify({'master_rows': master, 'actual_rows': actual, 'closed_rows': closed,
                    'total': master + actual, 'columns': len(excel_export.headers(COLS))})


@bp.route('/api/module/RP01/vessel-call-report/export')
@login_required
def vcr_export():
    return excel_export.sheet_response(COLS, report_rows(), 'Vessel Calls', 'Vessel_Call_Report')
