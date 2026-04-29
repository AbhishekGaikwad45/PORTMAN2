from database import get_db, get_cursor


def _ensure_agent(code, cur):
    code = code.strip()
    if not code:
        return
    cur.execute('SELECT id FROM vessel_agents WHERE agent_code=%s', [code])
    if not cur.fetchone():
        cur.execute('INSERT INTO vessel_agents (agent_code, name, is_active) VALUES (%s, %s, 1)', [code, code])


def _ensure_tank(code, cur):
    code = code.strip()
    if not code:
        return
    cur.execute('SELECT id FROM tank_master WHERE tank_code=%s', [code])
    if not cur.fetchone():
        cur.execute('INSERT INTO tank_master (tank_code, tank_name, is_active) VALUES (%s, %s, TRUE)', [code, code])


def _ensure_consignee(code, cur):
    code = code.strip()
    if not code:
        return
    cur.execute('SELECT id FROM vessel_customers WHERE customer_code=%s', [code])
    if not cur.fetchone():
        cur.execute("INSERT INTO vessel_customers (customer_code, name, default_currency) VALUES (%s, %s, 'INR')", [code, code])


def _ensure_cargo(name, cur):
    name = name.strip()
    if not name:
        return
    cur.execute("SELECT id FROM vessel_cargo WHERE cargo_name=%s", [name])
    if not cur.fetchone():
        cur.execute("INSERT INTO vessel_cargo (cargo_name, cargo_type, cargo_category) VALUES (%s, '', '')", [name])


def upsert_from_pdf(rows, username):
    conn = get_db()
    cur = get_cursor(conn)
    inserted = updated = 0
    _skip = {'id', 'vcn_id', 'doc_status', 'created_by', 'created_at'}

    for row in rows:
        for code in (row.get('agents') or '').split(','):
            _ensure_agent(code, cur)
        for code in (row.get('tanks') or '').split(','):
            _ensure_tank(code, cur)
        for code in (row.get('consignees') or '').split(','):
            _ensure_consignee(code, cur)
        for name in (row.get('cargo_name') or '').split(','):
            _ensure_cargo(name, cur)

        via = row.get('via_number')
        data_cols = {k: v for k, v in row.items() if k not in _skip and v is not None}

        if via:
            cur.execute('SELECT id FROM expected_vessels WHERE via_number=%s', [via])
            existing = cur.fetchone()
            if existing:
                if data_cols:
                    cur.execute(
                        f"UPDATE expected_vessels SET {', '.join(f'{c}=%s' for c in data_cols)} WHERE via_number=%s",
                        list(data_cols.values()) + [via]
                    )
                updated += 1
                continue

        data_cols['created_by'] = username
        data_cols['doc_status'] = 'Pending'
        cols = list(data_cols)
        cur.execute(
            f"INSERT INTO expected_vessels ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})",
            [data_cols[c] for c in cols]
        )
        inserted += 1

    conn.commit()
    conn.close()
    return {'inserted': inserted, 'updated': updated}


def _clean_empty(data):
    for k in list(data.keys()):
        if data[k] == '':
            data[k] = None
    return data

def get_data(page=1, size=20, filters=None):
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT COUNT(*) FROM expected_vessels')
        total = cur.fetchone()['count']
        cur.execute('SELECT * FROM expected_vessels ORDER BY id DESC LIMIT %s OFFSET %s',
                    [size, (page - 1) * size])
        return [dict(r) for r in cur.fetchall()], total
    finally:
        conn.close()

def save(data, username=None):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    _computed = {'id', 'vcn_id', 'doc_status', 'created_by', 'created_at'}
    row_id = data.get('id')
    if row_id:
        cols = [k for k in data if k not in _computed]
        cur.execute(
            f"UPDATE expected_vessels SET {', '.join(f'{c}=%s' for c in cols)} WHERE id=%s",
            [data[c] for c in cols] + [row_id]
        )
    else:
        data['created_by'] = username
        cols = [k for k in data if k not in {'id'}]
        cur.execute(
            f"INSERT INTO expected_vessels ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))}) RETURNING id",
            [data[c] for c in cols]
        )
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM expected_vessels WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

def get_by_id(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM expected_vessels WHERE id=%s', (row_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def mark_moved_to_vcn(ev_id, vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(
        "UPDATE expected_vessels SET vcn_id=%s, doc_status='Moved to VCN' WHERE id=%s",
        [vcn_id, ev_id]
    )
    conn.commit()
    conn.close()
