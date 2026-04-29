from database import get_db, get_cursor

def get_data(page=1, size=50, filters=None):
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('''SELECT COUNT(*) FROM pipeline_terminal_mapping m
                       JOIN pipeline_master p ON p.id = m.pipeline_id
                       JOIN terminal_master t ON t.id = m.terminal_id''')
        total = cur.fetchone()['count']
        cur.execute('''SELECT m.id, p.pipeline_name, t.terminal_name, m.is_active, m.pipeline_id, m.terminal_id
                       FROM pipeline_terminal_mapping m
                       JOIN pipeline_master p ON p.id = m.pipeline_id
                       JOIN terminal_master t ON t.id = m.terminal_id
                       ORDER BY p.pipeline_name, t.terminal_name
                       LIMIT %s OFFSET %s''', [size, (page - 1) * size])
        return [dict(r) for r in cur.fetchall()], total
    finally:
        conn.close()

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    if row_id:
        cur.execute('UPDATE pipeline_terminal_mapping SET pipeline_id=%s, terminal_id=%s, is_active=%s WHERE id=%s',
                    [data['pipeline_id'], data['terminal_id'], data.get('is_active', True), row_id])
    else:
        cur.execute('''INSERT INTO pipeline_terminal_mapping (pipeline_id, terminal_id, is_active)
                       VALUES (%s, %s, %s) RETURNING id''',
                    [data['pipeline_id'], data['terminal_id'], data.get('is_active', True)])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM pipeline_terminal_mapping WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

def get_matrix_data():
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT id, pipeline_name FROM pipeline_master ORDER BY pipeline_name')
        pipelines = [dict(r) for r in cur.fetchall()]
        cur.execute('SELECT id, terminal_name FROM terminal_master ORDER BY terminal_name')
        terminals = [dict(r) for r in cur.fetchall()]
        cur.execute('SELECT id, pipeline_id, terminal_id, is_active FROM pipeline_terminal_mapping')
        mappings = [dict(r) for r in cur.fetchall()]
        return pipelines, terminals, mappings
    finally:
        conn.close()


def toggle_mapping(pipeline_id, terminal_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT id FROM pipeline_terminal_mapping WHERE pipeline_id=%s AND terminal_id=%s',
                [pipeline_id, terminal_id])
    existing = cur.fetchone()
    if existing:
        cur.execute('DELETE FROM pipeline_terminal_mapping WHERE id=%s', [existing['id']])
        conn.commit()
        conn.close()
        return 'removed'
    else:
        cur.execute('INSERT INTO pipeline_terminal_mapping (pipeline_id, terminal_id, is_active) VALUES (%s, %s, TRUE)',
                    [pipeline_id, terminal_id])
        conn.commit()
        conn.close()
        return 'added'


def get_pipelines():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT id, pipeline_name FROM pipeline_master WHERE is_active=TRUE ORDER BY pipeline_name')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_terminals():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT id, terminal_name FROM terminal_master WHERE is_active=TRUE ORDER BY terminal_name')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
