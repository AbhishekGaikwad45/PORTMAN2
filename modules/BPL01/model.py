"""BPL01 berth planning — draft plans, never written back to EV01/VCN/LDUD.

A vessel's plan is an ordered list of line items that run one after another:

    Prior Documentation   (fixed bookend, typed hours)
    ... parcels and delays the planner inserts between them ...
    Post Documentation    (fixed bookend, typed hours)

A parcel's hours are derived from qty / flow rate. A doc or delay line carries
typed hours.

Scheduling treats a pipeline as a resource: a line starts when its own pipeline
frees, so parcels on different pipelines overlap while parcels on the same one
queue. Lines that name no pipeline — the documentation bookends, and any delay
that holds the whole vessel — are barriers that wait for every pipeline and
block everything after them. Vessels chain too: each starts when the vessel
ahead of it in the berth ends, so a berth is one continuous schedule from
whatever is alongside now to the last vessel planned.

A planned parcel on a VCN points at that VCN's declared parcel by id, and reads
its name and quantity from there on every load — the plan tracks the
declaration rather than a copy of it. EV01 vessels are pre-VCN and have nothing
to link to, so their parcel lines stay free text.

A plan hangs off either an EV01 expected vessel or a VCN, identified through
the API as (source, source_id) with source in SOURCES.
"""
import json
from datetime import date, datetime, timedelta

from database import get_db, get_cursor

# Element shape of the items JSONB column. Written straight from a browser
# payload, so the key set is a whitelist, not a suggestion.
ITEM_KEYS = {'kind', 'name', 'qty', 'pipeline', 'rate', 'hours', 'fixed', 'parcel_id'}
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

def default_items():
    """Every vessel starts with the two documentation lines and nothing else."""
    return [_doc_item(PRIOR_DOC), _doc_item(POST_DOC)]


def _normalize(item):
    """Fill in the keys this item's kind doesn't use, so every stored item has
    the same shape and no reader has to guess whether a key is missing."""
    return {k: item.get(k) for k in ITEM_KEYS}


def _doc_item(name):
    return _normalize({'kind': 'doc', 'name': name, 'hours': DOC_HOURS, 'fixed': True})


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


def _pipe(item):
    """The pipeline an item occupies, or None if it occupies the whole vessel."""
    return (str(item.get('pipeline') or '').strip()) or None


def chain(items, start, simultaneous=True):
    """Schedule the items from `start`, returning each with its own start/end
    and computed hours.

    A pipeline is a resource. An item that names one starts as soon as that
    pipeline frees, so two parcels on different pipelines run side by side
    while two on the same pipeline queue.

    `simultaneous=False` is for a vessel that cannot work two lines at once
    whatever the berth offers — the limit is its own pumps, so every line is
    treated as a barrier and the plan falls back to one line at a time.

    An item with no pipeline is a **barrier**: the documentation lines, and any
    delay that holds the whole vessel. A barrier waits for every pipeline to
    finish, and nothing may start until it ends. A parcel with no pipeline
    chosen yet is treated as a barrier too — without knowing what it competes
    with, the conservative answer is that it competes with everything.

    An item with no computable hours has no end. That poisons its own pipeline
    (and, at the next barrier, the whole vessel) rather than the entire plan —
    a visible gap beats a schedule built on a guess.
    """
    out, barrier, free = [], _dt(start), {}
    for item in items or []:
        hours = item_hours(item)
        pipe = _pipe(item) if simultaneous else None
        if pipe:
            begin = free.get(pipe, barrier)
        else:
            waits_for = list(free.values()) + [barrier]
            begin = None if any(w is None for w in waits_for) else max(waits_for)
        end = begin + timedelta(hours=hours) if (begin and hours) else None
        out.append({**item, 'hours': hours, 'start': begin, 'end': end})
        if pipe:
            free[pipe] = end
        else:
            barrier, free = end, {}   # the barrier absorbed every pipeline
    return out


