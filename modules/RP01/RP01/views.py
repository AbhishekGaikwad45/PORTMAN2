from flask import render_template, session, redirect, url_for, request, jsonify, Response
from functools import wraps
import csv, io
from datetime import datetime
from . import bp
from database import get_db, get_cursor, get_user_permissions

MODULE_CODE = 'RP01'


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


@bp.route('/module/RP01/')
@login_required
def index():
    return render_template('rp01.html', username=session.get('username'))


# ══════════════════════════════════════════════════════════════════
#  Historical base datasets for reports, loaded from CSV templates.
#  Uploads are a full replace: DELETE all rows, INSERT the file. Never upsert.
#  Two datasets: mis_history (parcel lines) and mis_vessel_master (vessel calls).
# ══════════════════════════════════════════════════════════════════

_JUNK = {'#N/A', '#DIV/0!', '#VALUE!', '#REF!'}
_DT_FORMATS = ('%d-%m-%Y %H:%M', '%d/%m/%Y %H:%M', '%d/%m/%y %H:%M', '%d-%m-%y %H:%M',
               '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%d-%m-%Y', '%d/%m/%Y', '%d/%m/%y')


def _clean(val):
    """Trim; treat Excel error values and lone dashes as blank."""
    val = (val or '').strip()
    return '' if val.upper() in _JUNK or val.strip('- ') == '' else val


def _num(val):
    val = _clean(val).replace(',', '').replace(' ', '')
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        raise ValueError(f'not a number: {val!r}')


def _dt(val):
    val = _clean(val)
    if not val:
        return None
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(val, fmt).strftime('%Y-%m-%dT%H:%M')
        except ValueError:
            pass
    raise ValueError(f'bad date: {val!r} (use DD-MM-YYYY HH:MM)')


def _parse_flat_csv(text, columns, num_cols, dt_cols, ffill_cols, anchor_col, required_cols):
    """Parse a template CSV → (rows, errors).

    anchor_col blank → the row is skipped: subtotal/total rows, blank rows and
    the template's format-hint row never have one, and per the users totals are
    never uploaded — reports compute them. ffill_cols inherit from the row
    above when blank.
    """
    db_cols = [c for _, c, _ in columns]
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = {(f or '').strip().lower(): f for f in (reader.fieldnames or [])}
    header_map, missing = {}, []
    for hdr, col, _hint in columns:
        actual = fieldnames.get(hdr.strip().lower())
        if actual is None:
            missing.append(hdr)
        else:
            header_map[col] = actual
    if missing:
        return [], ['Missing columns: ' + ', '.join(missing) + ' — please re-download the template.']

    rows, errors, carry = [], [], {}
    for line_no, r in enumerate(reader, start=2):
        raw = {col: _clean(r.get(header_map[col])) for col in db_cols}
        if not raw[anchor_col]:
            continue  # subtotal / blank / junk row
        for col in ffill_cols:
            if raw[col]:
                carry[col] = raw[col]
            else:
                raw[col] = carry.get(col, '')
        row = {}
        for col in db_cols:
            try:
                if col in dt_cols:
                    row[col] = _dt(raw[col])
                elif col in num_cols:
                    row[col] = _num(raw[col])
                else:
                    row[col] = raw[col] or None
            except ValueError as e:
                errors.append(f'Row {line_no} [{col}]: {e}')
        for col in required_cols:
            if not row.get(col):
                errors.append(f'Row {line_no}: missing {col}')
        rows.append(row)
    return rows, errors


def _replace_all(table, db_cols, rows):
    """Delete every row, insert the new set. One transaction — all or nothing."""
    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute(f'DELETE FROM {table}')
        deleted = cur.rowcount
        cols = db_cols + ['uploaded_by']
        sql = f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({", ".join(["%s"] * len(cols))})'
        user = session.get('email') or session.get('username')
        cur.executemany(sql, [[row[c] for c in db_cols] + [user] for row in rows])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return deleted


