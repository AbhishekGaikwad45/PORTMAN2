"""BPL01 berth planning.

A vessel's plan is an ordered list of line items that run one after another:

    Prior Documentation   (fixed bookend, typed hours)
    ... parcels and delays the planner inserts ...
    Post Documentation    (fixed bookend, typed hours)

A parcel's hours are derived from qty / flow rate; a doc or delay line carries
typed hours. Each item starts when the one before it ends, and each vessel in a
berth starts when the vessel before it ends.

DB-backed tests use the dev DB with throwaway rows, cleaned up after.
"""
from datetime import datetime

import pytest

from database import get_db, get_cursor
from modules.BPL01 import model


def _dt(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M')


def _doc(name, hours=4):
    return {'kind': 'doc', 'name': name, 'hours': hours}


def _parcel(name, qty, rate, pipeline=None):
    return {'kind': 'parcel', 'name': name, 'qty': qty, 'rate': rate, 'pipeline': pipeline}


def _delay(name, hours):
    return {'kind': 'delay', 'name': name, 'hours': hours}


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
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO expected_vessels (vessel_name, doc_status, cargo_name, quantity) "
                "VALUES ('ZZ TEST VESSEL', 'Pending', 'HSD', '9600') RETURNING id")
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


# ── item hours: parcels derive from qty/rate, everything else is typed ──

def test_parcel_hours_come_from_quantity_over_flow_rate():
    assert model.item_hours(_parcel('Furnace Oil', 15000, 1000)) == 15.0


def test_parcel_hours_can_be_fractional():
    # 1050 MT at 250 MT/hr = 4.2 h = 4 h 12 min
    assert model.item_hours(_parcel('Tolune', 1050, 250)) == 4.2


def test_parcel_hours_are_none_without_a_usable_rate():
    assert model.item_hours(_parcel('Furnace Oil', 15000, None)) is None
    assert model.item_hours(_parcel('Furnace Oil', 15000, 0)) is None
    assert model.item_hours(_parcel('Furnace Oil', None, 1000)) is None


def test_doc_and_delay_hours_are_typed_not_derived():
    assert model.item_hours(_doc('Prior Documentation', 4)) == 4.0
    assert model.item_hours(_delay('Rain', 2)) == 2.0
    assert model.item_hours(_delay('Rain', None)) is None


def test_a_typed_rate_never_overrides_a_parcels_derived_hours():
    """Hours is computed for parcels; a stale 'hours' on the payload must not
    win, or the table would disagree with its own qty and rate."""
    stale = {**_parcel('Furnace Oil', 15000, 1000), 'hours': 999}
    assert model.item_hours(stale) == 15.0


# ── chaining: each item starts when the previous one ends ──

def test_chain_runs_items_back_to_back():
    """The DAWN MANSAROVA R row from the planner's sheet, start to finish."""
    items = [_doc('Prior Documentation', 4),
             _parcel('Furnace Oil', 15000, 1000),
             _doc('Post Documentation', 4),
             _delay('Select Delay if any', 2)]
    out = model.chain(items, _dt('2026-08-15 02:00'))
    assert [(i['start'], i['end']) for i in out] == [
        (_dt('2026-08-15 02:00'), _dt('2026-08-15 06:00')),
        (_dt('2026-08-15 06:00'), _dt('2026-08-15 21:00')),
        (_dt('2026-08-15 21:00'), _dt('2026-08-16 01:00')),
        (_dt('2026-08-16 01:00'), _dt('2026-08-16 03:00')),
    ]


def test_chain_carries_fractional_hours_through_to_later_items():
    """SOUTHERN UNICORN: Tolune must start when SM ends, not when SM starts —
    this is what makes the plan sequential rather than parallel."""
    items = [_doc('Prior Documentation', 4),
             _parcel('SM', 2000, 250),        # 8 h
             _parcel('Tolune', 1050, 250),    # 4.2 h
             _doc('Post Documentation', 4)]
    out = model.chain(items, _dt('2026-08-16 03:00'))
    assert out[1]['start'] == _dt('2026-08-16 07:00')
    assert out[2]['start'] == _dt('2026-08-16 15:00')
    assert out[2]['end'] == _dt('2026-08-16 19:12')
    assert out[3]['end'] == _dt('2026-08-16 23:12')


