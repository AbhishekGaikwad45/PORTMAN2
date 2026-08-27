"""BPL01 berth planning — draft plans, never written back to EV01/VCN/LDUD.

A plan hangs off either an EV01 expected vessel or a VCN, identified through
the API as (source, source_id) with source in SOURCES.

The planner states how long each parcel takes rather than a flow rate, and
adds delay line items against it (the same delay master LUEU01 picks from):

    parcel end = start + hours + sum(delay hours)

Parcels run in parallel, so a vessel is done when its latest parcel is —
matching RP01's max(parcel ETCs) rollup. The math lives here rather than in
the page so there is one source of truth and pytest can reach it.
"""
import json
from datetime import date, datetime, timedelta

from database import get_db, get_cursor

# Element shape of the parcels JSONB column. Written straight from a browser
# payload, so the key sets are whitelists, not suggestions.
PARCEL_KEYS = {'cargo', 'qty', 'start', 'hours', 'delays'}
DELAY_KEYS = {'name', 'hours'}

# source -> the berth_plan column it lands in
SOURCES = {'EV': 'ev_id', 'VCN': 'vcn_id'}


def _dt(v):
    """Parse a 'YYYY-MM-DDTHH:MM' (or space-separated) stamp; None if unusable.
    Same tolerance RP01 applies to ldud_parcel_ops.start_dt, plus date-only —
    vcn_header.doc_date is stored as a bare date string."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    text = str(v).replace('T', ' ')
    for fmt, width in (('%Y-%m-%d %H:%M', 16), ('%Y-%m-%d', 10)):
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
    return None


def _num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── planning math ────────────────────────────────────────────────────────────

def delay_hours(parcel):
    """Total hours of delay line items on a parcel. Lines the planner has
    named but not yet costed contribute nothing."""
    total = 0.0
    for d in parcel.get('delays') or []:
        total += _num(d.get('hours')) or 0.0
    return total


def parcel_end(parcel):
    """end = start + hours + delay hours. None until the planner has said how
    long the parcel takes — an unhoured parcel is incomplete, not invalid.

    Delay alone is not a schedule: with no working hours there is no end.
    """
    start, hours = _dt(parcel.get('start')), _num(parcel.get('hours'))
    if start is None or not hours or hours <= 0:
        return None
    return start + timedelta(hours=hours + delay_hours(parcel))


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
    for b in ['LB-01', 'LB-02']:
        if b not in berths:
            berths.append(b)
    return sorted(berths)


def _validate(parcels):
    """Trust boundary: this goes into a JSONB column straight off the wire."""
    if not isinstance(parcels, list):
        raise ValueError('parcels must be a list')
    for p in parcels:
        if not isinstance(p, dict) or set(p) - PARCEL_KEYS:
            raise ValueError(f'parcels entries must have only {sorted(PARCEL_KEYS)}')
        for key in ('qty', 'hours'):
            if p.get(key) not in (None, '') and _num(p.get(key)) is None:
                raise ValueError(f'parcels {key} must be numeric')
        if p.get('start') and _dt(p.get('start')) is None:
            raise ValueError('parcels start must be YYYY-MM-DDTHH:MM')
        _validate_delays(p.get('delays'))


def _validate_delays(delays):
    if delays is None:
        return
    if not isinstance(delays, list):
        raise ValueError('parcels delays must be a list')
    for d in delays:
        if not isinstance(d, dict) or set(d) - DELAY_KEYS:
            raise ValueError(f'parcels delays entries must have only {sorted(DELAY_KEYS)}')
        if d.get('hours') not in (None, '') and _num(d.get('hours')) is None:
            raise ValueError('parcels delays hours must be numeric')


def _source_col(source):
    try:
        return SOURCES[source]
    except KeyError:
        raise ValueError(f'unknown source: {source} (expected one of {sorted(SOURCES)})')


def save_plan(source, source_id, berth_name, parcels, username):
    """Upsert one plan. The source column is whitelisted through SOURCES, so
    it is safe to interpolate into the conflict target."""
    col = _source_col(source)
    if berth_name not in get_berths():
        raise ValueError(f'unknown berth: {berth_name}')
    _validate(parcels)
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'''INSERT INTO berth_plan ({col}, berth_name, parcels, created_by, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s, now())
                    ON CONFLICT ({col}) DO UPDATE
                      SET berth_name = EXCLUDED.berth_name,
                          parcels    = EXCLUDED.parcels,
                          updated_at = now()
                    RETURNING id''',
                [source_id, berth_name, json.dumps(parcels), username])
    row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id


def delete_plan(source, source_id):
    col = _source_col(source)
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'DELETE FROM berth_plan WHERE {col}=%s', [source_id])
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


def get_canvas(show_all=False):
    """Everything the page draws: berths, real occupancy, draft plans, and the
    vessels still waiting to be planned — EV01 expected vessels and VCNs alike.

    show_all reveals VCNs that are already alongside; by default only
    un-berthed ones are offered, since a berthed vessel has nothing left to
    plan.
    """
    berths = get_berths()
    occupied = _occupied_by_berth(berths)

    conn = get_db()
    cur = get_cursor(conn)
    # eta is cast to text on both sides: expected_vessels.eta is a timestamptz
    # while vcn_header.doc_date is text, so the UNION needs a common type.
    # _norm_eta turns them back into datetimes below.
    cur.execute('''SELECT 'EV' AS source, p.ev_id AS source_id, p.berth_name, p.parcels,
                          e.vessel_name, e.via_number, e.loa, e.draft, e.eta::text AS eta
                   FROM berth_plan p
                   JOIN expected_vessels e ON e.id = p.ev_id
                   UNION ALL
                   SELECT 'VCN', p.vcn_id, p.berth_name, p.parcels,
                          h.vessel_name, h.via_number, h.loa, h.draft, h.doc_date
                   FROM berth_plan p
                   JOIN vcn_header h ON h.id = p.vcn_id''')
    plans = [_norm_eta(dict(r)) for r in cur.fetchall()]

    cur.execute('''SELECT 'EV' AS source, id AS source_id, vessel_name, via_number,
                          loa, draft, eta::text AS eta, cargo_name, quantity
                   FROM expected_vessels
                   WHERE doc_status IS DISTINCT FROM %s
                     AND id NOT IN (SELECT ev_id FROM berth_plan WHERE ev_id IS NOT NULL)
                   ORDER BY eta NULLS LAST, id''', [_MOVED])
    waiting = [_norm_eta(dict(r)) for r in cur.fetchall()]

    # VCNs with no LDUD alongside time are still to be scheduled — the same
    # "not berthed yet" test RP01's expected/waiting section applies.
    # Quantity lives on the parcel tables, not the header; union both the way
    # RP01 does, since a VCN only has rows in one of them.
    cur.execute('''SELECT 'VCN' AS source, h.id AS source_id, h.vessel_name, h.via_number,
                          h.loa, h.draft, h.doc_date AS eta,
                          h.cargo_type AS cargo_name,
                          (SELECT SUM(NULLIF(TRIM(p.quantity), '')::numeric) FROM (
                               SELECT quantity FROM vcn_consigners WHERE vcn_id = h.id
                               UNION ALL
                               SELECT quantity FROM vcn_export_cargo_declaration WHERE vcn_id = h.id
                           ) p) AS quantity
                   FROM vcn_header h
                   LEFT JOIN LATERAL (
                       SELECT alongside_datetime FROM ldud_header
                       WHERE vcn_id = h.id ORDER BY id DESC LIMIT 1
                   ) l ON TRUE
                   WHERE (%s OR l.alongside_datetime IS NULL
                            OR NULLIF(TRIM(l.alongside_datetime::text), '') IS NULL)
                     AND h.id NOT IN (SELECT vcn_id FROM berth_plan WHERE vcn_id IS NOT NULL)
                   ORDER BY h.doc_date NULLS LAST, h.id''', [bool(show_all)])
    waiting += [_norm_eta(dict(r)) for r in cur.fetchall()]
    conn.close()

    lanes = []
    for berth in berths:
        lane_plans = [p for p in plans if p['berth_name'] == berth]
        lane_plans.sort(key=lambda p: (vessel_start(p['parcels']) or datetime.max,
                                       p['source'], p['source_id']))
        lane_occ = occupied.get(berth, [])
        lanes.append({
            'berth_name': berth,
            'occupied': [_iso(o) for o in lane_occ],
            'plans': [_iso(p) for p in annotate_lane(lane_occ, lane_plans)],
        })
    return {'lanes': lanes, 'expected': [_iso(e) for e in waiting],
            'delay_types': get_delay_types(),
            'now': datetime.now().isoformat(timespec='minutes')}


def _norm_eta(row):
    """eta arrives as text from either source; hand the page a real datetime
    (or None) so it formats the same regardless of which table it came from."""
    row['eta'] = _dt(row.get('eta'))
    return row


def get_delay_types():
    """Delay master, same source LUEU01's Delay dropdown reads."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT name FROM port_delay_types "
                "WHERE name IS NOT NULL AND name != '' ORDER BY name")
    names = [r['name'] for r in cur.fetchall()]
    conn.close()
    return names


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


