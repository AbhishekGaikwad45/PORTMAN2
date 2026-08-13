"""BPL01 berth planning — draft plans, never written back to EV01/VCN/LDUD.

The planning math is the same shape LUEU01 uses for its planned ETC
(lueu01.html etcText): end = start + qty / rate, per parcel, parcels running
in parallel, so the vessel's end is the latest of them (matching RP01's
max(parcel ETCs) rollup). It lives here rather than in the page so there is
one source of truth and pytest can reach it.
"""
import json
from datetime import date, datetime, timedelta

from database import get_db, get_cursor

# Element shape of the parcels JSONB column. Written straight from a browser
# payload, so the key set is a whitelist, not a suggestion.
PARCEL_KEYS = {'cargo', 'qty', 'start', 'rate'}


def _dt(v):
    """Parse a 'YYYY-MM-DDTHH:MM' (or space-separated) stamp; None if unusable.
    Same tolerance RP01 applies to ldud_parcel_ops.start_dt."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.strptime(str(v).replace('T', ' ')[:16], '%Y-%m-%d %H:%M')
    except ValueError:
        return None


def _num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── planning math ────────────────────────────────────────────────────────────

def parcel_end(parcel):
    """end = start + qty/rate hours. None until the planner has typed a rate —
    an unrated parcel is incomplete, not invalid."""
    start, qty, rate = _dt(parcel.get('start')), _num(parcel.get('qty')), _num(parcel.get('rate'))
    if start is None or not rate or rate <= 0 or qty is None:
        return None
    return start + timedelta(hours=qty / rate)


def vessel_start(parcels):
    """Earliest parcel start — where the vessel's bar begins in its lane."""
    starts = [d for d in (_dt(p.get('start')) for p in parcels or []) if d]
    return min(starts) if starts else None


def vessel_end(parcels):
    """Latest parcel end. Parcels are parallel discharge lines, so the vessel
    is done when the slowest one is — same rollup as RP01."""
    ends = [d for d in (parcel_end(p) for p in parcels or []) if d]
    return max(ends) if ends else None


def lane_free_at(occupied, plans):
    """When the berth is next free: the latest end across everything in the
    lane. A plan with no rate yet has no end and simply doesn't count — it
    can't pull the berth's free time earlier than it really is.

    None means nothing in this lane has a known end, so a new vessel has
    nothing to queue behind.
    """
    ends = [o.get('end') for o in occupied]
    ends += [vessel_end(p.get('parcels') or []) for p in plans]
    ends = [e for e in ends if e]
    return max(ends) if ends else None


def annotate_lane(occupied, plans):
    """Add 'start', 'end' and 'conflict_with' to each plan in one berth's queue.

    A plan conflicts when it starts before the berth is free — i.e. before the
    running high-water mark of everything ahead of it in the lane. Starting
    exactly at the previous end is legal.

    An unrated plan (no end) does NOT lower the high-water mark, so it can't
    make the vessel behind it look falsely clear.
    """
    free_at, blocker = None, None
    for occ in occupied:
        end = occ.get('end')
        if end and (free_at is None or end > free_at):
            free_at, blocker = end, occ.get('vessel_name')

    out = []
    for plan in plans:
        parcels = plan.get('parcels') or []
        start, end = vessel_start(parcels), vessel_end(parcels)
        conflict = blocker if (start and free_at and start < free_at) else None
        out.append({**plan, 'start': start, 'end': end, 'conflict_with': conflict})
        if end and (free_at is None or end > free_at):
            free_at, blocker = end, plan.get('vessel_name')
    return out


# ── persistence ──────────────────────────────────────────────────────────────

def get_berths():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM port_berth_master ORDER BY berth_name')
    berths = [r['berth_name'] for r in cur.fetchall()]
    conn.close()
    return berths


def _validate(parcels):
    """Trust boundary: this goes into a JSONB column straight off the wire."""
    if not isinstance(parcels, list):
        raise ValueError('parcels must be a list')
    for p in parcels:
        if not isinstance(p, dict) or set(p) - PARCEL_KEYS:
            raise ValueError(f'parcels entries must have only {sorted(PARCEL_KEYS)}')
        for key in ('qty', 'rate'):
            if p.get(key) not in (None, '') and _num(p.get(key)) is None:
                raise ValueError(f'parcels {key} must be numeric')
        if p.get('start') and _dt(p.get('start')) is None:
            raise ValueError('parcels start must be YYYY-MM-DDTHH:MM')


