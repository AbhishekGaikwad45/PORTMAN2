"""SRV01 required custom fields.

is_required was decorative: the inputs are never submitted as a <form>, so the
browser never enforced it, and the save route validated nothing. Enforcement now
bites when a record becomes Approved — by either route — while Draft and Pending
stay saveable half-filled so operators can fill records in passes.
Uses the dev DB directly; creates throwaway rows and deletes them.
"""
from database import get_db, get_cursor
from modules.SRV01 import model as srv_model
from modules.SRV01.views import _approval_blocker


def _seed(cur, *, billable=0):
    """Service type with one required field. Returns (svc_id, field_id)."""
    cur.execute("""INSERT INTO finance_service_types (service_code, service_name, has_custom_fields)
                   VALUES ('ZZTEST02', 'Throwaway Required Service', 1) RETURNING id""")
    svc_id = cur.fetchone()['id']
    cur.execute("""INSERT INTO service_field_definitions
                   (service_type_id, field_name, field_label, field_type,
                    is_required, is_billable_qty, is_active)
                   VALUES (%s, 'zz_start', 'ZZ Start Time', 'datetime', 1, %s, 1) RETURNING id""",
                [svc_id, billable])
    return svc_id, cur.fetchone()['id']


def _cleanup(cur, svc_id, field_id):
    cur.execute('DELETE FROM service_field_definitions WHERE id=%s', [field_id])
    cur.execute('DELETE FROM finance_service_types WHERE id=%s', [svc_id])


def test_a_blank_required_field_is_reported_by_its_label():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_id = _seed(cur)
    conn.commit()
    try:
        assert srv_model.missing_required(svc_id, []) == ['ZZ Start Time']
        assert srv_model.missing_required(
            svc_id, [{'field_definition_id': field_id, 'field_value': '   '}]) == ['ZZ Start Time']
        assert srv_model.missing_required(
            svc_id, [{'field_definition_id': field_id, 'field_value': '2026-09-01 08:00'}]) == []
    finally:
        _cleanup(cur, svc_id, field_id)
        conn.commit(); conn.close()


def test_approval_is_blocked_while_a_required_field_is_empty():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_id = _seed(cur)
    conn.commit()
    try:
        header = {'service_type_id': svc_id, 'billable_quantity': 5}
        blocker = _approval_blocker(header, [])
        assert blocker is not None and 'ZZ Start Time' in blocker

        filled = [{'field_definition_id': field_id, 'field_value': '2026-09-01 08:00'}]
        assert _approval_blocker(header, filled) is None
    finally:
        _cleanup(cur, svc_id, field_id)
        conn.commit(); conn.close()


def test_a_blank_billable_quantity_blocks_approval_but_zero_is_named_as_such():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_id = _seed(cur, billable=1)
    conn.commit()
    try:
        filled = [{'field_definition_id': field_id, 'field_value': '2026-09-01 08:00'}]
        assert srv_model.has_billable_qty_field(svc_id) is True

        # Blank arrives as None now (the page used to coerce it to 0).
        assert 'Billable quantity is required' in _approval_blocker(
            {'service_type_id': svc_id, 'billable_quantity': None}, filled)
        assert 'greater than zero' in _approval_blocker(
            {'service_type_id': svc_id, 'billable_quantity': 0}, filled)
        assert _approval_blocker(
            {'service_type_id': svc_id, 'billable_quantity': 6.5}, filled) is None
    finally:
        _cleanup(cur, svc_id, field_id)
        conn.commit(); conn.close()


def test_a_service_type_without_required_fields_approves_freely():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("""INSERT INTO finance_service_types (service_code, service_name)
                   VALUES ('ZZTEST03', 'Throwaway Plain Service') RETURNING id""")
    svc_id = cur.fetchone()['id']
    conn.commit()
    try:
        assert srv_model.missing_required(svc_id, []) == []
        assert _approval_blocker({'service_type_id': svc_id, 'billable_quantity': None}, []) is None
    finally:
        cur.execute('DELETE FROM finance_service_types WHERE id=%s', [svc_id])
        conn.commit(); conn.close()
