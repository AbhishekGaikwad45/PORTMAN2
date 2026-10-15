"""Pure helpers behind the Port Overview cards and tide strip."""
from datetime import datetime

from modules.RP01.RP01.port_overview.views import (
    _classify_tides, _op_day_start, _required_daily, _target_totals)


def test_target_totals_outlook_overrides_target():
    t = {'targets': [
        {'name': 'Edible Oil', 'monthly_data': [
            {'month': 'Oct', 'target': 100, 'outlook': 150},
            {'month': 'Nov', 'target': 200, 'outlook': 0}]},
        {'name': 'POL', 'monthly_data': [{'month': 'Oct', 'budget_quantity': 50}]},
    ]}
    assert _target_totals(t, 'Oct') == (400, 200)
    assert _target_totals(None, 'Oct') == (0, 0)


def test_required_daily_never_negative():
    assert _required_daily(1000, 400, 6) == 100
    assert _required_daily(1000, 1200, 6) == 0
    assert _required_daily(0, 0, 6) == 0


def test_op_day_rolls_over_at_seven():
    assert _op_day_start(datetime(2026, 10, 15, 6, 59)) == datetime(2026, 10, 14, 7, 0)
    assert _op_day_start(datetime(2026, 10, 15, 7, 0)) == datetime(2026, 10, 15, 7, 0)


def test_tides_alternate_hw_lw():
    rows = [(datetime(2026, 10, 15, h), m) for h, m in ((1, 4.1), (7, 0.9), (13, 4.3), (19, 1.0))]
    assert [t for _, _, t in _classify_tides(rows)] == ['HW', 'LW', 'HW', 'LW']