def save_plan(ev_id, berth_name, parcels, username):
    if berth_name not in get_berths():
        raise ValueError(f'unknown berth: {berth_name}')
    _validate(parcels)
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''INSERT INTO berth_plan (ev_id, berth_name, parcels, created_by, updated_at)
                   VALUES (%s, %s, %s::jsonb, %s, now())
                   ON CONFLICT (ev_id) DO UPDATE
                     SET berth_name = EXCLUDED.berth_name,
                         parcels    = EXCLUDED.parcels,
                         updated_at = now()
                   RETURNING id''',
                [ev_id, berth_name, json.dumps(parcels), username])
    row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id


def delete_plan(ev_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM berth_plan WHERE ev_id=%s', [ev_id])
    conn.commit()
    conn.close()


# ── canvas assembly ──────────────────────────────────────────────────────────

_MOVED = 'Closed - Other Terminal'   # same exclusion EV01's own grid applies


def _occupied_by_berth(berths):
    """Real vessels currently at a berth, with the ETC the existing math
    produces. Reuses RP01's get_berthed_vessels rather than re-deriving ETC —
    a second implementation of that formula is exactly what this module must
    not become.

    ponytail: get_berthed_vessels issues several queries per vessel. Fine for a
    handful of berths; fold into one query if the berth count grows.
    """
    # imported inside the function: RP01's view module binds to the RP01
    # blueprint at import time, same reason its own cross-module imports are local
    from modules.RP01.RP01.Berth_plan.view import get_berthed_vessels

    now = datetime.now()
    # only window_end matters here — window_start bounds RP01's "last 24 hrs"
    # figure, which this page does not show
    rows = get_berthed_vessels(now - timedelta(days=1), now, berths)

    out = {}
    for r in rows:
        out.setdefault(r.get('berth_name'), []).append({
            'vessel_name': r.get('vessel_name'),
            'via_no': r.get('via_no'),
            'cargo': r.get('cargo'),
            'quantity': r.get('quantity'),
            'alongside': r.get('alongside'),
            'end': _dt_ddmm(r.get('expected_completion')),
            'is_planned': r.get('is_planned'),
        })
    return out


def _dt_ddmm(v):
    """RP01 hands back display strings ('DD-MM-YYYY HH:MM'); we need datetimes."""
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:16], '%d-%m-%Y %H:%M')
    except ValueError:
        return None


def get_canvas():
    """Everything the page draws: berths, real occupancy, draft plans, and the
    expected vessels still waiting to be planned."""
    berths = get_berths()
    occupied = _occupied_by_berth(berths)

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT p.ev_id, p.berth_name, p.parcels,
                          e.vessel_name, e.via_number, e.loa, e.draft, e.eta
                   FROM berth_plan p
                   JOIN expected_vessels e ON e.id = p.ev_id
                   ORDER BY p.ev_id''')
    plans = [dict(r) for r in cur.fetchall()]
    cur.execute('''SELECT id AS ev_id, vessel_name, via_number, loa, draft, eta,
                          cargo_name, quantity
                   FROM expected_vessels
                   WHERE doc_status IS DISTINCT FROM %s
                     AND id NOT IN (SELECT ev_id FROM berth_plan WHERE ev_id IS NOT NULL)
                   ORDER BY eta NULLS LAST, id''', [_MOVED])
    expected = [dict(r) for r in cur.fetchall()]
    conn.close()

    lanes = []
    for berth in berths:
        lane_plans = [p for p in plans if p['berth_name'] == berth]
        lane_plans.sort(key=lambda p: (vessel_start(p['parcels']) or datetime.max, p['ev_id']))
        lane_occ = occupied.get(berth, [])
        lanes.append({
            'berth_name': berth,
            'occupied': [_iso(o) for o in lane_occ],
            'plans': [_iso(p) for p in annotate_lane(lane_occ, lane_plans)],
        })
    return {'lanes': lanes, 'expected': [_iso(e) for e in expected],
            'now': datetime.now().isoformat(timespec='minutes')}


def _iso(row):
    """Datetimes out to the page as ISO strings — Flask's default datetime
    encoding is RFC 1123, which JS Date parses inconsistently."""
    def conv(v):
        if isinstance(v, datetime):
            return v.isoformat(timespec='minutes')
        if isinstance(v, date):
            return v.isoformat()
        return v
    return {k: conv(v) for k, v in row.items()}


def seed_parcels(ev, berth_name):
    """Parcels for a freshly-dropped vessel: the EV01 row's comma-joined
    cargo/quantity pairs, split the same way EV01's cargo_quotas splits them.

    Each parcel starts when the berth is next free, so dropping a vessel behind
    one that already has an end time (or a berthed vessel's ETC) queues it there
    instead of making the planner retype the handover. All parcels get the same
    start because they are parallel discharge lines, not a sequence.

    On a free berth the start stays blank — there is nothing to queue behind,
    and guessing the ETA would be a schedule the planner never entered.
    """
    from modules.EV01.model import cargo_quotas

    free_at = _berth_free_at(berth_name)
    start = free_at.isoformat(timespec='minutes') if free_at else None
    return [{'cargo': name, 'qty': qty, 'start': start, 'rate': None}
            for name, qty in cargo_quotas(ev).items()]


def _berth_free_at(berth_name):
    """lane_free_at for one berth, reading its current occupancy and plans."""
    occupied = _occupied_by_berth([berth_name]).get(berth_name, [])
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT parcels FROM berth_plan WHERE berth_name=%s', [berth_name])
    plans = [dict(r) for r in cur.fetchall()]
    conn.close()
    return lane_free_at(occupied, plans)
