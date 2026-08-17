"""BPL01 berth planning — draft plans, never written back to EV01/VCN/LDUD.

A vessel's plan is an ordered list of line items that run one after another:

    Prior Documentation   (fixed bookend, typed hours)
    ... parcels and delays the planner inserts between them ...
    Post Documentation    (fixed bookend, typed hours)

A parcel's hours are derived from qty / flow rate. A doc or delay line carries
typed hours. Each item starts when the one before it ends, and each vessel in a
berth starts when the vessel before it ends — so a berth is one continuous
chain from whatever is alongside now to the last vessel planned.

Note this is deliberately NOT how LUEU01/RP01 treat a berthed vessel, where
parcel ops are parallel discharge lines and the ETC is max(parcel ETCs). This
module plans a sequence; that one reports concurrent reality.

A plan hangs off either an EV01 expected vessel or a VCN, identified through
the API as (source, source_id) with source in SOURCES.
"""
import json
from datetime import date, datetime, timedelta

from database import get_db, get_cursor

# Element shape of the items JSONB column. Written straight from a browser
# payload, so the key set is a whitelist, not a suggestion.
ITEM_KEYS = {'kind', 'name', 'qty', 'pipeline', 'rate', 'hours', 'fixed'}
ITEM_KINDS = {'doc', 'parcel', 'delay'}

# source -> the berth_plan column it lands in
SOURCES = {'EV': 'ev_id', 'VCN': 'vcn_id'}

# The two documentation lines every vessel carries, and their default hours.
DOC_HOURS = 4
PRIOR_DOC = 'Prior Documentation'
POST_DOC = 'Post Documentation'


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


# ── the fixed bookends ────────────────────────────────────────────────────────

def _doc_item(name):
    return {'kind': 'doc', 'name': name, 'qty': None, 'pipeline': None,
            'rate': None, 'hours': DOC_HOURS, 'fixed': True}


def default_items():
    """Every vessel starts with the two documentation lines and nothing else."""
    return [_doc_item(PRIOR_DOC), _doc_item(POST_DOC)]


def _normalize(item):
    """Fill in the keys this item's kind doesn't use, so every stored item has
    the same shape and no reader has to guess whether a key is missing."""
    return {k: item.get(k) for k in ITEM_KEYS}


def with_bookends(items):
    """Guarantee Prior Documentation first and Post Documentation last, and
    normalize every item's key set.

    The bookends are fixed for every vessel, so a payload that has lost one
    (an old draft, a hand-rolled request) is repaired rather than rejected —
    a plan must never end up without its documentation time.
    """
    items = [_normalize(i) for i in (items or [])]
    body = [i for i in items
            if not (i.get('kind') == 'doc' and i.get('name') in (PRIOR_DOC, POST_DOC))]
    prior = next((i for i in items if i.get('name') == PRIOR_DOC), _doc_item(PRIOR_DOC))
    post = next((i for i in items if i.get('name') == POST_DOC), _doc_item(POST_DOC))
    return [{**prior, 'fixed': True}] + body + [{**post, 'fixed': True}]


# ── planning math ────────────────────────────────────────────────────────────

def item_hours(item):
    """How long a line takes. A parcel is always qty / flow rate — a stale
    'hours' on the payload never wins, or the row would disagree with the qty
    and rate shown beside it. Docs and delays carry typed hours."""
    if item.get('kind') == 'parcel':
        qty, rate = _num(item.get('qty')), _num(item.get('rate'))
        if qty is None or not rate or rate <= 0:
            return None
        return qty / rate
    return _num(item.get('hours'))


def chain(items, start):
    """Run the items back to back from `start`, returning each with its own
    start/end and computed hours.

    An item with no computable hours has no end, and nothing after it has a
    known time either — a visible gap beats a schedule built on a guess.
    """
    out, cursor = [], _dt(start)
    for item in items or []:
        hours = item_hours(item)
        end = cursor + timedelta(hours=hours) if (cursor and hours) else None
        out.append({**item, 'hours': hours, 'start': cursor, 'end': end})
        cursor = end
    return out


def vessel_end(items, start):
    """When the vessel is done: the end of its last line, not its longest."""
    done = chain(items, start)
    return done[-1]['end'] if done else _dt(start)


def annotate_lane(occupied, plans):
    """Walk one berth's queue in order, chaining each vessel off the previous.

    A vessel's start is its pinned start_dt when set, otherwise the moment the
    berth frees. Pinning a start earlier than the berth frees is flagged as a
    conflict rather than silently reordering the queue.
    """
    free_at, blocker = None, None
    for occ in occupied:
        end = occ.get('end')
        if end and (free_at is None or end > free_at):
            free_at, blocker = end, occ.get('vessel_name')

    out = []
    for plan in plans:
        pinned = _dt(plan.get('start_dt'))
        start = pinned or free_at
        conflict = blocker if (pinned and free_at and pinned < free_at) else None
        items = chain(plan.get('items') or [], start)
        end = items[-1]['end'] if items else start
        out.append({**plan, 'items': items, 'start': start, 'end': end,
                    'conflict_with': conflict})
        if end:
            free_at, blocker = end, plan.get('vessel_name')
    return out


def lane_free_at(occupied, plans):
    """When the berth is next free, after everything already in the lane."""
    annotated = annotate_lane(occupied, plans)
    ends = [o.get('end') for o in occupied] + [p['end'] for p in annotated]
    ends = [e for e in ends if e]
    return max(ends) if ends else None


