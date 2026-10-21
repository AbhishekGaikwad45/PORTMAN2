"""An Approved VCN's parcels can have Pipeline/Terminal changed — with a reason,
written to approval_log — and nothing else (quantity stays locked).
Uses the dev DB; throwaway vcn_header rows are deleted (parcels cascade)."""
import pytest
from database import get_db, get_cursor
from modules.VCN01 import model


def _vcn(op_type, status):
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vcn_header (operation_type, doc_status) VALUES (%s, %s) RETURNING id",
                [op_type, status])
    vid = cur.fetchone()['id']; conn.commit(); conn.close()
    return vid


def _cleanup(vid):
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("DELETE FROM approval_log WHERE module_code='VCN01' AND record_id=%s", [vid])
    cur.execute("DELETE FROM vcn_header WHERE id=%s", [vid])
    conn.commit(); conn.close()


@pytest.mark.parametrize('op_type,table', [('Import', 'consigners'), ('Export', 'export_cargo')])
def test_amend_changes_only_route_and_logs_it(op_type, table):
    vid = _vcn(op_type, 'Draft')
    try:
        save = model.save_consigner if table == 'consigners' else model.save_export_cargo_declaration
        pid = save({'vcn_id': vid, 'cargo_name': 'PALM OIL', 'quantity': '500',
                    'pipeline_name': 'PL1', 'unload_terminal': 'T1'})
        model.approve_record(vid, 'approver')

        model.amend_parcel_route(table, pid, {'pipeline_name': 'PL2', 'unload_terminal': 'T2, T3',
                                              'quantity': '9999'}, 'Line 1 under maintenance', 'ops')

        conn = get_db(); cur = get_cursor(conn)
        cur.execute(f"SELECT pipeline_name, unload_terminal, quantity FROM {model.PARCEL_TABLES[table]} WHERE id=%s", [pid])
        p = cur.fetchone(); conn.close()
        assert (p['pipeline_name'], p['unload_terminal']) == ('PL2', 'T2, T3')
        assert float(p['quantity']) == 500          # quantity ignored
        log = model.get_approval_log(vid)
        assert [e['action'] for e in log] == ['Parcel Route Changed', 'Approved']   # newest first
        amend = [e for e in log if e['action'] == 'Parcel Route Changed']
        assert len(amend) == 1
        c = amend[0]['comment']
        assert 'Line 1 under maintenance' in c and 'PL1 → PL2' in c and 'T1 → T2, T3' in c
        assert amend[0]['actioned_by'] == 'ops'
    finally:
        _cleanup(vid)


def test_amend_needs_reason_approved_vcn_and_a_terminal():
    vid = _vcn('Import', 'Draft')
    try:
        pid = model.save_consigner({'vcn_id': vid, 'cargo_name': 'X', 'quantity': '1',
                                    'pipeline_name': 'PL1', 'unload_terminal': 'T1'})
        new = {'pipeline_name': 'PL2', 'unload_terminal': 'T2'}
        with pytest.raises(ValueError, match='Approved'):
            model.amend_parcel_route('consigners', pid, new, 'why', 'ops')
        model.approve_record(vid, 'approver')
        with pytest.raises(ValueError, match='[Rr]eason'):
            model.amend_parcel_route('consigners', pid, new, '  ', 'ops')
        with pytest.raises(ValueError, match='[Tt]erminal'):
            model.amend_parcel_route('consigners', pid, {'pipeline_name': 'PL2', 'unload_terminal': ''}, 'why', 'ops')
        with pytest.raises(ValueError, match='[Nn]o change'):
            model.amend_parcel_route('consigners', pid, {'pipeline_name': 'PL1', 'unload_terminal': 'T1'}, 'why', 'ops')
    finally:
        _cleanup(vid)
