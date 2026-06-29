from database import get_db, get_cursor

def _clean_empty(data):
    """Convert empty strings to None so timestamp/date columns get NULL."""
    for k in data:
        if data[k] == '':
            data[k] = None
    return data

def get_next_doc_num():
    import datetime
    conn = get_db()
    cur = get_cursor(conn)
    now = datetime.datetime.now()
    fy_start = now.year if now.month >= 4 else now.year - 1
    fy_suffix = f"{str(fy_start)[2:]}{str(fy_start + 1)[2:]}"  # e.g. "2526"
    prefix = f"VCN-{fy_suffix}-"
    cur.execute(
        "SELECT MAX(CAST(SPLIT_PART(vcn_doc_num, '-', 3) AS INTEGER)) FROM vcn_header WHERE vcn_doc_num LIKE %s",
        (prefix + '%',)
    )
    result = cur.fetchone()['max']
    conn.close()
    next_num = (result or 0) + 1
    return f"{prefix}{next_num:03d}"

def get_vessels():
    """Get vessels from VC01 for dropdown"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT doc_num, vessel_name, pbl FROM vessels ORDER BY doc_num')
    rows = cur.fetchall()
    conn.close()
    return [{'value': f"{r['doc_num']}/{r['vessel_name']}", 'doc_num': r['doc_num'],
             'vessel_name': r['vessel_name'], 'pbl': r['pbl']} for r in rows]

def get_data(page=1, size=20, filters=None):
    conn = get_db()
    cur = get_cursor(conn)

    allowed = {'operation_type','vcn_doc_num','vessel_name','vessel_agent_name',
               'cargo_type','doc_status','doc_date',
               'customer_name','load_port','discharge_port'}
    where_clauses, params = [], []
    for f in (filters or []):
        field = f.get('field', '')
        if field not in allowed:
            continue
        ftype = f.get('type')
        if ftype == 'contains' and f.get('value'):
            where_clauses.append(f"{field} ILIKE %s")
            params.append(f"%{f['value']}%")
        elif ftype == 'multi' and f.get('values'):
            ph = ','.join(['%s'] * len(f['values']))
            where_clauses.append(f"{field} IN ({ph})")
            params.extend(f['values'])
        elif ftype == 'range':
            if f.get('from'):
                where_clauses.append(f"{field} >= %s")
                params.append(f['from'])
            if f.get('to'):
                where_clauses.append(f"{field} <= %s")
                params.append(f['to'])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    try:
        cur.execute(f'SELECT COUNT(*) FROM vcn_header {where_sql}', params)
        total = cur.fetchone()['count']
        cur.execute(f'SELECT * FROM vcn_header {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s',
                    params + [size, (page - 1) * size])
        rows = []
        for r in cur.fetchall():
            r = dict(r)
            r.pop('igm_document', None)   # BYTEA — not JSON-serializable
            r['has_igm_doc'] = bool(r.get('igm_document_name'))
            rows.append(r)
        return rows, total
    finally:
        conn.close()

def save_header(data):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')

    # computed / blob fields never come through the JSON save path
    for k in ('has_igm_doc', 'igm_document', 'igm_document_name'):
        data.pop(k, None)

    if row_id:
        cols = [k for k in data if k not in ['id', 'vcn_doc_num']]
        cur.execute(f"UPDATE vcn_header SET {', '.join([f'{c}=%s' for c in cols])} WHERE id=%s",
                   [data[c] for c in cols] + [row_id])
    else:
        data['vcn_doc_num'] = get_next_doc_num()
        cols = [k for k in data if k != 'id']
        cur.execute(f"INSERT INTO vcn_header ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))}) RETURNING id",
                   [data[c] for c in cols])
        row_id = cur.fetchone()['id']

    # PBL entered on the VCN flows back to the VC01 vessel master (one-way; only
    # when provided, so a blank never clears the master). vessel_master_doc is
    # 'DOCNUM/NAME' — match the vessel by its doc_num.
    pbl = data.get('pbl')
    vmd = data.get('vessel_master_doc')
    if pbl not in (None, '') and vmd:
        cur.execute('UPDATE vessels SET pbl=%s WHERE doc_num=%s', [pbl, str(vmd).split('/', 1)[0]])

    conn.commit()
    conn.close()
    return row_id, data.get('vcn_doc_num')

def delete_header(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM vcn_header WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

# Consigner (customer details) sub-table — each row is one PARCEL (one IGM/FORM III
# line: product + receiver + BL). vessel agent is captured on the header.
_CONSIGNER_COLS = ['igm_line_no', 'bl_no', 'bl_date', 'cargo_name', 'quantity',
                   'consigner_name', 'importer_name',
                   'pipeline_name', 'unload_terminal',
                   'toll_applicable', 'equipment_names']


def get_equipment():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT name FROM equipment ORDER BY name')
    rows = [r['name'] for r in cur.fetchall()]
    conn.close()
    return rows


def _parcel_no(cur, vcn_id, seq):
    """Build the stored parcel label '<vcn_doc_num>/P<seq>' (or 'P<seq>' if the
    parent VCN has no doc number yet — e.g. a brand-new draft)."""
    cur.execute('SELECT vcn_doc_num FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    doc = (row or {}).get('vcn_doc_num') if row else None
    return f"{doc}/P{seq}" if doc else f"P{seq}"


def get_parcels(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM vcn_consigners WHERE vcn_id=%s ORDER BY parcel_seq NULLS LAST, id',
                (vcn_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_parcel(row_id):
    """Single parcel row — used to return the generated parcel_no after a save."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT id, parcel_no, parcel_seq FROM vcn_consigners WHERE id=%s', [row_id])
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

