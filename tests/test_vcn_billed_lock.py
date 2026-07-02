"""Billed-status ledger + strict VCN closure validation.
Uses the dev DB with a throwaway VCN + consigner parcel, cleaned up after."""
from database import get_db, get_cursor
from modules.VCN01 import model as vcn
from modules.FIN01 import model as fin


def _mk_parcel(cur, vcn_id, **over):
    cols = dict(cargo_name='OIL', quantity='100', consigner_name='ABS', importer_name='ABS',
                pipeline_name='PL1', unload_terminal='T1', parcel_seq=1, parcel_no='P1')
    cols.update(over)
    keys = list(cols)
    cur.execute(f"INSERT INTO vcn_consigners (vcn_id, {', '.join(keys)}) "
                f"VALUES (%s, {', '.join(['%s'] * len(keys))}) RETURNING id",
                [vcn_id] + [cols[k] for k in keys])
    return cur.fetchone()['id']


def test_closure_validation_requires_all_six_fields_on_every_parcel():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vcn_header (operation_type, vessel_name, vessel_agent_name, discharge_port) "
                "VALUES ('Import','V','A','PORTX') RETURNING id")
    vid = cur.fetchone()['id']
    _mk_parcel(cur, vid, parcel_no='P1')
    bad_id = _mk_parcel(cur, vid, parcel_no='P2', unload_terminal='', pipeline_name='')  # incomplete
    conn.commit(); conn.close()
    try:
        elig = vcn.get_approval_eligibility(vid)
        assert elig['eligible'] is False
        joined = ' '.join(elig['missing'])
        assert 'P2' in joined and 'Unload Terminal' in joined and 'Pipeline' in joined, elig
        assert 'P1' not in joined  # complete parcel not flagged

        # fill P2 -> now eligible
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("UPDATE vcn_consigners SET unload_terminal='T2', pipeline_name='PL2' WHERE id=%s", [bad_id])
        conn.commit(); conn.close()
        assert vcn.get_approval_eligibility(vid)['eligible'] is True
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("DELETE FROM vcn_header WHERE id=%s", [vid])  # cascades consigners
        conn.commit(); conn.close()


def test_billed_ledger_and_is_vcn_billed():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vcn_header (operation_type) VALUES ('Import') RETURNING id")
    vid = cur.fetchone()['id']
    pid = _mk_parcel(cur, vid)
    conn.commit(); conn.close()
    try:
        assert fin.is_vcn_billed(vid) is False

        conn = get_db(); cur = get_cursor(conn)
        fin.record_parcel_charge(cur, 'VCN_IMPORT', pid, service_type_id=2,
                                 service_code='CHGU01', bill_id=999, billed_quantity=100, created_by='t')
        conn.commit(); conn.close()

        assert fin.is_vcn_billed(vid) is True
        assert fin.billed_qty('VCN_IMPORT', pid, 2) == 100.0

        conn = get_db(); cur = get_cursor(conn)
        fin.void_bill_charges(cur, 999)
        conn.commit(); conn.close()

        assert fin.is_vcn_billed(vid) is False
        assert fin.billed_qty('VCN_IMPORT', pid, 2) == 0.0
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("DELETE FROM parcel_charge_billed WHERE cargo_source_id=%s", [pid])
        cur.execute("DELETE FROM vcn_header WHERE id=%s", [vid])
        conn.commit(); conn.close()
