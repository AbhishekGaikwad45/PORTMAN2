from database import get_db, get_cursor

TABLE = 'vessel_flags'

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
    flag_type = data.get('flag_type') or None

    if row_id:
        cur.execute(f"UPDATE {TABLE} SET name=%s, flag_type=%s WHERE id=%s", [name, flag_type, row_id])
    else:
        cur.execute(f"INSERT INTO {TABLE} (name, flag_type) VALUES (%s, %s) RETURNING id", [name, flag_type])
        row_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return row_id

def delete_data(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'DELETE FROM {TABLE} WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()
