from database import get_db, get_cursor

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM equipment ORDER BY name')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute('UPDATE equipment SET name=%s WHERE id=%s', [data['name'], data['id']])
        row_id = data['id']
    else:
        cur.execute('INSERT INTO equipment (name) VALUES (%s) RETURNING id', [data['name']])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM equipment WHERE id=%s', [row_id])
    conn.commit()
    conn.close()
