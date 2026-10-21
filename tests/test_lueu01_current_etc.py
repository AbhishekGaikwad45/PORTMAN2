"""ETC follows the current flow, not the slow start.

DAWN MANSAROVAR / VCN-2627-245 P1: target 8800, logged 278 over 03:42-08:00
(ramp-up, ~65 MT/h) then 720 in 08:00-09:00. The cumulative avg (188.3 MT/h)
put ETC at 15 Oct ~01:22; at the current 720 MT/h the remaining 7802 MT
finishes 13 Oct ~19:50.
Run: python tests/test_lueu01_current_etc.py"""
from datetime import datetime
from modules.LUEU01.model import current_etc

ROWS = [
    {'entry_date': '2026-10-13', 'from_time': '03:42', 'to_time': '08:00', 'quantity': 278},
    {'entry_date': '2026-10-13', 'from_time': '08:00', 'to_time': '09:00', 'quantity': 720},
]


def test_etc_uses_latest_row_rate_from_last_log_end():
    rate, etc = current_etc(ROWS, 8800 - 998)
    assert rate == 720
    assert etc.strftime('%Y-%m-%d %H:%M') == '2026-10-13 19:50'


def test_idle_row_moves_the_anchor_but_keeps_the_rate():
    rows = ROWS + [{'entry_date': '2026-10-13', 'from_time': '09:00', 'to_time': '10:00', 'quantity': 0}]
    rate, etc = current_etc(rows, 7802)
    assert rate == 720
    assert etc.strftime('%Y-%m-%d %H:%M') == '2026-10-13 20:50'


def test_row_crossing_midnight_ends_next_day():
    rows = [{'entry_date': '2026-10-13', 'from_time': '23:00', 'to_time': '01:00', 'quantity': 1000}]
    rate, etc = current_etc(rows, 500)
    assert rate == 500 and etc == datetime(2026, 10, 14, 2, 0)


def test_no_etc_when_done_or_no_flow():
    assert current_etc(ROWS, 0)[1] is None
    assert current_etc([dict(ROWS[0], quantity=0)], 100) == (0.0, None)
    assert current_etc([], 100) == (0.0, None)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all passed')
