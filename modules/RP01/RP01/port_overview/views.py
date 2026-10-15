"""Port Overview — live wall dashboard for the liquid jetty.

Layout follows PORTMAN's RP01 Port Overview (bulk); the data is liquid:
tankers on berth come from the Berth Plan, cargo cards from the DPR's
Section B grid, pipelines replace the bulk equipment/MBC panels.
"""
import calendar
import json
from datetime import date, datetime, time, timedelta
from functools import wraps

from flask import render_template, session, redirect, url_for, jsonify

from .. import bp
from database import get_db, get_cursor
from ..dpr.dpr import _get_section_b, _get_fy_info
from ..Berth_plan.view import get_berths, get_berthed_vessels, get_expected_waiting_vessels
from modules.LUEU01.model import get_started_parcels
from weather_service import get_weather

IMAGE_SIZE = (540, 808)   # static/img/jjltpljetty.png natural pixel size
DAY_START = time(7, 0)    # operational day runs 07:00 -> 07:00, same as the DPR
CATEGORIES = ['Edible Oil', 'Chemical', 'POL', 'Other liquid']   # DPR Section B columns
# Section B row order (see dpr._get_section_b row_specs)
_SECTION_B_KEYS = ['balance_on_board', 'day', 'month', 'fy', 'fy_prev', 'fy_prev2', 'cumulative']


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@bp.route('/module/RP01/port-overview/')
@login_required
def port_overview_index():
    return render_template('port_overview/port_overview.html', username=session.get('username'))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _op_day_start(now):
    """Start of the current 07:00 -> 07:00 operational day."""
    start = datetime.combine(now.date(), DAY_START)
    return start if now >= start else start - timedelta(days=1)


def _section_b(cur, selected_date, window_start, window_end):
    """DPR Section B as {row_key: {category: qty}}."""
    rows = _get_section_b(cur, selected_date, window_start, window_end)
    return {k: {c: float(r.get(c) or 0) for c in CATEGORIES} for k, r in zip(_SECTION_B_KEYS, rows)}


def _target_totals(targets_json, month_abbr):
    """(FY target, month target) from financial_year_targets.targets — Outlook
    overrides Target when set, the same rule the DPR's budget section uses."""
    t = targets_json
    if isinstance(t, str):
        t = json.loads(t)
    items = t.get('targets', []) if isinstance(t, dict) else []
    fy = month = 0.0
    for item in items:
        for md in item.get('monthly_data') or []:
            base = float(md.get('target') or md.get('budget_quantity') or 0)
            v = float(md.get('outlook') or 0) or base
            fy += v
            if (md.get('month') or '').strip() == month_abbr:
                month += v
    return round(fy, 2), round(month, 2)


def _required_daily(target, achieved, days_left):
    if not target or days_left <= 0:
        return 0
    return round(max(target - achieved, 0) / days_left, 2)


def _classify_tides(rows):
    """[(datetime, metres)] sorted -> [(dt, m, 'HW'|'LW')]. A reading higher than
    its next neighbour (or previous, for the last one) is high water.
    ponytail: assumes tide_master holds HW/LW turning points, not hourly heights."""
    out = []
    for i, (dt, m) in enumerate(rows):
        other = rows[i + 1][1] if i + 1 < len(rows) else (rows[i - 1][1] if i else m)
        out.append((dt, m, 'HW' if m > other else 'LW'))
    return out


def _parse_dt(v):
    s = str(v or '').strip().replace('T', ' ')[:16]
    try:
        return datetime.strptime(s, '%Y-%m-%d %H:%M')
    except ValueError:
        return None


def _load_berth_layout(cur):
    """Berth positions live on port_berth_master.image_position (PBM01)."""
    cur.execute("""
        SELECT berth_name, image_position FROM port_berth_master
        WHERE image_position IS NOT NULL ORDER BY berth_name
    """)
    berths = []
    for r in cur.fetchall():
        pos = r['image_position']
        if isinstance(pos, str):
            try:
                pos = json.loads(pos)
            except ValueError:
                pos = None
        if not pos:
            continue
        berths.append({'label': r['berth_name'], 'cx': pos.get('cx'), 'cy': pos.get('cy'),
                       'w': pos.get('w'), 'h': pos.get('h'), 'angle': pos.get('angle', 0)})
    return {'image': 'jjltpljetty.png', 'image_size': list(IMAGE_SIZE), 'berths': berths}


def _parcel_state(p):
    if p.get('is_removed'):
        return 'Removed'
    if p.get('end_dt'):
        return 'Completed'
    return 'Pumping' if p.get('start_dt') else 'Not Started'