def test_chain_stops_dead_at_an_item_with_no_hours():
    """An un-costed line has no end, so nothing after it has a known time —
    better a visible gap than a schedule built on a guess."""
    items = [_doc('Prior Documentation', 4),
             _parcel('Furnace Oil', 15000, None),
             _doc('Post Documentation', 4)]
    out = model.chain(items, _dt('2026-08-15 02:00'))
    assert out[0]['end'] == _dt('2026-08-15 06:00')
    assert out[1]['start'] == _dt('2026-08-15 06:00') and out[1]['end'] is None
    assert out[2]['start'] is None and out[2]['end'] is None


def test_chain_with_no_start_gives_every_item_no_time():
    items = [_doc('Prior Documentation', 4), _parcel('Furnace Oil', 15000, 1000)]
    out = model.chain(items, None)
    assert all(i['start'] is None and i['end'] is None for i in out)


def test_vessel_end_is_the_last_items_end_not_the_longest():
    items = [_doc('Prior Documentation', 4),
             _parcel('SM', 2000, 250),
             _parcel('Tolune', 1050, 250),
             _doc('Post Documentation', 4)]
    assert model.vessel_end(items, _dt('2026-08-16 03:00')) == _dt('2026-08-16 23:12')


def test_vessel_end_is_none_when_the_chain_breaks():
    items = [_doc('Prior Documentation', 4), _parcel('X', 100, None)]
    assert model.vessel_end(items, _dt('2026-08-16 03:00')) is None


# ── the fixed bookends ──

def test_default_items_are_the_two_documentation_bookends():
    items = model.default_items()
    assert [i['name'] for i in items] == ['Prior Documentation', 'Post Documentation']
    assert all(i['kind'] == 'doc' and i['fixed'] is True for i in items)
    assert [i['hours'] for i in items] == [model.DOC_HOURS, model.DOC_HOURS]


def test_seeded_parcels_land_between_the_bookends(berths, ev_id):
    items = model.seed_items('EV', ev_id, berths[0])
    assert [i['name'] for i in items] == ['Prior Documentation', 'HSD', 'Post Documentation']
    assert items[1]['kind'] == 'parcel' and items[1]['qty'] == 9600.0


