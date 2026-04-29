from database import get_db, get_cursor

def get_data(page=1, size=50):
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT COUNT(*) FROM tank_master')
        total = cur.fetchone()['count']
        cur.execute('SELECT * FROM tank_master ORDER BY tank_code LIMIT %s OFFSET %s',
                    [size, (page - 1) * size])
        return [dict(r) for r in cur.fetchall()], total
    finally:
        conn.close()

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    if row_id:
        cur.execute('UPDATE tank_master SET tank_code=%s, tank_name=%s, is_active=%s WHERE id=%s',
                    [data.get('tank_code'), data.get('tank_name'), data.get('is_active', True), row_id])
    else:
        cur.execute('INSERT INTO tank_master (tank_code, tank_name, is_active) VALUES (%s, %s, %s) RETURNING id',
                    [data.get('tank_code'), data.get('tank_name'), data.get('is_active', True)])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM tank_master WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()
