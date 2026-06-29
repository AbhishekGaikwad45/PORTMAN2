from database import get_db, get_cursor

TABLE = 'port_master'

def get_all():
    """Ports with their codes for dropdowns (search by code or name)."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f"SELECT name, port_code FROM {TABLE} WHERE name IS NOT NULL AND name != '' ORDER BY name ASC")
    rows = [{'name': r['name'], 'port_code': r['port_code'] or ''} for r in cur.fetchall()]
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
    port_code = data.get('port_code') or None

    if data.get('id'):
        cur.execute(f"UPDATE {TABLE} SET name=%s, port_code=%s WHERE id=%s", [name, port_code, data['id']])
        row_id = data['id']
    else:
        cur.execute(f"INSERT INTO {TABLE} (name, port_code) VALUES (%s, %s) RETURNING id", [name, port_code])
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
