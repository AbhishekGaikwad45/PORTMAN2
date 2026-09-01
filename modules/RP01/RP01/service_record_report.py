"""SRV01 Service Records — xlsx dump.

Approved records only: those are the billing-relevant set, and a draft is by
definition still being filled in.

SRV01's custom fields are EAV, so they differ per service type and cannot all be
fixed columns. Two shapes, one route:

  no service type  -> every approved record, custom fields collapsed into one
                      readable 'Details' cell
  a service type   -> only that type's records, with its custom fields expanded
                      into real columns you can sort and pivot on
"""
from flask import render_template, session, jsonify, request
from functools import wraps

from . import bp
from database import get_db, get_cursor, get_user_permissions
import excel_export

MODULE_CODE = 'RP01'

# Fixed header columns, shared by both shapes. Custom fields are appended after
# these. 'dt:' would split into date+time; record_date is date-only, so plain.
BASE_COLS = [
    ('Record No',    'record_number'),
    ('Service Code', 'service_code'),
    ('Service',      'service_name'),
    ('Bill To Type', 'source_type'),
    ('Bill To',      'source_display'),
    ('Ref Document', 'ref_source_display'),
    ('Date',         'record_date'),
    ('Billable Qty', 'billable_quantity'),
    ('UOM',          'billable_uom'),
    ('Status',       'doc_status'),
    ('Billed',       'billed'),
    ('Bill No',      'bill_number'),
    ('Created By',   'created_by'),
    ('Approved By',  'approved_by'),
    ('Approved On',  'approved_date'),
    ('Remarks',      'remarks'),
]


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return wrapper


def _custom_fields(cur, service_type_id):
    """Ordered active field definitions for one service type."""
    cur.execute('''SELECT id, field_label FROM service_field_definitions
                   WHERE service_type_id = %s AND is_active = 1
                   ORDER BY display_order, id''', [service_type_id])
    return [dict(r) for r in cur.fetchall()]


def report_rows(service_type_id=None):
    """(cols, rows) for the requested shape. One pass over approved records,
    one pass over their values — not a query per record."""
    conn = get_db()
    cur = get_cursor(conn)

    where, params = "WHERE r.doc_status = 'Approved'", []
    if service_type_id:
        where += ' AND r.service_type_id = %s'
        params.append(service_type_id)

    cur.execute(f'''
        SELECT r.id, r.record_number, r.source_type, r.source_display,
               r.ref_source_display, r.record_date, r.billable_quantity,
               r.billable_uom, r.doc_status, r.is_billed, r.created_by,
               r.approved_by, r.approved_date, r.remarks,
               st.service_code, st.service_name,
               b.bill_number
        FROM service_records r
        LEFT JOIN finance_service_types st ON st.id = r.service_type_id
        LEFT JOIN bill_header b ON b.id = r.bill_id
        {where}
        ORDER BY r.record_number
    ''', params)
    rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        row['billed'] = bool(row.pop('is_billed', 0))

    if not rows:
        # Still return the shape the caller asked for — a sheet with no rows must
        # carry the same headers as one with rows, or the two can't be appended.
        cols = (BASE_COLS + [(d['field_label'], f"cf_{d['id']}")
                             for d in _custom_fields(cur, service_type_id)]
                if service_type_id else BASE_COLS + [('Details', 'details')])
        conn.close()
        return cols, rows

    # Every recorded value for these records, in one query.
    ids = [r['id'] for r in rows]
    cur.execute('''SELECT v.service_record_id, v.field_value,
                          d.id AS field_id, d.field_label, d.display_order
                   FROM service_record_values v
                   JOIN service_field_definitions d ON d.id = v.field_definition_id
                   WHERE v.service_record_id = ANY(%s)
                   ORDER BY d.display_order, d.id''', [ids])
    values = [dict(r) for r in cur.fetchall()]

    if service_type_id:
        defs = _custom_fields(cur, service_type_id)
        conn.close()
        by_record = {}
        for v in values:
            by_record.setdefault(v['service_record_id'], {})[v['field_id']] = v['field_value']
        for row in rows:
            vals = by_record.get(row['id'], {})
            for d in defs:
                row[f"cf_{d['id']}"] = vals.get(d['id'], '')
        cols = BASE_COLS + [(d['field_label'], f"cf_{d['id']}") for d in defs]
        return cols, rows

    conn.close()
    details = {}
    for v in values:
        if str(v['field_value'] or '').strip() == '':
            continue
        details.setdefault(v['service_record_id'], []).append(
            f"{v['field_label']}: {v['field_value']}")
    for row in rows:
        row['details'] = ' | '.join(details.get(row['id'], []))
    return BASE_COLS + [('Details', 'details')], rows


@bp.route('/module/RP01/service-records/')
@login_required
def srv_report_page():
    perms = ({'can_read': 1} if session.get('is_admin')
             else get_user_permissions(session.get('user_id'), MODULE_CODE))
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('service_record_report.html')


@bp.route('/api/module/RP01/service-records/summary')
@login_required
def srv_report_summary():
    """Counts plus the service types worth offering — only those that actually
    have approved records, so the dropdown can't lead to an empty sheet."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT COUNT(*) AS c FROM service_records WHERE doc_status = 'Approved'")
    approved = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM service_records WHERE doc_status = 'Approved' AND COALESCE(is_billed,0) = 1")
    billed = cur.fetchone()['c']
    cur.execute('''SELECT st.id, st.service_code, st.service_name, COUNT(*) AS records
                   FROM service_records r
                   JOIN finance_service_types st ON st.id = r.service_type_id
                   WHERE r.doc_status = 'Approved'
                   GROUP BY st.id, st.service_code, st.service_name
                   ORDER BY st.service_name''')
    types = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'approved': approved, 'billed': billed,
                    'unbilled': approved - billed, 'service_types': types})


@bp.route('/api/module/RP01/service-records/export')
@login_required
def srv_report_export():
    raw = request.args.get('service_type_id') or ''
    service_type_id = int(raw) if raw.isdigit() else None
    cols, rows = report_rows(service_type_id)
    stem = f'Service_Records_{service_type_id}' if service_type_id else 'Service_Records'
    return excel_export.sheet_response(cols, rows, 'Service Records', stem)
