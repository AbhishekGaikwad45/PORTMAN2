"""SRV01 service record numbers: plain integers starting at the admin start
number, with the newest number freed for reuse when its row is deleted.
Uses the dev DB directly; creates throwaway rows and deletes them."""
from database import get_db, get_cursor, get_module_config, save_module_config
from modules.SRV01 import model as srv_model


def test_service_record_number_is_a_plain_number_from_the_start_number():
    cfg = get_module_config('SRV01')
    save_module_config('SRV01', dict(cfg, service_start_no=999900))
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT id FROM finance_service_types ORDER BY id LIMIT 1')
    svc_id = cur.fetchone()['id']
    ids = []
    try:
        assert srv_model.get_next_record_number() == '999900'

        cur.execute("INSERT INTO service_records (record_number, service_type_id, source_type, source_id) "
                    "VALUES ('999900', %s, 'VCN', 0) RETURNING id", [svc_id])
        ids.append(cur.fetchone()['id'])
        conn.commit()
        assert srv_model.get_next_record_number() == '999901'

        # A mistake on the newest record: delete it and the number comes back.
        cur.execute('DELETE FROM service_records WHERE id=%s', [ids.pop()])
        conn.commit()
        assert srv_model.get_next_record_number() == '999900'
        cur.execute("INSERT INTO service_records (record_number, service_type_id, source_type, source_id) "
                    "VALUES ('999900', %s, 'VCN', 0) RETURNING id", [svc_id])
        ids.append(cur.fetchone()['id'])
        conn.commit()

        # Legacy SRV#### numbers are ignored, not continued.
        cur.execute("INSERT INTO service_records (record_number, service_type_id, source_type, source_id) "
                    "VALUES ('SRV9999', %s, 'VCN', 0) RETURNING id", [svc_id])
        ids.append(cur.fetchone()['id'])
        conn.commit()
        assert srv_model.get_next_record_number() == '999901'
    finally:
        for row_id in ids:
            cur.execute('DELETE FROM service_records WHERE id=%s', [row_id])
        conn.commit(); conn.close()
        save_module_config('SRV01', cfg)
