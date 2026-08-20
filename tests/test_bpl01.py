"""BPL01 berth planning: the draft-plan timeline math, lane conflict detection,
queueing behind an occupied berth, and the payload guard on the JSONB parcels
column. Uses the dev DB for the cascade + validation tests, cleaned up after.

A planned parcel carries the hours the planner expects it to take, plus delay
line items (delay type + hours, the same delay master LUEU01 picks from).
end = start + hours + delay hours.
"""
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


@pytest.fixture
def vcn_id():
    """A throwaway VCN — planning now accepts VCN vessels too, not just EV01."""
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vcn_header (operation_type, vessel_name) "
                "VALUES ('Import', 'ZZ TEST VCN VESSEL') RETURNING id")
    row_id = cur.fetchone()['id']
    conn.commit(); conn.close()
    try:
        yield row_id
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM berth_plan WHERE vcn_id=%s', [row_id])
        cur.execute('DELETE FROM vcn_header WHERE id=%s', [row_id])
        conn.commit(); conn.close()


# ── planning math: end = start + hours + delay hours ─────────────────────────

def test_parcel_end_is_start_plus_hours():
    assert model.parcel_end({'start': '2026-08-14T22:00', 'hours': 20}) \
        == _dt('2026-08-15 18:00')


def test_parcel_end_adds_delay_line_items_to_the_hours():
    # 20 h of work + 2 h rain + 1.5 h tank change = 23.5 h
    parcel = {'start': '2026-08-14T22:00', 'hours': 20,
              'delays': [{'name': 'Rain', 'hours': 2},
                         {'name': 'Tank change', 'hours': 1.5}]}
    assert model.parcel_end(parcel) == _dt('2026-08-15 21:30')


def test_parcel_end_ignores_delay_lines_with_no_hours_yet():
    parcel = {'start': '2026-08-14T22:00', 'hours': 20,
              'delays': [{'name': 'Rain', 'hours': None}, {'name': '', 'hours': ''}]}
    assert model.parcel_end(parcel) == _dt('2026-08-15 18:00')


def test_parcel_end_is_none_without_hours():
    # the planner has not said how long it takes — no end time, not an error
    assert model.parcel_end({'start': '2026-08-14T22:00', 'hours': None}) is None
    assert model.parcel_end({'start': '2026-08-14T22:00', 'hours': 0}) is None


def test_parcel_end_is_none_without_a_start():
    assert model.parcel_end({'start': None, 'hours': 20}) is None


def test_a_date_only_stamp_is_read_as_midnight():
    """vcn_header.doc_date is date-only text. Dropping it on the floor would
    leave every VCN vessel showing no ETA."""
    assert model.parcel_end({'start': '2026-08-14', 'hours': 10}) == _dt('2026-08-14 10:00')


def test_delay_only_parcel_has_no_end_without_working_hours():
    # a parcel that is nothing but delay is not a schedule
    assert model.parcel_end({'start': '2026-08-14T22:00', 'hours': None,
                             'delays': [{'name': 'Rain', 'hours': 4}]}) is None


def test_vessel_end_is_the_latest_parcel_because_parcels_run_in_parallel():
    parcels = [
        {'start': '2026-08-14T22:00', 'hours': 10},   # ends 08-15 08:00
        {'start': '2026-08-14T22:00', 'hours': 20},   # ends 08-15 18:00
    ]
    assert model.vessel_end(parcels) == _dt('2026-08-15 18:00')


def test_vessel_end_ignores_parcels_with_no_hours_but_still_uses_the_rest():
    parcels = [
        {'start': '2026-08-14T22:00', 'hours': 10},
        {'start': '2026-08-14T22:00', 'hours': None},
    ]
    assert model.vessel_end(parcels) == _dt('2026-08-15 08:00')


def test_vessel_end_is_none_when_no_parcel_has_both_start_and_hours():
    assert model.vessel_end([{'start': None, 'hours': None}]) is None
    assert model.vessel_end([]) is None


def test_vessel_start_is_the_earliest_parcel_start():
    parcels = [
        {'start': '2026-08-15T06:00', 'hours': 1},
        {'start': '2026-08-14T22:00', 'hours': 1},
        {'start': None, 'hours': 1},
    ]
    assert model.vessel_start(parcels) == _dt('2026-08-14 22:00')


# ── lane conflicts: a planned vessel starting before the one ahead of it ends ──

def _plan(source_id, start, hours=10, delays=None):
    return {'source': 'EV', 'source_id': source_id,
            'parcels': [{'cargo': 'HSD', 'qty': 4800, 'start': start,
                         'hours': hours, 'delays': delays or []}]}


def test_plan_conflicts_when_it_starts_before_the_berthed_vessel_finishes():
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
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T18:00')],
    )
    assert lane[0]['conflict_with'] is None


