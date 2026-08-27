from database import get_db, get_cursor

# Hydro test validity: a pipeline is usable until this timestamp. NULL = no
# hydro test on record, which stays usable (existing pipelines predate the field).
_COLS = ("id, pipeline_name, description, is_active, created_at, "
         "to_char(hydro_test_valid_until, 'YYYY-MM-DD\"T\"HH24:MI') AS hydro_test_valid_until")
_VALID = "(hydro_test_valid_until IS NULL OR hydro_test_valid_until >= NOW())"

def get_data(page=1, size=50, filters=None):
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT COUNT(*) FROM pipeline_master')
        total = cur.fetchone()['count']
        cur.execute(f'SELECT {_COLS} FROM pipeline_master ORDER BY pipeline_name LIMIT %s OFFSET %s',
                    [size, (page - 1) * size])
        return [dict(r) for r in cur.fetchall()], total
    finally:
        conn.close()

def save(data):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    hydro = data.get('hydro_test_valid_until') or None
    if row_id:
        cur.execute('UPDATE pipeline_master SET pipeline_name=%s, description=%s, is_active=%s, '
                    'hydro_test_valid_until=%s WHERE id=%s',
                    [data['pipeline_name'], data.get('description'), data.get('is_active', True),
                     hydro, row_id])
    else:
        cur.execute('INSERT INTO pipeline_master (pipeline_name, description, is_active, '
                    'hydro_test_valid_until) VALUES (%s, %s, %s, %s) RETURNING id',
                    [data['pipeline_name'], data.get('description'), data.get('is_active', True), hydro])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM pipeline_master WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

def get_all_active(hydro_valid_only=False):
    conn = get_db()
    cur = get_cursor(conn)
    where = 'is_active=TRUE' + (f' AND {_VALID}' if hydro_valid_only else '')
    cur.execute(f'SELECT id, pipeline_name FROM pipeline_master WHERE {where} ORDER BY pipeline_name')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