def _vessels_on_berth(cur, day_start, now):
    """Berth Plan's berthed-vessel rows plus their parcels, keyed by berth."""
    out = {}
    for v in get_berthed_vessels(day_start, now, get_berths(cur)):
        parcels = [{
            'parcel_no': p['parcel_no'], 'cargo': p['cargo_name'], 'pipeline': p['pipeline_name'],
            'terminal': p['terminal_name'], 'target': p['target_qty'], 'done': p['logged_qty'],
            'balance': p['remaining_qty'], 'rate': p['avg_rate'], 'state': _parcel_state(p),
        } for p in get_started_parcels(v['vcn_id'])]
        status = ('Awaiting Ops' if not v.get('ops_commenced')
                  else 'Ops Completed' if (v.get('balance') or 0) <= 0 else 'Under Operation')
        out.setdefault(str(v['berth_name']).strip().upper(), []).append({
            'name': v['vessel_name'], 'via': v.get('via_no'), 'cargo': v.get('cargo'),
            'consigner': v.get('consigner'), 'pipeline': v.get('pipeline'), 'terminal': v.get('terminal'),
            'agent': v.get('agent'), 'loa': v.get('loa'), 'alongside': v.get('alongside'),
            'commenced': v.get('ops_commenced'), 'total_qty': v.get('quantity') or 0,
            'done_qty': v.get('till_now_qty') or 0, 'balance_qty': v.get('balance') or 0,
            'today_qty': v.get('last_24hr_qty') or 0, 'rate': v.get('present_flow_rate') or 0,
            'rate_planned': v.get('is_planned'), 'etc': v.get('expected_completion'),
            'remarks': v.get('remarks'), 'status': status, 'parcels': parcels,
        })
    return out


def _waiting_vessels():
    """VCNs not yet alongside — at anchorage when an anchored time is logged."""
    return [{'name': w['vessel_name'], 'cargo': w.get('cargo') or '',
             'qty': float(w.get('quantity') or 0), 'ata': w.get('ata') or '',
             'eta': w.get('eta') or '', 'state': 'anch' if w.get('ata') else 'exp'}
            for w in get_expected_waiting_vessels(None, None) if w.get('vessel_name')]


def _pipeline_month_qty(cur, since):
    """Quantity logged through each pipeline since `since`, keyed UPPER(name).
    ponytail: a parcel declared on two pipelines counts its full log on both."""
    cur.execute("""
        SELECT src.pipe, SUM(COALESCE(log.quantity, 0)) AS qty
        FROM lueu_parcel_log log
        JOIN ldud_parcel_ops po ON po.id = log.parcel_op_id
        JOIN ldud_header lh ON lh.id = po.ldud_id
        JOIN vcn_header vh ON vh.id = lh.vcn_id
        CROSS JOIN LATERAL (
            SELECT DISTINCT UPPER(TRIM(pl)) AS pipe
            FROM (
                SELECT id, pipeline_name FROM vcn_consigners
                 WHERE vh.operation_type IS DISTINCT FROM 'Export'
                UNION ALL
                SELECT id, pipeline_name FROM vcn_export_cargo_declaration
                 WHERE vh.operation_type = 'Export'
            ) s, unnest(string_to_array(s.pipeline_name, ',')) AS pl
            WHERE s.id::text = ANY(string_to_array(REPLACE(po.parcel_ids, ' ', ''), ','))
              AND NULLIF(TRIM(pl), '') IS NOT NULL
        ) src
        WHERE log.is_deleted IS NOT TRUE AND log.is_shortclose IS NOT TRUE
          AND lh.is_deleted IS NOT TRUE
          AND NULLIF(log.entry_date, '')::timestamp
              + COALESCE(NULLIF(log.from_time, '')::time, '00:00'::time) >= %s
        GROUP BY src.pipe
    """, [since])
    return {r['pipe']: float(r['qty'] or 0) for r in cur.fetchall()}


