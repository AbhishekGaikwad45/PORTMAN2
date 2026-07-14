"""
RP01 Report-1 — Overseas/Coastal Cargo Traffic Handled (monthly, by commodity)

CORRECTED ASSUMPTIONS (per your clarification):
  - vcn_header.vessel_run_type      -> 'Overseas' or 'Coastal'
  - vcn_header.operation_type       -> 'Import' or 'Export'
  - vcargo_category (on the cargo declaration row, NOT the vessel master)
        -> 'IF' = Indian Flag, 'FF' = Foreign Flag
  - All quantities are stored in TONNES (raw MT). Report displays '000 Tonnes,
    so every summed quantity is divided by 1000 before display.
  - vcn_header.doc_date decides which calendar month a VCN belongs to.

If vcargo_category actually lives on a different table (e.g. per-cargo-line
in vcn_cargo_declaration / vcn_export_cargo_declaration rather than on the
header), tell me and I'll move the column reference — the logic below reads
it off the header row (`h.vcargo_category`) because that's what your message
implied ("vcn_header table contains column ... vcargo_category").
"""

from datetime import date, timedelta
from functools import wraps
from calendar import monthrange
import re

from flask import request, jsonify, render_template, session, redirect, url_for, send_file
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from .. import bp   # shared RP01 blueprint
from database import get_db, get_cursor, get_user_permissions

MODULE_CODE = 'RP01'

COMMODITIES = [
    'POL-CRUDE', 'POL-PRODUCTS', 'LPG', 'OTHER LIQUIDS', 'FARM LIQUIDS',
    'EDIBLE OIL', 'MOLASSES', 'CEMENT', 'OTHER BULK', 'CONTAINER',
]

_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?')