# back-compat alias — existing callers/endpoints use get_consigners
get_consigners = get_parcels


def _operation_type(cur, vcn_id):
    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    return (row or {}).get('operation_type') if row else None


def get_picker_parcels(vcn_id):
    """Operation-type-aware parcel list for cross-module pickers (LDUD).
    Import → consigner rows; Export → export cargo declaration rows.
    Returns: id, parcel_no, cargo_name, consigner_name, quantity, terminals (list).
    Terminals come from the import consigner's unload_terminal (multi-value, comma
    separated); Export parcels have no terminal source → empty list."""
    conn = get_db()
    cur = get_cursor(conn)
    is_export = _operation_type(cur, vcn_id) == 'Export'
    if is_export:
        cur.execute('''SELECT id, parcel_no, cargo_name, customer_name AS consigner_name,
                              bl_quantity AS quantity, NULL AS unload_terminal
                       FROM vcn_export_cargo_declaration WHERE vcn_id=%s
                       ORDER BY parcel_seq NULLS LAST, id''', (vcn_id,))
    else:
        cur.execute('''SELECT id, parcel_no, cargo_name, consigner_name, quantity, unload_terminal
                       FROM vcn_consigners WHERE vcn_id=%s
                       ORDER BY parcel_seq NULLS LAST, id''', (vcn_id,))
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d['terminals'] = [t.strip() for t in str(d.pop('unload_terminal', '') or '').split(',') if t.strip()]
        rows.append(d)
    conn.close()
    return rows