def _paged_data(table):
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 25))
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT COUNT(*) FROM {table}')
    total = cur.fetchone()['count']
    cur.execute(f'SELECT * FROM {table} ORDER BY id LIMIT %s OFFSET %s',
                (size, (page - 1) * size))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'data': rows, 'last_page': max((total + size - 1) // size, 1), 'total': total})


def _csv_template(columns, filename):
    """Header row + a format-hint row. The hint row's anchor column is blank,
    so the upload parser ignores it — users may keep or delete it."""
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow([h for h, _, _ in columns])
    writer.writerow([hint for _, _, hint in columns])
    return Response(si.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


def _grid_cols(columns, num_cols, dt_cols=frozenset()):
    """(title, field, kind) per template column — drives the preview grid,
    so the grid always shows every column the CSV template has."""
    return [(h, c, 'num' if c in num_cols else 'dt' if c in dt_cols else '')
            for h, c, _ in columns]


def _do_upload(parse_fn, table, db_cols):
    perms = get_perms()
    if not (perms.get('can_add') and perms.get('can_delete')):
        return jsonify({'error': 'Upload replaces all data — add + delete permission required'}), 403
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
    rows, errors = parse_fn(file.stream.read().decode('utf-8-sig'))
    if errors:
        return jsonify({'error': 'Fix these and re-upload (nothing was changed):',
                        'details': errors[:30], 'error_count': len(errors)}), 400
    if not rows:
        return jsonify({'error': 'No data rows found in file'}), 400
    deleted = _replace_all(table, db_cols, rows)
    return jsonify({'success': True, 'deleted': deleted, 'inserted': len(rows)})


# ──────────────────────────────────────────────────────────────────
#  Dataset 1: MIS history — one row per customer/cargo parcel line
# ──────────────────────────────────────────────────────────────────

# (csv header, db column, format hint shown on the template's second row).
# The hint row's Customer cell stays blank so the parser ignores that row.
MIS_COLUMNS = [
    ('Sr No',                 'sr_no',            'number, e.g. 1'),
    ('Fin Year',              'fin_year',         'e.g. 2024-25'),
    ('Month JSW',             'month_jsw',        'MMM-YY e.g. Nov-24'),
    ('Month JNPT',            'month_jnpt',       'MMM-YY e.g. Nov-24'),
    ('VCN No',                'vcn_no',           'e.g. Q5928'),
    ('Vessel Name',           'vessel_name',      'e.g. MT WISDOM STAR'),
    ('Customer',              'customer',         ''),
    ('Payment By',            'payment_by',       'text'),
    # cargo classification: same names as the VCG01 cargo master (vessel_cargo)
    ('Cargo Type',            'cargo_type',           'Edible Oil / Chemical / POL / Other Liquid'),
    ('Cargo Category',        'cargo_category',       'Edible Oil / Chemical / Ph.Acid / Other'),
    ('Cargo Category 2',      'cargo_category_2',     'optional'),
    ('Cargo Sub Category',    'cargo_sub_category',   'optional'),
    ('Cargo Sub Category 2',  'cargo_sub_category_2', 'optional'),
    ('Cargo Name',            'cargo_name',           'e.g. CPO / CDSBO / Acetic Acid'),
    ('Terminal',              'terminal',         'e.g. GBL / Suraj / IMC'),
    ('Quantity MT',           'quantity',         'number, e.g. 12000.000'),
    ('Overseas/Coastal',      'overseas_coastal', 'Overseas / Costal'),
    ('Import/Export',         'import_export',    'Import / Export'),
    ('Cargo Handling Rate',   'cargo_rate',       'number, e.g. 252'),
    ('Cargo Handling Amount', 'cargo_amount',     'number'),
    ('Infra & Misc Rate',     'infra_rate',       'number, e.g. 100'),
    ('Infra & Misc Amount',   'infra_amount',     'number'),
    ('Toll Rate',             'toll_rate',        'number, e.g. 24.2'),
    ('Toll Amount',           'toll_amount',      'number'),
    ('Gangway Agent',         'gangway_agent',    'first row of vessel only'),
    ('Gangway Amount',        'gangway_amount',   'number, first row of vessel only'),
    ('MLA Rate',              'mla_rate',         'number, optional'),
    ('MLA Amount',            'mla_amount',       'number, optional'),
    ('Remarks',               'remarks',          'optional'),
    ('Importer',              'importer',         'text'),
]
MIS_DB_COLS = [c for _, c, _ in MIS_COLUMNS]
MIS_NUM = {'sr_no', 'quantity', 'cargo_rate', 'cargo_amount', 'infra_rate', 'infra_amount',
           'toll_rate', 'toll_amount', 'gangway_amount', 'mla_rate', 'mla_amount'}
# Vessel-level cells: filled on the first row of a vessel group in the legacy
# sheet, blank on continuation rows — inherit from the row above on ingest.
MIS_FFILL = {'fin_year', 'month_jsw', 'month_jnpt', 'vcn_no', 'vessel_name'}


def parse_mis_csv(text):
    return _parse_flat_csv(text, MIS_COLUMNS, MIS_NUM, set(), MIS_FFILL,
                           anchor_col='customer', required_cols=('vcn_no', 'vessel_name'))


@bp.route('/module/RP01/mis-history/')
@login_required
def mis_history_page():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('mis_history.html', permissions=perms,
                           grid_cols=_grid_cols(MIS_COLUMNS, MIS_NUM))


@bp.route('/api/module/RP01/mis-history/template')
@login_required
def mis_template():
    return _csv_template(MIS_COLUMNS, 'MIS_History_Template.csv')


@bp.route('/api/module/RP01/mis-history/summary')
@login_required
def mis_summary():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT COUNT(*) AS total_rows,
               COUNT(DISTINCT vcn_no) AS vessels,
               COALESCE(SUM(quantity), 0) AS quantity,
               COALESCE(SUM(COALESCE(cargo_amount,0) + COALESCE(infra_amount,0)
                          + COALESCE(toll_amount,0) + COALESCE(gangway_amount,0)
                          + COALESCE(mla_amount,0)), 0) AS amount,
               STRING_AGG(DISTINCT fin_year, ', ' ORDER BY fin_year) AS fin_years,
               MAX(uploaded_at)::text AS uploaded_at,
               MAX(uploaded_by) AS uploaded_by
        FROM mis_history
    ''')
    row = dict(cur.fetchone())
    conn.close()
    return jsonify(row)


@bp.route('/api/module/RP01/mis-history/data')
@login_required
def mis_data():
    return _paged_data('mis_history')


@bp.route('/api/module/RP01/mis-history/upload', methods=['POST'])
@login_required
def mis_upload():
    return _do_upload(parse_mis_csv, 'mis_history', MIS_DB_COLS)

# @bp.route('/api/module/RP01/jjltpl/data')
# @login_required
# def jjltpl_data():
#     return _paged_data('jjltpl')


# ──────────────────────────────────────────────────────────────────
#  Dataset 2: Vessel call master — one row per vessel call, with
#  berthing timings and turnaround KPIs. Excluded from the legacy
#  sheet: Code/Status, daily-update tracking fields,
#  Excel concat helper columns.
# ──────────────────────────────────────────────────────────────────

# The hint row's Vessel Name cell stays blank so the parser ignores that row.
_DT_HINT = 'DD-MM-YYYY HH:MM'
VM_COLUMNS = [
    ('Sr No',                        'sr_no',                'number, e.g. 1'),
    ('Fin Year',                     'fin_year',             'e.g. 2024-25'),
    ('Month',                        'month',                'MMM-YY e.g. Nov-24'),
    ('Berth No',                     'berth_no',             'e.g. LB-03'),
    ('VCN No',                       'vcn_no',               'e.g. Q5928'),
    ('Vessel Name',                  'vessel_name',          ''),
    ('Overseas/Coastal',             'overseas_coastal',     'Overseas / Costal'),
    ('F/I',                          'foreign_indian',       'F / I'),
    ('IMO No',                       'imo_no',               'e.g. 9251559'),
    ('Flag',                         'flag',                 'e.g. Panama'),
    ('BHC',                          'bhc',                  'optional'),
    ('Port Code',                    'port_code',            'e.g. UAILK'),
    ('Port of Loading',              'port_of_loading',      'e.g. CHORNOMORSK, UKRAINE'),
    ('GRT',                          'grt',                  'number'),
    ('Draft',                        'draft',                'number, e.g. 7.5'),
    ('LOA',                          'loa',                  'number, e.g. 183'),
    ('Import/Export',                'import_export',        'Import / Export'),
    ('Agent',                        'agent',                'e.g. Interocean'),
    ('Unload Pipeline',              'unload_pipeline',      'e.g. 12" dia x 2'),
    ('Consigner',                    'consigner',            'text'),
    ('Unloading Terminal',           'unloading_terminal',   'e.g. Suraj/GBL/IMC'),
    ('New Cat',                      'new_cat',              'e.g. Edible Oil'),
    ('Category-1',                   'category1',            'e.g. Other'),
    ('Category',                     'category',             'e.g. Edible Oil'),
    ('Cargo',                        'cargo',                'e.g. EDIBLE OIL'),
    ('NOR',                          'nor',                  _DT_HINT),
    ('Anchorage Time',               'anchorage_time',       _DT_HINT),
    ('Pilot Pick Up',                'pilot_pickup',         _DT_HINT),
    ('First Line',                   'first_line',           _DT_HINT),
    ('Alongside',                    'alongside',            _DT_HINT),
    ('Ops Commenced',                'ops_commenced',        _DT_HINT),
    ('Cargo Completion',             'cargo_completion',     _DT_HINT),
    ('Sail Cast Off',                'sail_cast_off',        _DT_HINT),
    ('Cast Off',                     'cast_off',             _DT_HINT),
    ('Pilot Board Departure',        'pilot_board_departure', _DT_HINT),
    ('Pilot Disembarked',            'pilot_disembarked',    _DT_HINT),
    ('Quantity MT',                  'quantity',             'number, e.g. 12000.000'),
    ('Flow Rate (MT/hr)',            'flow_rate',            'number, e.g. 405'),
    ('Remarks',                      'remarks',              'optional'),
    ('Pre-Berthing Waiting (days)',  'pre_berthing_waiting', 'number (days)'),
    ('Waiting Port (days)',          'waiting_port',         'number (days)'),
    ('Waiting Non-Port (days)',      'waiting_non_port',     'number (days)'),
    ('Stay at Berth (days)',         'stay_at_berth',        'number (days)'),
    ('Arrive to Comm (days)',        'arrive_to_comm',       'number (days)'),
    ('Working Time (days)',          'working_time',         'number (days)'),
    ('Non-Working Total (days)',     'non_working_total',    'number (days)'),
    ('Non-Working Port (days)',      'non_working_port',     'number (days)'),
    ('Non-Working Non-Port (days)',  'non_working_non_port', 'number (days)'),
    ('Inward Movement (days)',       'inward_movement',      'number (days)'),
    ('Outward Movement (days)',      'outward_movement',     'number (days)'),
]
VM_DB_COLS = [c for _, c, _ in VM_COLUMNS]
VM_NUM = {'sr_no', 'grt', 'draft', 'loa', 'quantity', 'flow_rate',
          'pre_berthing_waiting', 'waiting_port', 'waiting_non_port', 'stay_at_berth',
          'arrive_to_comm', 'working_time', 'non_working_total', 'non_working_port',
          'non_working_non_port', 'inward_movement', 'outward_movement'}
VM_DT = {'nor', 'anchorage_time', 'pilot_pickup', 'first_line', 'alongside',
         'ops_commenced', 'cargo_completion', 'sail_cast_off', 'cast_off',
         'pilot_board_departure', 'pilot_disembarked'}


def parse_vm_csv(text):
    return _parse_flat_csv(text, VM_COLUMNS, VM_NUM, VM_DT, set(),
                           anchor_col='vessel_name', required_cols=('vcn_no',))


@bp.route('/module/RP01/vessel-master/')
@login_required
def vm_page():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('vessel_master.html', permissions=perms,
                           grid_cols=_grid_cols(VM_COLUMNS, VM_NUM, VM_DT))


@bp.route('/api/module/RP01/vessel-master/template')
@login_required
def vm_template():
    return _csv_template(VM_COLUMNS, 'Vessel_Master_Template.csv')


@bp.route('/api/module/RP01/vessel-master/summary')
@login_required
def vm_summary():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT COUNT(*) AS total_rows,
               COUNT(DISTINCT vcn_no) AS vessels,
               COALESCE(SUM(quantity), 0) AS quantity,
               ROUND(AVG(pre_berthing_waiting), 2) AS avg_pre_berthing,
               STRING_AGG(DISTINCT fin_year, ', ' ORDER BY fin_year) AS fin_years,
               MAX(uploaded_at)::text AS uploaded_at,
               MAX(uploaded_by) AS uploaded_by
        FROM mis_vessel_master
    ''')
    row = dict(cur.fetchone())
    conn.close()
    return jsonify(row)


@bp.route('/api/module/RP01/vessel-master/data')
@login_required
def vm_data():
    return _paged_data('mis_vessel_master')


@bp.route('/api/module/RP01/vessel-master/upload', methods=['POST'])
@login_required
def vm_upload():
    return _do_upload(parse_vm_csv, 'mis_vessel_master', VM_DB_COLS)