# ── persistence ──────────────────────────────────────────────────────────────

def get_berths():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT berth_name FROM port_berth_master ORDER BY berth_name')
    berths = [r['berth_name'] for r in cur.fetchall()]
    conn.close()
    return berths


def get_pipelines():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT pipeline_name FROM pipeline_master '
                'WHERE is_active IS NOT FALSE ORDER BY pipeline_name')
    names = [r['pipeline_name'] for r in cur.fetchall()]
    conn.close()
    return names


def get_delay_types():
    """Delay master, same source LUEU01's Delay dropdown reads."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT name FROM port_delay_types "
                "WHERE name IS NOT NULL AND name != '' ORDER BY name")
    names = [r['name'] for r in cur.fetchall()]
    conn.close()
    return names


def _validate(items):
    """Trust boundary: this goes into a JSONB column straight off the wire."""
    if not isinstance(items, list):
        raise ValueError('items must be a list')
    for i in items:
        if not isinstance(i, dict) or set(i) - ITEM_KEYS:
            raise ValueError(f'items entries must have only {sorted(ITEM_KEYS)}')
        if i.get('kind') not in ITEM_KINDS:
            raise ValueError(f'items kind must be one of {sorted(ITEM_KINDS)}')
        for key in ('qty', 'rate', 'hours'):
            if i.get(key) not in (None, '') and _num(i.get(key)) is None:
                raise ValueError(f'items {key} must be numeric')


def _source_col(source):
    try:
        return SOURCES[source]
    except KeyError:
        raise ValueError(f'unknown source: {source} (expected one of {sorted(SOURCES)})')


def save_plan(source, source_id, berth_name, items, start_dt, username):
    """Upsert one plan. The source column is whitelisted through SOURCES, so
    it is safe to interpolate into the conflict target."""
    col = _source_col(source)
    if berth_name not in get_berths():
        raise ValueError(f'unknown berth: {berth_name}')
    _validate(items)
    start = _dt(start_dt)
    if start_dt and start is None:
        raise ValueError('start must be YYYY-MM-DDTHH:MM')
    items = with_bookends(items)

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'''INSERT INTO berth_plan ({col}, berth_name, items, start_dt,
                                            created_by, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s, now())
                    ON CONFLICT ({col}) DO UPDATE
                      SET berth_name = EXCLUDED.berth_name,
                          items      = EXCLUDED.items,
                          start_dt   = EXCLUDED.start_dt,
                          updated_at = now()
                    RETURNING id''',
                [source_id, berth_name, json.dumps(items), start, username])
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


def _norm_eta(row):
    """eta arrives as text from either source; hand the page a real datetime
    (or None) so it formats the same regardless of which table it came from."""
    row['eta'] = _dt(row.get('eta'))
    return row


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
    cur.execute('''SELECT 'EV' AS source, p.ev_id AS source_id, p.berth_name, p.items,
                          p.start_dt, e.vessel_name, e.via_number, e.loa, e.draft,
                          e.eta::text AS eta
                   FROM berth_plan p
                   JOIN expected_vessels e ON e.id = p.ev_id
                   UNION ALL
                   SELECT 'VCN', p.vcn_id, p.berth_name, p.items,
                          p.start_dt, h.vessel_name, h.via_number, h.loa, h.draft,
                          h.doc_date
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
        # queue order: pinned vessels by their pinned start, the rest behind
        lane_plans.sort(key=lambda p: (_dt(p['start_dt']) or datetime.max,
                                       p['source'], p['source_id']))
        lane_occ = occupied.get(berth, [])
        lanes.append({
            'berth_name': berth,
            'occupied': [_iso(o) for o in lane_occ],
            'plans': [_iso_plan(p) for p in annotate_lane(lane_occ, lane_plans)],
        })
    return {'lanes': lanes, 'expected': [_iso(e) for e in waiting],
            'delay_types': get_delay_types(), 'pipelines': get_pipelines(),
            'doc_hours': DOC_HOURS,
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


def _iso_plan(plan):
    return {**_iso(plan), 'items': [_iso(i) for i in plan.get('items') or []]}


# ── seeding a freshly dropped vessel ─────────────────────────────────────────

def seed_items(source, source_id, berth_name):
    """Opening line items for a freshly-dropped vessel: the documentation
    bookends wrapped around whatever cargo the vessel already declares.

    EV01 vessels only have comma-joined cargo/quantity text, split the same way
    EV01's cargo_quotas splits it. A VCN declares real parcels, so those are
    used instead. Flow rate is always blank — only the planner knows it, and
    the hours follow from it.
    """
    _source_col(source)   # reject unknown sources before touching the DB
    pairs = _ev_cargo(source_id) if source == 'EV' else _vcn_cargo(source_id)
    parcels = [{'kind': 'parcel', 'name': cargo, 'qty': qty, 'pipeline': None,
                'rate': None, 'hours': None} for cargo, qty in pairs]
    return [_doc_item(PRIOR_DOC)] + parcels + [_doc_item(POST_DOC)]


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


def berth_free_at(berth_name):
    """When a berth is next free, reading its current occupancy and plans."""
    occupied = _occupied_by_berth([berth_name]).get(berth_name, [])
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT items, start_dt FROM berth_plan WHERE berth_name=%s', [berth_name])
    plans = [dict(r) for r in cur.fetchall()]
    conn.close()
    return lane_free_at(occupied, plans)