def seed_parcels(source, source_id, berth_name):
    """Opening parcel list for a freshly-dropped vessel — a starting point the
    planner edits, adds to, or deletes outright.

    EV01 vessels only have comma-joined cargo/quantity text, split the same way
    EV01's cargo_quotas splits it. A VCN already declares real parcels, so
    those are used instead.

    Each parcel starts when the berth is next free, so dropping a vessel behind
    one that already has an end time (or a berthed vessel's ETC) queues it there
    instead of making the planner retype the handover. All parcels get the same
    start because they are parallel discharge lines, not a sequence.

    On a free berth the start stays blank — there is nothing to queue behind,
    and guessing the ETA would be a schedule the planner never entered. Hours
    are always blank: only the planner knows how long it will take.
    """
    _source_col(source)   # reject unknown sources before touching the DB
    free_at = _berth_free_at(berth_name)
    start = free_at.isoformat(timespec='minutes') if free_at else None
    pairs = _ev_cargo(source_id) if source == 'EV' else _vcn_cargo(source_id)
    return [{'cargo': cargo, 'qty': qty, 'start': start, 'hours': None, 'delays': []}
            for cargo, qty in pairs]


def _ev_cargo(ev_id):
    from modules.EV01.model import cargo_quotas
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM expected_vessels WHERE id=%s', [ev_id])
    row = cur.fetchone()
    conn.close()
    return list(cargo_quotas(dict(row)).items()) if row else []


def _vcn_cargo(vcn_id):
    """The VCN's declared parcels, from whichever table its operation_type
    points at — same import/export split LUEU01 applies."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    tbl = ('vcn_export_cargo_declaration'
           if (row or {}).get('operation_type') == 'Export' else 'vcn_consigners')
    cur.execute(f'SELECT cargo_name, quantity FROM {tbl} WHERE vcn_id=%s ORDER BY parcel_seq, id',
                [vcn_id])
    out = []
    for r in cur.fetchall():
        try:
            qty = float(str(r['quantity']).replace(',', '')) if r['quantity'] else None
        except (TypeError, ValueError):
            qty = None
        out.append((r['cargo_name'] or '', qty))
    conn.close()
    return out


def _berth_free_at(berth_name):
    """lane_free_at for one berth, reading its current occupancy and plans."""
    occupied = _occupied_by_berth([berth_name]).get(berth_name, [])
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT parcels FROM berth_plan WHERE berth_name=%s', [berth_name])
    plans = [dict(r) for r in cur.fetchall()]
    conn.close()
    return lane_free_at(occupied, plans)
