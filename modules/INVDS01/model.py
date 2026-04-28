from database import get_db, get_cursor

TABLE = 'invoice_doc_series'

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
    cur.execute(f"SELECT id, name, prefix, is_default FROM {TABLE} ORDER BY name ASC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_data(data):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    name = data.get('name', '')
    prefix = (data.get('prefix', '') or '').upper().strip()
    is_default = bool(data.get('is_default', False))

    if is_default:
        cur.execute(f"UPDATE {TABLE} SET is_default = FALSE WHERE is_default = TRUE")

    if row_id:
        cur.execute(f"UPDATE {TABLE} SET name=%s, prefix=%s, is_default=%s WHERE id=%s",
                    [name, prefix, is_default, row_id])
    else:
        cur.execute(f"INSERT INTO {TABLE} (name, prefix, is_default) VALUES (%s, %s, %s) RETURNING id",
                    [name, prefix, is_default])
        row_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return row_id

def delete_data(row_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f'DELETE FROM {TABLE} WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()
