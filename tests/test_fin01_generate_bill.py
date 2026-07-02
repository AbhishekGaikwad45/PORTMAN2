"""Multi-vessel bill generation: one bill across two vessels, lines with GST/TDS
computed by save_bill_line, bill_vessels populated, ledger recorded (billed-lock)."""
from database import get_db, get_cursor
from modules.FIN01 import model as fin


def _mk_vessel(cur, doc):
    cur.execute("INSERT INTO vcn_header (operation_type, vcn_doc_num, vessel_name) "
                "VALUES ('Import',%s,'V') RETURNING id", [doc])
    vid = cur.fetchone()['id']
    cur.execute("""INSERT INTO vcn_consigners
        (vcn_id, parcel_no, cargo_name, quantity, consigner_name, importer_name,
         pipeline_name, unload_terminal, parcel_seq)
        VALUES (%s,'P1','OIL','100','GENC','GENC','PL','T',1) RETURNING id""", [vid])
    pid = cur.fetchone()['id']
    cur.execute("INSERT INTO ldud_header (vcn_id, doc_status) VALUES (%s,'Closed')", [vid])
    return vid, pid


def _svc_id(cur, code):
    cur.execute("SELECT id FROM finance_service_types WHERE service_code=%s", [code])
    return cur.fetchone()['id']


def _mk_export_vessel(cur, doc):
    cur.execute("INSERT INTO vcn_header (operation_type, vcn_doc_num, vessel_name) "
                "VALUES ('Export',%s,'V') RETURNING id", [doc])
    vid = cur.fetchone()['id']
    cur.execute("""INSERT INTO vcn_export_cargo_declaration
        (vcn_id, parcel_no, cargo_name, quantity, consigner_name, importer_name,
         pipeline_name, unload_terminal, parcel_seq)
        VALUES (%s,'P1','OIL','100','GENC','GENC','PL','T',1) RETURNING id""", [vid])
    pid = cur.fetchone()['id']
    cur.execute("INSERT INTO ldud_header (vcn_id, doc_status) VALUES (%s,'Closed')", [vid])
    return vid, pid


def test_generate_multi_vessel_bill_records_ledger_and_vessels():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vessel_customers (name) VALUES ('GENC') RETURNING id")
    cid = cur.fetchone()['id']
    v1, p1 = _mk_vessel(cur, 'VCN-GEN-1')
    v2, p2 = _mk_vessel(cur, 'VCN-GEN-2')
    chg = _svc_id(cur, 'CHGU01')
    conn.commit(); conn.close()

    payload = {
        'customer_type': 'Customer', 'customer_id': cid, 'customer_name': 'GENC',
        'customer_gstin': '', 'customer_gst_state_code': '', 'customer_gl_code': '',
        'lines': [
            {'cargo_source_type': 'VCN_IMPORT', 'cargo_source_id': p1, 'vcn_id': v1,
             'service_type_id': chg, 'service_code': 'CHGU01', 'service_name': 'Cargo Handling Unloading',
             'quantity': 100, 'rate': 50, 'uom': 'MT', 'gst_rate_id': 4, 'sac_code': '996719',
             'gl_code': '4101076030', 'tds_applicable': 1, 'tds_percent': 2},
            {'cargo_source_type': 'VCN_IMPORT', 'cargo_source_id': p2, 'vcn_id': v2,
             'service_type_id': chg, 'service_code': 'CHGU01', 'service_name': 'Cargo Handling Unloading',
             'quantity': 100, 'rate': 50, 'uom': 'MT', 'gst_rate_id': 4, 'sac_code': '996719',
             'gl_code': '4101076030', 'tds_applicable': 1, 'tds_percent': 2},
        ],
    }
    bill_id = bill_number = None
    try:
        bill_id, bill_number = fin.generate_bill(payload, 'tester', 'Draft')
        assert bill_id and bill_number

        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT source_type, source_id, source_display, subtotal FROM bill_header WHERE id=%s", [bill_id])
        h = cur.fetchone()
        assert h['source_type'] == 'MULTI' and h['source_id'] is None
        assert 'VCN-GEN-1' in h['source_display'] and 'VCN-GEN-2' in h['source_display']
        assert abs(float(h['subtotal']) - 10000.0) < 1e-6   # 2 x 100 x 50

        cur.execute("SELECT COUNT(*) AS c FROM bill_lines WHERE bill_id=%s", [bill_id])
        assert cur.fetchone()['c'] == 2
        cur.execute("SELECT COUNT(*) AS c FROM bill_vessels WHERE bill_id=%s", [bill_id])
        assert cur.fetchone()['c'] == 2
        conn.close()

        assert fin.is_vcn_billed(v1) is True
        assert fin.is_vcn_billed(v2) is True
    finally:
        conn = get_db(); cur = get_cursor(conn)
        if bill_id:
            cur.execute("DELETE FROM parcel_charge_billed WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_vessels WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_lines WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_header WHERE id=%s", [bill_id])
        cur.execute("DELETE FROM ldud_header WHERE vcn_id IN (%s,%s)", [v1, v2])
        cur.execute("DELETE FROM vcn_header WHERE id IN (%s,%s)", [v1, v2])  # cascades consigner
        cur.execute("DELETE FROM vessel_customers WHERE id=%s", [cid])
        conn.commit(); conn.close()


def test_generate_bill_with_export_line_does_not_crash():
    """VCN_EXPORT bill lines must not crash: vcn_export_cargo_declaration (jnpa35)
    no longer has billed_quantity/bill_id/is_billed columns. Billed-status is
    recorded solely in the parcel_charge_billed ledger."""
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vessel_customers (name) VALUES ('GENC') RETURNING id")
    cid = cur.fetchone()['id']
    vid, pid = _mk_export_vessel(cur, 'VCN-EXP-1')
    chg = _svc_id(cur, 'CHGL01')
    conn.commit(); conn.close()

    payload = {
        'customer_type': 'Customer', 'customer_id': cid, 'customer_name': 'GENC',
        'customer_gstin': '', 'customer_gst_state_code': '', 'customer_gl_code': '',
        'lines': [
            {'cargo_source_type': 'VCN_EXPORT', 'cargo_source_id': pid, 'vcn_id': vid,
             'service_type_id': chg, 'service_code': 'CHGL01', 'service_name': 'Cargo Handling Loading',
             'quantity': 100, 'rate': 50, 'uom': 'MT', 'gst_rate_id': 4, 'sac_code': '996719',
             'gl_code': '4101076030', 'tds_applicable': 1, 'tds_percent': 2},
        ],
    }
    bill_id = bill_number = None
    try:
        bill_id, bill_number = fin.generate_bill(payload, 'tester', 'Draft')
        assert bill_id and bill_number

        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT COUNT(*) AS c FROM bill_lines WHERE bill_id=%s", [bill_id])
        assert cur.fetchone()['c'] == 1
        conn.close()

        assert fin.is_vcn_billed(vid) is True
    finally:
        conn = get_db(); cur = get_cursor(conn)
        if bill_id:
            cur.execute("DELETE FROM parcel_charge_billed WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_vessels WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_lines WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_header WHERE id=%s", [bill_id])
        cur.execute("DELETE FROM ldud_header WHERE vcn_id=%s", [vid])
        cur.execute("DELETE FROM vcn_header WHERE id=%s", [vid])  # cascades export declaration
        cur.execute("DELETE FROM vessel_customers WHERE id=%s", [cid])
        conn.commit(); conn.close()