def test_second_plan_conflicts_with_the_first_plan_ahead_of_it():
    # MT ASHOK runs 08-15 18:00 -> 08-16 04:00 (10 h)
    lane = model.annotate_lane(
        occupied=[],
        plans=[
            {**_plan(1, '2026-08-15T18:00'), 'vessel_name': 'MT ASHOK'},
            {**_plan(2, '2026-08-16T00:00'), 'vessel_name': 'NEW HOPE'},
        ],
    )
    assert lane[0]['conflict_with'] is None
    assert lane[1]['conflict_with'] == 'MT ASHOK'


def test_a_delay_line_can_push_the_next_vessel_into_conflict():
    """The point of delay lines: 4 h of rain on the vessel ahead means the one
    behind it no longer fits where it was planned."""
    ahead_clean = {**_plan(1, '2026-08-15T18:00'), 'vessel_name': 'MT ASHOK'}
    behind = {**_plan(2, '2026-08-16T04:00'), 'vessel_name': 'NEW HOPE'}
    assert model.annotate_lane([], [ahead_clean, behind])[1]['conflict_with'] is None

    ahead_delayed = {**_plan(1, '2026-08-15T18:00', delays=[{'name': 'Rain', 'hours': 4}]),
                     'vessel_name': 'MT ASHOK'}
    assert model.annotate_lane([], [ahead_delayed, behind])[1]['conflict_with'] == 'MT ASHOK'


def test_unhoured_plan_ahead_does_not_falsely_clear_the_one_behind_it():
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[
            {**_plan(1, '2026-08-15T20:00', hours=None), 'vessel_name': 'MT ASHOK'},
            {**_plan(2, '2026-08-15T12:00'), 'vessel_name': 'NEW HOPE'},
        ],
    )
    assert lane[1]['conflict_with'] == 'SC GARNET'


# ── queueing: a vessel dropped behind another starts when the berth frees ──

def test_lane_free_at_is_the_latest_end_in_the_lane():
    assert model.lane_free_at(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T18:00')],          # 10 h -> 08-16 04:00
    ) == _dt('2026-08-16 04:00')


def test_lane_free_at_is_none_for_an_empty_berth():
    assert model.lane_free_at(occupied=[], plans=[]) is None


def test_lane_free_at_ignores_plans_with_no_hours_yet():
    assert model.lane_free_at(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[_plan(1, '2026-08-15T20:00', hours=None)],
    ) == _dt('2026-08-15 18:00')


def test_seed_parcels_starts_the_new_vessel_when_the_berth_frees(berths, ev_id):
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO expected_vessels (vessel_name, doc_status, cargo_name, quantity) "
                "VALUES ('ZZ AHEAD', 'Pending', 'HSD', '4800') RETURNING id")
    ahead = cur.fetchone()['id']
    cur.execute("UPDATE expected_vessels SET cargo_name='MS', quantity='2400' WHERE id=%s", [ev_id])
    conn.commit(); conn.close()
    try:
        model.save_plan('EV', ahead, berths[0],
                        [{'cargo': 'HSD', 'qty': 4800, 'start': '2026-08-15T18:00',
                          'hours': 10, 'delays': []}], 'tester')
        parcels = model.seed_parcels('EV', ev_id, berths[0])
        assert [p['start'] for p in parcels] == ['2026-08-16T04:00']
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM berth_plan WHERE ev_id=%s', [ahead])
        cur.execute('DELETE FROM expected_vessels WHERE id=%s', [ahead])
        conn.commit(); conn.close()


def test_seed_parcels_leaves_start_and_hours_blank_on_a_free_berth(berths, ev_id):
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("UPDATE expected_vessels SET cargo_name='HSD,MS', quantity='9600,4800' "
                "WHERE id=%s", [ev_id])
    conn.commit(); conn.close()
    parcels = model.seed_parcels('EV', ev_id, berths[0])
    assert [p['cargo'] for p in parcels] == ['HSD', 'MS']
    assert [p['start'] for p in parcels] == [None, None]
    assert [p['hours'] for p in parcels] == [None, None]
    assert [p['delays'] for p in parcels] == [[], []]


def test_seed_parcels_for_a_vcn_uses_its_own_declared_parcels(berths, vcn_id):
    """A VCN already declares its parcels — seed from those rather than make
    the planner retype what the system knows."""
    conn = get_db(); cur = get_cursor(conn)
    for seq, (cargo, qty) in enumerate([('HSD', '9600'), ('MS', '4800')], start=1):
        cur.execute('''INSERT INTO vcn_consigners (vcn_id, cargo_name, quantity, parcel_seq, parcel_no)
                       VALUES (%s,%s,%s,%s,%s)''', [vcn_id, cargo, qty, seq, f'P{seq}'])
    conn.commit(); conn.close()
    parcels = model.seed_parcels('VCN', vcn_id, berths[0])
    assert [(p['cargo'], p['qty']) for p in parcels] == [('HSD', 9600.0), ('MS', 4800.0)]
    assert [p['hours'] for p in parcels] == [None, None]


# ── payload guard: parcels is JSONB written straight from the browser ──

def test_save_plan_rejects_a_berth_that_is_not_in_the_master(ev_id):
    with pytest.raises(ValueError, match='berth'):
        model.save_plan('EV', ev_id, 'NOT A REAL BERTH', [], 'tester')


