from database import get_db, get_cursor

TABLE = 'port_master'

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f"SELECT name FROM {TABLE} WHERE name IS NOT NULL AND name != '' ORDER BY name ASC")
    rows = [r['name'] for r in cur.fetchall()]
    conn.close()
    return rows

def get_data(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT COUNT(*) FROM {TABLE}')
    total = cur.fetchone()['count']
    cur.execute(f'SELECT * FROM {TABLE} ORDER BY id DESC LIMIT %s OFFSET %s', (size, (page-1)*size))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows, total

def save_data(data):
    conn = get_db()
    cur = get_cursor(conn)
    name = data.get('name', '')

    if data.get('id'):
        cur.execute(f"UPDATE {TABLE} SET name=%s WHERE id=%s", [name, data['id']])
        row_id = data['id']
    else:
        cur.execute(f"INSERT INTO {TABLE} (name) VALUES (%s) RETURNING id", [name])
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