def get_export_parcel(row_id):
    """Single export-cargo parcel — returns generated parcel_no after a save."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT id, parcel_no, parcel_seq FROM vcn_export_cargo_declaration WHERE id=%s', [row_id])
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _parse_qty(v):
    try:
        return float(str(v).replace(',', '')) if v not in (None, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


def save_consigner(data):
    # The per-cargo quota (from EV01) is informational only — the "Available per
    # cargo" panel shows allocated vs total and flags over-allocation, but parcels
    # are NOT blocked from exceeding it.
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute(f"UPDATE vcn_consigners SET {', '.join(f'{c}=%s' for c in _CONSIGNER_COLS)} WHERE id=%s",
                   [data.get(c) for c in _CONSIGNER_COLS] + [data['id']])
        row_id = data['id']
        # backfill parcel_no if it was created on a draft before the VCN had a doc number
        cur.execute('SELECT parcel_seq, parcel_no FROM vcn_consigners WHERE id=%s', [row_id])
        cur_row = cur.fetchone()
        if cur_row and cur_row['parcel_seq'] and not cur_row['parcel_no']:
            cur.execute('UPDATE vcn_consigners SET parcel_no=%s WHERE id=%s',
                        [_parcel_no(cur, data['vcn_id'], cur_row['parcel_seq']), row_id])
    else:
        cur.execute('SELECT COALESCE(MAX(parcel_seq), 0) + 1 AS nxt FROM vcn_consigners WHERE vcn_id=%s',
                    [data['vcn_id']])
        seq = cur.fetchone()['nxt']
        parcel_no = _parcel_no(cur, data['vcn_id'], seq)
        cols = _CONSIGNER_COLS + ['parcel_seq', 'parcel_no']
        vals = [data.get(c) for c in _CONSIGNER_COLS] + [seq, parcel_no]
        cur.execute(f'''INSERT INTO vcn_consigners (vcn_id, {', '.join(cols)})
                       VALUES ({', '.join(['%s'] * (len(cols) + 1))}) RETURNING id''',
                   [data['vcn_id']] + vals)
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

# back-compat alias
save_parcel = save_consigner


def save_cargo_quotas(vcn_id, quotas):
    """Upsert per-cargo totals {cargo_name: qty} for a VCN (captured on EV01 move)."""
    conn = get_db()
    cur = get_cursor(conn)
    for cargo, qty in (quotas or {}).items():
        cur.execute('''INSERT INTO vcn_cargo_quota (vcn_id, cargo_name, total_qty)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (vcn_id, cargo_name) DO UPDATE SET total_qty = EXCLUDED.total_qty''',
                    [vcn_id, cargo, qty])
    conn.commit()
    conn.close()


def get_cargo_quotas(vcn_id):
    """Per-cargo available/allocated/remaining for a VCN's parcel allocation."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT cargo_name, total_qty FROM vcn_cargo_quota WHERE vcn_id=%s ORDER BY cargo_name', [vcn_id])
    quotas = [dict(r) for r in cur.fetchall()]
    cur.execute('SELECT cargo_name, quantity FROM vcn_consigners WHERE vcn_id=%s', [vcn_id])
    alloc = {}
    for r in cur.fetchall():
        alloc[r['cargo_name']] = alloc.get(r['cargo_name'], 0.0) + _parse_qty(r['quantity'])
    conn.close()
    out = []
    for q in quotas:
        total = float(q['total_qty'] or 0)
        a = round(alloc.get(q['cargo_name'], 0.0), 3)
        out.append({'cargo_name': q['cargo_name'], 'total_qty': round(total, 3),
                    'allocated': a, 'remaining': round(total - a, 3)})
    return out

def save_igm_document(vcn_id, filename, file_bytes):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('UPDATE vcn_header SET igm_document=%s, igm_document_name=%s WHERE id=%s',
                [file_bytes, filename, vcn_id])
    conn.commit()
    conn.close()

