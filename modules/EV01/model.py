import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from database import get_db, get_cursor

# Columns a PDF upload is allowed to touch (never id/vcn_id/doc_status/audit cols)
PDF_FIELDS = {
    'terminal_name', 'vessel_name', 'via_number', 'loa', 'draft',
    'agents', 'tanks', 'consignees', 'cargo_name', 'mla', 'quantity',
    'ddp', 'dop', 'eta', 'ata', 'lpc', 'doc', 'nor', 'berth_name',
}


def normalize_vessel_name(name):
    """Uppercase, drop status tags like [PR]/[S], collapse punctuation —
    so 'SWARNA PUSHP [PR]' matches 'SWARNA PUSHP' and 'NO.5 X' matches 'NO 5 X'."""
    if not name:
        return ''
    name = re.sub(r'\[.*?\]', ' ', name.upper())
    name = re.sub(r'[^A-Z0-9]+', ' ', name)
    return ' '.join(name.split())


def _disp_val(v):
    """Normalize DB/parsed values to a comparable display string."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M')
    if isinstance(v, date):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, Decimal):
        v = format(v.normalize(), 'f')
        return v
    s = str(v).strip()
    # parsed datetimes look like 'YYYY-MM-DD HH:MM:00' — trim seconds for compare
    if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', s):
        return s[:16]
    try:
        return format(Decimal(s).normalize(), 'f')
    except (InvalidOperation, ValueError):
        return s


def _ensure_agent(code, cur):
    code = code.strip()
    if not code:
        return
    cur.execute('SELECT id FROM vessel_agents WHERE agent_code=%s', [code])
    if not cur.fetchone():
        cur.execute('INSERT INTO vessel_agents (agent_code, name, is_active) VALUES (%s, %s, 1)', [code, code])


def _ensure_tank(code, cur):
    code = code.strip()
    if not code:
        return
    cur.execute('SELECT id FROM tank_master WHERE tank_code=%s', [code])
    if not cur.fetchone():
        cur.execute('INSERT INTO tank_master (tank_code, tank_name, is_active) VALUES (%s, %s, TRUE)', [code, code])


def _ensure_consignee(code, cur):
    code = code.strip()
    if not code:
        return
    cur.execute('SELECT id FROM vessel_customers WHERE customer_code=%s', [code])
    if not cur.fetchone():
        cur.execute("INSERT INTO vessel_customers (customer_code, name, default_currency) VALUES (%s, %s, 'INR')", [code, code])


def _ensure_cargo(name, cur):
    name = name.strip()
    if not name:
        return
    cur.execute("SELECT id FROM vessel_cargo WHERE cargo_name=%s", [name])
    if not cur.fetchone():
        cur.execute("INSERT INTO vessel_cargo (cargo_name, cargo_type, cargo_category) VALUES (%s, '', '')", [name])


def _vessel_display_name(name):
    """PDF name without status tags: 'SWARNA PUSHP [PR]' → 'SWARNA PUSHP'."""
    return ' '.join(re.sub(r'\[.*?\]', ' ', name or '').split())


def _norm_no_mt(name):
    """Normalized vessel name with a leading 'MT' prefix stripped, so
    'MT SC GARNET' and 'SC GARNET' match (auto-created masters carry 'MT')."""
    norm = normalize_vessel_name(name)
    return norm[3:] if norm.startswith('MT ') else norm


def _ensure_vessel(vessel_name, loa, cur, username):
    """Make sure the vessel exists in the VC01 Vessel Master (vessels table).

    Auto-created masters are prefixed with 'MT' (motor tanker). Inserts a
    Pending master record if missing; backfills LOA when the master has none.
    Never overwrites existing master data.
    """
    display = _vessel_display_name(vessel_name)
    key = _norm_no_mt(display)
    if not key:
        return
    cur.execute('SELECT id, vessel_name, loa FROM vessels')
    for r in cur.fetchall():
        if _norm_no_mt(r['vessel_name']) == key:
            if loa and not r['loa']:
                cur.execute('UPDATE vessels SET loa=%s WHERE id=%s', [loa, r['id']])
            return
    mt_name = display if display.upper().startswith('MT ') else f'MT {display}'
    cur.execute(
        "SELECT MAX(CAST(SUBSTR(doc_num, 3) AS INTEGER)) AS max FROM vessels WHERE doc_num LIKE %s",
        ['VM%']
    )
    nxt = ((cur.fetchone() or {}).get('max') or 0) + 1
    cur.execute(
        "INSERT INTO vessels (doc_num, doc_status, vessel_name, loa, created_by, created_date) "
        "VALUES (%s, 'Pending', %s, %s, %s, %s)",
        [f'VM{nxt}', mt_name, loa, username,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    )


def _ensure_masters(row, cur):
    for code in (row.get('agents') or '').split(','):
        _ensure_agent(code, cur)
    for code in (row.get('tanks') or '').split(','):
        _ensure_tank(code, cur)
    for code in (row.get('consignees') or '').split(','):
        _ensure_consignee(code, cur)
    for name in (row.get('cargo_name') or '').split(','):
        _ensure_cargo(name, cur)


def _find_match(row, by_via, by_name):
    """Match a parsed row against existing records.

    Returns (status, existing_row, reason):
      'update'   — confident match (via_number, or vessel name when via absent/new)
      'conflict' — via_number exists but holds a different vessel
      'new'      — no match
    """
    via = row.get('via_number')
    norm = normalize_vessel_name(row.get('vessel_name'))

    if via and via in by_via:
        cands = by_via[via]
        named = [r for r in cands if normalize_vessel_name(r['vessel_name']) == norm]
        if named:
            return 'update', max(named, key=lambda r: r['id']), None
        other = max(cands, key=lambda r: r['id'])
        return 'conflict', other, (
            f"VIA No. {via} already belongs to '{other['vessel_name']}' (record #{other['id']})"
        )

    if norm in by_name:
        cands = by_name[norm]
        # same vessel, no via recorded yet → update (backfills via_number)
        no_via = [r for r in cands if not r['via_number']]
        if no_via:
            return 'update', max(no_via, key=lambda r: r['id']), None
        if not via:
            # parsed row has no via either → same expected call, update latest
            return 'update', max(cands, key=lambda r: r['id']), None
        # name exists but under a different via → treat as a new call
    return 'new', None, None


def preview_upsert(rows):
    """Classify parsed PDF rows against existing records without writing.

    Each result: {data, status, action, match_id, existing, changes, reason}
    status: new | update | conflict | duplicate
    """
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT * FROM expected_vessels')
        existing_rows = [dict(r) for r in cur.fetchall()]
        cur.execute('SELECT vessel_name FROM vessels')
        master_names = {normalize_vessel_name(r['vessel_name']) for r in cur.fetchall()}
    finally:
        conn.close()

    by_via, by_name = {}, {}
    for r in existing_rows:
        if r.get('via_number'):
            by_via.setdefault(r['via_number'].strip(), []).append(r)
        by_name.setdefault(normalize_vessel_name(r.get('vessel_name')), []).append(r)

    results = []
    seen = {}  # batch key → vessel name, to catch duplicates inside one file
    for row in rows:
        data = {k: v for k, v in row.items() if k in PDF_FIELDS}
        via = data.get('via_number')
        norm = normalize_vessel_name(data.get('vessel_name'))
        entry = {'data': data, 'match_id': None, 'existing': None,
                 'changes': {}, 'reason': None,
                 'in_vessel_master': norm in master_names}

        batch_key = ('VIA', via) if via else ('NAME', norm)
        if batch_key in seen:
            if seen[batch_key] == norm:
                entry.update(status='duplicate', action='skip',
                             reason='Duplicate row in this file')
            else:
                entry.update(status='conflict', action='skip',
                             reason=f"VIA No. {via} appears twice in this file "
                                    f"(also used by '{seen[batch_key]}')")
            results.append(entry)
            continue
        seen[batch_key] = norm

        status, match, reason = _find_match(data, by_via, by_name)
        if status == 'update':
            changes = {}
            for k, v in data.items():
                if v is None:
                    continue
                old, new = _disp_val(match.get(k)), _disp_val(v)
                if old != new:
                    changes[k] = {'old': old, 'new': new}
            entry.update(status='update', action='update' if changes else 'skip',
                         match_id=match['id'], changes=changes,
                         existing={'id': match['id'],
                                   'vessel_name': match['vessel_name'],
                                   'via_number': match['via_number'],
                                   'doc_status': match['doc_status']},
                         reason=None if changes else 'No changes — already up to date')
        elif status == 'conflict':
            entry.update(status='conflict', action='skip', match_id=match['id'],
                         existing={'id': match['id'],
                                   'vessel_name': match['vessel_name'],
                                   'via_number': match['via_number'],
                                   'doc_status': match['doc_status']},
                         reason=reason)
        else:
            entry.update(status='new', action='insert')
        results.append(entry)

    summary = {}
    for e in results:
        summary[e['status']] = summary.get(e['status'], 0) + 1
    return {'rows': results, 'summary': summary}


def apply_upsert(decisions, username):
    """Apply user-confirmed wizard decisions.

    decisions: [{action: insert|update|skip, match_id, data}, ...]
    """
    conn = get_db()
    cur = get_cursor(conn)
    inserted = updated = skipped = 0
    try:
        for d in decisions:
            action = d.get('action')
            data = {k: v for k, v in (d.get('data') or {}).items()
                    if k in PDF_FIELDS and v is not None}
            if action == 'update' and d.get('match_id') and data:
                _ensure_masters(data, cur)
                _ensure_vessel(data.get('vessel_name'), data.get('loa'), cur, username)
                cur.execute(
                    f"UPDATE expected_vessels SET {', '.join(f'{c}=%s' for c in data)} WHERE id=%s",
                    list(data.values()) + [d['match_id']]
                )
                updated += 1
            elif action == 'insert' and data.get('vessel_name'):
                _ensure_masters(data, cur)
                _ensure_vessel(data.get('vessel_name'), data.get('loa'), cur, username)
                # guard against a record created since the preview was taken
                via = data.get('via_number')
                if via:
                    cur.execute(
                        'SELECT id FROM expected_vessels WHERE via_number=%s AND vessel_name=%s',
                        [via, data['vessel_name']]
                    )
                    dup = cur.fetchone()
                    if dup:
                        cur.execute(
                            f"UPDATE expected_vessels SET {', '.join(f'{c}=%s' for c in data)} WHERE id=%s",
                            list(data.values()) + [dup['id']]
                        )
                        updated += 1
                        continue
                data['created_by'] = username
                data['doc_status'] = 'Pending'
                cols = list(data)
                cur.execute(
                    f"INSERT INTO expected_vessels ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})",
                    [data[c] for c in cols]
                )
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'inserted': inserted, 'updated': updated, 'skipped': skipped}


def _clean_empty(data):
    for k in list(data.keys()):
        if data[k] == '':
            data[k] = None
    return data

_MOVED = 'Closed - Other Terminal'


def get_data(page=1, size=20, filters=None):
    # Vessels moved to another terminal are hidden from the main grid
    # (shown in the bottom accordion via get_moved_to_terminal()).
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT COUNT(*) FROM expected_vessels WHERE doc_status IS DISTINCT FROM %s', [_MOVED])
        total = cur.fetchone()['count']
        cur.execute('SELECT * FROM expected_vessels WHERE doc_status IS DISTINCT FROM %s ORDER BY id DESC LIMIT %s OFFSET %s',
                    [_MOVED, size, (page - 1) * size])
        return [dict(r) for r in cur.fetchall()], total
    finally:
        conn.close()


def get_moved_to_terminal():
    """Vessels closed because they were handled at another terminal."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM expected_vessels WHERE doc_status=%s ORDER BY id DESC', [_MOVED])
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def save(data, username=None):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    _computed = {'id', 'vcn_id', 'doc_status', 'created_by', 'created_at'}
    row_id = data.get('id')
    if row_id:
        cols = [k for k in data if k not in _computed]
        cur.execute(
            f"UPDATE expected_vessels SET {', '.join(f'{c}=%s' for c in cols)} WHERE id=%s",
            [data[c] for c in cols] + [row_id]
        )
    else:
        data['created_by'] = username
        cols = [k for k in data if k not in {'id'}]
        cur.execute(
            f"INSERT INTO expected_vessels ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))}) RETURNING id",
            [data[c] for c in cols]
        )
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