def _pipelines(cur, occupancy, month_start, today):
    cur.execute("""
        SELECT p.pipeline_name, p.is_active, p.hydro_test_valid_until::date AS hydro,
               STRING_AGG(t.terminal_name, ', ' ORDER BY t.terminal_name) AS terminals
        FROM pipeline_master p
        LEFT JOIN pipeline_terminal_mapping m ON m.pipeline_id = p.id AND m.is_active IS NOT FALSE
        LEFT JOIN terminal_master t ON t.id = m.terminal_id
        GROUP BY p.id ORDER BY p.pipeline_name
    """)
    rows = cur.fetchall()
    month_qty = _pipeline_month_qty(cur, month_start)

    live = {}   # UPPER(pipeline) -> parcels pumping through it right now
    for berth, vessels in occupancy.items():
        for v in vessels:
            for p in v['parcels']:
                if p['state'] != 'Pumping':
                    continue
                for name in str(p['pipeline'] or '').split(','):
                    if name.strip():
                        live.setdefault(name.strip().upper(), []).append({
                            'vessel': v['name'], 'berth': berth, 'cargo': p['cargo'],
                            'rate': p['rate'], 'balance': p['balance']})

    out = []
    for r in rows:
        key = r['pipeline_name'].strip().upper()
        hydro = r['hydro']
        out.append({
            'name': r['pipeline_name'], 'active': r['is_active'] is not False,
            'terminals': r['terminals'] or '', 'month_qty': round(month_qty.get(key, 0), 2),
            'hydro': hydro.strftime('%d %b %y') if hydro else '',
            'hydro_days': (hydro - today).days if hydro else None,
            'live': live.get(key, []),
        })
    return out


def _top_delays(cur, day_start, now):
    """Delay-tagged LUEU log intervals in the current operational day, summed
    per (vessel, equipment, delay) and ranked."""
    cur.execute("""
        SELECT lh.vessel_name, log.equipment_name, TRIM(log.delay_name) AS delay_name,
               SUM(EXTRACT(EPOCH FROM (
                   COALESCE(NULLIF(log.to_time,'')::time, '00:00'::time)
                   - COALESCE(NULLIF(log.from_time,'')::time, '00:00'::time)
                   + CASE WHEN NULLIF(log.to_time,'')::time < NULLIF(log.from_time,'')::time
                          THEN INTERVAL '24 hours' ELSE INTERVAL '0' END)) / 60) AS minutes
        FROM lueu_parcel_log log
        JOIN ldud_parcel_ops po ON po.id = log.parcel_op_id
        JOIN ldud_header lh ON lh.id = po.ldud_id
        WHERE log.is_deleted IS NOT TRUE AND lh.is_deleted IS NOT TRUE
          AND NULLIF(TRIM(log.delay_name), '') IS NOT NULL
          AND NULLIF(log.entry_date, '')::timestamp
              + COALESCE(NULLIF(log.from_time, '')::time, '00:00'::time) >= %s
          AND NULLIF(log.entry_date, '')::timestamp
              + COALESCE(NULLIF(log.from_time, '')::time, '00:00'::time) < %s
        GROUP BY 1, 2, 3
    """, [day_start, now])
    ranked = []
    for r in cur.fetchall():
        src = ' · '.join(x for x in (r['vessel_name'], r['equipment_name']) if x and x.strip())
        ranked.append({'delay_name': f"{src} — {r['delay_name']}" if src else r['delay_name'],
                       'minutes': int(r['minutes'] or 0)})
    ranked = [d for d in ranked if d['minutes'] > 0]
    ranked.sort(key=lambda d: d['minutes'], reverse=True)
    return ranked


def _shift_incharge(cur, op_date):
    cur.execute("""
        SELECT shift_incharge FROM lueu_parcel_log
        WHERE is_deleted IS NOT TRUE AND NULLIF(TRIM(shift_incharge), '') IS NOT NULL
          AND entry_date >= %s
        ORDER BY entry_date DESC, id DESC LIMIT 1
    """, [op_date.strftime('%Y-%m-%d')])
    row = cur.fetchone()
    return (row['shift_incharge'] or '').strip() if row else ''


def _tide(cur, now):
    cur.execute(r"""
        SELECT tide_datetime, tide_meters FROM tide_master
        WHERE tide_datetime ~ '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}' AND tide_datetime >= %s
        ORDER BY tide_datetime LIMIT 16
    """, [(now - timedelta(days=1)).strftime('%Y-%m-%d')])
    rows = [(_parse_dt(r['tide_datetime']), float(r['tide_meters'] or 0)) for r in cur.fetchall()]
    rows = [r for r in rows if r[0]]
    return [{'type': t, 'time': dt.strftime('%d %b %H:%M'), 'height': round(m, 2)}
            for dt, m, t in _classify_tides(rows) if dt >= now][:6]


