from database import get_db, get_cursor


def get_all(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    offset = (page - 1) * size

    cur.execute('''
        SELECT * FROM conveyor_routes ORDER BY route_name LIMIT %s OFFSET %s
    ''', [size, offset])
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute('SELECT COUNT(*) as cnt FROM conveyor_routes')
    total = cur.fetchone()['cnt']
    conn.close()

    return {
        'data': rows,
        'last_page': (total + size - 1) // size if total > 0 else 1,
        'total': total
    }


def get_all_routes():
    """Get all active route names for dropdown"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT route_name FROM conveyor_routes WHERE is_active = 1 ORDER BY route_name')
    rows = [r['route_name'] for r in cur.fetchall()]
    conn.close()
    return rows


def save(data):
    conn = get_db()
    cur = get_cursor(conn)

    route_id = data.get('id')

    if route_id:
        cur.execute('''
            UPDATE conveyor_routes SET
                route_name = %s, description = %s, is_active = %s
            WHERE id = %s
        ''', [
            data.get('route_name'), data.get('description'),
            data.get('is_active', 1), route_id
        ])
    else:
        from datetime import datetime
        cur.execute('''
            INSERT INTO conveyor_routes (route_name, description, is_active, created_by, created_date)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        ''', [
            data.get('route_name'), data.get('description'),
            data.get('is_active', 1), data.get('created_by'),
            datetime.now().strftime('%Y-%m-%d')
        ])
        route_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return route_id


def delete(route_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM conveyor_routes WHERE id = %s', [route_id])
    conn.commit()
    conn.close()