def vessel_end(items, start, simultaneous=True):
    """When the vessel is done: the last line to finish, across all pipelines.

    None if any line has no end — an unfinishable line makes the whole finish
    unknown, and Post Documentation cannot start until every line is done.
    """
    done = chain(items, start, simultaneous)
    if not done:
        return _dt(start)
    ends = [i['end'] for i in done]
    return None if any(e is None for e in ends) else max(ends)


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
        sim = plan.get('simultaneous')
        sim = True if sim is None else bool(sim)
        items = chain(plan.get('items') or [], start, sim)
        end = vessel_end(plan.get('items') or [], start, sim)
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
    for b in ['LB-01', 'LB-02']:
        if b not in berths:
            berths.append(b)
    return sorted(berths)


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


def _validate(items, source, source_id):
    """Trust boundary: this goes into a JSONB column straight off the wire."""
    if not isinstance(items, list):
        raise ValueError('items must be a list')
    own = {p['id'] for p in vessel_parcels(source, source_id)}
    for i in items:
        if not isinstance(i, dict) or set(i) - ITEM_KEYS:
            raise ValueError(f'items entries must have only {sorted(ITEM_KEYS)}')
        if i.get('kind') not in ITEM_KINDS:
            raise ValueError(f'items kind must be one of {sorted(ITEM_KINDS)}')
        for key in ('qty', 'rate', 'hours'):
            if i.get(key) not in (None, '') and _num(i.get(key)) is None:
                raise ValueError(f'items {key} must be numeric')
        pid = i.get('parcel_id')
        if pid is not None and int(pid) not in own:
            raise ValueError(f'parcel_id {pid} does not belong to this vessel')


def vessel_parcels(source, source_id):
    """The real parcels a vessel declares, for a planned line to point at.

    Only a VCN has any — an EV01 vessel is pre-VCN, so its parcel lines stay
    free text with nothing to link to.
    """
    if source != 'VCN' or not source_id:
        return []
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT operation_type FROM vcn_header WHERE id=%s', [source_id])
    row = cur.fetchone()
    tbl = ('vcn_export_cargo_declaration'
           if (row or {}).get('operation_type') == 'Export' else 'vcn_consigners')
    cur.execute(f'''SELECT id, parcel_no, cargo_name, quantity, pipeline_name
                    FROM {tbl} WHERE vcn_id=%s ORDER BY parcel_seq, id''', [source_id])
    out = []
    for r in cur.fetchall():
        out.append({'id': r['id'],
                    'name': r['parcel_no'] or r['cargo_name'] or f"#{r['id']}",
                    'cargo_name': r['cargo_name'],
                    'qty': _num(str(r['quantity']).replace(',', '') if r['quantity'] else None),
                    'pipeline': r['pipeline_name'] or None})
    conn.close()
    return out


def resolve_links(items, source, source_id):
    """Refresh every linked line from the VCN parcel it points at.

    This is what the link buys: name and quantity are read from the source
    rather than a copy taken when the line was added, so a plan can never
    quietly hold a number the VCN has since changed.
    """
    if source != 'VCN':
        return items
    by_id = {p['id']: p for p in vessel_parcels(source, source_id)}
    out = []
    for i in items:
        src = by_id.get(i.get('parcel_id')) if i.get('parcel_id') is not None else None
        out.append({**i, 'name': src['name'], 'qty': src['qty']} if src else i)
    return out


def _source_col(source):
    try:
        return SOURCES[source]
    except KeyError:
        raise ValueError(f'unknown source: {source} (expected one of {sorted(SOURCES)})')


def save_plan(source, source_id, berth_name, items, start_dt, username,
              simultaneous=True):
    """Upsert one plan. The source column is whitelisted through SOURCES, so
    it is safe to interpolate into the conflict target."""
    col = _source_col(source)
    if berth_name not in get_berths():
        raise ValueError(f'unknown berth: {berth_name}')
    _validate(items, source, source_id)
    start = _dt(start_dt)
    if start_dt and start is None:
        raise ValueError('start must be YYYY-MM-DDTHH:MM')
    items = with_bookends(items)

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(f'''INSERT INTO berth_plan ({col}, berth_name, items, start_dt,
                                            simultaneous, created_by, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s, %s, now())
                    ON CONFLICT ({col}) DO UPDATE
                      SET berth_name   = EXCLUDED.berth_name,
                          items        = EXCLUDED.items,
                          start_dt     = EXCLUDED.start_dt,
                          simultaneous = EXCLUDED.simultaneous,
                          updated_at   = now()
                    RETURNING id''',
                [source_id, berth_name, json.dumps(items), start,
                 bool(simultaneous), username])
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
            'vcn_id': r.get('vcn_id'),
            'vessel_name': r.get('vessel_name'),
            'via_no': r.get('via_no'),
            'cargo': r.get('cargo'),
            'quantity': r.get('quantity'),
            'alongside': r.get('alongside'),
            'end': _dt_ddmm(r.get('expected_completion')),
            'is_planned': r.get('is_planned'),
            'items': _actual_items(r.get('vcn_id')),
            # this is what is happening, not what someone plans — the page
            # renders it but must never offer to edit it
            'readonly': True,
        })
    return out


