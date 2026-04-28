from database import get_db, get_cursor

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM port_berth_master ORDER BY berth_name')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute('UPDATE port_berth_master SET berth_name=%s, berth_location=%s, remarks=%s WHERE id=%s',
                   [data.get('berth_name'), data.get('berth_location'), data.get('remarks'), data['id']])
        row_id = data['id']
    else:
        cur.execute('INSERT INTO port_berth_master (berth_name, berth_location, remarks) VALUES (%s, %s, %s) RETURNING id',
                   [data.get('berth_name'), data.get('berth_location'), data.get('remarks')])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM port_berth_master WHERE id=%s', [row_id])
    conn.commit()
    conn.close()
