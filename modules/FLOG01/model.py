from database import get_db, get_cursor


def get_logs(page=1, size=50, filters=None):
    conn = get_db()
    cur = get_cursor(conn)
    where = []
    params = []

    if filters:
        if filters.get('integration_type'):
            where.append('integration_type = %s')
            params.append(filters['integration_type'])
        if filters.get('status'):
            where.append('status = %s')
            params.append(filters['status'])
        if filters.get('date_from'):
            where.append('created_date >= %s')
            params.append(filters['date_from'])
        if filters.get('date_to'):
            where.append('created_date <= %s')
            params.append(filters['date_to'])

    where_sql = ' AND '.join(where) if where else '1=1'

    cur.execute(f'SELECT COUNT(*) as cnt FROM integration_logs WHERE {where_sql}', params)
    total = cur.fetchone()['cnt']
    cur.execute(f'''SELECT * FROM integration_logs
        WHERE {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s''',
        params + [size, (page - 1) * size])
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_log_detail(log_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM integration_logs WHERE id = %s', [log_id])
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None
