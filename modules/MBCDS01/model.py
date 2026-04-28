from database import get_db, get_cursor

TABLE = 'mbc_doc_series'

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT name, is_default FROM {TABLE} ORDER BY name')
    rows = [{'name': r['name'], 'is_default': r['is_default']} for r in cur.fetchall()]
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
    is_default = bool(data.get('is_default', False))

    if is_default:
        cur.execute(f"UPDATE {TABLE} SET is_default = FALSE WHERE is_default = TRUE")

    if data.get('id'):
        cur.execute(f"UPDATE {TABLE} SET name=%s, is_default=%s WHERE id=%s", [name, is_default, data['id']])
        row_id = data['id']
    else:
        cur.execute(f"INSERT INTO {TABLE} (name, is_default) VALUES (%s, %s) RETURNING id", [name, is_default])
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
