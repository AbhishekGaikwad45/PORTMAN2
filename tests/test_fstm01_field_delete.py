"""FSTM01 custom-field deletion.

service_record_values.field_definition_id has no ON DELETE CASCADE, so deleting
a field that anyone has entered data for used to raise a FK violation. It now
deletes the values with the field, in one transaction, and only with a reason.
Uses the dev DB directly; creates throwaway rows and deletes them.
"""
import pytest
from database import get_db, get_cursor
from modules.FSTM01 import model as fstm_model


def _seed(cur, *, required=0, billable=0):
    """A service type with one custom field and one service record holding a
    value for it. Returns (service_type_id, field_id, record_id)."""
    cur.execute("""INSERT INTO finance_service_types (service_code, service_name, has_custom_fields)
                   VALUES ('ZZTEST01', 'Throwaway Test Service', 1) RETURNING id""")
    svc_id = cur.fetchone()['id']
    cur.execute("""INSERT INTO service_field_definitions
                   (service_type_id, field_name, field_label, field_type, is_required, is_billable_qty)
                   VALUES (%s, 'zz_hours', 'ZZ Hours', 'number', %s, %s) RETURNING id""",
                [svc_id, required, billable])
    field_id = cur.fetchone()['id']
    cur.execute("""INSERT INTO service_records
                   (record_number, service_type_id, source_type, source_id, is_billed)
                   VALUES ('ZZ999999', %s, 'Customer', 0, 1) RETURNING id""", [svc_id])
    record_id = cur.fetchone()['id']
    cur.execute("""INSERT INTO service_record_values
                   (service_record_id, field_definition_id, field_value)
                   VALUES (%s, %s, '6.5')""", [record_id, field_id])
    return svc_id, field_id, record_id


def _cleanup(cur, svc_id, field_id, record_id):
    cur.execute('DELETE FROM service_record_values WHERE field_definition_id=%s', [field_id])
    cur.execute('DELETE FROM service_records WHERE id=%s', [record_id])
    cur.execute('DELETE FROM service_field_definitions WHERE id=%s', [field_id])
    cur.execute("DELETE FROM approval_log WHERE module_code='FSTM01' AND record_id=%s", [field_id])
    cur.execute('DELETE FROM finance_service_types WHERE id=%s', [svc_id])


def test_field_usage_counts_what_the_delete_would_destroy():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_id, record_id = _seed(cur, billable=1)
    conn.commit()
    try:
        usage = fstm_model.field_usage(field_id)
        assert usage['field_label'] == 'ZZ Hours'
        assert usage['values'] == 1
        assert usage['records'] == 1
        assert usage['billed_records'] == 1      # the seeded record is is_billed=1
        assert usage['is_billable_qty'] is True
    finally:
        _cleanup(cur, svc_id, field_id, record_id)
        conn.commit(); conn.close()


def test_deleting_a_field_with_values_removes_both_and_logs_the_reason():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_id, record_id = _seed(cur)
    conn.commit()
    try:
        fstm_model.delete_field_definition(field_id, 'Field added by mistake', 'tester')

        cur.execute('SELECT COUNT(*) AS n FROM service_field_definitions WHERE id=%s', [field_id])
        assert cur.fetchone()['n'] == 0
        cur.execute('SELECT COUNT(*) AS n FROM service_record_values WHERE field_definition_id=%s',
                    [field_id])
        assert cur.fetchone()['n'] == 0, 'orphaned values left behind'

        # Last field gone, so the service type is no longer custom-field bearing.
        cur.execute('SELECT has_custom_fields FROM finance_service_types WHERE id=%s', [svc_id])
        assert cur.fetchone()['has_custom_fields'] == 0

        cur.execute("""SELECT action, comment FROM approval_log
                       WHERE module_code='FSTM01' AND record_id=%s""", [field_id])
        log = cur.fetchone()
        assert log['action'] == 'Delete Custom Field'
        assert 'Field added by mistake' in log['comment']
        assert 'ZZ Hours' in log['comment']
    finally:
        _cleanup(cur, svc_id, field_id, record_id)
        conn.commit(); conn.close()


def test_a_blank_reason_is_refused_and_nothing_is_deleted():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_id, record_id = _seed(cur)
    conn.commit()
    try:
        with pytest.raises(ValueError):
            fstm_model.delete_field_definition(field_id, '   ', 'tester')

        cur.execute('SELECT COUNT(*) AS n FROM service_field_definitions WHERE id=%s', [field_id])
        assert cur.fetchone()['n'] == 1, 'field deleted despite the blank reason'
        cur.execute('SELECT COUNT(*) AS n FROM service_record_values WHERE field_definition_id=%s',
                    [field_id])
        assert cur.fetchone()['n'] == 1, 'values deleted despite the blank reason'
    finally:
        _cleanup(cur, svc_id, field_id, record_id)
        conn.commit(); conn.close()
