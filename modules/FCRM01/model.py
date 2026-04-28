from database import get_db, get_cursor
from datetime import datetime


def get_all_currencies():
    """Get all active currencies for dropdown"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT currency_code, currency_name, currency_symbol FROM currency_master WHERE is_active = 1 ORDER BY currency_code')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_currency_data(page=1, size=20):
    """Get paginated currency data"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT COUNT(*) FROM currency_master')
    total = cur.fetchone()['count']
    cur.execute('SELECT * FROM currency_master ORDER BY currency_code LIMIT %s OFFSET %s', (size, (page-1)*size))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def save_currency(data):
    """Save currency master record"""
    conn = get_db()
    cur = get_cursor(conn)

    if data.get('id'):
        cur.execute('''
            UPDATE currency_master
            SET currency_name=%s, currency_symbol=%s, is_base_currency=%s, is_active=%s
            WHERE id=%s
        ''', [
            data.get('currency_name'),
            data.get('currency_symbol'),
            data.get('is_base_currency', 0),
            data.get('is_active', 1),
            data['id']
        ])
        row_id = data['id']
    else:
        cur.execute('''
            INSERT INTO currency_master (currency_code, currency_name, currency_symbol, is_base_currency, is_active, created_by, created_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', [
            data.get('currency_code'),
            data.get('currency_name'),
            data.get('currency_symbol'),
            data.get('is_base_currency', 0),
            data.get('is_active', 1),
            data.get('created_by'),
            datetime.now().strftime('%Y-%m-%d')
        ])
        row_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return row_id


def delete_currency(row_id):
    """Delete currency record"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM currency_master WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()


def get_exchange_rates(page=1, size=20):
    """Get paginated exchange rates"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT COUNT(*) FROM currency_exchange_rates')
    total = cur.fetchone()['count']
    cur.execute('''
        SELECT * FROM currency_exchange_rates
        ORDER BY effective_date DESC, id DESC
        LIMIT %s OFFSET %s
    ''', (size, (page-1)*size))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def save_exchange_rate(data):
    """Save exchange rate record"""
    conn = get_db()
    cur = get_cursor(conn)

    if data.get('id'):
        cur.execute('''
            UPDATE currency_exchange_rates
            SET from_currency=%s, to_currency=%s, exchange_rate=%s, effective_date=%s, rate_type=%s, is_active=%s
            WHERE id=%s
        ''', [
            data.get('from_currency'),
            data.get('to_currency'),
            data.get('exchange_rate'),
            data.get('effective_date'),
            data.get('rate_type', 'Mid'),
            data.get('is_active', 1),
            data['id']
        ])
        row_id = data['id']
    else:
        cur.execute('''
            INSERT INTO currency_exchange_rates
            (from_currency, to_currency, exchange_rate, effective_date, rate_type, is_active, created_by, created_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', [
            data.get('from_currency'),
            data.get('to_currency'),
            data.get('exchange_rate'),
            data.get('effective_date'),
            data.get('rate_type', 'Mid'),
            data.get('is_active', 1),
            data.get('created_by'),
            datetime.now().strftime('%Y-%m-%d')
        ])
        row_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return row_id


def delete_exchange_rate(row_id):
    """Delete exchange rate record"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM currency_exchange_rates WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()


def get_exchange_rate(from_curr, to_curr, as_of_date):
    """Get exchange rate for a currency pair as of a specific date"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT exchange_rate FROM currency_exchange_rates
        WHERE from_currency = %s AND to_currency = %s AND effective_date <= %s AND is_active = 1
        ORDER BY effective_date DESC
        LIMIT 1
    ''', [from_curr, to_curr, as_of_date])
    row = cur.fetchone()
    conn.close()

    if row:
        return row['exchange_rate']
    return 1.0  # Default to 1.0 if no rate found
