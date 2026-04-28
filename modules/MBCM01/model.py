from database import get_db, get_cursor

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM mbc_master ORDER BY mbc_name')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute('UPDATE mbc_master SET mbc_name=%s, dwt=%s, mbc_owner_name=%s WHERE id=%s',
                   [data.get('mbc_name'), data.get('dwt'), data.get('mbc_owner_name'), data['id']])
        row_id = data['id']
    else:
        cur.execute('INSERT INTO mbc_master (mbc_name, dwt, mbc_owner_name) VALUES (%s, %s, %s) RETURNING id',
                   [data.get('mbc_name'), data.get('dwt'), data.get('mbc_owner_name')])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM mbc_master WHERE id=%s', [row_id])
    conn.commit()
    conn.close()
