from database import get_db, get_cursor
from datetime import datetime

# parcel_ids on ldud_parcel_ops point at the VCN's parcel source table,
# chosen by the linked VCN's operation_type (whitelisted — safe to interpolate).
def _parse_ids(csv):
    return [int(x) for x in str(csv or '').split(',') if str(x).strip().isdigit()]


def _num(v):
    if v is None or (isinstance(v, str) and v.strip() == ''):
        return None
    return v


def get_vessels_with_started_parcels():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT h.id AS vcn_id, h.vcn_doc_num, h.vessel_name, h.berth_name,
               COUNT(po.id) AS parcel_count
        FROM ldud_parcel_ops po
        JOIN ldud_header l ON l.id = po.ldud_id
        JOIN vcn_header h ON h.id = l.vcn_id
        WHERE po.start_dt IS NOT NULL
        GROUP BY h.id, h.vcn_doc_num, h.vessel_name, h.berth_name
        ORDER BY h.vcn_doc_num DESC
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_started_parcels(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    # operation_type decides which table holds the parcel master rows
    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    op = (row or {}).get('operation_type') if row else None
    is_export = op == 'Export'
    tbl = 'vcn_export_cargo_declaration' if is_export else 'vcn_consigners'
    qty_col = 'bl_quantity' if is_export else 'quantity'

    cur.execute('''
        SELECT po.id AS parcel_op_id, po.parcel_ids, po.cargo_name,
               po.start_dt, po.end_dt
        FROM ldud_parcel_ops po
        JOIN ldud_header l ON l.id = po.ldud_id
        WHERE l.vcn_id = %s AND po.start_dt IS NOT NULL
        ORDER BY po.id
    ''', [vcn_id])
    parcels = [dict(r) for r in cur.fetchall()]

    # resolve parcel_no + declared qty from the source table
    all_ids = sorted({pid for p in parcels for pid in _parse_ids(p['parcel_ids'])})
    labels, qty = {}, {}
    if all_ids:
        cur.execute(f'SELECT id, parcel_no, {qty_col} AS q FROM {tbl} WHERE id = ANY(%s)', [all_ids])
        for r in cur.fetchall():
            labels[r['id']] = r['parcel_no'] or f"#{r['id']}"
            try:
                qty[r['id']] = float(str(r['q']).replace(',', '')) if r['q'] is not None else 0.0
            except (ValueError, TypeError):
                qty[r['id']] = 0.0

    # logged qty per parcel (non-deleted)
    pop_ids = [p['parcel_op_id'] for p in parcels]
    logged = {}
    if pop_ids:
        cur.execute('''SELECT parcel_op_id, COALESCE(SUM(quantity),0) AS s
                       FROM lueu_parcel_log
                       WHERE parcel_op_id = ANY(%s) AND is_deleted IS NOT TRUE
                       GROUP BY parcel_op_id''', [pop_ids])
        logged = {r['parcel_op_id']: float(r['s'] or 0) for r in cur.fetchall()}
    conn.close()

    out = []
    for p in parcels:
        ids = _parse_ids(p['parcel_ids'])
        out.append({
            'parcel_op_id': p['parcel_op_id'],
            'parcel_no': ', '.join(labels.get(i, f"#{i}") for i in ids) or '—',
            'cargo_name': p['cargo_name'] or '',
            'declared_qty': round(sum(qty.get(i, 0.0) for i in ids), 3),
            'logged_qty': round(logged.get(p['parcel_op_id'], 0.0), 3),
            'uom': 'MT',
            'start_dt': p['start_dt'],
            'end_dt': p['end_dt'],
            'status': 'Completed' if p['end_dt'] else 'In Progress',
        })
    return out


_LOG_COLS = ['parcel_op_id', 'entry_date', 'from_time', 'to_time', 'quantity',
             'quantity_uom', 'medium', 'equipment_name', 'delay_name', 'shift',
             'operator_name', 'shift_incharge', 'berth_name', 'remarks']


def get_log(parcel_op_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT * FROM lueu_parcel_log
                   WHERE parcel_op_id=%s AND is_deleted IS NOT TRUE
                   ORDER BY entry_date, from_time, id''', [parcel_op_id])
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_log(data):
    # Direct Pipe carries no equipment
    if data.get('medium') == 'Direct Pipe':
        data['equipment_name'] = None
    data['quantity'] = _num(data.get('quantity'))
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        sets = ', '.join(f'{c}=%s' for c in _LOG_COLS)
        cur.execute(f'UPDATE lueu_parcel_log SET {sets} WHERE id=%s',
                    [data.get(c) for c in _LOG_COLS] + [data['id']])
        row_id = data['id']
    else:
        cols = _LOG_COLS + ['created_by', 'created_date']
        vals = [data.get(c) for c in _LOG_COLS] + [data.get('created_by'),
                                                   datetime.now().strftime('%Y-%m-%d')]
        ph = ', '.join(['%s'] * len(cols))
        cur.execute(f'INSERT INTO lueu_parcel_log ({", ".join(cols)}) VALUES ({ph}) RETURNING id', vals)
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id


def soft_delete_log(ids, username):
    conn = get_db()
    cur = get_cursor(conn)
    today = datetime.now().strftime('%Y-%m-%d')
    for log_id in ids:
        cur.execute('''UPDATE lueu_parcel_log
                       SET is_deleted=TRUE, deleted_by=%s, deleted_date=%s
                       WHERE id=%s AND is_deleted IS NOT TRUE''', [username, today, log_id])
    conn.commit()
    conn.close()
