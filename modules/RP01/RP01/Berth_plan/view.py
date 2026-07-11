"""
RP02 — Berth Plan (page + daily-report data), living on the shared
RP01 blueprint — same pattern as RP01/JJLTPL/jjltpl.py.
"""

from datetime import datetime, timedelta
from functools import wraps

from flask import request, jsonify, render_template, session, redirect, url_for

from .. import bp          # shared RP01 blueprint
from database import get_db, get_cursor, get_user_permissions
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from flask import send_file
# from modules.LUEU01.model import get_started_parcels

MODULE_CODE = 'RP01'

# ---- adjust if your real column name differs ----------
SAIL_COLUMN = 'cast_off_datetime'   # ldud_header column: actual sail time
# BERTHS constant removed — berths are now fetched live from port_berth_master
# -------------------------------------------------------------------------


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def get_perms():
    if session.get('is_admin'):
        return {'can_read': 1, 'can_add': 1, 'can_edit': 1, 'can_delete': 1}
    return get_user_permissions(session.get('user_id'), MODULE_CODE)


def get_berths(cur=None):
    """Live list of berth names from port_berth_master (no hardcoding)."""
    own_conn = cur is None
    if own_conn:
        conn = get_db()
        cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM port_berth_master ORDER BY berth_name')
    berths = [r['berth_name'] for r in cur.fetchall()]
    if own_conn:
        conn.close()
    return berths