def _weather_card(now):
    """Cached WeatherAPI payload trimmed to the fields the weather card shows.
    None when the cache is empty or stale — see weather_service.TTL_HOURS."""
    w = get_weather()
    if not w:
        return None
    cur = w.get('current') or {}
    days = (w.get('forecast') or {}).get('forecastday') or []
    day0 = days[0] if days else {}
    now_s = now.strftime('%Y-%m-%d %H:%M')
    hours = [h for d in days for h in (d.get('hour') or []) if h.get('time', '') >= now_s][:6]
    return {
        'temp':     cur.get('temp_c'),
        'feels':    cur.get('feelslike_c'),
        'text':     (cur.get('condition') or {}).get('text'),
        'icon':     (cur.get('condition') or {}).get('icon'),
        'wind':     cur.get('wind_kph'),
        'wind_dir': cur.get('wind_dir'),
        'gust':     cur.get('gust_kph'),
        'humidity': cur.get('humidity'),
        'pressure': cur.get('pressure_mb'),
        'vis':      cur.get('vis_km'),
        'rain':     (day0.get('day') or {}).get('totalprecip_mm'),
        'sunrise':  (day0.get('astro') or {}).get('sunrise'),
        'sunset':   (day0.get('astro') or {}).get('sunset'),
        'updated':  cur.get('last_updated'),
        'hours':    [{'t': h['time'][11:16], 'temp': h.get('temp_c'),
                      'icon': (h.get('condition') or {}).get('icon'),
                      'rain': h.get('chance_of_rain')} for h in hours],
        'days':     [{'d': d.get('date'),
                      'icon': ((d.get('day') or {}).get('condition') or {}).get('icon'),
                      'max':  (d.get('day') or {}).get('maxtemp_c'),
                      'min':  (d.get('day') or {}).get('mintemp_c'),
                      'wind': (d.get('day') or {}).get('maxwind_kph'),
                      'rain': (d.get('day') or {}).get('daily_chance_of_rain')} for d in days[:3]],
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@bp.route('/api/module/RP01/port-overview/data')
@login_required
def port_overview_data():
    now = datetime.now()
    day_start = _op_day_start(now)
    op_date = day_start.date()
    month_start = datetime.combine(op_date.replace(day=1), DAY_START)
    fy_label, fy_start = _get_fy_info(op_date)

    conn = get_db()
    try:
        cur = get_cursor(conn)
        live = _section_b(cur, op_date, day_start, now)
        yday = _section_b(cur, op_date, day_start - timedelta(days=1), day_start)['day']

        cur.execute("SELECT targets FROM financial_year_targets WHERE financial_year = %s", [fy_label])
        row = cur.fetchone()
        fy_target, month_target = _target_totals(row['targets'] if row else None, op_date.strftime('%b'))

        layout = _load_berth_layout(cur)
        occupancy = _vessels_on_berth(cur, day_start, now)
        for b in layout['berths']:
            b['assets'] = occupancy.get(str(b['label']).strip().upper(), [])

        pipelines = _pipelines(cur, occupancy, month_start, op_date)
        delays = _top_delays(cur, day_start, now)
        incharge = _shift_incharge(cur, op_date)
        tide = _tide(cur, now)
    finally:
        conn.close()

    fy_end = date(fy_start.year + 1, 3, 31)
    month_days_left = calendar.monthrange(op_date.year, op_date.month)[1] - op_date.day + 1
    month_total = sum(live['month'].values())
    fy_total = sum(live['fy'].values())

    cards = {
        'today':         {'label': 'Today', 'by_type': live['day']},
        'yesterday':     {'label': 'Yesterday', 'by_type': yday},
        'current_month': {'label': op_date.strftime('%b %Y'), 'by_type': live['month'],
                          'target': month_target,
                          'required_daily': _required_daily(month_target, month_total, month_days_left)},
        'current_fy':    {'label': f'FY {fy_label}', 'by_type': live['fy'],
                          'target': fy_target,
                          'required_daily': _required_daily(fy_target, fy_total, (fy_end - op_date).days + 1)},
        'all_time':      {'label': 'Cumulative', 'by_type': live['cumulative']},
    }
    for c in cards.values():
        c['total'] = round(sum(c['by_type'].values()), 2)
        c['by_type'] = {k: round(v, 2) for k, v in c['by_type'].items() if v > 0}

    return jsonify({
        'layout':           layout,
        'balance_on_board': round(sum(live['balance_on_board'].values()), 2),
        'waiting':          _waiting_vessels(),
        'cargo_cards':      cards,
        'pipelines':        pipelines,
        'delays':           delays,
        'tide':             tide,
        'weather':          _weather_card(now),
        'shift_incharge':   incharge,
        'fy_label':         fy_label,
        'as_of':            now.strftime('%Y-%m-%d %H:%M:%S'),
    })
