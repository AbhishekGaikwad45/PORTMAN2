from database import get_db, get_cursor
from datetime import datetime


def get_credit_notes(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT COUNT(*) as cnt FROM credit_note_header')
    total = cur.fetchone()['cnt']
    cur.execute('''
        SELECT cn.id,
               cn.credit_note_number  AS cn_number,
               cn.credit_note_date    AS cn_date,
               cn.original_invoice_id AS invoice_id,
               cn.reason,
               cn.total_amount,
               cn.total_amount        AS grand_total,
               cn.credit_note_status  AS status,
               cn.sap_document_number,
               cn.sap_posting_date    AS sap_fiscal_year,
               cn.cgst_amount, cn.sgst_amount, cn.igst_amount,
               i.invoice_number
        FROM credit_note_header cn
        LEFT JOIN invoice_header i ON cn.original_invoice_id = i.id
        ORDER BY cn.id DESC LIMIT %s OFFSET %s
    ''', [size, (page - 1) * size])
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_credit_note(cn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''
        SELECT cn.id,
               cn.credit_note_number  AS cn_number,
               cn.credit_note_date    AS cn_date,
               cn.original_invoice_id AS invoice_id,
               cn.reason,
               cn.total_amount,
               cn.total_amount        AS grand_total,
               cn.credit_note_status  AS status,
               cn.sap_document_number,
               cn.sap_posting_date    AS sap_fiscal_year,
               cn.cgst_amount, cn.sgst_amount, cn.igst_amount,
               i.invoice_number
        FROM credit_note_header cn
        LEFT JOIN invoice_header i ON cn.original_invoice_id = i.id
        WHERE cn.id = %s
    ''', [cn_id])
    header = cur.fetchone()
    if not header:
        conn.close()
        return None, []
    header = dict(header)
    cur.execute('''
        SELECT id, credit_note_id, original_invoice_line_id,
               service_name,
               service_description AS description,
               quantity, rate,
               line_amount         AS amount,
               cgst_amount, sgst_amount, igst_amount,
               gl_code,
               sac_code            AS sap_tax_code
        FROM credit_note_lines
        WHERE credit_note_id = %s ORDER BY id
    ''', [cn_id])
    lines = [dict(r) for r in cur.fetchall()]
    conn.close()
    return header, lines


def save_credit_note(data, username=None):
    conn = get_db()
    cur = get_cursor(conn)
    cn_id = data.get('id')
    now = datetime.now().strftime('%Y-%m-%d')
    total_amount = float(data.get('total_amount') or 0)
    cgst = float(data.get('cgst_amount') or 0)
    sgst = float(data.get('sgst_amount') or 0)
    igst = float(data.get('igst_amount') or 0)

    if cn_id:
        cur.execute('''UPDATE credit_note_header SET
            original_invoice_id=%s, credit_note_number=%s, credit_note_date=%s,
            reason=%s, total_amount=%s, cgst_amount=%s, sgst_amount=%s, igst_amount=%s,
            credit_note_status=%s, sap_document_number=%s, sap_posting_date=%s
            WHERE id=%s''', [
            data.get('invoice_id'), data.get('cn_number'), data.get('cn_date'),
            data.get('reason'), total_amount, cgst, sgst, igst,
            data.get('status', 'Draft'),
            data.get('sap_document_number'), data.get('sap_fiscal_year'),
            cn_id
        ])
    else:
        cur.execute('''INSERT INTO credit_note_header
            (original_invoice_id, credit_note_number, credit_note_date,
             reason, total_amount, cgst_amount, sgst_amount, igst_amount,
             credit_note_status, created_by, created_date,
             financial_year, party_type, party_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id''', [
            data.get('invoice_id'), data.get('cn_number'), data.get('cn_date'),
            data.get('reason'), total_amount, cgst, sgst, igst,
            'Draft', username, now,
            datetime.now().strftime('%Y-%m'), 'Customer', 0
        ])
        cn_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return cn_id


def save_credit_note_line(data):
    conn = get_db()
    cur = get_cursor(conn)
    line_id = data.get('id')
    amount = float(data.get('amount') or 0)
    cgst = float(data.get('cgst_amount') or 0)
    sgst = float(data.get('sgst_amount') or 0)
    igst = float(data.get('igst_amount') or 0)
    line_total = amount + cgst + sgst + igst

    if line_id:
        cur.execute('''UPDATE credit_note_lines SET
            service_name=%s, service_description=%s,
            quantity=%s, rate=%s, line_amount=%s,
            cgst_amount=%s, sgst_amount=%s, igst_amount=%s,
            line_total=%s, gl_code=%s, sac_code=%s
            WHERE id=%s''', [
            data.get('service_name'), data.get('description'),
            data.get('quantity'), data.get('rate'), amount,
            cgst, sgst, igst, line_total,
            data.get('gl_code'), data.get('sap_tax_code'),
            line_id
        ])
    else:
        cur.execute('''INSERT INTO credit_note_lines
            (credit_note_id, original_invoice_line_id, service_name,
             service_description, quantity, rate, line_amount,
             cgst_amount, sgst_amount, igst_amount, line_total, gl_code, sac_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id''', [
            data.get('credit_note_id'), data.get('invoice_line_id'),
            data.get('service_name'), data.get('description'),
            data.get('quantity'), data.get('rate'), amount,
            cgst, sgst, igst, line_total,
            data.get('gl_code'), data.get('sap_tax_code')
        ])
        line_id = cur.fetchone()['id']

    conn.commit()
    conn.close()
    return line_id


def delete_credit_note(cn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM credit_note_lines WHERE credit_note_id = %s', [cn_id])
    cur.execute('DELETE FROM credit_note_header WHERE id = %s', [cn_id])
    conn.commit()
    conn.close()


def delete_credit_note_line(line_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM credit_note_lines WHERE id = %s', [line_id])
    conn.commit()
    conn.close()


def get_invoices_for_dropdown():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT id, invoice_number, invoice_date, customer_name,
                          total_amount AS grand_total
        FROM invoice_header
        WHERE invoice_status != 'Cancelled'
        ORDER BY id DESC LIMIT 200''')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