def delete(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('DELETE FROM expected_vessels WHERE id=%s', (row_id,))
    conn.commit()
    conn.close()

def get_by_id(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM expected_vessels WHERE id=%s', (row_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_vessel_master_doc(vessel_name):
    """Return 'VM#/NAME' reference for the VC01 master record, or None.

    Same format the VCN01 vessel dropdown uses (see VCN01 model.get_vessels).
    """
    key = _norm_no_mt(vessel_name)
    if not key:
        return None
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT doc_num, vessel_name FROM vessels')
        for r in cur.fetchall():
            if _norm_no_mt(r['vessel_name']) == key:
                return f"{r['doc_num']}/{r['vessel_name']}"
    finally:
        conn.close()
    return None


def build_consigner_rows(ev):
    """Expand an EV01 row into VCN consigner rows — one row per IGM line.

    Each row carries a single cargo + quantity (IGM/FORM III grain). When the
    PDF's '+'-separated lists line up positionally, cargo[i]/qty[i] go to
    consignee[i]; otherwise every consignee gets a line per cargo. Importer
    defaults to the consignee (usually the same party on FORM III). BL no/date
    are not in the daily report — the user fills them from the IGM.
    """
    def _split(key):
        return [s.strip() for s in (ev.get(key) or '').split(',')
                if s.strip() and not re.fullmatch(r'-+', s.strip())]

    tanks = _split('tanks')
    consignees = _split('consignees')
    cargos = _split('cargo_name')
    qtys = _split('quantity')
    terminal = ev.get('terminal_name')

    def _pick(lst, i):
        if not lst:
            return None
        if len(lst) == len(consignees):
            return lst[i]
        return lst[0]

    def _qty_for(j):
        if j >= len(qtys):
            return None
        raw = qtys[j]
        try:                       # cap at 3 decimal places, drop trailing zeros
            return f'{round(float(raw), 3):.3f}'.rstrip('0').rstrip('.')
        except (TypeError, ValueError):
            return raw

    def _cargo_items(i):
        """[(cargo, qty), ...] for consignee i, index pairing preserved."""
        if not cargos:
            return [(None, None)]
        if len(cargos) == len(consignees):
            return [(cargos[i], _qty_for(i))]
        if len(cargos) == 1:
            return [(cargos[0], _qty_for(0))]
        return [(c, _qty_for(j)) for j, c in enumerate(cargos)]

    rows = []
    line_no = 0
    for i, consignee in enumerate(consignees or [None]):
        for cargo, _qty in _cargo_items(i):
            line_no += 1
            rows.append({
                'igm_line_no':     str(line_no),
                'cargo_name':      cargo,
                # quantity, pipeline and unload terminal are NOT autofilled on the
                # EV01→VCN move (the per-cargo total was being duplicated across
                # consignees). The operator allocates per parcel in VCN01, validated
                # against the per-cargo quota captured below.
                'quantity':        None,
                'consigner_name':  consignee,
                'importer_name':   consignee,
                'pipeline_name':   None,
                'unload_terminal': None,
            })
    return rows


def cargo_quotas(ev):
    """Per-cargo total quantity from the EV01 record: {cargo_name: total_qty}.
    Captured on move so VCN01 can show available-per-cargo and validate parcels."""
    def _split(key):
        return [s.strip() for s in (ev.get(key) or '').split(',')
                if s.strip() and not re.fullmatch(r'-+', s.strip())]
    cargos, qtys = _split('cargo_name'), _split('quantity')
    out = {}
    for i, name in enumerate(cargos):
        if i >= len(qtys):
            break
        try:
            out[name] = out.get(name, 0.0) + float(qtys[i])
        except (TypeError, ValueError):
            pass
    return out


def close_to_other_terminal(ev_id, terminal_name):
    """Vessel is handled at another terminal — close it in EV01 without
    creating a VCN. Records the terminal and marks the row Closed."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(
        "UPDATE expected_vessels SET terminal_name=%s, doc_status='Closed - Other Terminal' WHERE id=%s",
        [terminal_name, ev_id]
    )
    conn.commit()
    conn.close()


def mark_moved_to_vcn(ev_id, vcn_id):
    """Once moved to a VCN the expected-vessel row is removed from EV01 —
    the vessel now lives in Vessel Call Number, not the expected list."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("DELETE FROM expected_vessels WHERE id=%s", [ev_id])
    conn.commit()
    conn.close()