def get_expected_waiting_vessels():
    """Section C data — queried directly from expected_vessels (EV01 table).
    Excludes vessels already moved to VCN or closed to another terminal,
    and excludes vessels that already have a berth assigned (those show
    up in Section A/B instead)."""
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute("""
            SELECT terminal_name, vessel_name, via_number, loa, draft,
                agents, tanks, consignees, cargo_name, mla, quantity,
                eta, ata, lpc, doc, nor, berth_name
            FROM expected_vessels
            WHERE (doc_status IS NULL OR doc_status NOT IN ('Moved to VCN', 'Closed - Other Terminal'))
              AND (berth_name IS NULL OR TRIM(berth_name) = '')
            ORDER BY eta ASC NULLS LAST, id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    def _combine(r):
        parts = [r.get('agents'), r.get('tanks'), r.get('consignees')]
        return ' / '.join(p for p in parts if p)

    out = []
    for r in rows:
        out.append({
            'terminal':     r.get('terminal_name'),
            'vessel_name':  r.get('vessel_name'),
            'via_no':       r.get('via_number'),
            'loa':          r.get('loa'),
            'dft':          r.get('draft'),
            'agt_tnk_cons': _combine(r),
            'cargo':        r.get('cargo_name'),
            'mla':          r.get('mla'),
            'quantity':     r.get('quantity'),
            'eta':          _fmt_dt(r.get('eta')),
            'ata':          _fmt_dt(r.get('ata')),
            'lpc':          _fmt_dt(r.get('lpc')),
            'doc':          _fmt_dt(r.get('doc')),
            'nor':          _fmt_dt(r.get('nor')),
            'berth':        r.get('berth_name'),
        })
    return out

# ══════════════════════════════════════════════════════════════════
#  Page route
# ══════════════════════════════════════════════════════════════════

@bp.route('/module/RP01/berth-plan/')
@login_required
def berth_plan_page():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('berth_plan.html', permissions=perms, berths=get_berths())


def get_report_window(plan_date_str):
    """'As on <date> @ 07:00' covers the PRIOR 24 hours: (date-1) 07:00 -> date 07:00."""
    plan_date = datetime.strptime(plan_date_str, '%Y-%m-%d')
    window_end = plan_date.replace(hour=7, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(days=1)
    return window_start, window_end


def _fmt_dt(v, fmt='%d-%m-%Y %H:%M'):
    """Format a value that may be a real datetime OR a raw text timestamp
    (e.g. po.start_dt/end_dt stored as 'YYYY-MM-DDTHH:MM' strings)."""
    if not v:
        return ''
    if isinstance(v, str):
        try:
            return datetime.strptime(v.replace('T', ' ')[:16], '%Y-%m-%d %H:%M').strftime(fmt)
        except ValueError:
            return v
    return v.strftime(fmt)

MIN_HOURS_FOR_ACTUAL = 4      # must match MIN_HOURS_FOR_ACTUAL in lueu01.html
MAX_REASONABLE_DAYS = 90      # if the actual-rate ETC projects beyond this, treat it as unreliable


def _enrich_vessel(cur, vcn_id, ldud_id, window_start, window_end):
    from modules.LUEU01.model import get_started_parcels

    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    is_export = (row or {}).get('operation_type') == 'Export'
    tbl = 'vcn_export_cargo_declaration' if is_export else 'vcn_consigners'

    cur.execute(f'SELECT DISTINCT consigner_name FROM {tbl} '
                f'WHERE vcn_id=%s AND consigner_name IS NOT NULL', [vcn_id])
    consigner = ', '.join(r['consigner_name'] for r in cur.fetchall() if r['consigner_name'])

    cur.execute('''SELECT MIN(po.start_dt::timestamp) AS started
                   FROM ldud_parcel_ops po WHERE po.ldud_id=%s''', [ldud_id])
    ops_commenced = cur.fetchone()['started']

    parcels = get_started_parcels(vcn_id)
    target_qty = float(sum(p['target_qty'] for p in parcels))
    logged_qty = float(sum(p['logged_qty'] for p in parcels))
    balance_qty = round(target_qty - logged_qty, 3)
    total_hours = float(sum(p['op_hours'] for p in parcels))
    present_flow_rate = round(logged_qty / total_hours, 2) if total_hours > 0 else 0

    cur.execute('''
        SELECT COALESCE(SUM(l.quantity), 0) AS q
        FROM lueu_parcel_log l
        JOIN ldud_parcel_ops po ON po.id = l.parcel_op_id
        WHERE po.ldud_id = %s
          AND l.is_deleted IS NOT TRUE
          AND (l.entry_date::timestamp + COALESCE(l.from_time::time, '00:00'::time))
              BETWEEN %s AND %s
    ''', [ldud_id, window_start, window_end])
    last_24hr_qty = round(float(cur.fetchone()['q'] or 0), 3)

    expected_completion = ''
    is_planned = False
    display_rate = present_flow_rate   # what we SHOW as Present Flow Rate — always the real actual rate when it exists

    def _planned_etc():
        """Latest projected ETC across all parcels, from Expected Start/Rate."""
        best_etc, best_rate = None, 0
        for p in parcels:
            rate = float(p.get('expected_flow_rate') or 0)
            start = p.get('expected_start')
            tgt = float(p.get('target_qty') or 0)
            if not (rate and start and tgt):
                continue
            try:
                start_dt = datetime.strptime(str(start).replace('T', ' ')[:16], '%Y-%m-%d %H:%M')
            except ValueError:
                continue
            etc_dt = start_dt + timedelta(hours=tgt / rate)
            if best_etc is None or etc_dt > best_etc:
                best_etc, best_rate = etc_dt, rate
        return best_etc, best_rate

    if balance_qty > 0:
        actual_etc = None
        if present_flow_rate > 0 and total_hours >= MIN_HOURS_FOR_ACTUAL:
            hrs_left = balance_qty / present_flow_rate
            actual_etc = window_end + timedelta(hours=hrs_left)

        # trust the actual-rate ETC only if it's within a sane horizon
        if actual_etc and (actual_etc - window_end).days <= MAX_REASONABLE_DAYS:
            expected_completion = actual_etc.strftime('%d-%m-%Y %H:%M')
        else:
            # actual rate missing, too little data, OR projects absurdly far out
            # (e.g. one tiny log entry over many idle hours) — fall back to plan
            best_etc, best_rate = _planned_etc()
            if best_etc:
                expected_completion = best_etc.strftime('%d-%m-%Y %H:%M')
                is_planned = True
                # only borrow the planned rate for display if there's no real rate at all;
                # if a real (if slow) rate exists, keep showing it — it's still correct data
                if not (present_flow_rate > 0 and total_hours >= MIN_HOURS_FOR_ACTUAL):
                    display_rate = best_rate

    return {
        'consigner': consigner,
        'quantity': target_qty,
        'ops_commenced': _fmt_dt(ops_commenced),
        'last_24hr_qty': last_24hr_qty,
        'till_now_qty': round(logged_qty, 3),
        'balance': balance_qty,
        'expected_completion': expected_completion,
        'present_flow_rate': display_rate,
        'is_planned': is_planned,
    }

def _base_row(h):
    return {
        'via_no': h.get('via_number') or '',
        'vessel_name': h.get('vessel_name') or '',
        'loa': h.get('loa'),
        'draft': h.get('draft'),
        'agent': h.get('vessel_agent_name') or '',
        'cargo': h.get('cargo_type') or '',
        'berth_name': h.get('berth_name') or '',
        'imo_num': h.get('imo_num') or '',
        'nationality': h.get('nationality') or '',
        'remarks': '',
    }


def get_berthed_vessels(window_start, window_end, berths):
    conn = get_db()
    cur = get_cursor(conn)
def get_berthed_vessels(window_start, window_end, berths):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT DISTINCT h.id AS vcn_id, l.id AS ldud_id, h.via_number, h.vessel_name,
               h.loa, h.draft, h.vessel_agent_name, h.cargo_type, h.berth_name,
               v.imo_num, v.nationality,
               l.alongside_datetime
        FROM ldud_parcel_ops po
        JOIN ldud_header l ON l.id = po.ldud_id
        JOIN vcn_header h ON h.id = l.vcn_id
        LEFT JOIN vessels v ON v.vessel_name = h.vessel_name
        WHERE h.berth_name = ANY(%s)
          AND po.start_dt IS NOT NULL
          AND po.end_dt IS NULL
        ORDER BY h.berth_name
    ''', [berths])
    headers = [dict(r) for r in cur.fetchall()]

    out = []
    for h in headers:
        row = _base_row(h)
        row['alongside'] = _fmt_dt(h['alongside_datetime'])
        row.update(_enrich_vessel(cur, h['vcn_id'], h['ldud_id'], window_start, window_end))
        out.append(row)
    conn.close()
    return out


def get_sailed_vessels(window_start, window_end, berths):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT h.id AS vcn_id, l.id AS ldud_id, h.via_number, h.vessel_name,
               h.loa, h.draft, h.vessel_agent_name, h.cargo_type, h.berth_name,
               v.imo_num, v.nationality,
               l.alongside_datetime, MAX(po.end_dt::timestamp) AS sail_dt
        FROM ldud_parcel_ops po
        JOIN ldud_header l ON l.id = po.ldud_id
        JOIN vcn_header h ON h.id = l.vcn_id
        LEFT JOIN vessels v ON v.vessel_name = h.vessel_name
        WHERE h.berth_name = ANY(%s)
        GROUP BY h.id, l.id, h.via_number, h.vessel_name, h.loa, h.draft,
                 h.vessel_agent_name, h.cargo_type, h.berth_name, v.imo_num, v.nationality,
                 l.alongside_datetime
        HAVING COUNT(*) FILTER (WHERE po.end_dt IS NULL) = 0
           AND MAX(po.end_dt::timestamp) BETWEEN %s AND %s
        ORDER BY h.berth_name
    ''', (berths, window_start, window_end))
    headers = [dict(r) for r in cur.fetchall()]

    out = []
    for h in headers:
        row = _base_row(h)
        row['alongside'] = _fmt_dt(h['alongside_datetime'])
        row['cast_off'] = _fmt_dt(h['sail_dt'])
        row.update(_enrich_vessel(cur, h['vcn_id'], h['ldud_id'], window_start, window_end))
        out.append(row)
    conn.close()
    return out


def get_daily_report(plan_date_str):
    window_start, window_end = get_report_window(plan_date_str)
    conn = get_db()
    cur = get_cursor(conn)
    berths = get_berths(cur)
    conn.close()

    return {
        'as_on_date': window_end.strftime('%d-%m-%Y'),
        'as_on_time': window_end.strftime('%H:%M'),
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'berthed': get_berthed_vessels(window_start, window_end, berths),
        'sailed': get_sailed_vessels(window_start, window_end, berths),
        'berths': berths,
        'expected': get_expected_waiting_vessels(),   # <-- ADD THIS LINE
    }

@bp.route('/api/module/RP02/berthplan/data')
@login_required
def rp02_data():
    plan_date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    try:
        report = get_daily_report(plan_date)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(report)

FIELDS_A = [
    ('VIA/F/OVERSEAS/IMO', '__via_f_ovs_imo'), ('VESSEL NAME', 'vessel_name'),
    ('LOA/BHC/DFT', '__loa_dft'), ('AGT / TF/PL', 'agent'), ('Consigner', 'consigner'),
    ('CARGO', 'cargo'), ('QUANTITY', 'quantity'), ('Alongside (Date/Time)', 'alongside'),
    ('OPS COMMENECED', 'ops_commenced'), ('Last 24 hrs Load/Discharge', 'last_24hr_qty'),
    ('Till now discharged / Load', 'till_now_qty'), ('BALANCE', 'balance'),
    ('Expected completion (Date/Time)', 'expected_completion'),
    ('Present Flow Rate(MT/hr)', 'present_flow_rate'), ('Remarks', 'remarks'),
]
FIELDS_B = [
    ('VIA/F/OVERSEAS/IMO', '__via_f_ovs_imo'), ('VESSEL NAME', 'vessel_name'),
    ('LOA/BHC/DFT', '__loa_dft'), ('AGT / TF/PL', 'agent'), ('Consigner', 'consigner'),
    ('CARGO', 'cargo'), ('QUANTITY', 'quantity'), ('Alongside (Date/Time)', 'alongside'),
    ('OPS COMMENECED', 'ops_commenced'), ('Cargo Completion Time', 'expected_completion'),
    ('Sail Cast off time', 'cast_off'), ('Flow Rate (MT/hr)', 'present_flow_rate'),
]

def _xl_field_value(row, field):
    if row is None:
        return ''
    if field == '__loa_dft':
        loa, dft = row.get('loa'), row.get('draft')
        return f"{loa or ''} / {dft or ''}" if (loa or dft) else ''
    if field == '__via_f_ovs_imo':
        via = row.get('via_no') or ''
        flag = (row.get('nationality') or '').strip().lower()
        ovs = 'Domestic' if flag == 'india' else 'Overseas'
        imo = row.get('imo_num') or ''
        return f"{via} / F / {ovs} / {imo}"
    val = row.get(field)
    if val is None:
        return ''
    # mirror the webpage: append "(Exp)" to a planned expected-completion value
    if field == 'expected_completion' and row.get('is_planned') and val:
        return f"{val} (Exp)"
    return val


@bp.route('/api/module/RP02/berthplan/export/excel')
@login_required
def rp02_export_excel():
    plan_date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    report = get_daily_report(plan_date)
    berths = report['berths']

    wb = Workbook()
    ws = wb.active
    ws.title = 'Berth Plan'

    bold = Font(bold=True)
    section_font = Font(bold=True, underline='single', color='0000C8')
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    header_fill = PatternFill('solid', fgColor='DCE6F1')
    label_fill = PatternFill('solid', fgColor='F4F6FA')
    thin = Side(style='thin', color='444444')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # value-cell fonts, matching the webpage's CSS color rules
    FONT_VALUE   = Font(color='0000C8', bold=True)   # normal logged value      -> blue
    FONT_PLANNED = Font(color='B8860B', bold=True)   # planned/no data yet      -> amber
    FONT_EMPTY   = Font(color='CBD5E1', bold=False)  # no vessel at this berth  -> light grey

    r = 1
    title_rows = []  # (row_idx, text) — merged + centered across full width once max_col is known
    title_rows.append((r, 'JSW JNPT LIQUID TERMINAL PRIVATE LIMITED')); r += 1
    title_rows.append((r, 'JAWAHARLAL NEHRU PORT AUTHORITY (BULK TERMINAL)')); r += 1
    title_rows.append((r, 'DAILY PERFORMANCE REPORT')); r += 2

    # "As on <date> @ <time>" — colored like the webpage's .bpln-as-on-row
    ws.cell(r, 1, 'As on').font = bold
    date_cell = ws.cell(r, 2, report['as_on_date'])
    date_cell.font = Font(bold=True, color='C00000')          # red, like .val-date
    date_cell.alignment = Alignment(horizontal='center')
    ws.cell(r, 3, '@').font = bold
    time_cell = ws.cell(r, 4, report['as_on_time'])
    time_cell.font = Font(bold=True, color='0000C8')          # blue, like .val-time
    time_cell.alignment = Alignment(horizontal='center')
    r += 2

    max_col = 1

    def write_vertical_section(title, vessels, fields):
        nonlocal r, max_col
        ws.cell(r, 1, title).font = section_font
        r += 1

        by_berth = {b: [] for b in berths}
        for v in vessels:
            b = v.get('berth_name') or '(no berth)'
            by_berth.setdefault(b, []).append(v)
        cols = [(b, vs if vs else [None]) for b, vs in by_berth.items()]

        # header row
        c = 2
        ws.cell(r, 1, 'DETAILS').font = bold
        ws.cell(r, 1).fill = header_fill
        ws.cell(r, 1).border = border
        for b, vs in cols:
            start_c = c
            for _ in vs:
                cell = ws.cell(r, c)
                cell.fill = header_fill
                cell.border = border
                c += 1
            ws.cell(r, start_c, b).font = bold
            ws.cell(r, start_c).alignment = center
            if len(vs) > 1:
                ws.merge_cells(start_row=r, start_column=start_c, end_row=r, end_column=start_c + len(vs) - 1)
        r += 1
        max_col = max(max_col, c - 1)

        for label, field in fields:
            ws.cell(r, 1, label).font = bold
            ws.cell(r, 1).fill = label_fill
            ws.cell(r, 1).border = border
            c = 2
            for b, vs in cols:
                for v in vs:
                    val = _xl_field_value(v, field)
                    cell = ws.cell(r, c, val)
                    cell.border = border
                    cell.alignment = center
                    if v is None:
                        cell.font = FONT_EMPTY
                    elif v.get('is_planned') and field in ('present_flow_rate', 'expected_completion'):
                        cell.font = FONT_PLANNED
                    else:
                        cell.font = FONT_VALUE
                    c += 1
            r += 1
        r += 1

    write_vertical_section('A] VESSEL OPERATION :- BERTHED VESSELS', report['berthed'], FIELDS_A)
    write_vertical_section('B] VESSEL OPERATION :- SAILED VESSELS', report['sailed'], FIELDS_B)

    ws.cell(r, 1, 'C] Expected /Waiting Tank Vessels at JJLTPL Berth').font = section_font
    r += 1
    c_headers = ['TERMINAL', 'VESSEL NAME', 'VIA NO.', 'LOA', 'DFT', 'AGT/TNK/CONS', 'CARGO',
                 'MLA', 'QTY.', 'ETA', 'ATA', 'LPC', 'DOC', 'NOR', 'BERTH']
    for col_i, h in enumerate(c_headers, start=1):
        cell = ws.cell(r, col_i, h)
        cell.font = bold; cell.fill = header_fill; cell.alignment = center; cell.border = border
    r += 1
    max_col = max(max_col, len(c_headers))

    for row in report['expected']:
        vals = [row.get('terminal'), row.get('vessel_name'), row.get('via_no'), row.get('loa'),
                row.get('dft'), row.get('agt_tnk_cons'), row.get('cargo'), row.get('mla'),
                row.get('quantity'), row.get('eta'), row.get('ata'), row.get('lpc'),
                row.get('doc'), row.get('nor'), row.get('berth')]
        for col_i, v in enumerate(vals, start=1):
            cell = ws.cell(r, col_i, v if v is not None else '')
            cell.border = border
            cell.alignment = center
        r += 1

    # now that max_col is known, merge + center the three title rows across the full width
    for row_idx, text in title_rows:
        ws.cell(row_idx, 1, text).font = bold
        ws.cell(row_idx, 1).alignment = Alignment(horizontal='center')
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=max_col)

    ws.column_dimensions['A'].width = 26
    for i in range(2, max_col + 1):
        ws.column_dimensions[get_column_letter(i)].width = 16

    # center the whole report horizontally on the printed page
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"Berth_Plan_{plan_date}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )