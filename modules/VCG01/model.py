from database import get_db, get_cursor

TABLE = 'vessel_cargo'

def get_all():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT * FROM {TABLE} ORDER BY cargo_type, cargo_category, cargo_name')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cargo_types():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT DISTINCT cargo_type FROM {TABLE} WHERE cargo_type IS NOT NULL ORDER BY cargo_type')
    rows = cur.fetchall()
    conn.close()
    return [r['cargo_type'] for r in rows]

def get_cargo_categories(cargo_type=None):
    conn = get_db()
    cur = get_cursor(conn)
    if cargo_type:
        cur.execute(f'SELECT DISTINCT cargo_category FROM {TABLE} WHERE cargo_type = %s AND cargo_category IS NOT NULL ORDER BY cargo_category', [cargo_type])
    else:
        cur.execute(f'SELECT DISTINCT cargo_category FROM {TABLE} WHERE cargo_category IS NOT NULL ORDER BY cargo_category')
    rows = cur.fetchall()
    conn.close()
    return [r['cargo_category'] for r in rows]

def get_cargo_names(cargo_type=None, cargo_category=None):
    conn = get_db()
    cur = get_cursor(conn)
    if cargo_type and cargo_category:
        cur.execute(f'SELECT DISTINCT cargo_name FROM {TABLE} WHERE cargo_type = %s AND cargo_category = %s AND cargo_name IS NOT NULL ORDER BY cargo_name', [cargo_type, cargo_category])
    elif cargo_type:
        cur.execute(f'SELECT DISTINCT cargo_name FROM {TABLE} WHERE cargo_type = %s AND cargo_name IS NOT NULL ORDER BY cargo_name', [cargo_type])
    else:
        cur.execute(f'SELECT DISTINCT cargo_name FROM {TABLE} WHERE cargo_name IS NOT NULL ORDER BY cargo_name')
    rows = cur.fetchall()
    conn.close()
    return [r['cargo_name'] for r in rows]

def get_data(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT COUNT(*) FROM {TABLE}')
    total = cur.fetchone()['count']
    cur.execute(f'SELECT * FROM {TABLE} ORDER BY id DESC LIMIT %s OFFSET %s', (size, (page-1)*size))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total

def save_data(data):
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute(f"UPDATE {TABLE} SET cargo_type=%s, cargo_category=%s, cargo_name=%s, cargo_category_2=%s, cargo_sub_category=%s, cargo_sub_category_2=%s WHERE id=%s",
                   [data.get('cargo_type', ''), data.get('cargo_category', ''), data.get('cargo_name', ''),
                    data.get('cargo_category_2'), data.get('cargo_sub_category'), data.get('cargo_sub_category_2'), data['id']])
        row_id = data['id']
    else:
        cur.execute(f"INSERT INTO {TABLE} (cargo_type, cargo_category, cargo_name, cargo_category_2, cargo_sub_category, cargo_sub_category_2) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                   [data.get('cargo_type', ''), data.get('cargo_category', ''), data.get('cargo_name', ''),
                    data.get('cargo_category_2'), data.get('cargo_sub_category'), data.get('cargo_sub_category_2')])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def bulk_insert(rows):
    conn = get_db()
    cur = get_cursor(conn)
    inserted = 0
    for row in rows:
        if not row.get('cargo_type') and not row.get('cargo_name'):
            continue
        cur.execute(f"""INSERT INTO {TABLE} (cargo_type, cargo_category, cargo_name, cargo_category_2, cargo_sub_category, cargo_sub_category_2)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                   [row.get('cargo_type', ''), row.get('cargo_category', ''), row.get('cargo_name', ''),
                    row.get('cargo_category_2'), row.get('cargo_sub_category'), row.get('cargo_sub_category_2')])
        inserted += 1
    conn.commit()
    conn.close()
    return inserted

def delete_data(row_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f'DELETE FROM {TABLE} WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()
