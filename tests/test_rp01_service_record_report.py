"""RP01 Service Records report: the SRV01 xlsx dump.

Two shapes from one builder - a flat sheet with a Details column when no service
type is chosen, and real per-field columns when one is. Approved records only.
Uses the dev DB directly; creates throwaway rows and deletes them.
"""
from database import get_db, get_cursor
from modules.RP01.RP01 import service_record_report as srr
import excel_export


def _seed(cur):
    """One approved and one draft record on a throwaway service type with two
    custom fields. Returns (svc_id, [field_ids], approved_id, draft_id)."""
    cur.execute("""INSERT INTO finance_service_types (service_code, service_name, has_custom_fields)
                   VALUES ('ZZRP01', 'Throwaway Report Service', 1) RETURNING id""")
    svc_id = cur.fetchone()['id']
    field_ids = []
    for order, (name, label) in enumerate([('zz_make', 'ZZ Make'), ('zz_hours', 'ZZ Hours')], 1):
        cur.execute("""INSERT INTO service_field_definitions
                       (service_type_id, field_name, field_label, field_type, display_order, is_active)
                       VALUES (%s, %s, %s, 'text', %s, 1) RETURNING id""",
                    [svc_id, name, label, order])
        field_ids.append(cur.fetchone()['id'])

    cur.execute("""INSERT INTO service_records
                   (record_number, service_type_id, source_type, source_id, source_display,
                    record_date, billable_quantity, billable_uom, doc_status, is_billed)
                   VALUES ('ZZR00001', %s, 'Customer', 0, 'ZZ Test Customer',
                           '2026-09-01', 6.5, 'HRS', 'Approved', 0) RETURNING id""", [svc_id])
    approved_id = cur.fetchone()['id']
    for fid, val in zip(field_ids, ['Liebherr', '6.5']):
        cur.execute("""INSERT INTO service_record_values
                       (service_record_id, field_definition_id, field_value)
                       VALUES (%s, %s, %s)""", [approved_id, fid, val])

    cur.execute("""INSERT INTO service_records
                   (record_number, service_type_id, source_type, source_id, source_display,
                    record_date, doc_status)
                   VALUES ('ZZR00002', %s, 'Customer', 0, 'ZZ Test Customer',
                           '2026-09-02', 'Draft') RETURNING id""", [svc_id])
    draft_id = cur.fetchone()['id']
    return svc_id, field_ids, approved_id, draft_id


def _cleanup(cur, svc_id, field_ids, *record_ids):
    for rid in record_ids:
        cur.execute('DELETE FROM service_record_values WHERE service_record_id=%s', [rid])
        cur.execute('DELETE FROM service_records WHERE id=%s', [rid])
    for fid in field_ids:
        cur.execute('DELETE FROM service_field_definitions WHERE id=%s', [fid])
    cur.execute('DELETE FROM finance_service_types WHERE id=%s', [svc_id])


def test_flat_dump_collapses_custom_fields_into_details_and_skips_drafts():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_ids, approved_id, draft_id = _seed(cur)
    conn.commit()
    try:
        cols, rows = srr.report_rows()
        assert cols[-1] == ('Details', 'details')

        ours = [r for r in rows if r['record_number'] == 'ZZR00001']
        assert len(ours) == 1, 'approved record missing from the dump'
        assert 'ZZ Make: Liebherr' in ours[0]['details']
        assert 'ZZ Hours: 6.5' in ours[0]['details']

        assert not any(r['record_number'] == 'ZZR00002' for r in rows), \
            'draft record leaked into an Approved-only report'
    finally:
        _cleanup(cur, svc_id, field_ids, approved_id, draft_id)
        conn.commit(); conn.close()


def test_a_service_type_filter_expands_custom_fields_into_real_columns():
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_ids, approved_id, draft_id = _seed(cur)
    conn.commit()
    try:
        cols, rows = srr.report_rows(svc_id)

        labels = [h for h, _ in cols]
        assert 'ZZ Make' in labels and 'ZZ Hours' in labels
        assert 'Details' not in labels
        # Custom fields keep their configured display_order.
        assert labels.index('ZZ Make') < labels.index('ZZ Hours')

        assert len(rows) == 1                      # only this type, only approved
        assert rows[0][f'cf_{field_ids[0]}'] == 'Liebherr'
        assert rows[0][f'cf_{field_ids[1]}'] == '6.5'
    finally:
        _cleanup(cur, svc_id, field_ids, approved_id, draft_id)
        conn.commit(); conn.close()


def test_both_shapes_produce_a_row_matching_the_header_width():
    """Guards the sheet itself: a col spec and a row that disagree silently
    shift every value one column across in Excel."""
    conn = get_db(); cur = get_cursor(conn)
    svc_id, field_ids, approved_id, draft_id = _seed(cur)
    conn.commit()
    try:
        for service_type_id in (None, svc_id):
            cols, rows = srr.report_rows(service_type_id)
            width = len(excel_export.headers(cols))
            for row in rows:
                assert len(excel_export.row_values(cols, row)) == width
    finally:
        _cleanup(cur, svc_id, field_ids, approved_id, draft_id)
        conn.commit(); conn.close()


def test_an_empty_report_still_carries_its_custom_field_columns():
    """A sheet with no rows must carry the same columns as one with rows,
    or the Details column vanishes and two exports cannot be appended."""
    conn = get_db(); cur = get_cursor(conn)
    # A service type with fields but deliberately no service records at all.
    cur.execute("""INSERT INTO finance_service_types (service_code, service_name, has_custom_fields)
                   VALUES ('ZZRP02', 'Throwaway Empty Service', 1) RETURNING id""")
    svc_id = cur.fetchone()['id']
    cur.execute("""INSERT INTO service_field_definitions
                   (service_type_id, field_name, field_label, field_type, display_order, is_active)
                   VALUES (%s, 'zz_only', 'ZZ Only Field', 'text', 1, 1) RETURNING id""", [svc_id])
    field_id = cur.fetchone()['id']
    conn.commit()
    try:
        cols, rows = srr.report_rows(svc_id)
        assert rows == []
        assert ('ZZ Only Field', f'cf_{field_id}') in cols, \
            'empty per-type sheet lost its custom field columns'

        flat_cols, _ = srr.report_rows()
        assert flat_cols[-1] == ('Details', 'details'), \
            'flat sheet lost its Details column'
    finally:
        cur.execute('DELETE FROM service_field_definitions WHERE id=%s', [field_id])
        cur.execute('DELETE FROM finance_service_types WHERE id=%s', [svc_id])
        conn.commit(); conn.close()
