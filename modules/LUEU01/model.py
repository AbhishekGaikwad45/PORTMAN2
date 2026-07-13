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
               po.expected_flow_rate, l.alongside_datetime, l.doc_status AS ldud_status
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
    # export parcels mirror import since jnpa35 — same columns on both tables
    all_ids = sorted({pid for p in parcels for pid in _parse_ids(p['parcel_ids'])})
    labels, src_qty, src_equip, src_pipe, src_term = {}, {}, {}, {}, {}
    if all_ids:
        cur.execute(f'''SELECT id, parcel_no, quantity AS q, equipment_names AS equip,
                               pipeline_name AS pipe, unload_terminal AS term
                        FROM {tbl} WHERE id = ANY(%s)''', [all_ids])
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
        cur.execute('''SELECT parcel_op_id, from_time, to_time, COALESCE(quantity,0) AS q, is_shortclose
                       FROM lueu_parcel_log
                       WHERE parcel_op_id = ANY(%s) AND is_deleted IS NOT TRUE
                       ORDER BY parcel_op_id, entry_date, from_time NULLS LAST, id''', [pop_ids])
        for r in cur.fetchall():
            a = agg.setdefault(r['parcel_op_id'], [0.0, 0.0, 0.0])  # [real_qty, hours, shortclose_qty]
            tgt = targets.get(r['parcel_op_id'], 0)
            if tgt > 0 and (a[0] + a[2]) >= tgt - 1e-6:
                continue  # parcel already complete — ignore this row
            if r['is_shortclose']:
                a[2] += float(r['q'] or 0)  # counts toward completion, NOT toward avg rate
            else:
                a[0] += float(r['q'] or 0)
                a[1] += _hours(r['from_time'], r['to_time'])
    conn.close()

    out = []
    for p in parcels:
        ids = _parse_ids(p['parcel_ids'])
        target = targets[p['parcel_op_id']]
        logged_real, hours, shortclosed = agg.get(p['parcel_op_id'], [0.0, 0.0, 0.0])
        logged = logged_real + shortclosed  # total toward target (Remaining)
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
            'avg_rate': round(logged_real / hours, 2) if hours > 0 else 0,
            'is_shortclosed': shortclosed > 1e-6,
            'uom': 'MT',
            'equipment_names': ', '.join(equip),
            'pipeline_name': ', '.join(_distinct(src_pipe)),
            'expected_start': p['expected_start'],
            'expected_flow_rate': _num(p['expected_flow_rate']),
            'alongside_datetime': p['alongside_datetime'],
            'ldud_status': p['ldud_status'],
            'start_dt': p['start_dt'],
            'end_dt': p['end_dt'],
            'status': 'Completed' if p['end_dt'] else 'In Progress',
        })
    return out


def ops_locked(parcel_op_ids):
    """True if any parcel op belongs to a fully Closed LDUD — LUEU01 entry is
    then locked. (Partial Close is a billing cut-off; ops may continue.)"""
    ids = [int(i) for i in parcel_op_ids if i]
    if not ids:
        return False
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT 1 FROM ldud_parcel_ops po
                   JOIN ldud_header l ON l.id = po.ldud_id
                   WHERE po.id = ANY(%s) AND l.doc_status = 'Closed' LIMIT 1''', [ids])
    locked = cur.fetchone() is not None
    conn.close()
    return locked


def logs_locked(log_ids):
    """True if any logbook row belongs to a fully Closed LDUD."""
    ids = [int(i) for i in log_ids if i]
    if not ids:
        return False
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT 1 FROM lueu_parcel_log lg
                   JOIN ldud_parcel_ops po ON po.id = lg.parcel_op_id
                   JOIN ldud_header l ON l.id = po.ldud_id
                   WHERE lg.id = ANY(%s) AND l.doc_status = 'Closed' LIMIT 1''', [ids])
    locked = cur.fetchone() is not None
    conn.close()
    return locked


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


def _single_parcel_target(cur, parcel_op_id):
    """Target qty for one parcel-op: sum of its VCN parcel quantities (import or
    export source table), falling back to the op snapshot quantity. Mirrors the
    per-parcel target logic in get_started_parcels."""
    cur.execute('''SELECT po.parcel_ids, po.quantity AS op_qty, l.vcn_id
                   FROM ldud_parcel_ops po JOIN ldud_header l ON l.id = po.ldud_id
                   WHERE po.id=%s''', [parcel_op_id])
    row = cur.fetchone()
    if not row:
        return 0.0
    ids = _parse_ids(row['parcel_ids'])
    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [row['vcn_id']])
    op = cur.fetchone()
    tbl = 'vcn_export_cargo_declaration' if (op or {}).get('operation_type') == 'Export' else 'vcn_consigners'
    total = 0.0
    if ids:
        cur.execute(f'SELECT quantity FROM {tbl} WHERE id = ANY(%s)', [ids])
        for r in cur.fetchall():
            try:
                total += float(str(r['quantity']).replace(',', '')) if r['quantity'] else 0.0
            except (ValueError, TypeError):
                pass
    return total or float(row['op_qty'] or 0)


def shortclose_parcel(parcel_op_id, username):
    """Close a parcel's leftover quantity: insert one flagged, timeless log row
    carrying the remaining qty so Remaining -> 0. Raises ValueError if nothing
    is left to close. Reversible via revert_shortclose."""
    conn = get_db()
    cur = get_cursor(conn)
    target = _single_parcel_target(cur, parcel_op_id)
    cur.execute('''SELECT COALESCE(SUM(quantity), 0) AS q FROM lueu_parcel_log
                   WHERE parcel_op_id=%s AND is_deleted IS NOT TRUE''', [parcel_op_id])
    logged = float(cur.fetchone()['q'] or 0)
    remaining = round(target - logged, 3)
    if remaining <= 1e-6:
        conn.close()
        raise ValueError('Nothing to short-close — no remaining quantity')
    today = datetime.now().strftime('%Y-%m-%d')
    cur.execute('''INSERT INTO lueu_parcel_log
                   (parcel_op_id, entry_date, quantity, quantity_uom, is_shortclose,
                    remarks, created_by, created_date)
                   VALUES (%s, %s, %s, 'MT', TRUE, 'Short close', %s, %s) RETURNING id''',
                [parcel_op_id, today, remaining, username, today])
    row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id


def revert_shortclose(parcel_op_id, username):
    """Undo a short-close: soft-delete the parcel's short-close row(s), restoring
    the previous Remaining and avg rate. Raises ValueError if there is none."""
    conn = get_db()
    cur = get_cursor(conn)
    today = datetime.now().strftime('%Y-%m-%d')
    cur.execute('''UPDATE lueu_parcel_log
                   SET is_deleted=TRUE, deleted_by=%s, deleted_date=%s
                   WHERE parcel_op_id=%s AND is_shortclose IS TRUE AND is_deleted IS NOT TRUE''',
                [username, today, parcel_op_id])
    n = cur.rowcount
    conn.commit()
    conn.close()
    if not n:
        raise ValueError('No short-close to revert')
    return n
