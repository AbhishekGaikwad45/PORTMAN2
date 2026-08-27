"""Hydro test validity gates the VCN01 pipeline picker, and LDUD01 shows the
live VCN doc number after a rename. Uses the dev DB with throwaway rows."""
from database import get_db, get_cursor
from modules.PLM01 import model as plm
from modules.LDUD01 import model as ldud


def test_expired_hydro_test_drops_pipeline_from_picker():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO pipeline_master (pipeline_name, is_active, hydro_test_valid_until) "
                "VALUES ('ZZ-TEST-LIVE', TRUE, NOW() + INTERVAL '1 day') RETURNING id")
    live = cur.fetchone()['id']
    cur.execute("INSERT INTO pipeline_master (pipeline_name, is_active, hydro_test_valid_until) "
                "VALUES ('ZZ-TEST-EXPIRED', TRUE, NOW() - INTERVAL '1 day') RETURNING id")
    expired = cur.fetchone()['id']
    cur.execute("INSERT INTO pipeline_master (pipeline_name, is_active) "
                "VALUES ('ZZ-TEST-UNSET', TRUE) RETURNING id")
    unset = cur.fetchone()['id']
    conn.commit(); conn.close()
    try:
        names = [r['pipeline_name'] for r in plm.get_all_active(hydro_valid_only=True)]
        assert 'ZZ-TEST-LIVE' in names
        assert 'ZZ-TEST-EXPIRED' not in names
        assert 'ZZ-TEST-UNSET' in names          # never tested stays selectable

        # the master grid still lists all three, date rendered for the editor
        plm.save({'id': live, 'pipeline_name': 'ZZ-TEST-LIVE',
                  'hydro_test_valid_until': '2030-01-31T18:45'})
        rows, _ = plm.get_data(1, 500)
        row = next(r for r in rows if r['id'] == live)
        assert row['hydro_test_valid_until'] == '2030-01-31T18:45'
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM pipeline_master WHERE id = ANY(%s)', [[live, expired, unset]])
        conn.commit(); conn.close()


def test_ldud_shows_renamed_vcn_doc_num_without_touching_the_snapshot():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vcn_header (operation_type, vcn_doc_num, vessel_name) "
                "VALUES ('Import', 'VCN-9998-001', 'ZZ TEST VESSEL') RETURNING id")
    vcn_id = cur.fetchone()['id']
    cur.execute("INSERT INTO ldud_header (doc_num, vcn_id, vcn_doc_num, vessel_name) "
                "VALUES ('LDUD-9998-001', %s, 'VCN-9998-001', 'ZZ TEST VESSEL') RETURNING id",
                [vcn_id])
    ldud_id = cur.fetchone()['id']
    conn.commit(); conn.close()
    try:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("UPDATE vcn_header SET vcn_doc_num='VCN-9998-042' WHERE id=%s", [vcn_id])
        conn.commit(); conn.close()

        rows, _ = ldud.get_data(1, 500)
        row = next(r for r in rows if r['id'] == ldud_id)
        assert row['vcn_doc_num'] == 'VCN-9998-042'          # live value shown

        # stored snapshot untouched by the read
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('SELECT vcn_doc_num FROM ldud_header WHERE id=%s', [ldud_id])
        assert cur.fetchone()['vcn_doc_num'] == 'VCN-9998-001'
        conn.close()

        # filtering uses the live number too
        rows, total = ldud.get_data(1, 50, [{'field': 'vcn_doc_num', 'type': 'contains',
                                             'value': 'VCN-9998-042'}])
        assert [r['id'] for r in rows] == [ldud_id] and total == 1
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM ldud_header WHERE id=%s', [ldud_id])
        cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id])
        conn.commit(); conn.close()
