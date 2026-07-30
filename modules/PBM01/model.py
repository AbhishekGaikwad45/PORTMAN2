import json
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
    image_position = data.get('image_position')
    image_position_json = json.dumps(image_position) if image_position else None
    if data.get('id'):
        cur.execute('UPDATE port_berth_master SET berth_name=%s, berth_location=%s, remarks=%s, image_position=%s::jsonb WHERE id=%s',
                   [data.get('berth_name'), data.get('berth_location'), data.get('remarks'), image_position_json, data['id']])
        row_id = data['id']
    else:
        cur.execute('INSERT INTO port_berth_master (berth_name, berth_location, remarks, image_position) VALUES (%s, %s, %s, %s::jsonb) RETURNING id',
                   [data.get('berth_name'), data.get('berth_location'), data.get('remarks'), image_position_json])
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
