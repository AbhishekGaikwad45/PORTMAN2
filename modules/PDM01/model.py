from database import get_db, get_cursor

TABLE = 'port_delay_types'

def get_data(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT COUNT(*) FROM {TABLE}')
    total = cur.fetchone()['count']
    cur.execute(f'SELECT * FROM {TABLE} ORDER BY id DESC LIMIT %s OFFSET %s', (size, (page-1)*size))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f"SELECT name FROM {TABLE} WHERE name IS NOT NULL AND name != '' ORDER BY name ASC")
    rows = cur.fetchall()
    conn.close()
    return [r['name'] for r in rows]

def save_data(data):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    name = data.get('name', '')
    to_sof = data.get('to_sof', '')
    dtype = data.get('type', '')

    if row_id:
        cur.execute(f"UPDATE {TABLE} SET name=%s, to_sof=%s, type=%s WHERE id=%s", [name, to_sof, dtype, row_id])
    else:
        cur.execute(f"INSERT INTO {TABLE} (name, to_sof, type) VALUES (%s, %s, %s) RETURNING id", [name, to_sof, dtype])
        row_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return row_id

def bulk_insert(rows):
    conn = get_db()
    cur = get_cursor(conn)
    inserted = 0
    for row in rows:
        if not row.get('name'):
            continue
        cur.execute(f"INSERT INTO {TABLE} (name, to_sof, type) VALUES (%s, %s, %s)",
                   [row.get('name', ''), row.get('to_sof', ''), row.get('type', '')])
        inserted += 1
    conn.commit()
    conn.close()
    return inserted

def delete_data(row_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f'DELETE FROM {TABLE} WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()