def test_save_plan_rejects_an_unknown_source(berths, ev_id):
    with pytest.raises(ValueError, match='source'):
        model.save_plan('BARGE', ev_id, berths[0], [], 'tester')


def test_save_plan_rejects_parcels_that_are_not_a_list(berths, ev_id):
    with pytest.raises(ValueError, match='parcels'):
        model.save_plan('EV', ev_id, berths[0], {'cargo': 'HSD'}, 'tester')


def test_save_plan_rejects_a_parcel_with_an_unknown_key(berths, ev_id):
    with pytest.raises(ValueError, match='parcels'):
        model.save_plan('EV', ev_id, berths[0],
                        [{'cargo': 'HSD', 'qty': 1, 'start': None, 'hours': 1,
                          'delays': [], 'evil': 'x'}], 'tester')


def test_save_plan_rejects_non_numeric_hours(berths, ev_id):
    with pytest.raises(ValueError, match='parcels'):
        model.save_plan('EV', ev_id, berths[0],
                        [{'cargo': 'HSD', 'qty': 1, 'start': None,
                          'hours': 'ages', 'delays': []}], 'tester')


def test_save_plan_rejects_delays_that_are_not_a_list(berths, ev_id):
    with pytest.raises(ValueError, match='delays'):
        model.save_plan('EV', ev_id, berths[0],
                        [{'cargo': 'HSD', 'qty': 1, 'start': None, 'hours': 1,
                          'delays': 'Rain'}], 'tester')


def test_save_plan_rejects_a_delay_line_with_a_bad_shape(berths, ev_id):
    with pytest.raises(ValueError, match='delays'):
        model.save_plan('EV', ev_id, berths[0],
                        [{'cargo': 'HSD', 'qty': 1, 'start': None, 'hours': 1,
                          'delays': [{'name': 'Rain', 'hours': 'lots'}]}], 'tester')


# ── sources: a plan hangs off exactly one of EV01 or a VCN ──

def test_a_vcn_vessel_can_be_planned(berths, vcn_id):
    model.save_plan('VCN', vcn_id, berths[0],
                    [{'cargo': 'HSD', 'qty': 4800, 'start': '2026-08-15T18:00',
                      'hours': 10, 'delays': []}], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT ev_id, vcn_id, berth_name FROM berth_plan WHERE vcn_id=%s', [vcn_id])
    row = cur.fetchone(); conn.close()
    assert row['ev_id'] is None and row['vcn_id'] == vcn_id
    assert row['berth_name'] == berths[0]


def test_plan_is_deleted_when_its_expected_vessel_is_deleted(berths, ev_id):
    """EV01 deletes the expected_vessels row on move-to-VCN. The ON DELETE
    CASCADE is the entire cleanup story, so it must actually be there."""
    model.save_plan('EV', ev_id, berths[0], [], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('DELETE FROM expected_vessels WHERE id=%s', [ev_id])
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM berth_plan WHERE ev_id=%s', [ev_id])
    assert cur.fetchone()['n'] == 0, 'ON DELETE CASCADE missing on berth_plan.ev_id'
    conn.close()


def test_plan_is_deleted_when_its_vcn_is_deleted(berths, vcn_id):
    model.save_plan('VCN', vcn_id, berths[0], [], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id])
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM berth_plan WHERE vcn_id=%s', [vcn_id])
    assert cur.fetchone()['n'] == 0, 'ON DELETE CASCADE missing on berth_plan.vcn_id'
    conn.close()


def test_a_plan_row_cannot_carry_both_sources(berths, ev_id, vcn_id):
    """The CHECK constraint is what stops a plan being two vessels at once."""
    conn = get_db(); cur = get_cursor(conn)
    with pytest.raises(Exception):
        cur.execute('INSERT INTO berth_plan (ev_id, vcn_id, berth_name) VALUES (%s,%s,%s)',
                    [ev_id, vcn_id, berths[0]])
        conn.commit()
    conn.close()


def test_saving_the_same_vessel_twice_moves_it_rather_than_duplicating_it(berths, ev_id):
    model.save_plan('EV', ev_id, berths[0], [], 'tester')
    model.save_plan('EV', ev_id, berths[1], [], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM berth_plan WHERE ev_id=%s', [ev_id])
    rows = cur.fetchall(); conn.close()
    assert len(rows) == 1, 'UNIQUE(ev_id) missing — vessel planned at two berths'
    assert rows[0]['berth_name'] == berths[1]


def test_saving_the_same_vcn_twice_moves_it_rather_than_duplicating_it(berths, vcn_id):
    model.save_plan('VCN', vcn_id, berths[0], [], 'tester')
    model.save_plan('VCN', vcn_id, berths[1], [], 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM berth_plan WHERE vcn_id=%s', [vcn_id])
    rows = cur.fetchall(); conn.close()
    assert len(rows) == 1, 'UNIQUE(vcn_id) missing — VCN planned at two berths'
    assert rows[0]['berth_name'] == berths[1]
