from database import get_db, get_cursor

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM barges ORDER BY barge_name')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute('UPDATE barges SET barge_name=%s, dwt=%s, barge_owner_name=%s, barge_owner_email=%s WHERE id=%s',
                   [data.get('barge_name'), data.get('dwt'), data.get('barge_owner_name'), data.get('barge_owner_email'), data['id']])
        row_id = data['id']
    else:
        cur.execute('INSERT INTO barges (barge_name, dwt, barge_owner_name, barge_owner_email) VALUES (%s, %s, %s, %s) RETURNING id',
                   [data.get('barge_name'), data.get('dwt'), data.get('barge_owner_name'), data.get('barge_owner_email')])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM barges WHERE id=%s', [row_id])
    conn.commit()
    conn.close()
