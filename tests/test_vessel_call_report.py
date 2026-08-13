"""Vessel Call Report: the two source queries must run against the real schema,
and the derived columns must be right. Run: python tests/test_vessel_call_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import excel_export
from database import get_db, get_cursor
from modules.RP01.RP01.vessel_call_report import (
    COLS, _ACTUAL_SQL, _MASTER_SQL, _dedupe_csv, _fin_year, _hours, _month,
)


def test_dedupe_csv():
    # parcels store multi-value cells, so aggregating repeats the shared entries
    assert _dedupe_csv('P1, P1, P2') == 'P1, P2'
    assert _dedupe_csv('T2,  T2') == 'T2'
    assert _dedupe_csv('ADM AGRO, JUBILENT') == 'ADM AGRO, JUBILENT'
    assert _dedupe_csv('') is None
    assert _dedupe_csv(None) is None


def test_fin_year():
    assert _fin_year('VCN-2526-001', None) == '2025-26'
    assert _fin_year('VCN-2425-017', None) == '2024-25'
    assert _fin_year(None, '2024-11-20') == '2024-25'   # Nov -> FY starting Apr 2024
    assert _fin_year(None, '2025-02-10') == '2024-25'   # Feb -> still the Apr-2024 FY
    assert _fin_year(None, '2025-04-01') == '2025-26'   # Apr -> new FY
    assert _fin_year(None, None) == ''


def test_month():
    assert _month('2024-11-25T07:48') == 'Nov-24'
    assert _month(None, '', '2025-01-03T10:00') == 'Jan-25'   # falls through to the first usable
    assert _month(None, '') == ''
    assert _month('garbage') == ''


def test_hours():
    assert _hours('2024-11-25T06:00', '2024-11-25T18:00') == 12.0
    assert _hours('2024-11-25T18:00', '2024-11-25T06:00') is None   # end before start
    assert _hours('2024-11-25T06:00', None) is None
    assert _hours('not-a-date', '2024-11-25T06:00') is None


def test_cols_cover_both_sources():
    """Every non-'dt:' COLS field must be produced by at least one query, or the
    column is silently blank in the sheet."""
    fields = {f[3:] if f.startswith('dt:') else f for _, f in COLS}
    sql = _MASTER_SQL + _ACTUAL_SQL
    missing = sorted(f for f in fields if f not in sql)
    # these are assembled in Python, not selected
    assert missing == ['month_jnpt', 'month_jsw'] or missing == [], missing


def test_queries_run():
    """Both queries execute — catches a column renamed or dropped under us."""
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute(_MASTER_SQL)
        master = [dict(r) for r in cur.fetchall()]
        cur.execute(_ACTUAL_SQL)
        actual = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    # a row from either side must fill the sheet without blowing up
    for row in master + actual:
        assert len(excel_export.row_values(COLS, row)) == len(excel_export.headers(COLS))
    print(f'  queries ok — {len(master)} master rows, {len(actual)} actual rows')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print(f'ok  {name}')
    print('all passed')