def _actual_items(vcn_id):
    """A berthed vessel's real discharge lines, shaped like plan items so the
    page can render them in the same table.

    Read straight from LUEU01 — quantities, rates and times here are actuals,
    never the planner's estimates. Note these are genuinely parallel lines, so
    their times come from the operation itself and are NOT chained.
    """
    if not vcn_id:
        return []
    from modules.LUEU01.model import get_started_parcels

    out = []
    for p in get_started_parcels(vcn_id):
        out.append({
            'kind': 'parcel',
            'name': p.get('parcel_no') or p.get('cargo_name') or '',
            'qty': p.get('target_qty'),
            'pipeline': p.get('pipeline_name') or '',
            'rate': p.get('avg_rate') or _num(p.get('expected_flow_rate')),
            'hours': p.get('op_hours'),
            'start': _dt(p.get('start_dt')),
            'end': _dt(p.get('end_dt')),
            'fixed': True,
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
                          p.start_dt, p.simultaneous, e.vessel_name, e.via_number,
                          e.loa, e.draft, e.eta::text AS eta
                   FROM berth_plan p
                   JOIN expected_vessels e ON e.id = p.ev_id
                   UNION ALL
                   SELECT 'VCN', p.vcn_id, p.berth_name, p.items,
                          p.start_dt, p.simultaneous, h.vessel_name, h.via_number,
                          h.loa, h.draft, h.doc_date
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

    # linked lines read their name and quantity from the VCN parcel itself,
    # and every VCN plan offers its declared parcels to pick from
    for p in plans:
        p['available_parcels'] = vessel_parcels(p['source'], p['source_id'])
        p['items'] = resolve_links(p['items'] or [], p['source'], p['source_id'])

    lanes = []
    for berth in berths:
        lane_plans = [p for p in plans if p['berth_name'] == berth]
        # queue order: pinned vessels by their pinned start, the rest behind
        lane_plans.sort(key=lambda p: (_dt(p['start_dt']) or datetime.max,
                                       p['source'], p['source_id']))
        lane_occ = occupied.get(berth, [])
        lanes.append({
            'berth_name': berth,
            'occupied': [_iso_plan(o) for o in lane_occ],
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
    if source == 'VCN':
        # linked from the start: each line points at the parcel it came from
        parcels = [{'kind': 'parcel', 'name': p['name'], 'qty': p['qty'],
                    'pipeline': p['pipeline'], 'rate': None, 'hours': None,
                    'parcel_id': p['id']} for p in vessel_parcels(source, source_id)]
    else:
        parcels = [{'kind': 'parcel', 'name': cargo, 'qty': qty, 'pipeline': None,
                    'rate': None, 'hours': None, 'parcel_id': None}
                   for cargo, qty in _ev_cargo(source_id)]
    return [_doc_item(PRIOR_DOC)] + parcels + [_doc_item(POST_DOC)]


def _ev_cargo(ev_id):
    from modules.EV01.model import cargo_quotas
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM expected_vessels WHERE id=%s', [ev_id])
    row = cur.fetchone()
    conn.close()
    return list(cargo_quotas(dict(row)).items()) if row else []


def berth_free_at(berth_name):
    """When a berth is next free, reading its current occupancy and plans."""
    occupied = _occupied_by_berth([berth_name]).get(berth_name, [])
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT items, start_dt, simultaneous FROM berth_plan WHERE berth_name=%s',
                [berth_name])
    plans = [dict(r) for r in cur.fetchall()]
    conn.close()
    return lane_free_at(occupied, plans)
