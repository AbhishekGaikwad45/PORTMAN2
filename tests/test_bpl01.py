"""BPL01 berth planning: the draft-plan timeline math, lane conflict detection,
and the payload guard on the JSONB parcels column. Uses the dev DB for the
cascade + validation tests, cleaned up after."""
from datetime import datetime

import pytest

from database import get_db, get_cursor
from modules.BPL01 import model


def _dt(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M')


@pytest.fixture
def berths():
    """Two throwaway berths — port_berth_master may be empty in a dev DB, and
    these tests must not depend on whatever happens to be configured."""
    conn = get_db(); cur = get_cursor(conn)
    names = ['ZZ TEST BERTH A', 'ZZ TEST BERTH B']
    for n in names:
        cur.execute('INSERT INTO port_berth_master (berth_name) VALUES (%s)', [n])
    conn.commit(); conn.close()
    try:
        yield names
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM berth_plan WHERE berth_name = ANY(%s)', [names])
        cur.execute('DELETE FROM port_berth_master WHERE berth_name = ANY(%s)', [names])
        conn.commit(); conn.close()


@pytest.fixture
def ev_id():
    """A throwaway expected-vessel row to hang a plan off."""
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO expected_vessels (vessel_name, doc_status) "
                "VALUES ('ZZ TEST VESSEL', 'Pending') RETURNING id")
    row_id = cur.fetchone()['id']
    conn.commit(); conn.close()
    try:
        yield row_id
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM berth_plan WHERE ev_id=%s', [row_id])
        cur.execute('DELETE FROM expected_vessels WHERE id=%s', [row_id])
        conn.commit(); conn.close()


# ── planning math: end = start + qty/rate, same shape as LUEU01's etcText ──

def test_parcel_end_is_start_plus_qty_over_rate():
    # 9600 MT at 480 MT/hr = 20 h
    assert model.parcel_end({'start': '2026-08-14T22:00', 'qty': 9600, 'rate': 480}) \
        == _dt('2026-08-15 18:00')


def test_parcel_end_is_none_without_a_rate():
    # the planner has not typed a rate yet — no end time, not an error
    assert model.parcel_end({'start': '2026-08-14T22:00', 'qty': 9600, 'rate': None}) is None
    assert model.parcel_end({'start': '2026-08-14T22:00', 'qty': 9600, 'rate': 0}) is None


def test_parcel_end_is_none_without_a_start():
    assert model.parcel_end({'start': None, 'qty': 9600, 'rate': 480}) is None


def test_vessel_end_is_the_latest_parcel_because_parcels_run_in_parallel():
    # mirrors RP01's max(parcel ETCs) rollup — the last line to finish wins
    parcels = [
        {'start': '2026-08-14T22:00', 'qty': 4800, 'rate': 480},   # ends 08-15 08:00
        {'start': '2026-08-14T22:00', 'qty': 9600, 'rate': 480},   # ends 08-15 18:00
    ]
    assert model.vessel_end(parcels) == _dt('2026-08-15 18:00')


def test_vessel_end_ignores_unrated_parcels_but_still_uses_rated_ones():
    parcels = [
        {'start': '2026-08-14T22:00', 'qty': 4800, 'rate': 480},
        {'start': '2026-08-14T22:00', 'qty': 9600, 'rate': None},
    ]
    assert model.vessel_end(parcels) == _dt('2026-08-15 08:00')


def test_vessel_end_is_none_when_no_parcel_has_both_start_and_rate():
    assert model.vessel_end([{'start': None, 'qty': 9600, 'rate': None}]) is None
    assert model.vessel_end([]) is None


def test_vessel_start_is_the_earliest_parcel_start():
    parcels = [
        {'start': '2026-08-15T06:00', 'qty': 100, 'rate': 10},
        {'start': '2026-08-14T22:00', 'qty': 100, 'rate': 10},
        {'start': None, 'qty': 100, 'rate': 10},
    ]
    assert model.vessel_start(parcels) == _dt('2026-08-14 22:00')


# ── lane conflicts: a planned vessel starting before the one ahead of it ends ──

def _plan(ev_id, start, qty=4800, rate=480):
    return {'ev_id': ev_id, 'parcels': [{'cargo': 'HSD', 'qty': qty, 'rate': rate,
                                         'start': start}]}


def test_plan_conflicts_when_it_starts_before_the_berthed_vessel_finishes():
    # berthed vessel is busy until 08-15 18:00; the plan tries to start at 12:00
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T12:00')],
    )
    assert lane[0]['conflict_with'] == 'SC GARNET'


def test_plan_is_clear_when_it_starts_after_the_berthed_vessel_finishes():
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T19:00')],
    )
    assert lane[0]['conflict_with'] is None


def test_plan_starting_exactly_at_the_previous_end_is_not_a_conflict():
    # boundary: berth frees at 18:00, next vessel starts 18:00 — legal
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T18:00')],
    )
    assert lane[0]['conflict_with'] is None


def test_second_plan_conflicts_with_the_first_plan_ahead_of_it():
    # MT ASHOK runs 08-15 18:00 -> 08-16 04:00 (4800 @ 480 = 10h);
    # NEW HOPE tries to start at 08-16 00:00
    lane = model.annotate_lane(
        occupied=[],
        plans=[
            {**_plan(1, '2026-08-15T18:00'), 'vessel_name': 'MT ASHOK'},
            {**_plan(2, '2026-08-16T00:00'), 'vessel_name': 'NEW HOPE'},
        ],
    )
    assert lane[0]['conflict_with'] is None
    assert lane[1]['conflict_with'] == 'MT ASHOK'


