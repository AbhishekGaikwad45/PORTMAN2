from database import get_db, get_cursor
from datetime import datetime

TABLE = 'customer_virtual_accounts'


def get_va_list(party_type, party_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'SELECT * FROM {TABLE} WHERE party_type=%s AND party_id=%s ORDER BY id',
                [party_type, party_id])
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_va(data, created_by=None):
    conn = get_db()
    cur = get_cursor(conn)
    row_id = data.get('id')
    if row_id:
        cur.execute(f'''UPDATE {TABLE} SET
            account_number=%s, ifsc_code=%s, bank_name=%s, branch_name=%s,
            account_holder_name=%s, account_type=%s, purpose=%s, is_active=%s,
            effective_from=%s, effective_to=%s, gl_account_code=%s, remarks=%s
            WHERE id=%s''', [
            data.get('account_number'), data.get('ifsc_code'), data.get('bank_name'),
            data.get('branch_name'), data.get('account_holder_name'),
            data.get('account_type', 'Current'), data.get('purpose'),
            data.get('is_active', 1),
            data.get('effective_from') or None, data.get('effective_to') or None,
            data.get('gl_account_code'), data.get('remarks'), row_id
        ])
    else:
        cur.execute(f'''INSERT INTO {TABLE}
            (party_type, party_id, party_name, account_number, ifsc_code, bank_name,
             branch_name, account_holder_name, account_type, purpose, is_active,
             effective_from, effective_to, gl_account_code, remarks, created_by, created_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id''', [
            data.get('party_type'), data.get('party_id'), data.get('party_name'),
            data.get('account_number'), data.get('ifsc_code'), data.get('bank_name'),
            data.get('branch_name'), data.get('account_holder_name'),
            data.get('account_type', 'Current'), data.get('purpose'),
            data.get('is_active', 1),
            data.get('effective_from') or None, data.get('effective_to') or None,
            data.get('gl_account_code'), data.get('remarks'),
            created_by, datetime.now().strftime('%Y-%m-%d')
        ])
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id


def delete_va(va_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'DELETE FROM {TABLE} WHERE id=%s', (va_id,))
    conn.commit()
    conn.close()
