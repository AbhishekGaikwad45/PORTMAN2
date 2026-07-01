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


def _hours(f, t):
    """Duration in hours between two 'HH:MM' strings (wraps past midnight)."""
    try:
        fh, fm = (int(x) for x in str(f).split(':')[:2])
        th, tm = (int(x) for x in str(t).split(':')[:2])
    except (ValueError, AttributeError):
        return 0.0
    mins = (th * 60 + tm) - (fh * 60 + fm)
    if mins < 0:
        mins += 1440
    return mins / 60.0


def get_vessels_with_started_parcels():
    """Vessels that have any LDUD parcel-ops rows. Parcel start/end is entered
    here in LUEU01, so vessels appear as soon as parcels exist (not gated on
    start_dt)."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT h.id AS vcn_id, h.vcn_doc_num, h.vessel_name, h.berth_name,
               COUNT(po.id) AS parcel_count
        FROM ldud_parcel_ops po
        JOIN ldud_header l ON l.id = po.ldud_id
        JOIN vcn_header h ON h.id = l.vcn_id
        GROUP BY h.id, h.vcn_doc_num, h.vessel_name, h.berth_name
        ORDER BY h.vcn_doc_num DESC
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_started_parcels(vcn_id):
    """Each parcel-ops row (parcel + terminal) for the vessel. The per-row target
    is ldud_parcel_ops.quantity; remaining = target - logged. start/end are
    entered in LUEU01."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT po.id AS parcel_op_id, po.parcel_ids, po.cargo_name, po.terminal_name,
               po.quantity AS op_qty, po.start_dt, po.end_dt, po.expected_start,
               po.expected_flow_rate, l.alongside_datetime
        FROM ldud_parcel_ops po
        JOIN ldud_header l ON l.id = po.ldud_id
        WHERE l.vcn_id = %s
        ORDER BY po.id
    ''', [vcn_id])
    parcels = [dict(r) for r in cur.fetchall()]

    # resolve parcel_no label + CURRENT quantity from the operation-type source
    # table, so the validation target tracks VCN updates (falls back to the
    # parcel-op's own quantity when the parcels can't be resolved).
    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    is_export = (row or {}).get('operation_type') == 'Export'
    tbl = 'vcn_export_cargo_declaration' if is_export else 'vcn_consigners'
    qty_col = 'quantity'  # both source tables now use a TEXT 'quantity' column (export mirrors import)
    # equipment_names / pipeline_name / unload_terminal only exist on the import consigner table
    equip_col = 'NULL' if is_export else 'equipment_names'
    pipe_col = 'NULL' if is_export else 'pipeline_name'
    term_col = 'NULL' if is_export else 'unload_terminal'
    all_ids = sorted({pid for p in parcels for pid in _parse_ids(p['parcel_ids'])})
    labels, src_qty, src_equip, src_pipe, src_term = {}, {}, {}, {}, {}
    if all_ids:
        cur.execute(f'SELECT id, parcel_no, {qty_col} AS q, {equip_col} AS equip, {pipe_col} AS pipe, {term_col} AS term FROM {tbl} WHERE id = ANY(%s)', [all_ids])
        for r in cur.fetchall():
            labels[r['id']] = r['parcel_no'] or f"#{r['id']}"
            src_equip[r['id']] = r['equip'] or ''
            src_pipe[r['id']] = r['pipe'] or ''
            src_term[r['id']] = r['term'] or ''
            try:
                src_qty[r['id']] = float(str(r['q']).replace(',', '')) if r['q'] is not None else 0.0
            except (ValueError, TypeError):
                src_qty[r['id']] = 0.0

    # per-parcel target (current VCN parcel qty, falling back to the op snapshot)
    targets = {}
    for p in parcels:
        ids = _parse_ids(p['parcel_ids'])
        targets[p['parcel_op_id']] = sum(src_qty.get(i, 0.0) for i in ids) or float(p['op_qty'] or 0)

    # logged qty + operating hours per parcel (non-deleted), for total & avg flow rate.
    # ponytail: hardcoded completion cap — once cumulative qty reaches the target,
    # later log rows (top-ups, idle entries) are dropped from Run hours so they
    # can't drag the actual ETC out. Rows must be ordered for the cap to apply.
    pop_ids = [p['parcel_op_id'] for p in parcels]
    agg = {}  # parcel_op_id -> [logged_qty, hours]
    if pop_ids:
        cur.execute('''SELECT parcel_op_id, from_time, to_time, COALESCE(quantity,0) AS q
                       FROM lueu_parcel_log
                       WHERE parcel_op_id = ANY(%s) AND is_deleted IS NOT TRUE
                       ORDER BY parcel_op_id, entry_date, from_time, id''', [pop_ids])
        for r in cur.fetchall():
            a = agg.setdefault(r['parcel_op_id'], [0.0, 0.0])
            tgt = targets.get(r['parcel_op_id'], 0)
            if tgt > 0 and a[0] >= tgt - 1e-6:
                continue  # parcel already complete — ignore this row
            a[0] += float(r['q'] or 0)
            a[1] += _hours(r['from_time'], r['to_time'])
    conn.close()

    out = []
    for p in parcels:
        ids = _parse_ids(p['parcel_ids'])
        target = targets[p['parcel_op_id']]
        logged, hours = agg.get(p['parcel_op_id'], [0.0, 0.0])
        # distinct equipment / pipelines across the VCN parcel(s)
        def _distinct(src):
            vals = []
            for i in ids:
                for x in str(src.get(i, '')).split(','):
                    if x.strip() and x.strip() not in vals:
                        vals.append(x.strip())
            return vals
        equip = _distinct(src_equip)
        # terminal from the live VCN consigner (unload_terminal); fall back to the
        # op snapshot (covers export parcels + legacy rows without a source terminal)
        terminals = _distinct(src_term)
        out.append({
            'parcel_op_id': p['parcel_op_id'],
            'parcel_no': ', '.join(labels.get(i, f"#{i}") for i in ids) or '—',
            'cargo_name': p['cargo_name'] or '',
            'terminal_name': ', '.join(terminals) or (p['terminal_name'] or ''),
            'target_qty': round(target, 3),
            'logged_qty': round(logged, 3),
            'remaining_qty': round(target - logged, 3),
            'op_hours': round(hours, 2),
            'avg_rate': round(logged / hours, 2) if hours > 0 else 0,
            'uom': 'MT',
            'equipment_names': ', '.join(equip),
            'pipeline_name': ', '.join(_distinct(src_pipe)),
            'expected_start': p['expected_start'],
            'expected_flow_rate': _num(p['expected_flow_rate']),
            'alongside_datetime': p['alongside_datetime'],
            'start_dt': p['start_dt'],
            'end_dt': p['end_dt'],
            'status': 'Completed' if p['end_dt'] else 'In Progress',
        })
    return out


def set_expected_start(parcel_op_id, expected_start, expected_flow_rate=None):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('UPDATE ldud_parcel_ops SET expected_start=%s, expected_flow_rate=%s WHERE id=%s',
                [expected_start or None, _num(expected_flow_rate), parcel_op_id])
    conn.commit()
    conn.close()


def set_parcel_times(parcel_op_id, start_dt, end_dt):
    """Operators enter the parcel start/end here; persisted on ldud_parcel_ops."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('UPDATE ldud_parcel_ops SET start_dt=%s, end_dt=%s WHERE id=%s',
                [start_dt or None, end_dt or None, parcel_op_id])
    conn.commit()
    conn.close()


_LOG_COLS = ['parcel_op_id', 'entry_date', 'from_time', 'to_time', 'quantity',
             'pressure', 'quantity_uom', 'medium', 'equipment_name', 'delay_name',
             'shift', 'operator_name', 'shift_incharge', 'berth_name', 'remarks']


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
    data['pressure'] = _num(data.get('pressure'))
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