def test_unrated_plan_ahead_does_not_falsely_clear_the_one_behind_it():
    # a plan with no rate has no end; it must not silently reset the lane's
    # running high-water mark and let the next vessel look conflict-free
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[
            {**_plan(1, '2026-08-15T20:00', rate=None), 'vessel_name': 'MT ASHOK'},
            {**_plan(2, '2026-08-15T12:00'), 'vessel_name': 'NEW HOPE'},
        ],
    )
    assert lane[1]['conflict_with'] == 'SC GARNET'


# ── queueing: a vessel dropped behind another starts when the berth frees ──

def test_lane_free_at_is_the_latest_end_in_the_lane():
    assert model.lane_free_at(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T18:00')],          # 4800 @ 480 = 10h -> 08-16 04:00
    ) == _dt('2026-08-16 04:00')


def test_lane_free_at_is_none_for_an_empty_berth():
    assert model.lane_free_at(occupied=[], plans=[]) is None


def test_lane_free_at_ignores_plans_with_no_rate_yet():
    # an unrated plan has no end and must not hide the berthed vessel's ETC
    assert model.lane_free_at(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T20:00', rate=None)],
    ) == _dt('2026-08-15 18:00')


def test_seed_parcels_starts_the_new_vessel_when_the_berth_frees(berths, ev_id):
    """Dropping a vessel behind one that ends at a known time should queue it
    at that time, not leave the planner to retype it."""
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO expected_vessels (vessel_name, doc_status, cargo_name, quantity) "
                "VALUES ('ZZ AHEAD', 'Pending', 'HSD', '4800') RETURNING id")
    ahead = cur.fetchone()['id']
    conn.commit(); conn.close()
    try:
        # the vessel already in the lane runs 08-15 18:00 -> 08-16 04:00
        model.save_plan(ahead, berths[0], [{'cargo': 'HSD', 'qty': 4800, 'rate': 480,
                                            'start': '2026-08-15T18:00'}], 'tester')
        ev = {'cargo_name': 'MS', 'quantity': '2400'}
        parcels = model.seed_parcels(ev, berths[0])
        assert [p['start'] for p in parcels] == ['2026-08-16T04:00']
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM berth_plan WHERE ev_id=%s', [ahead])
        cur.execute('DELETE FROM expected_vessels WHERE id=%s', [ahead])
        conn.commit(); conn.close()


def test_seed_parcels_leaves_start_blank_on_a_free_berth(berths):
    parcels = model.seed_parcels({'cargo_name': 'HSD,MS', 'quantity': '9600,4800'}, berths[0])
    assert [p['cargo'] for p in parcels] == ['HSD', 'MS']
    assert [p['start'] for p in parcels] == [None, None]
    assert [p['rate'] for p in parcels] == [None, None]


# ── payload guard: parcels is JSONB written straight from the browser ──

def test_save_plan_rejects_a_berth_that_is_not_in_the_master(ev_id):
    with pytest.raises(ValueError, match='berth'):
        model.save_plan(ev_id, 'NOT A REAL BERTH', [], 'tester')


def test_save_plan_rejects_parcels_that_are_not_a_list(berths, ev_id):
    with pytest.raises(ValueError, match='parcels'):
        model.save_plan(ev_id, berths[0], {'cargo': 'HSD'}, 'tester')


def test_save_plan_rejects_a_parcel_with_an_unknown_key(berths, ev_id):
    with pytest.raises(ValueError, match='parcels'):
        model.save_plan(ev_id, berths[0], [{'cargo': 'HSD', 'qty': 1, 'rate': 1,
                                            'start': None, 'evil': 'x'}], 'tester')


def test_save_plan_rejects_a_non_numeric_quantity(berths, ev_id):
    with pytest.raises(ValueError, match='parcels'):
        model.save_plan(ev_id, berths[0], [{'cargo': 'HSD', 'qty': 'lots', 'rate': 1,
                                            'start': None}], 'tester')


# ── schema: the plan dies with its expected-vessel row ──

def test_plan_is_deleted_when_its_expected_vessel_is_deleted(berths, ev_id):
    """EV01 deletes the expected_vessels row on move-to-VCN. The ON DELETE
    CASCADE is the entire cleanup story, so it must actually be there."""
    model.save_plan(ev_id, berths[0], [{'cargo': 'HSD', 'qty': 100, 'rate': 10,
                                        'start': '2026-08-14T22:00'}], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT COUNT(*) AS n FROM berth_plan WHERE ev_id=%s', [ev_id])
    assert cur.fetchone()['n'] == 1
    cur.execute('DELETE FROM expected_vessels WHERE id=%s', [ev_id])
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM berth_plan WHERE ev_id=%s', [ev_id])
    assert cur.fetchone()['n'] == 0, 'ON DELETE CASCADE missing on berth_plan.ev_id'
    conn.close()


def test_saving_the_same_vessel_twice_moves_it_rather_than_duplicating_it(berths, ev_id):
    model.save_plan(ev_id, berths[0], [], 'tester')
    model.save_plan(ev_id, berths[1], [], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM berth_plan WHERE ev_id=%s', [ev_id])
    rows = cur.fetchall(); conn.close()
    assert len(rows) == 1, 'UNIQUE(ev_id) missing — vessel planned at two berths'
    assert rows[0]['berth_name'] == berths[1]
