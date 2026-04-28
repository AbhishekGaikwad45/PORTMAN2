from database import get_db, get_cursor, get_module_table

TABLE = get_module_table('TM01') or 'tide_master'


def get_data(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT COUNT(*) FROM {TABLE}')
    total = cur.fetchone()['count']
    cur.execute(
        f'SELECT * FROM {TABLE} ORDER BY tide_datetime DESC NULLS LAST, id DESC LIMIT %s OFFSET %s',
        (size, (page - 1) * size)
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def save(data):
    conn = get_db()
    cur = get_cursor(conn)

    if data.get('id'):
        cur.execute(
            f'UPDATE {TABLE} SET tide_datetime=%s, tide_meters=%s WHERE id=%s',
            [data.get('tide_datetime'), data.get('tide_meters'), data['id']]
        )
        row_id = data['id']
    else:
        cur.execute(
            f'INSERT INTO {TABLE} (tide_datetime, tide_meters) VALUES (%s, %s) RETURNING id',
            [data.get('tide_datetime'), data.get('tide_meters')]
        )
        row_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return row_id


def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'DELETE FROM {TABLE} WHERE id=%s', [row_id])
    conn.commit()
    conn.close()
