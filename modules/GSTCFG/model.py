from database import get_db, get_cursor
from datetime import datetime


def get_all_configs():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM gst_api_config ORDER BY id')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_config_by_env(environment):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM gst_api_config WHERE environment=%s', [environment])
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_config(data, updated_by=None):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if row_id:
        cur.execute('''UPDATE gst_api_config SET
            api_base_url=%s, asp_id=%s, asp_secret=%s, gstin=%s,
            public_key_path=%s, is_active=%s,
            updated_by=%s, updated_date=%s
            WHERE id=%s''', [
            data.get('api_base_url'), data.get('asp_id'), data.get('asp_secret'),
            data.get('gstin'), data.get('public_key_path'),
            data.get('is_active', 0), updated_by, now, row_id
        ])
    else:
        cur.execute('''INSERT INTO gst_api_config
            (environment, api_base_url, asp_id, asp_secret, gstin,
             public_key_path, is_active, created_by, created_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id''', [
            data.get('environment'), data.get('api_base_url'),
            data.get('asp_id'), data.get('asp_secret'), data.get('gstin'),
            data.get('public_key_path'), data.get('is_active', 0),
            updated_by, now
        ])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id


def set_active_env(environment):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('UPDATE gst_api_config SET is_active=0')
    cur.execute('UPDATE gst_api_config SET is_active=1 WHERE environment=%s', [environment])
    conn.commit()
    conn.close()
