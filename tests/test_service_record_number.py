"""FSTM01 record numbers: plain integers starting at the admin start number,
with the newest number freed for reuse when its row is deleted.
Uses the dev DB directly; creates throwaway service types and deletes them."""
from database import get_db, get_cursor, get_module_config, save_module_config
from modules.FSTM01 import model


def _code(row_id):
    return model.get_service_type_by_id(row_id)['service_code']


def test_record_number_starts_at_config_and_reuses_freed_top():
    cfg = get_module_config('FSTM01')
    save_module_config('FSTM01', dict(cfg, service_start_no=999900))
    ids = []
    try:
        ids.append(model.save_service_type({'service_name': 'PT record no A'}))
        assert _code(ids[0]) == '999900', _code(ids[0])

        ids.append(model.save_service_type({'service_name': 'PT record no B'}))
        assert _code(ids[1]) == '999901', _code(ids[1])

        # Mistake on the newest row: delete it and the number comes back.
        model.delete_service_type(ids.pop())
        ids.append(model.save_service_type({'service_name': 'PT record no C'}))
        assert _code(ids[-1]) == '999901', _code(ids[-1])

        # A client-supplied code is ignored — numbering is system-assigned.
        ids.append(model.save_service_type({'service_name': 'PT record no D',
                                            'service_code': 'SRV01'}))
        assert _code(ids[-1]) == '999902', _code(ids[-1])
    finally:
        conn = get_db(); cur = get_cursor(conn)
        for row_id in ids:
            cur.execute('DELETE FROM finance_service_types WHERE id=%s', [row_id])
        conn.commit(); conn.close()
        save_module_config('FSTM01', cfg)