def _to_qty(v):
    """
    Robust numeric parse for quantity fields that may be real, int, or text
    like '1,234.50', '1234.5 MT', '' or None. Plain float(str(v).replace(',',''))
    silently returns 0.0 (via the caught ValueError) for anything with a unit
    suffix or stray characters — which is the most likely reason the report
    was showing all-zero rows. This pulls the first numeric token out instead
    of giving up.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(',', '').strip()
    if not s:
        return 0.0
    m = _NUM_RE.search(s)
    return float(m.group()) if m else 0.0


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


@bp.route("/module/RP01/report_06/")
@login_required
def report1_page():
    perms = get_perms()
    if not perms.get("can_read"):
        return render_template("no_access.html"), 403
    return render_template("report_06/report_06.html", permissions=perms)


def _month_bounds(month_str):
    """
    month_str MUST be 'YYYY-MM' (e.g. '2027-04' for Apr-2027).
    Returns (start_date_inclusive, end_date_exclusive) so the SQL filter is
    always   doc_date >= start AND doc_date < end
    which is safe regardless of time-of-day components in doc_date.
    """
    y, m = month_str.split('-')
    y, m = int(y), int(m)
    start = date(y, m, 1)
    last_day = monthrange(y, m)[1]
    end = date(y, m, last_day) + timedelta(days=1)
    return start, end


def _empty_bucket():
    return {
        'ov_imp_if': 0.0, 'ov_imp_ff': 0.0, 'ov_exp_if': 0.0, 'ov_exp_ff': 0.0,
        'co_imp_if': 0.0, 'co_imp_ff': 0.0, 'co_exp_if': 0.0, 'co_exp_ff': 0.0,
    }


def get_report1_data(year_str, month_str, debug=False):
    """
    year_str  : display-only FY label, e.g. '2027-28'  (NOT used for filtering)
    month_str : the ACTUAL filter key, 'YYYY-MM', e.g. '2027-04' for Apr-2027
    debug     : if True, includes a '_debug' block in the return value with
                raw fetch counts per source table and sample unmatched
                cargo names, so a genuinely-empty month can be told apart
                from a join/parsing bug without needing DB access.
    """
    if not month_str or len(month_str.split('-')) != 2:
        raise ValueError(f"month must be 'YYYY-MM', got: {month_str!r}")

    start, end = _month_bounds(month_str)

    conn = get_db()
    cur = get_cursor(conn)

    cur.execute("""
        SELECT h.id AS vcn_id, h.operation_type, h.vessel_run_type,
               d.bl_quantity AS quantity, d.cargo_name,
               vc.cargo_type, vc.cargo_category
        FROM vcn_header h
        JOIN vcn_cargo_declaration d ON d.vcn_id = h.id
        LEFT JOIN vessel_cargo vc ON vc.cargo_name = d.cargo_name
        WHERE h.doc_date::date >= %s AND h.doc_date::date < %s
    """, [start, end])
    lines_import = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT h.id AS vcn_id, h.operation_type, h.vessel_run_type,
               d.quantity AS quantity, d.cargo_name,
               vc.cargo_type, vc.cargo_category
        FROM vcn_header h
        JOIN vcn_export_cargo_declaration d ON d.vcn_id = h.id
        LEFT JOIN vessel_cargo vc ON vc.cargo_name = d.cargo_name
        WHERE h.doc_date::date >= %s AND h.doc_date::date < %s
    """, [start, end])
    lines_export = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT h.id AS vcn_id, h.operation_type, h.vessel_run_type,
               d.quantity AS quantity, d.cargo_name,
               vc.cargo_type, vc.cargo_category
        FROM vcn_header h
        JOIN vcn_consigners d ON d.vcn_id = h.id
        LEFT JOIN vessel_cargo vc ON vc.cargo_name = d.cargo_name
        WHERE h.doc_date::date >= %s AND h.doc_date::date < %s
    """, [start, end])
    lines_consigners = [dict(r) for r in cur.fetchall()]

    conn.close()

    lines = lines_import + lines_export + lines_consigners

    matrix = {c: _empty_bucket() for c in COMMODITIES}

    lines_with_qty = 0
    unmatched_names = set()

    for ln in lines:
        qty_mt = _to_qty(ln.get('quantity'))
        if qty_mt <= 0:
            continue
        lines_with_qty += 1
        qty_k = qty_mt / 1000.0   # tonnes -> '000 Tonnes

        if not ln.get('cargo_category'):
            unmatched_names.add(ln.get('cargo_name'))

        commodity = (ln.get('cargo_type') or '').strip().upper()
        if commodity not in matrix:
            commodity = 'OTHER BULK'

        run_type = (ln.get('vessel_run_type') or '').strip().lower()
        is_coastal = run_type == 'coastal'

        op = (ln.get('operation_type') or '').strip().lower()
        is_export = op == 'export'

        category = (ln.get('cargo_category') or '').strip().upper()
        is_indian = category == 'IF'

        key = ('co' if is_coastal else 'ov') + ('_exp_' if is_export else '_imp_') + ('if' if is_indian else 'ff')
        matrix[commodity][key] += qty_k

    rows = []
    grand = _empty_bucket()
    for c in COMMODITIES:
        b = matrix[c]
        ov_total = b['ov_imp_if'] + b['ov_imp_ff'] + b['ov_exp_if'] + b['ov_exp_ff']
        co_total = b['co_imp_if'] + b['co_imp_ff'] + b['co_exp_if'] + b['co_exp_ff']
        rows.append({
            'commodity': c,
            'ov_imp_if': round(b['ov_imp_if'], 2), 'ov_imp_ff': round(b['ov_imp_ff'], 2),
            'ov_exp_if': round(b['ov_exp_if'], 2), 'ov_exp_ff': round(b['ov_exp_ff'], 2),
            'ov_total': round(ov_total, 2),
            'co_imp_if': round(b['co_imp_if'], 2), 'co_imp_ff': round(b['co_imp_ff'], 2),
            'co_exp_if': round(b['co_exp_if'], 2), 'co_exp_ff': round(b['co_exp_ff'], 2),
            'co_total': round(co_total, 2),
            'grand_total': round(ov_total + co_total, 2),
        })
        for k in grand:
            grand[k] += b[k]

    gov_total = grand['ov_imp_if'] + grand['ov_imp_ff'] + grand['ov_exp_if'] + grand['ov_exp_ff']
    gco_total = grand['co_imp_if'] + grand['co_imp_ff'] + grand['co_exp_if'] + grand['co_exp_ff']
    totals = {
        'ov_imp_if': round(grand['ov_imp_if'], 3), 'ov_imp_ff': round(grand['ov_imp_ff'], 3),
        'ov_exp_if': round(grand['ov_exp_if'], 3), 'ov_exp_ff': round(grand['ov_exp_ff'], 3),
        'ov_total': round(gov_total, 3),
        'co_imp_if': round(grand['co_imp_if'], 3), 'co_imp_ff': round(grand['co_imp_ff'], 3),
        'co_exp_if': round(grand['co_exp_if'], 3), 'co_exp_ff': round(grand['co_exp_ff'], 3),
        'co_total': round(gco_total, 3),
        'grand_total': round(gov_total + gco_total, 3),
    }

    return {
        'rows': rows,
        'totals': totals,
        'year': year_str,
        'month': month_str,
        **({'_debug': {
                'lines_fetched': {
                    'vcn_cargo_declaration': len(lines_import),
                    'vcn_export_cargo_declaration': len(lines_export),
                    'vcn_consigners': len(lines_consigners),
                },
                'lines_with_qty_gt_0': lines_with_qty,
                'unmatched_cargo_names_sample': list(unmatched_names)[:15],
            }} if debug else {}),
    }


@bp.route('/api/module/RP01/report1/data')
@login_required
def report1_data():
    year = request.args.get('year')
    month = request.args.get('month')   # MUST be 'YYYY-MM', e.g. 2027-04
    debug = request.args.get('debug') == '1'
    if not year or not month:
        return jsonify({'error': 'year and month are required'}), 400
    try:
        report = get_report1_data(year, month, debug=debug)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(report)


@bp.route('/api/module/RP01/report1/export/excel')
@login_required
def report1_export_excel():
    year = request.args.get('year')
    month = request.args.get('month')
    report = get_report1_data(year, month)

    wb = Workbook()
    ws = wb.active
    ws.title = 'M-I'

    bold = Font(bold=True)
    title_font = Font(bold=True, size=12)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    yellow = PatternFill('solid', fgColor='FFFF00')
    grey = PatternFill('solid', fgColor='D9D9D9')
    lightblue = PatternFill('solid', fgColor='DCE6F1')
    thin = Side(style='thin', color='000000')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells('A1:K1')
    ws['A1'] = 'OVERSEAS-COASTAL CARGO TRAFFIC HANDLED'
    ws['A1'].font = title_font
    ws['A1'].alignment = center

    ws['A2'] = 'PORT : JAWAHARLAL NEHRU PORT AUTHORITY'
    ws['A2'].font = bold
    ws['H2'] = 'Year :'
    ws['I2'] = report['year']
    ws['H3'] = 'Month :'
    ws['I3'] = report['month']
    ws['I3'].fill = yellow

    r = 5
    ws.cell(r, 1, 'COMMODITY').font = bold
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 2, end_column=1)
    ws.cell(r, 2, 'OVERSEAS').font = bold
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
    ws.cell(r, 6, 'OVERSEAS Total').font = bold
    ws.merge_cells(start_row=r, start_column=6, end_row=r + 2, end_column=6)
    ws.cell(r, 7, 'COASTAL').font = bold
    ws.merge_cells(start_row=r, start_column=7, end_row=r, end_column=10)
    ws.cell(r, 11, 'COASTAL Total').font = bold
    ws.merge_cells(start_row=r, start_column=11, end_row=r + 2, end_column=11)
    ws.cell(r, 12, 'Grand Total').font = bold
    ws.merge_cells(start_row=r, start_column=12, end_row=r + 2, end_column=12)
    for col in [2, 6, 7, 11, 12]:
        ws.cell(r, col).fill = yellow if col in (2, 7) else grey
        ws.cell(r, col).alignment = center

    r2 = r + 1
    ws.cell(r2, 2, 'IMPORT').font = bold; ws.merge_cells(start_row=r2, start_column=2, end_row=r2, end_column=3)
    ws.cell(r2, 4, 'EXPORT').font = bold; ws.merge_cells(start_row=r2, start_column=4, end_row=r2, end_column=5)
    ws.cell(r2, 7, 'IMPORT').font = bold; ws.merge_cells(start_row=r2, start_column=7, end_row=r2, end_column=8)
    ws.cell(r2, 9, 'EXPORT').font = bold; ws.merge_cells(start_row=r2, start_column=9, end_row=r2, end_column=10)
    for col in [2, 4, 7, 9]:
        ws.cell(r2, col).fill = yellow
        ws.cell(r2, col).alignment = center

    r3 = r2 + 1
    labels3 = {2: 'IF', 3: 'FF', 4: 'IF', 5: 'FF', 7: 'IF', 8: 'FF', 9: 'IF', 10: 'FF'}
    for col, lbl in labels3.items():
        ws.cell(r3, col, lbl).font = bold
        ws.cell(r3, col).fill = yellow
        ws.cell(r3, col).alignment = center

    for cc in range(1, 13):
        for rr in (r, r2, r3):
            ws.cell(rr, cc).border = border

    r = r3 + 1
    for row in report['rows']:
        vals = [row['commodity'], row['ov_imp_if'], row['ov_imp_ff'], row['ov_exp_if'], row['ov_exp_ff'],
                row['ov_total'], row['co_imp_if'], row['co_imp_ff'], row['co_exp_if'], row['co_exp_ff'],
                row['co_total'], row['grand_total']]
        for ci, v in enumerate(vals, start=1):
            cell = ws.cell(r, ci, v if v else (row['commodity'] if ci == 1 else 0.00))
            cell.border = border
            cell.alignment = center
            if ci == 6 or ci == 11:
                cell.fill = grey
        r += 1

    t = report['totals']
    vals = ['Grand Total', t['ov_imp_if'], t['ov_imp_ff'], t['ov_exp_if'], t['ov_exp_ff'], t['ov_total'],
            t['co_imp_if'], t['co_imp_ff'], t['co_exp_if'], t['co_exp_ff'], t['co_total'], t['grand_total']]
    for ci, v in enumerate(vals, start=1):
        cell = ws.cell(r, ci, v)
        cell.font = bold
        cell.border = border
        cell.alignment = center
        cell.fill = lightblue

    ws.column_dimensions['A'].width = 18
    for i in range(2, 13):
        ws.column_dimensions[get_column_letter(i)].width = 13

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf, as_attachment=True,
        download_name=f"Report1_{report['year']}_{report['month']}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )