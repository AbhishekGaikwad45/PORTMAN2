"""Editing the number part of a VCN doc number must renumber its parcel labels.
Uses the dev DB directly; creates a throwaway Export vcn_header and deletes it."""
from database import get_db, get_cursor
from modules.VCN01 import model


def test_doc_num_edit_renumbers_parcels_and_flags_duplicates():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vcn_header (operation_type, vcn_doc_num) "
                "VALUES ('Export', 'VCN-9999-001') RETURNING id")
    vcn_id = cur.fetchone()['id']
    conn.commit(); conn.close()
    try:
        model.save_export_cargo_declaration({'vcn_id': vcn_id, 'cargo_name': 'EDIBLE OIL'})
        assert model.get_export_cargo_declarations(vcn_id)[0]['parcel_no'] == 'VCN-9999-001/P1'

        model.save_header({'id': vcn_id, 'vcn_doc_num': 'VCN-9999-007'})
        assert model.get_export_cargo_declarations(vcn_id)[0]['parcel_no'] == 'VCN-9999-007/P1'

        assert model.doc_num_taken('VCN-9999-007', 0)          # someone else's number
        assert not model.doc_num_taken('VCN-9999-007', vcn_id)  # its own is fine
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id])
        conn.commit(); conn.close()
