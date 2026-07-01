"""Round-trip check for VCN01 export parcels after mirroring the import shape.
Uses the dev DB directly (get_db is a plain psycopg2 connection). Creates a
throwaway Export vcn_header and deletes it (ON DELETE CASCADE cleans parcels)."""
from database import get_db, get_cursor
from modules.VCN01 import model


def _make_export_vcn(cur):
    cur.execute("INSERT INTO vcn_header (operation_type) VALUES ('Export') RETURNING id")
    return cur.fetchone()['id']


def test_export_parcel_cols_mirror_import_minus_bl():
    assert model._EXPORT_PARCEL_COLS == [
        'igm_line_no', 'cargo_name', 'quantity', 'consigner_name', 'importer_name',
        'pipeline_name', 'unload_terminal', 'toll_applicable', 'toll_reason',
        'equipment_names',
    ]


def test_export_parcel_roundtrip():
    conn = get_db(); cur = get_cursor(conn)
    vcn_id = _make_export_vcn(cur); conn.commit(); conn.close()
    try:
        rid = model.save_export_cargo_declaration({
            'vcn_id': vcn_id, 'cargo_name': 'EDIBLE OIL', 'quantity': '100.5',
            'consigner_name': 'ABS', 'importer_name': 'ABS',
            'pipeline_name': 'PL1', 'unload_terminal': 'T1, T2',
            'toll_applicable': True, 'toll_reason': '', 'equipment_names': 'CRANE',
        })
        rows = model.get_export_cargo_declarations(vcn_id)
        assert len(rows) == 1
        r = rows[0]
        assert r['cargo_name'] == 'EDIBLE OIL'
        assert r['pipeline_name'] == 'PL1'
        assert r['unload_terminal'] == 'T1, T2'
        assert r['toll_applicable'] is True
        assert r['equipment_names'] == 'CRANE'
        assert r['parcel_seq'] == 1

        model.save_export_cargo_declaration({'id': rid, 'vcn_id': vcn_id,
            'cargo_name': 'EDIBLE OIL', 'quantity': '200', 'pipeline_name': 'PL2'})
        r2 = model.get_export_cargo_declarations(vcn_id)[0]
        assert r2['quantity'] == '200'
        assert r2['pipeline_name'] == 'PL2'
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id])
        conn.commit(); conn.close()


def test_export_approval_eligibility_and_picker_no_dropped_columns():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("""INSERT INTO vcn_header (operation_type, vessel_name, vessel_agent_name, cargo_type, discharge_port)
                   VALUES ('Export','V','A','Bulk','PORTX') RETURNING id""")
    vcn_id = cur.fetchone()['id']; conn.commit(); conn.close()
    try:
        model.save_export_cargo_declaration({'vcn_id': vcn_id, 'cargo_name': 'EDIBLE OIL',
            'quantity': '50', 'consigner_name': 'ABS'})
        elig = model.get_approval_eligibility(vcn_id)   # must not raise UndefinedColumn
        assert elig['eligible'] is True, elig
        picker = model.get_picker_parcels(vcn_id)       # must not raise
        assert len(picker) == 1
        assert picker[0]['consigner_name'] == 'ABS'
        assert picker[0]['quantity'] == '50'
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id]); conn.commit(); conn.close()