def get_igm_document(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT igm_document, igm_document_name FROM vcn_header WHERE id=%s', (vcn_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row['igm_document']:
        return None, None
    return bytes(row['igm_document']), row['igm_document_name']

def delete_consigner(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM vcn_consigners WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

# Delays sub-table operations
def get_delays(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM vcn_delays WHERE vcn_id=%s ORDER BY id DESC', (vcn_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_delay(data):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute('UPDATE vcn_delays SET delay_name=%s, delay_start=%s, delay_end=%s WHERE id=%s',
                   [data.get('delay_name'), data.get('delay_start'), data.get('delay_end'), data['id']])
        row_id = data['id']
    else:
        cur.execute('INSERT INTO vcn_delays (vcn_id, delay_name, delay_start, delay_end) VALUES (%s, %s, %s, %s) RETURNING id',
                   [data['vcn_id'], data.get('delay_name'), data.get('delay_start'), data.get('delay_end')])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete_delay(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM vcn_delays WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

# Import cargo is declared in the consigner table now; vcn_cargo_declaration
# remains read-only for historic data (billing/LDUD still query it).
def get_all_cargo_names_for_vcn(vcn_id):
    """All cargo names for a VCN — consigners plus historic declarations."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT DISTINCT cargo_name FROM (
            SELECT cargo_name FROM vcn_consigners WHERE vcn_id=%s AND cargo_name IS NOT NULL
            UNION
            SELECT cargo_name FROM vcn_cargo_declaration WHERE vcn_id=%s AND cargo_name IS NOT NULL
            UNION
            SELECT cargo_name FROM vcn_export_cargo_declaration WHERE vcn_id=%s AND cargo_name IS NOT NULL
        ) combined ORDER BY cargo_name
    ''', (vcn_id, vcn_id, vcn_id))
    rows = cur.fetchall()
    conn.close()
    names = []
    for r in rows:
        if not r['cargo_name']:
            continue
        # consigner rows may hold comma-separated cargo lists
        for name in r['cargo_name'].split(','):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return sorted(names)

# Export Cargo Declaration sub-table operations
def get_export_cargo_declarations(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM vcn_export_cargo_declaration WHERE vcn_id=%s ORDER BY id DESC', (vcn_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_export_cargo_declaration(data):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute('''UPDATE vcn_export_cargo_declaration SET egm_shipping_bill_number=%s, egm_shipping_bill_date=%s,
                       cargo_name=%s, customer_name=%s, bl_no=%s, bl_date=%s, bl_quantity=%s, quantity_uom=%s WHERE id=%s''',
                   [data.get('egm_shipping_bill_number'), data.get('egm_shipping_bill_date'),
                    data.get('cargo_name'), data.get('customer_name'),
                    data.get('bl_no'), data.get('bl_date'), data.get('bl_quantity'),
                    data.get('quantity_uom'), data['id']])
        row_id = data['id']
        # backfill parcel_no if created before the VCN had a doc number
        cur.execute('SELECT parcel_seq, parcel_no FROM vcn_export_cargo_declaration WHERE id=%s', [row_id])
        cur_row = cur.fetchone()
        if cur_row and cur_row['parcel_seq'] and not cur_row['parcel_no']:
            cur.execute('UPDATE vcn_export_cargo_declaration SET parcel_no=%s WHERE id=%s',
                        [_parcel_no(cur, data['vcn_id'], cur_row['parcel_seq']), row_id])
    else:
        cur.execute('SELECT COALESCE(MAX(parcel_seq), 0) + 1 AS nxt FROM vcn_export_cargo_declaration WHERE vcn_id=%s',
                    [data['vcn_id']])
        seq = cur.fetchone()['nxt']
        parcel_no = _parcel_no(cur, data['vcn_id'], seq)
        cur.execute('''INSERT INTO vcn_export_cargo_declaration (vcn_id, egm_shipping_bill_number, egm_shipping_bill_date,
                       cargo_name, customer_name, bl_no, bl_date, bl_quantity, quantity_uom, parcel_seq, parcel_no)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
                   [data['vcn_id'], data.get('egm_shipping_bill_number'), data.get('egm_shipping_bill_date'),
                    data.get('cargo_name'), data.get('customer_name'),
                    data.get('bl_no'), data.get('bl_date'), data.get('bl_quantity'),
                    data.get('quantity_uom'), seq, parcel_no])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete_export_cargo_declaration(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM vcn_export_cargo_declaration WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

def get_export_cargo_names_for_vcn(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT DISTINCT cargo_name FROM vcn_export_cargo_declaration WHERE vcn_id=%s AND cargo_name IS NOT NULL', (vcn_id,))
    rows = cur.fetchall()
    conn.close()
    return [r['cargo_name'] for r in rows if r['cargo_name']]

def get_export_cargo_total_quantity(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT SUM(bl_quantity) FROM vcn_export_cargo_declaration WHERE vcn_id=%s', (vcn_id,))
    result = cur.fetchone()['sum']
    conn.close()
    return result or 0

def get_export_loading_totals(vcn_id):
    """Loading totals per cargo. ponytail: ldud_vessel_operations was dropped
    when LDUD01 moved to parcel-based ops; returns empty until re-sourced."""
    return {}


def get_hold_completion_by_vcn(vcn_id):
    """Hold completion across LDUDs for a VCN. ponytail: ldud_hold_completion
    was dropped; returns empty until the parcel-based ops flow re-feeds it."""
    return []


# Approval functions
def get_doc_status(record_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT doc_status FROM vcn_header WHERE id=%s', (record_id,))
    row = cur.fetchone()
    conn.close()
    return row['doc_status'] if row else None


def get_approval_eligibility(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT operation_type, vessel_name, vessel_agent_name,
                          cargo_type, discharge_port
                   FROM vcn_header WHERE id=%s''', (vcn_id,))
    header = cur.fetchone()
    if not header:
        conn.close()
        return {'eligible': False, 'missing': ['Record not found']}

    missing = []
    if not header['operation_type']:
        missing.append('Operation Type')
    if not header['vessel_name']:
        missing.append('Vessel Name')
    if not header['vessel_agent_name']:
        missing.append('Agent Name')
    if not header['cargo_type']:
        missing.append('Cargo Type')
    if not header['discharge_port']:
        missing.append('Discharge Port')

    op_type = header['operation_type']
    if op_type == 'Export':
        cur.execute('''SELECT COUNT(*) as cnt FROM vcn_export_cargo_declaration
                       WHERE vcn_id=%s AND cargo_name IS NOT NULL AND cargo_name != \'\'
                       AND bl_quantity IS NOT NULL AND bl_quantity > 0
                       AND quantity_uom IS NOT NULL AND quantity_uom != \'\'
                       AND bl_no IS NOT NULL AND bl_no != \'\'
                       AND bl_date IS NOT NULL''', (vcn_id,))
        if cur.fetchone()['cnt'] < 1:
            missing.append('Export Cargo Declaration (min 1 complete entry: cargo name, BL no, date, quantity, UOM)')
    else:
        # import cargo is declared via the Parcels (consigner) table
        cur.execute('''SELECT COUNT(*) as cnt FROM vcn_consigners
                       WHERE vcn_id=%s AND consigner_name IS NOT NULL AND consigner_name != \'\'
                       AND cargo_name IS NOT NULL AND cargo_name != \'\'
                       AND quantity IS NOT NULL AND quantity != \'\'''', (vcn_id,))
        if cur.fetchone()['cnt'] < 1:
            missing.append('Parcels (min 1 entry with consignee, cargo and quantity)')

    conn.close()
    return {'eligible': len(missing) == 0, 'missing': missing}


def approve_record(record_id, username):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("UPDATE vcn_header SET doc_status='Approved' WHERE id=%s", (record_id,))
    cur.execute("""INSERT INTO approval_log (module_code, record_id, action, comment, actioned_by)
                   VALUES ('VCN01', %s, 'Approved', NULL, %s)""", (record_id, username))
    conn.commit()
    conn.close()


def send_back_to_draft(record_id, comment, username):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("UPDATE vcn_header SET doc_status='Draft' WHERE id=%s", (record_id,))
    cur.execute("""INSERT INTO approval_log (module_code, record_id, action, comment, actioned_by)
                   VALUES ('VCN01', %s, 'Back to Draft', %s, %s)""", (record_id, comment, username))
    conn.commit()
    conn.close()


def get_approval_log(record_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("""SELECT action, comment, actioned_by,
                          to_char(actioned_at, 'DD-MM-YYYY HH24:MI') AS actioned_at
                   FROM approval_log WHERE module_code='VCN01' AND record_id=%s
                   ORDER BY actioned_at DESC""", (record_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