def test_stored_items_always_carry_the_full_key_set(berths, ev_id):
    """Callers may omit keys that don't apply to their kind; storing a ragged
    shape pushes the missing-key handling onto every reader."""
    model.save_plan('EV', ev_id, berths[0],
                    [{'kind': 'delay', 'name': 'Rain', 'hours': 2}], None, 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT items FROM berth_plan WHERE ev_id=%s', [ev_id])
    items = cur.fetchone()['items']; conn.close()
    for it in items:
        assert set(it) == model.ITEM_KEYS, it


def test_save_plan_reinstates_missing_bookends(berths, ev_id):
    """The bookends are fixed for every vessel — a payload without them is
    repaired rather than rejected, so the plan can never lose its documentation."""
    model.save_plan('EV', ev_id, berths[0], [_parcel('HSD', 9600, 800)], None, 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT items FROM berth_plan WHERE ev_id=%s', [ev_id])
    items = cur.fetchone()['items']; conn.close()
    assert [i['name'] for i in items] == ['Prior Documentation', 'HSD', 'Post Documentation']


# ── lane chaining: a vessel starts when the one before it ends ──

def test_second_vessel_in_a_lane_starts_when_the_first_ends():
    """DAWN ends 16/08 03:00, so SOUTHERN starts there — no retyping."""
    dawn = {'source': 'EV', 'source_id': 1, 'vessel_name': 'DAWN MANSAROVA R',
            'start_dt': _dt('2026-08-15 02:00'),
            'items': [_doc('Prior Documentation', 4),
                      _parcel('Furnace Oil', 15000, 1000),
                      _doc('Post Documentation', 4),
                      _delay('Select Delay if any', 2)]}
    southern = {'source': 'EV', 'source_id': 2, 'vessel_name': 'SOUTHERN UNICORN',
                'start_dt': None,
                'items': [_doc('Prior Documentation', 4),
                          _parcel('SM', 2000, 250),
                          _parcel('Tolune', 1050, 250),
                          _doc('Post Documentation', 4)]}
    lane = model.annotate_lane([], [dawn, southern])
    assert lane[0]['end'] == _dt('2026-08-16 03:00')
    assert lane[1]['start'] == _dt('2026-08-16 03:00')
    assert lane[1]['end'] == _dt('2026-08-16 23:12')


def test_the_first_vessel_starts_after_the_berthed_vessel_finishes():
    plan = {'source': 'EV', 'source_id': 1, 'vessel_name': 'MT ASHOK', 'start_dt': None,
            'items': [_doc('Prior Documentation', 4)]}
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[plan])
    assert lane[0]['start'] == _dt('2026-08-15 18:00')
    assert lane[0]['end'] == _dt('2026-08-15 22:00')


def test_an_explicit_start_overrides_the_chain():
    """The planner can pin a vessel's start; the sheet's first vessel is typed."""
    first = {'source': 'EV', 'source_id': 1, 'vessel_name': 'A', 'start_dt': None,
             'items': [_doc('Prior Documentation', 4)]}
    pinned = {'source': 'EV', 'source_id': 2, 'vessel_name': 'B',
              'start_dt': _dt('2026-08-20 09:00'),
              'items': [_doc('Prior Documentation', 4)]}
    lane = model.annotate_lane(
        occupied=[{'vessel_name': 'SC GARNET', 'end': _dt('2026-08-15 18:00')}],
        plans=[first, pinned])
    assert lane[0]['start'] == _dt('2026-08-15 18:00')
    assert lane[1]['start'] == _dt('2026-08-20 09:00')


def test_a_pinned_start_before_the_previous_vessel_ends_is_flagged():
    first = {'source': 'EV', 'source_id': 1, 'vessel_name': 'A',
             'start_dt': _dt('2026-08-15 02:00'),
             'items': [_doc('Prior Documentation', 4)]}          # ends 06:00
    clash = {'source': 'EV', 'source_id': 2, 'vessel_name': 'B',
             'start_dt': _dt('2026-08-15 04:00'),
             'items': [_doc('Prior Documentation', 4)]}
    lane = model.annotate_lane([], [first, clash])
    assert lane[0]['conflict_with'] is None
    assert lane[1]['conflict_with'] == 'A'


def test_a_broken_chain_leaves_the_next_vessel_unscheduled():
    """No end on the vessel ahead means no derived start for the one behind."""
    broken = {'source': 'EV', 'source_id': 1, 'vessel_name': 'A',
              'start_dt': _dt('2026-08-15 02:00'),
              'items': [_parcel('X', 100, None)]}
    behind = {'source': 'EV', 'source_id': 2, 'vessel_name': 'B', 'start_dt': None,
              'items': [_doc('Prior Documentation', 4)]}
    lane = model.annotate_lane([], [broken, behind])
    assert lane[0]['end'] is None
    assert lane[1]['start'] is None and lane[1]['conflict_with'] is None


# ── payload guard: items is JSONB written straight from the browser ──

def test_save_plan_rejects_a_berth_that_is_not_in_the_master(ev_id):
    with pytest.raises(ValueError, match='berth'):
        model.save_plan('EV', ev_id, 'NOT A REAL BERTH', [], None, 'tester')


def test_save_plan_rejects_an_unknown_source(berths, ev_id):
    with pytest.raises(ValueError, match='source'):
        model.save_plan('BARGE', ev_id, berths[0], [], None, 'tester')


def test_save_plan_rejects_items_that_are_not_a_list(berths, ev_id):
    with pytest.raises(ValueError, match='items'):
        model.save_plan('EV', ev_id, berths[0], {'kind': 'parcel'}, None, 'tester')


def test_save_plan_rejects_an_item_with_an_unknown_key(berths, ev_id):
    with pytest.raises(ValueError, match='items'):
        model.save_plan('EV', ev_id, berths[0],
                        [{**_parcel('HSD', 1, 1), 'evil': 'x'}], None, 'tester')


def test_save_plan_rejects_an_unknown_item_kind(berths, ev_id):
    with pytest.raises(ValueError, match='kind'):
        model.save_plan('EV', ev_id, berths[0],
                        [{'kind': 'sabotage', 'name': 'x'}], None, 'tester')


def test_save_plan_rejects_a_non_numeric_flow_rate(berths, ev_id):
    with pytest.raises(ValueError, match='items'):
        model.save_plan('EV', ev_id, berths[0],
                        [_parcel('HSD', 100, 'fast')], None, 'tester')


def test_save_plan_rejects_a_bad_start(berths, ev_id):
    with pytest.raises(ValueError, match='start'):
        model.save_plan('EV', ev_id, berths[0], [], 'whenever', 'tester')


# ── sources: a plan hangs off exactly one of EV01 or a VCN ──

def test_a_vcn_vessel_can_be_planned(berths, vcn_id):
    model.save_plan('VCN', vcn_id, berths[0], model.default_items(),
                    '2026-08-15T02:00', 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT ev_id, vcn_id, start_dt FROM berth_plan WHERE vcn_id=%s', [vcn_id])
    row = cur.fetchone(); conn.close()
    assert row['ev_id'] is None and row['vcn_id'] == vcn_id
    assert row['start_dt'] == _dt('2026-08-15 02:00')


def test_seed_items_for_a_vcn_uses_its_own_declared_parcels(berths, vcn_id):
    conn = get_db(); cur = get_cursor(conn)
    for seq, (cargo, qty) in enumerate([('HSD', '9600'), ('MS', '4800')], start=1):
        cur.execute('''INSERT INTO vcn_consigners (vcn_id, cargo_name, quantity, parcel_seq, parcel_no)
                       VALUES (%s,%s,%s,%s,%s)''', [vcn_id, cargo, qty, seq, f'P{seq}'])
    conn.commit(); conn.close()
    items = model.seed_items('VCN', vcn_id, berths[0])
    assert [i['name'] for i in items] == \
        ['Prior Documentation', 'HSD', 'MS', 'Post Documentation']
    assert [i['qty'] for i in items[1:3]] == [9600.0, 4800.0]
    assert all(i['rate'] is None for i in items[1:3]), 'flow rate is the planner\'s to set'


def test_plan_is_deleted_when_its_expected_vessel_is_deleted(berths, ev_id):
    model.save_plan('EV', ev_id, berths[0], [], None, 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('DELETE FROM expected_vessels WHERE id=%s', [ev_id])
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM berth_plan WHERE ev_id=%s', [ev_id])
    assert cur.fetchone()['n'] == 0, 'ON DELETE CASCADE missing on berth_plan.ev_id'
    conn.close()


def test_plan_is_deleted_when_its_vcn_is_deleted(berths, vcn_id):
    model.save_plan('VCN', vcn_id, berths[0], [], None, 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id])
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM berth_plan WHERE vcn_id=%s', [vcn_id])
    assert cur.fetchone()['n'] == 0, 'ON DELETE CASCADE missing on berth_plan.vcn_id'
    conn.close()


def test_a_plan_row_cannot_carry_both_sources(berths, ev_id, vcn_id):
    conn = get_db(); cur = get_cursor(conn)
    with pytest.raises(Exception):
        cur.execute('INSERT INTO berth_plan (ev_id, vcn_id, berth_name) VALUES (%s,%s,%s)',
                    [ev_id, vcn_id, berths[0]])
        conn.commit()
    conn.close()


def test_saving_the_same_vessel_twice_moves_it_rather_than_duplicating_it(berths, ev_id):
    model.save_plan('EV', ev_id, berths[0], [], None, 'tester')
    model.save_plan('EV', ev_id, berths[1], [], None, 'tester')
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM berth_plan WHERE ev_id=%s', [ev_id])
    rows = cur.fetchall(); conn.close()
    assert len(rows) == 1, 'UNIQUE(ev_id) missing — vessel planned at two berths'
    assert rows[0]['berth_name'] == berths[1]
