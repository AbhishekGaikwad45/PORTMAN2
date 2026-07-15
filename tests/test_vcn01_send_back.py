"""VCN01 send-back-to-Expected with an LDUD: the LDUD is soft-deleted (hidden,
vcn_id detached) instead of blocking the move. Uses the dev DB with a throwaway
VCN -> consigner -> LDUD -> parcel-op chain, cleaned up after."""
from database import get_db, get_cursor
from modules.VCN01 import model as vcn_model
from modules.LUEU01 import model as lueu_model


def test_send_back_soft_deletes_ldud():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("""INSERT INTO vcn_header (operation_type, vessel_name, vcn_doc_num)
                   VALUES ('Import', 'MT SENDBACK TEST', 'VCN-TEST-SB1') RETURNING id""")
    vid = cur.fetchone()['id']
    cur.execute("""INSERT INTO vcn_consigners (vcn_id, quantity, cargo_name, parcel_seq, parcel_no, consigner_name)
                   VALUES (%s,'1000','OIL',1,'P1','ACME') RETURNING id""", [vid])
    cid = cur.fetchone()['id']
    cur.execute("INSERT INTO ldud_header (vcn_id, vcn_doc_num, vessel_name) VALUES (%s,'VCN-TEST-SB1','MT SENDBACK TEST') RETURNING id", [vid])
    lid = cur.fetchone()['id']
    cur.execute("""INSERT INTO ldud_parcel_ops (ldud_id, parcel_ids, cargo_name, quantity)
                   VALUES (%s,%s,'OIL','1000') RETURNING id""", [lid, str(cid)])
    pid = cur.fetchone()['id']
    conn.commit(); conn.close()

    ev_id = None
    try:
        ev_id = vcn_model.send_back_to_expected(vid, 'tester')

        conn = get_db(); cur = get_cursor(conn)
        # expected_vessels row recreated, VCN gone
        cur.execute("SELECT vessel_name FROM expected_vessels WHERE id=%s", [ev_id])
        assert cur.fetchone()['vessel_name'] == 'MT SENDBACK TEST'
        cur.execute("SELECT 1 FROM vcn_header WHERE id=%s", [vid])
        assert cur.fetchone() is None

        # LDUD soft-deleted: flagged, detached, parcel op preserved
        cur.execute("SELECT is_deleted, deleted_by, vcn_id, vcn_doc_num FROM ldud_header WHERE id=%s", [lid])
        l = cur.fetchone()
        assert l['is_deleted'] is True and l['deleted_by'] == 'tester'
        assert l['vcn_id'] is None and l['vcn_doc_num'] == 'VCN-TEST-SB1'
        cur.execute("SELECT 1 FROM ldud_parcel_ops WHERE id=%s", [pid])
        assert cur.fetchone() is not None
        conn.close()

        # hidden from LUEU (joins via vcn_id) and from the LDUD01 list filter
        assert not any(v['vcn_id'] == vid for v in lueu_model.get_vessels_with_started_parcels())
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT 1 FROM ldud_header WHERE id=%s AND is_deleted IS NOT TRUE", [lid])
        assert cur.fetchone() is None
        conn.close()
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("DELETE FROM ldud_parcel_ops WHERE id=%s", [pid])
        cur.execute("DELETE FROM ldud_header WHERE id=%s", [lid])
        cur.execute("DELETE FROM vcn_header WHERE id=%s", [vid])  # cascades consigner (if still there)
        if ev_id:
            cur.execute("DELETE FROM expected_vessels WHERE id=%s", [ev_id])
        conn.commit(); conn.close()
