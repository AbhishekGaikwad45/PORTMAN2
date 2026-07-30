"""
Report-5 — Performance Report for the Month (Berth / Commodity / Vessels /
Occupancy / Handling). Flask Blueprint version. Reads from Postgres.

======================================================================
 DATA SOURCE CUTOVER
======================================================================
The Berth/Commodity/TOTAL-HANDLING/Commodity *label* columns are hard-coded
on the frontend (report5.html) — this backend only needs to supply, per
selected month:
    - quantity  (total handling, in tonnes)
    - vessel_count (distinct vessels for that month)
    - berth occupancy % (see BERTH OCCUPANCY section below)

Two different source systems are used depending on the month:

    - Apr .. Jun  ->  mis_vessel_master   (legacy system)
    - Jul .. Mar  ->  lueu_parcel_log (quantity) + ldud_header (vessel_name)
                      (new system, live from CUTOVER_DATE below)

The cutover is a ONE-TIME SYSTEM MIGRATION DATE, not a recurring
"July every year" rule — i.e. Jul-Aug-Sep-2025 is still legacy data,
but Jul-Aug-Sep-2026 onward is new-system data. Adjust CUTOVER_DATE
below if that's wrong.

======================================================================
 ASSUMPTIONS THAT STILL NEED CONFIRMATION
======================================================================
1. Vessel count for Jul+ uses ldud_header.created_date (per user
   instruction) to determine which month a vessel record counts toward.
2. lueu_parcel_log.entry_date / ldud_header's date column are stored as
   free-text (not a real DATE/TIMESTAMP column), matching the pattern
   seen on lueu_parcel_log. Rows are fetched and parsed in Python
   (via dateutil) rather than filtered in SQL, specifically to survive
   inconsistent text date formats. If entry_date turns out to be a real
   date/timestamp column, the parsing in `_parse_text_date()` still
   works, but you could simplify to a SQL WHERE clause instead.
3. mis_vessel_master.vessel_name is assumed to be the correct column
   for counting distinct vessels Apr-Jun (per your confirmation).
4. BERTH OCCUPANCY — column names (MIS_ALONGSIDE_COLUMN /
   MIS_CASTOFF_COLUMN / LDUD_ALONGSIDE_COLUMN / LDUD_CASTOFF_COLUMN
   below) are GUESSES and need confirmation. Also assumed: a vessel's
   hours are booked entirely to its ALONGSIDE month (no splitting
   across a month boundary), and "divide by 2" in the occupancy
   formula means 2 physical berths (NUM_BERTHS = 2).

======================================================================
 DEBUGGING NOTE (added)
======================================================================
Both berth-hours fetch functions now return a tuple of
(total_hours, debug_rows) instead of just a float. `debug_rows` is a
list of per-vessel dicts (vessel_name, alongside, castoff, hours) for
every row that actually contributed to the sum, so the numbers going
into the occupancy % can be checked against a manual list of vessels
instead of guessing whether the berth_no filter is really being
applied server-side. This is threaded through fetch_berth_hours() and
surfaced in compute_berth_occupancy()'s result under "debug_rows", and
therefore also under result["occupancy_detail"]["debug_rows"] in the
/report endpoint response.
======================================================================
"""

import calendar
import logging
import traceback
from datetime import date
from functools import wraps

from dateutil import parser as dateutil_parser

from flask import jsonify, request, render_template, session, redirect, url_for

from database import get_db, get_cursor

from .. import bp

# ---------------------------------------------------------------------
# DEBUG LOGGING
# ---------------------------------------------------------------------
# Dedicated logger for this module so berth-occupancy debugging doesn't
# get lost in general Flask/werkzeug request logs. Prints to console by
# default (propagates to root logger); set to logging.INFO or higher to
# quiet this down once things are confirmed working.
logger = logging.getLogger("report5")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[report5] %(levelname)s %(message)s"
    ))
    logger.addHandler(_handler)
logger.setLevel(logging.DEBUG)

# Flip to False once berth occupancy is confirmed working, to stop
# printing full row dumps on every request.
DEBUG_BERTH_OCCUPANCY = True


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


MONTH_NAMES = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
MONTH_NUM = {  # calendar month number, for date filtering against the new tables
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
NUM_TO_MONTH_ABBREV = {v: k for k, v in MONTH_NUM.items()}

# One-time system migration date. Any (month, calendar-year) at or after
# this date reads from the new tables; anything before reads from
# mis_vessel_master. See module docstring — this is NOT a recurring
# "every July" rule.
CUTOVER_DATE = date(2026, 7, 1)

# Per user instruction: use ldud_header.created_date to determine which
# month a vessel record counts toward.
LDUD_HEADER_DATE_COLUMN = "created_date"

# --- Berth occupancy column names — confirmed against information_schema ---
# mis_vessel_master has THREE candidate "end" columns: cast_off, sail_cast_off,
# and a pre-computed numeric stay_at_berth. Went with alongside/cast_off as the
# most literal match to "Cast off - All fast", but this is a judgment call —
# please confirm cast_off (not sail_cast_off) is the right one, and whether
# stay_at_berth (already numeric) might be a better/pre-computed source than
# deriving hours from alongside/cast_off ourselves.
# Confirmed from mis_vessel_master data (Jun-26): the Liquid berths are
# LB-03 and LB-04 (berth_no column). Berth occupancy must be scoped to
# just these, not every berth in the port, or the sum includes Shallow/
# Coastal/Anchorage hours too and comes out ~4-5x too high.
LIQUID_BERTH_CODES_MIS = ["LB-03", "LB-04"]  # <-- CONFIRM this is the full/correct set

MIS_ALONGSIDE_COLUMN = "alongside"      # confirmed column, text (needs datetime parse)
MIS_CASTOFF_COLUMN = "cast_off"         # CONFIRM vs sail_cast_off - which is "cast off"?
LDUD_ALONGSIDE_COLUMN = "alongside_datetime"  # confirmed column, text (needs datetime parse)
LDUD_CASTOFF_COLUMN = "cast_off_datetime"     # confirmed column, text (needs datetime parse)
NUM_BERTHS = 2  # per formula: divide by 2 -> 2 physical berths

# --- Commodity turnaround / parcel size (Commoditywise Av. Turn Around
# table) — column names.
#
# CONFIRMED against information_schema (portman_jnpa, 30-Jul-2026):
#   mis_vessel_master DOES have a cargo/commodity column, but it's named
#   "cargo", not "commodity". Fixed below.
#
# RESOLVED (per user instruction, 30-Jul-2026): neither ldud_header nor
#   lueu_parcel_log has ANY commodity-like column. Checked candidates:
#     ldud_header: id, doc_num, vcn_id, vcn_doc_num, vessel_name,
#       anchored_datetime, arrival_inner_anchorage, arrival_outer_anchorage,
#       arrived_mbpt, arrived_mfl, free_pratique_granted, nor_tendered,
#       nor_accepted, discharge_commenced, discharge_completed,
#       initial_draft_survey_quantity, doc_status, created_by,
#       created_date, custom_clearance, agent_stevedore_onboard,
#       operation_type, material_po_number, alongside_datetime,
#       cast_off_datetime, pilot_board_departure, pilot_disembarked,
#       first_line, pilot_pickup_time, is_deleted, deleted_by, deleted_date
#     lueu_parcel_log: id, parcel_op_id, entry_date, from_time, to_time,
#       quantity, quantity_uom, medium, equipment_name, delay_name, shift,
#       operator_name, shift_incharge, berth_name, remarks, created_by,
#       created_date, is_deleted, deleted_by, deleted_date, pressure,
#       is_shortclose
#   lueu_parcel_log.medium was checked directly (SELECT DISTINCT medium
#   FROM lueu_parcel_log) and only contains handling-method values
#   ('Direct Pipe', 'Equipment'), not commodity/cargo type -- ruled out.
#
#   DECISION: per user instruction, ldud_header/lueu_parcel_log are used
#   only for the Liquid berths, so fetch_commodity_turnaround_from_new_system
#   applies NO commodity filter -- every row for the given month/year is
#   treated as Liquid. LDUD_COMMODITY_COLUMN / PARCEL_LOG_COMMODITY_COLUMN
#   are left as None/unused (not referenced anywhere) to reflect that no
#   such column exists; if the new system ever handles another commodity
#   through these same tables, this will need revisiting.
MIS_COMMODITY_COLUMN = "cargo"            # CONFIRMED: real column on mis_vessel_master
LDUD_COMMODITY_COLUMN = None              # N/A: no commodity column on ldud_header; new-system data assumed Liquid-only
PARCEL_LOG_COMMODITY_COLUMN = None        # N/A: no commodity column on lueu_parcel_log; new-system data assumed Liquid-only

# --- mis_history — used for Av. Parcel Size on legacy (Apr-Jun) months ---
# CONFIRMED against information_schema + sample data (portman_jnpa, 30-Jul-2026):
#   - month_jsw stores the same "Mon-YY" format as mis_vessel_master.month
#     (sample: 'Jun-25', 'Jun-26').
#   - cargo_type holds commodity values, but UPPERCASE ('LIQUID', not
#     'Liquid') -- the ILIKE filter used below is already case-insensitive,
#     so this doesn't need special-casing.
#   - cargo_category / cargo_sub_category are a finer breakdown within a
#     cargo_type (e.g. LIQUID -> EDIBLE OIL / FERTILIZERS / OTHER LIQUID /
#     POL) -- NOT an alternate commodity label, so cargo_type is the right
#     column to match against "Liquid"/"Cement", not these.
MIS_HISTORY_MONTH_COLUMN = "month_jsw"
MIS_HISTORY_COMMODITY_COLUMN = "cargo_type"
MIS_HISTORY_QUANTITY_COLUMN = "quantity"


class ReportDataError(Exception):
    """Raised for any problem loading/validating the report's source data.
    Caught by the route handlers and turned into a clean JSON error response."""
    pass


def _parse_fin_year_start(raw) -> int:
    """Normalize a fin_year value into its starting calendar year (int).
    Handles a plain int/numeric-string ('2026'), a range string
    ('2026-27' or '2026-2027'), and strips stray whitespace. Raises
    ValueError if it can't be parsed, so callers can fall back safely."""
    if raw is None:
        raise ValueError("fin_year value is None")
    s = str(raw).strip()
    if not s:
        raise ValueError("fin_year value is empty")
    # Take the leading run of digits as the starting year, e.g.
    # "2026-27" -> "2026", "2026-2027" -> "2026", "2026" -> "2026".
    head = s.split("-")[0].strip()
    return int(head)


def fetch_latest_fin_year_start() -> int:
    """Most recent fiscal year (as its starting calendar year) present in
    mis_vessel_master.fin_year. Falls back to today's calendar-year-based
    fin year if the table/column is empty or unparsable, so a bad/missing
    fin_year value never crashes the report."""
    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute("SELECT DISTINCT fin_year FROM mis_vessel_master WHERE fin_year IS NOT NULL")
        rows = cur.fetchall()
    finally:
        conn.close()

    parsed = []
    for r in rows:
        try:
            parsed.append(_parse_fin_year_start(r["fin_year"]))
        except (ValueError, TypeError):
            continue  # skip unparsable values rather than failing the whole report

    if parsed:
        return max(parsed)

    # Fallback: derive fin_year_start from today's date the same way the
    # rest of this module thinks about fiscal years (Apr-Mar).
    today = date.today()
    return today.year if today.month >= 4 else today.year - 1


def month_str_to_idx(abbrev: str) -> int:
    try:
        return MONTH_NAMES.index(abbrev)
    except ValueError:
        raise ReportDataError(
            f"Unrecognized month '{abbrev}'. Expected one of: {', '.join(MONTH_NAMES)}"
        )


def calendar_year_for_month(fin_year_start: int, month_abbrev: str) -> int:
    """fin_year_start=2026 ('2026-27') + month 'Jun' -> 2026;
    fin_year_start=2026 + month 'Feb' -> 2027 (Jan-Mar fall in the FY end year)."""
    return fin_year_start + 1 if month_abbrev in ("Jan", "Feb", "Mar") else fin_year_start


def uses_legacy_source(month_abbrev: str, calendar_year: int) -> bool:
    """True -> read from mis_vessel_master. False -> read from the new
    lueu_parcel_log / ldud_header tables."""
    month_num = MONTH_NUM[month_abbrev]
    # Use day=1 of that calendar month to compare against CUTOVER_DATE.
    month_date = date(calendar_year, month_num, 1)
    return month_date < CUTOVER_DATE


def _parse_text_date(raw):
    """Best-effort parse of a free-text date column into a date(). Returns
    None if it can't be parsed (row is skipped rather than crashing the
    whole report).

    CONFIRMED FORMAT (per user, screenshot of ldud_header data):
    'YYYY-MM-DDTHH:MM' — ISO, year-first. dateutil_parser.parse() already
    reads a leading 4-digit year correctly regardless of dayfirst/
    yearfirst, so this alone wasn't an ambiguity bug for that exact
    shape. But we now parse with yearfirst=True (and dayfirst=False) to
    match the confirmed format explicitly rather than relying on
    dateutil's general heuristics, so any row that ISN'T in this format
    is more likely to fail loudly / get flagged in debug output instead
    of being silently misinterpreted."""
    if not raw:
        return None
    try:
        return dateutil_parser.parse(str(raw), yearfirst=True, dayfirst=False).date()
    except (ValueError, TypeError):
        return None


def _parse_text_datetime(raw):
    """Like _parse_text_date, but keeps the time component (needed for
    hours-alongside calculations, not just which day something falls
    on). Returns None if it can't be parsed.

    See _parse_text_date() docstring re: confirmed 'YYYY-MM-DDTHH:MM'
    format and yearfirst=True."""
    if not raw:
        return None
    try:
        return dateutil_parser.parse(str(raw), yearfirst=True, dayfirst=False)
    except (ValueError, TypeError):
        return None


def _days_in_month(month_abbrev: str, calendar_year: int) -> int:
    month_num = MONTH_NUM[month_abbrev]
    return calendar.monthrange(calendar_year, month_num)[1]


# ---------------------------------------------------------------------
# LEGACY SOURCE (Apr - Jun): mis_vessel_master
# ---------------------------------------------------------------------

def fetch_from_mis_vessel_master(month_abbrev: str, calendar_year: int):
    """quantity + distinct vessel count for one calendar month, from the
    legacy table. mis_vessel_master.month is stored like 'Jun-26'."""
    yy = str(calendar_year)[-2:]
    month_str = f"{month_abbrev}-{yy}"

    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute(
            """
            SELECT
                COALESCE(SUM(quantity), 0) AS quantity,
                COUNT(DISTINCT vessel_name) AS vessel_count
            FROM mis_vessel_master
            WHERE month = %(month_str)s
            """,
            {"month_str": month_str},
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return {"quantity": 0.0, "vessel_count": 0}

    return {
        "quantity": float(row["quantity"] or 0),
        "vessel_count": int(row["vessel_count"] or 0),
    }


# ---------------------------------------------------------------------
# NEW SOURCE (Jul onward): lueu_parcel_log (quantity) + ldud_header (vessels)
# ---------------------------------------------------------------------

def fetch_quantity_from_parcel_log(month_abbrev: str, calendar_year: int) -> float:
    """Sum of lueu_parcel_log.quantity for rows whose entry_date falls in
    the given calendar month/year, excluding soft-deleted rows."""
    month_num = MONTH_NUM[month_abbrev]

    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute(
            """
            SELECT entry_date, quantity
            FROM lueu_parcel_log
            WHERE COALESCE(is_deleted, false) = false
              AND quantity IS NOT NULL
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    total = 0.0
    for r in rows:
        d = _parse_text_date(r["entry_date"])
        if d and d.year == calendar_year and d.month == month_num:
            total += float(r["quantity"] or 0)

    return round(total, 3)


def fetch_vessel_count_from_ldud_header(month_abbrev: str, calendar_year: int) -> int:
    """Distinct vessel_name count from ldud_header for the given calendar
    month/year. See ASSUMPTION (1) at the top of this file re: date column."""
    month_num = MONTH_NUM[month_abbrev]

    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute(
            f"""
            SELECT vessel_name, {LDUD_HEADER_DATE_COLUMN} AS event_date
            FROM ldud_header
            WHERE vessel_name IS NOT NULL
              AND COALESCE(is_deleted, false) = false
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    vessels = set()
    for r in rows:
        d = _parse_text_date(r["event_date"])
        if d and d.year == calendar_year and d.month == month_num:
            vessels.add(r["vessel_name"])

    return len(vessels)


# ---------------------------------------------------------------------
# UNIFIED FETCH — picks the right source per month
# ---------------------------------------------------------------------

def fetch_month_figures(month_abbrev: str, calendar_year: int):
    if uses_legacy_source(month_abbrev, calendar_year):
        return fetch_from_mis_vessel_master(month_abbrev, calendar_year)

    return {
        "quantity": fetch_quantity_from_parcel_log(month_abbrev, calendar_year),
        "vessel_count": fetch_vessel_count_from_ldud_header(month_abbrev, calendar_year),
    }


def fetch_jjltpl_from_mis(month_abbrev: str, calendar_year: int) -> float:
    yy = str(calendar_year)[-2:]
    month_str = f"{month_abbrev}-{yy}"

    conn = get_db()
    cur = get_cursor(conn)

    cur.execute("""
        SELECT COALESCE(SUM(quantity),0) AS qty
        FROM mis_vessel_master
        WHERE month = %s
          AND terminal = 'JJLTPL'
    """, (month_str,))

    row = cur.fetchone()
    conn.close()

    return float(row["qty"] or 0)


def fetch_jjltpl_from_parcel_log(month_abbrev: str, calendar_year: int) -> float:
    month_num = MONTH_NUM[month_abbrev]

    conn = get_db()
    cur = get_cursor(conn)

    cur.execute("""
        SELECT entry_date, quantity
        FROM lueu_parcel_log
        WHERE COALESCE(is_deleted,false)=false
          AND terminal='JJLTPL'
    """)

    rows = cur.fetchall()
    conn.close()

    total = 0

    for r in rows:
        d = _parse_text_date(r["entry_date"])
        if d and d.year == calendar_year and d.month == month_num:
            total += float(r["quantity"] or 0)

    return round(total, 3)


def fiscal_year_start_for(month_abbrev: str, calendar_year: int) -> int:
    """Inverse of calendar_year_for_month: given a specific month/calendar-year,
    return the fiscal year's starting calendar year (Apr of that FY)."""
    return calendar_year - 1 if month_abbrev in ("Jan", "Feb", "Mar") else calendar_year


def fetch_fiscal_year_quantity_total(fin_year_start: int) -> float:
    """Sum of quantity across all 12 months of one fiscal year (Apr..Mar),
    pulling each month from whichever source it belongs to (legacy
    mis_vessel_master or the new lueu_parcel_log/ldud_header tables). This
    is how a fiscal year that straddles CUTOVER_DATE (e.g. 2026-27, where
    Apr-Jun is legacy and Jul-Mar is new-system) gets a single combined
    total: mis_vessel_master's months + lueu_parcel_log's months, added
    together."""
    total = 0.0
    for month_abbrev in MONTH_NAMES:
        calendar_year = calendar_year_for_month(fin_year_start, month_abbrev)
        figures = fetch_month_figures(month_abbrev, calendar_year)
        total += figures["quantity"]
    return round(total, 3)


def compute_report(month_abbrev: str, calendar_year: int):
    """Current month/year vs the same month one year earlier."""
    month_str_to_idx(month_abbrev)  # validates month_abbrev

    current = fetch_month_figures(month_abbrev, calendar_year)
    previous = fetch_month_figures(month_abbrev, calendar_year - 1)

    prev_qty = previous["quantity"]
    curr_qty = current["quantity"]
    increase_pct = ((curr_qty - prev_qty) / prev_qty * 100) if prev_qty else None

    return {
        "month": month_abbrev,
        "year": calendar_year,
        "current": current,
        "previous": previous,
        "increase_pct": round(increase_pct, 2) if increase_pct is not None else None,
    }


def compute_fiscal_year_comparison(fin_year_start: int, month_abbrev: str, calendar_year: int):
    """Current fiscal year vs the prior fiscal year, each summed across
    its own 12 months (mis + lueu combined per month, per year), plus the
    month-over-month report for the requested month."""
    current_total = fetch_fiscal_year_quantity_total(fin_year_start)
    previous_total = fetch_fiscal_year_quantity_total(fin_year_start - 1)

    result = compute_report(month_abbrev, calendar_year)

    increase_pct = (
        ((current_total - previous_total) / previous_total * 100)
        if previous_total else None
    )

    result["fin_year_start"] = fin_year_start
    result["fin_year_label"] = f"{fin_year_start}-{str(fin_year_start + 1)[-2:]}"
    result["prev_fin_year_label"] = f"{fin_year_start - 1}-{str(fin_year_start)[-2:]}"
    result["current_jjltpl"] = current_total
    result["previous_jjltpl"] = previous_total
    result["jjltpl_increase_pct"] = round(increase_pct, 2) if increase_pct is not None else None

    return result


# ---------------------------------------------------------------------
# BERTH OCCUPANCY
# ---------------------------------------------------------------------
# ASSUMPTIONS THAT STILL NEED CONFIRMATION (see ASSUMPTION 4 at top of
# file — please verify/correct):
#
#   1. MIS_ALONGSIDE_COLUMN / MIS_CASTOFF_COLUMN / LDUD_ALONGSIDE_COLUMN /
#      LDUD_CASTOFF_COLUMN are GUESSES. Update to match your real schema.
#   2. Both columns are assumed free-text date/time values (same
#      situation as entry_date / created_date elsewhere in this file),
#      parsed in Python via dateutil rather than filtered in SQL. If
#      they're real TIMESTAMP columns, this still works, but you could
#      simplify to a SQL WHERE/EXTRACT instead.
#   3. "Divide by 2" in your formula is assumed to mean 2 physical
#      berths, i.e. total available berth-hours in a month = days*24*2.
#   4. A vessel's occupancy hours are attributed to the month based on
#      its ALONGSIDE date (not castoff date). If a vessel comes
#      alongside in one month and casts off in the next, this version
#      books all its hours to the alongside month rather than splitting
#      across months. Flag if you need split-month handling.
#   5. Rows where castoff <= alongside, or either value fails to parse,
#      are skipped (bad data shouldn't silently corrupt the sum).
#
# DEBUG NOTE: both fetch_berth_hours_from_* functions below now return
# (total_hours, debug_rows) instead of a bare float. debug_rows is a
# list of {"vessel_name", "alongside", "castoff", "hours"} dicts, one
# per row actually counted in the sum, so the exact set of vessels
# behind a given occupancy % can be checked directly instead of by
# comparing two numbers and guessing where they diverge.

def fetch_berth_hours_from_mis_vessel_master(month_abbrev: str, calendar_year: int):
    """Total alongside-hours (sum of castoff - alongside, in hours) for
    the legacy table, for vessels whose alongside falls in this month.
    mis_vessel_master.month is stored like 'Jun-26' — same pattern as
    fetch_from_mis_vessel_master above.

    Returns (total_hours, debug_rows)."""
    yy = str(calendar_year)[-2:]
    month_str = f"{month_abbrev}-{yy}"

    logger.debug(
        "fetch_berth_hours_from_mis_vessel_master: month=%s year=%s "
        "-> querying month='%s' berth_no IN %s using columns alongside=%r castoff=%r",
        month_abbrev, calendar_year, month_str, LIQUID_BERTH_CODES_MIS,
        MIS_ALONGSIDE_COLUMN, MIS_CASTOFF_COLUMN,
    )

    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute(
            f"""
            SELECT vessel_name,
                   {MIS_ALONGSIDE_COLUMN} AS alongside_raw,
                   {MIS_CASTOFF_COLUMN} AS castoff_raw
            FROM mis_vessel_master
            WHERE month = %(month_str)s
              AND berth_no = ANY(%(berth_codes)s)
            """,
            {"month_str": month_str, "berth_codes": LIQUID_BERTH_CODES_MIS},
        )
        rows = cur.fetchall()
    except Exception:
        logger.exception(
            "fetch_berth_hours_from_mis_vessel_master: query FAILED "
            "(check MIS_ALONGSIDE_COLUMN / MIS_CASTOFF_COLUMN are real "
            "column names on mis_vessel_master)"
        )
        raise
    finally:
        conn.close()

    logger.debug(
        "fetch_berth_hours_from_mis_vessel_master: fetched %d row(s) for month='%s'",
        len(rows), month_str,
    )

    total_hours = 0.0
    debug_rows = []
    skipped_unparsed = 0
    skipped_bad_order = 0

    for i, r in enumerate(rows):
        vessel_name = r.get("vessel_name") if hasattr(r, "get") else r["vessel_name"]
        raw_alongside = r["alongside_raw"]
        raw_castoff = r["castoff_raw"]
        alongside = _parse_text_datetime(raw_alongside)
        castoff = _parse_text_datetime(raw_castoff)

        if not alongside or not castoff:
            skipped_unparsed += 1
            if DEBUG_BERTH_OCCUPANCY:
                logger.debug(
                    "  row %d: UNPARSEABLE vessel=%r alongside_raw=%r -> %r | castoff_raw=%r -> %r (skipped)",
                    i, vessel_name, raw_alongside, alongside, raw_castoff, castoff,
                )
            continue

        if castoff <= alongside:
            skipped_bad_order += 1
            if DEBUG_BERTH_OCCUPANCY:
                logger.debug(
                    "  row %d: vessel=%r castoff <= alongside (alongside=%s castoff=%s) - skipped",
                    i, vessel_name, alongside, castoff,
                )
            continue

        hours = (castoff - alongside).total_seconds() / 3600.0
        total_hours += hours
        debug_rows.append({
            "vessel_name": vessel_name,
            "alongside": alongside.isoformat(),
            "castoff": castoff.isoformat(),
            "hours": round(hours, 2),
        })
        if DEBUG_BERTH_OCCUPANCY:
            logger.debug(
                "  row %d: vessel=%r alongside=%s castoff=%s -> %.2f hours (running total=%.2f)",
                i, vessel_name, alongside, castoff, hours, total_hours,
            )

    logger.debug(
        "fetch_berth_hours_from_mis_vessel_master: TOTAL=%.2f hours "
        "(%d rows used, %d unparsed, %d bad-order)",
        total_hours, len(rows) - skipped_unparsed - skipped_bad_order,
        skipped_unparsed, skipped_bad_order,
    )

    return total_hours, debug_rows


def fetch_berth_hours_from_ldud_header(month_abbrev: str, calendar_year: int):
    """Total alongside-hours for the new table, for vessels whose
    alongside date falls in this calendar month/year. Mirrors
    fetch_vessel_count_from_ldud_header's approach: fetch broadly, parse
    dates in Python to survive inconsistent text formats, filter after.

    Returns (total_hours, debug_rows)."""
    month_num = MONTH_NUM[month_abbrev]

    logger.debug(
        "fetch_berth_hours_from_ldud_header: month=%s year=%s month_num=%s "
        "-> using columns alongside=%r castoff=%r",
        month_abbrev, calendar_year, month_num,
        LDUD_ALONGSIDE_COLUMN, LDUD_CASTOFF_COLUMN,
    )

    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute(
            f"""
            SELECT vessel_name,
                   {LDUD_ALONGSIDE_COLUMN} AS alongside_raw,
                   {LDUD_CASTOFF_COLUMN} AS castoff_raw
            FROM ldud_header
            WHERE COALESCE(is_deleted, false) = false
            """
        )
        rows = cur.fetchall()
    except Exception:
        logger.exception(
            "fetch_berth_hours_from_ldud_header: query FAILED "
            "(check LDUD_ALONGSIDE_COLUMN / LDUD_CASTOFF_COLUMN are real "
            "column names on ldud_header)"
        )
        raise
    finally:
        conn.close()

    logger.debug(
        "fetch_berth_hours_from_ldud_header: fetched %d row(s) TOTAL from ldud_header "
        "(before month/year filtering)",
        len(rows),
    )

    total_hours = 0.0
    debug_rows = []
    skipped_unparsed = 0
    skipped_bad_order = 0
    skipped_other_month = 0
    matched_rows = 0

    for i, r in enumerate(rows):
        vessel_name = r.get("vessel_name") if hasattr(r, "get") else r["vessel_name"]
        raw_alongside = r["alongside_raw"]
        raw_castoff = r["castoff_raw"]
        alongside = _parse_text_datetime(raw_alongside)
        castoff = _parse_text_datetime(raw_castoff)

        if not alongside or not castoff:
            skipped_unparsed += 1
            if DEBUG_BERTH_OCCUPANCY:
                logger.debug(
                    "  row %d: UNPARSEABLE vessel=%r alongside_raw=%r -> %r | castoff_raw=%r -> %r (skipped)",
                    i, vessel_name, raw_alongside, alongside, raw_castoff, castoff,
                )
            continue

        if castoff <= alongside:
            skipped_bad_order += 1
            if DEBUG_BERTH_OCCUPANCY:
                logger.debug(
                    "  row %d: vessel=%r castoff <= alongside (alongside=%s castoff=%s) - skipped",
                    i, vessel_name, alongside, castoff,
                )
            continue

        if not (alongside.year == calendar_year and alongside.month == month_num):
            skipped_other_month += 1
            continue

        hours = (castoff - alongside).total_seconds() / 3600.0
        total_hours += hours
        matched_rows += 1
        debug_rows.append({
            "vessel_name": vessel_name,
            "alongside": alongside.isoformat(),
            "castoff": castoff.isoformat(),
            "hours": round(hours, 2),
        })
        if DEBUG_BERTH_OCCUPANCY:
            logger.debug(
                "  row %d: MATCH vessel=%r alongside=%s castoff=%s -> %.2f hours (running total=%.2f)",
                i, vessel_name, alongside, castoff, hours, total_hours,
            )

    logger.debug(
        "fetch_berth_hours_from_ldud_header: TOTAL=%.2f hours for %s %s "
        "(%d rows matched this month, %d unparsed, %d bad-order, %d other-month)",
        total_hours, month_abbrev, calendar_year,
        matched_rows, skipped_unparsed, skipped_bad_order, skipped_other_month,
    )

    return total_hours, debug_rows


def fetch_berth_hours(month_abbrev: str, calendar_year: int):
    """Unified fetch, using the same legacy/new cutover logic as the rest
    of Report-5 (uses_legacy_source / CUTOVER_DATE).

    Returns (total_hours, debug_rows)."""
    if uses_legacy_source(month_abbrev, calendar_year):
        return fetch_berth_hours_from_mis_vessel_master(month_abbrev, calendar_year)
    return fetch_berth_hours_from_ldud_header(month_abbrev, calendar_year)


def compute_berth_occupancy(month_abbrev: str, calendar_year: int):
    """
    Berth Occupancy % = [ Σ(castoff - alongside) in hours ]
                         / (days_in_month * 24)
                         / 2
                         * 100

    Written as separate steps (not combined into one divisor) to match
    the formula exactly as specified: sum first, divide by days*24,
    then divide by 2 (number of berths), then convert to a percentage.

    Includes "debug_rows": the per-vessel rows that were actually
    summed, so the vessels behind a given % can be checked directly.
    """
    month_str_to_idx(month_abbrev)  # validates month_abbrev

    is_legacy = uses_legacy_source(month_abbrev, calendar_year)
    source = "mis_vessel_master" if is_legacy else "ldud_header"

    logger.debug(
        "compute_berth_occupancy: month=%s year=%s -> source=%s (legacy=%s)",
        month_abbrev, calendar_year, source, is_legacy,
    )

    try:
        # Step 1: Σ(castoff - alongside) in hours, across matching rows
        total_hours, debug_rows = fetch_berth_hours(month_abbrev, calendar_year)
    except Exception as e:
        logger.exception(
            "compute_berth_occupancy: fetch_berth_hours raised for %s %s (source=%s)",
            month_abbrev, calendar_year, source,
        )
        return {
            "month": month_abbrev,
            "year": calendar_year,
            "source": source,
            "total_alongside_hours": None,
            "days_in_month": _days_in_month(month_abbrev, calendar_year),
            "num_berths": NUM_BERTHS,
            "occupancy_pct": None,
            "debug_rows": [],
            "error": f"{type(e).__name__}: {e}",
        }

    days = _days_in_month(month_abbrev, calendar_year)

    # Step 2: divide by (days_in_month * 24)
    hours_in_month = days * 24
    step2 = (total_hours / hours_in_month) if hours_in_month else None

    # Step 3: divide by 2 (number of berths)
    step3 = (step2 / NUM_BERTHS) if step2 is not None else None

    # Step 4: convert fraction to a percentage
    occupancy_pct = (step3 * 100) if step3 is not None else None

    result = {
        "month": month_abbrev,
        "year": calendar_year,
        "source": source,
        "total_alongside_hours": round(total_hours, 2),
        "days_in_month": days,
        "hours_in_month": hours_in_month,
        "num_berths": NUM_BERTHS,
        "occupancy_pct": round(occupancy_pct, 2) if occupancy_pct is not None else None,
        "debug_rows": debug_rows,
    }

    logger.debug(
        "compute_berth_occupancy: total_hours=%.2f / hours_in_month=%d = %.6f / "
        "num_berths=%d = %.6f * 100 = occupancy_pct=%s (%d debug_rows)",
        total_hours, hours_in_month, step2 or 0, NUM_BERTHS, step3 or 0,
        result["occupancy_pct"], len(debug_rows),
    )

    return result


# ---------------------------------------------------------------------
# COMMODITYWISE AVERAGE TURN AROUND TIME (BERTHING TO SAILING) & PARCEL SIZE
# ---------------------------------------------------------------------
# Formula (per user):
#   Av. Turn Around (days) = SUM(cast_off - alongside) / vessel_count
#   Av. Parcel size        = SUM(quantity) / vessel_count
# for the vessels of the given commodity in the given month.
#
# Same legacy/new cutover as the rest of the report:
#   Apr..Jun  -> mis_vessel_master (alongside/cast_off/quantity/commodity
#                all on the same row, so this is a single query)
#   Jul..Mar  -> ldud_header (alongside_datetime/cast_off_datetime,
#                commodity, vessel_name) for turnaround + vessel_count,
#                joined to lueu_parcel_log (quantity, commodity) for the
#                quantity total. There's no confirmed shared key between
#                the two new-system tables, so quantity is summed by
#                commodity+month independently and divided by the
#                vessel_count from ldud_header -- same "join by
#                commodity+month, not by row" approach already used for
#                fiscal-year totals elsewhere in this file. Flag if a
#                real join key (e.g. a shared vessel_id or a parcel_log
#                -> ldud_header FK) exists -- that would be more precise
#                than this month-level aggregate approach.
#
# ASSUMPTIONS THAT STILL NEED CONFIRMATION:
#   1. MIS_COMMODITY_COLUMN / LDUD_COMMODITY_COLUMN / PARCEL_LOG_COMMODITY_COLUMN
#      are GUESSES (see constants above).
#   2. "commodity" value match is exact-string (e.g. "Liquid", "Cement")
#      -- case-sensitivity / exact spelling not yet confirmed. Below this
#      is done as TRIM(...) ILIKE %(commodity)s -- case-insensitive,
#      whitespace-tolerant -- rather than a strict "=" match, since a
#      strict match is the more likely cause of silently-empty results
#      if the stored value has different casing/padding than what the
#      frontend sends.
#   3. Turnaround hours -> days via /24 (not, e.g., business days).
#   4. Rows with unparsable or out-of-order (castoff <= alongside) dates
#      are excluded from BOTH the turnaround sum and the vessel_count
#      denominator (a vessel with bad data shouldn't silently drag the
#      average down by counting in the denominator but not the numerator).

def fetch_commodity_turnaround_from_mis(commodity: str, month_abbrev: str, calendar_year: int):
    """Turnaround + vessel_count for one commodity, one month, from
    mis_vessel_master. Av. Parcel Size comes from mis_history (see
    module note above).

    COMMODITY FILTER — CHANGED (30-Jul-2026): mis_vessel_master has no
    column that literally contains the word "Liquid"/"Cement". Checked
    cargo, category, category1, new_cat directly against Jul-25/Jun-26
    data -- all four hold either specific cargo names ("Base Oil", "CPO",
    "Acetic Acid") or Liquid sub-categories ("Other Liquid", "Edible
    Oil", "POL", "Chemical", "Ph.Acid"), never the bare label "Liquid",
    and no Cement rows appeared at all. So instead of a commodity-text
    match, this now filters by berth_no using LIQUID_BERTH_CODES_MIS --
    the same berth-code list already confirmed and used for berth
    occupancy (LB-03/LB-04) -- since that's the actual way "Liquid" is
    identified in this table. This function is therefore only meaningful
    for commodity="Liquid" for now; fetch_commodity_turnaround() already
    short-circuits "Cement" requests to None before this is ever called.

    mis_history.cargo_type, by contrast, DOES literally hold "LIQUID"
    (confirmed via SELECT DISTINCT), so that filter is left as an ILIKE
    commodity match, unchanged.
    """
    yy = str(calendar_year)[-2:]
    month_str = f"{month_abbrev}-{yy}"

    logger.debug(
        "fetch_commodity_turnaround_from_mis: commodity=%r month=%s "
        "-> mis_vessel_master filtered by berth_no IN %s (not by a commodity "
        "column -- see docstring), mis_history filtered by cargo_type ILIKE commodity",
        commodity, month_str, LIQUID_BERTH_CODES_MIS,
    )

    conn = get_db()
    try:
        cur = get_cursor(conn)

        # ---------------- Turnaround + vessel_count (mis_vessel_master) ----------------
        cur.execute(
            f"""
            SELECT
                vessel_name,
                {MIS_ALONGSIDE_COLUMN} AS alongside_raw,
                {MIS_CASTOFF_COLUMN} AS castoff_raw
            FROM mis_vessel_master
            WHERE month = %(month_str)s
              AND {MIS_ALONGSIDE_COLUMN} IS NOT NULL
              AND {MIS_CASTOFF_COLUMN} IS NOT NULL
              AND berth_no = ANY(%(berth_codes)s)
            """,
            {"month_str": month_str, "berth_codes": LIQUID_BERTH_CODES_MIS},
        )
        turnaround_rows = cur.fetchall()

        # ---------------- Av. Parcel Size (mis_history) ----------------
        cur.execute(
            f"""
            SELECT {MIS_HISTORY_QUANTITY_COLUMN} AS quantity
            FROM mis_history
            WHERE TRIM({MIS_HISTORY_MONTH_COLUMN}) = %(month_str)s
              AND TRIM({MIS_HISTORY_COMMODITY_COLUMN}) ILIKE %(commodity)s
              AND {MIS_HISTORY_QUANTITY_COLUMN} IS NOT NULL
            """,
            {"month_str": month_str, "commodity": commodity.strip()},
        )
        parcel_rows = cur.fetchall()
    except Exception:
        logger.exception(
            "fetch_commodity_turnaround_from_mis: query FAILED for commodity=%r "
            "month=%s (check LIQUID_BERTH_CODES_MIS / MIS_HISTORY_* are correct)",
            commodity, month_str,
        )
        raise
    finally:
        conn.close()

    logger.debug(
        "fetch_commodity_turnaround_from_mis: commodity=%r month=%s -> "
        "%d mis_vessel_master row(s), %d mis_history row(s)",
        commodity, month_str, len(turnaround_rows), len(parcel_rows),
    )

    avg_turnaround_days, vessel_count, debug_rows = _sum_turnaround_hours(turnaround_rows)
    avg_turnaround_days = (
        round(avg_turnaround_days / 24.0 / vessel_count, 2)
        if vessel_count else None
    )

    total_parcel_qty = sum(float(r["quantity"] or 0) for r in parcel_rows)
    parcel_count = len(parcel_rows)
    avg_parcel_size = round(total_parcel_qty / parcel_count, 2) if parcel_count else None

    if DEBUG_BERTH_OCCUPANCY:
        logger.debug(
            "fetch_commodity_turnaround_from_mis: commodity=%r month=%s -> "
            "avg_turnaround_days=%s vessel_count=%d avg_parcel_size=%s "
            "(from %d mis_history rows)",
            commodity, month_str, avg_turnaround_days, vessel_count,
            avg_parcel_size, parcel_count,
        )

    return avg_turnaround_days, avg_parcel_size, vessel_count, debug_rows


def fetch_commodity_turnaround_from_new_system(commodity: str, month_abbrev: str, calendar_year: int):
    """Turnaround (+ vessel_count) from ldud_header, parcel size from
    lueu_parcel_log, both filtered by commodity and by calendar
    month/year, joined only at the "same commodity + same month"
    aggregate level (no confirmed shared row key between the two
    tables -- see module note above).

    FIXED vs. the previous version:
      - Turnaround query had no commodity filter at all.
      - Parcel-size query filtered lueu_parcel_log with
        `entry_date::date >= ... AND entry_date::date < ...` in SQL.
        Everywhere else in this file, entry_date is treated as
        untrustworthy free text and parsed in Python with dateutil
        specifically to survive inconsistent formats (see module
        docstring, assumption 2) -- filtering it with a SQL cast risks
        a hard query failure (Postgres raising on a single unparsable
        entry_date value would fail the whole query, not just that
        row). This version fetches broadly and parses/filters in
        Python instead, matching fetch_quantity_from_parcel_log's
        approach.
      - There was no commodity filter on the parcel-size query either.

    ASSUMPTION (per user instruction, 30-Jul-2026): ldud_header and
    lueu_parcel_log are used only for the Liquid berths/commodity, so
    there's no commodity filter applied here -- every row in these two
    tables for the given month/year is treated as Liquid. This was
    confirmed to be necessary because neither table has any commodity
    column (see LDUD_COMMODITY_COLUMN / PARCEL_LOG_COMMODITY_COLUMN
    comments above for the full confirmed column lists), and the one
    candidate column, lueu_parcel_log.medium, was checked and only
    contains handling-method values ('Direct Pipe', 'Equipment'), not
    commodity/cargo type.

    If the new system ever handles a non-Liquid commodity through these
    same tables, this function will need a real commodity source (a
    join to another table, most likely) to stay correct -- right now it
    will attribute ALL rows to whatever commodity is requested, which is
    only safe under the "Liquid-only" assumption above.
    """
    month_num = MONTH_NUM[month_abbrev]

    logger.debug(
        "fetch_commodity_turnaround_from_new_system: commodity=%r (no commodity "
        "filter applied -- see Liquid-only assumption in docstring) month=%s year=%s "
        "using ldud columns alongside=%r castoff=%r",
        commodity, month_abbrev, calendar_year,
        LDUD_ALONGSIDE_COLUMN, LDUD_CASTOFF_COLUMN,
    )

    conn = get_db()
    try:
        cur = get_cursor(conn)

        # ---------------- Turnaround (+ vessel_count) ----------------
        cur.execute(
            f"""
            SELECT
                vessel_name,
                {LDUD_ALONGSIDE_COLUMN} AS alongside_raw,
                {LDUD_CASTOFF_COLUMN} AS castoff_raw
            FROM ldud_header
            WHERE COALESCE(is_deleted, false) = false
            """
        )
        turnaround_rows = cur.fetchall()

        # ---------------- Average Parcel Size ----------------
        # Fetched broadly and filtered/parsed in Python, per module
        # convention for entry_date (free-text, not a trustworthy real
        # date/timestamp column -- see docstring assumption 2).
        cur.execute(
            """
            SELECT entry_date, quantity
            FROM lueu_parcel_log
            WHERE COALESCE(is_deleted, false) = false
              AND quantity IS NOT NULL
            """
        )
        parcel_rows = cur.fetchall()
    except Exception:
        logger.exception(
            "fetch_commodity_turnaround_from_new_system: query FAILED for "
            "commodity=%r month=%s year=%s",
            commodity, month_abbrev, calendar_year,
        )
        raise
    finally:
        conn.close()

    logger.debug(
        "fetch_commodity_turnaround_from_new_system: commodity=%r -> "
        "%d ldud_header row(s), %d lueu_parcel_log row(s) (before month/year filtering)",
        commodity, len(turnaround_rows), len(parcel_rows),
    )

    # --- Turnaround: filter to this calendar month/year by alongside date ---
    matched_turnaround_rows = []
    for r in turnaround_rows:
        alongside = _parse_text_datetime(r["alongside_raw"])
        if alongside and alongside.year == calendar_year and alongside.month == month_num:
            matched_turnaround_rows.append(r)

    avg_turnaround_days, vessel_count, debug_rows = _sum_turnaround_hours(matched_turnaround_rows)
    avg_turnaround_days = (
        round(avg_turnaround_days / 24.0 / vessel_count, 2)
        if vessel_count else None
    )

    # --- Parcel size: filter to this calendar month/year by entry_date ---
    total_qty = 0.0
    parcel_count = 0
    for r in parcel_rows:
        d = _parse_text_date(r["entry_date"])
        if d and d.year == calendar_year and d.month == month_num:
            total_qty += float(r["quantity"] or 0)
            parcel_count += 1

    avg_parcel_size = round(total_qty / parcel_count, 2) if parcel_count else None

    logger.debug(
        "fetch_commodity_turnaround_from_new_system: commodity=%r month=%s year=%s -> "
        "avg_turnaround_days=%s vessel_count=%d avg_parcel_size=%s "
        "(from %d matched parcel rows)",
        commodity, month_abbrev, calendar_year, avg_turnaround_days, vessel_count,
        avg_parcel_size, parcel_count,
    )

    return avg_turnaround_days, avg_parcel_size, vessel_count, debug_rows


def _sum_turnaround_hours(rows):
    """Shared helper: given rows with vessel_name/alongside_raw/castoff_raw,
    return (total_hours, vessel_count, debug_rows). Rows with unparsable
    or out-of-order dates are excluded from both the sum and the count."""
    total_hours = 0.0
    vessel_count = 0
    debug_rows = []

    for r in rows:
        vessel_name = r["vessel_name"]
        alongside = _parse_text_datetime(r["alongside_raw"])
        castoff = _parse_text_datetime(r["castoff_raw"])

        if not alongside or not castoff or castoff <= alongside:
            continue

        hours = (castoff - alongside).total_seconds() / 3600.0
        total_hours += hours
        vessel_count += 1
        debug_rows.append({
            "vessel_name": vessel_name,
            "alongside": alongside.isoformat(),
            "castoff": castoff.isoformat(),
            "hours": round(hours, 2),
        })

    return total_hours, vessel_count, debug_rows


def _summarize_commodity_rows(rows):
    """Shared helper for the mis_vessel_master path: rows carry
    vessel_name/alongside_raw/castoff_raw/quantity together, so
    turnaround, vessel_count, and parcel size can all come from the
    same row set (unlike the new-system path, which has to combine two
    tables). Returns (avg_turnaround_days, avg_parcel_size, vessel_count,
    debug_rows)."""
    total_hours = 0.0
    total_quantity = 0.0
    vessel_count = 0
    debug_rows = []

    for r in rows:
        vessel_name = r["vessel_name"]
        alongside = _parse_text_datetime(r["alongside_raw"])
        castoff = _parse_text_datetime(r["castoff_raw"])

        if not alongside or not castoff or castoff <= alongside:
            continue

        hours = (castoff - alongside).total_seconds() / 3600.0
        qty = float(r["quantity"] or 0)
        total_hours += hours
        total_quantity += qty
        vessel_count += 1
        debug_rows.append({
            "vessel_name": vessel_name,
            "alongside": alongside.isoformat(),
            "castoff": castoff.isoformat(),
            "hours": round(hours, 2),
            "quantity": qty,
        })

    avg_turnaround_days = (total_hours / 24.0 / vessel_count) if vessel_count else None
    avg_parcel_size = (total_quantity / vessel_count) if vessel_count else None

    return (
        round(avg_turnaround_days, 2) if avg_turnaround_days is not None else None,
        round(avg_parcel_size, 2) if avg_parcel_size is not None else None,
        vessel_count,
        debug_rows,
    )


def fetch_commodity_turnaround(commodity: str, month_abbrev: str, calendar_year: int):

    # Don't display anything for Cement
    if commodity.lower() == "cement":
        return {
            "commodity": commodity,
            "month": month_abbrev,
            "year": calendar_year,
            "source": "",
            "avg_turnaround_days": None,
            "avg_parcel_size": None,
            "vessel_count": 0,
            "debug_rows": []
        }

    is_legacy = uses_legacy_source(month_abbrev, calendar_year)
    source = "mis_vessel_master" if is_legacy else "ldud_header+lueu_parcel_log"

    if is_legacy:
        avg_days, avg_parcel, vessel_count, debug_rows = fetch_commodity_turnaround_from_mis(
            commodity, month_abbrev, calendar_year
        )
    else:
        avg_days, avg_parcel, vessel_count, debug_rows = fetch_commodity_turnaround_from_new_system(
            commodity, month_abbrev, calendar_year
        )

    return {
        "commodity": commodity,
        "month": month_abbrev,
        "year": calendar_year,
        "source": source,
        "avg_turnaround_days": avg_days,
        "avg_parcel_size": avg_parcel,
        "vessel_count": vessel_count,
        "debug_rows": debug_rows,
    }


def compute_commodity_turnaround_report(commodity: str, month_abbrev: str, calendar_year: int):
    """Current month/year vs the same month one year earlier -- mirrors
    compute_report()'s current/previous shape."""
    month_str_to_idx(month_abbrev)  # validates month_abbrev

    current = fetch_commodity_turnaround(commodity, month_abbrev, calendar_year)
    previous = fetch_commodity_turnaround(commodity, month_abbrev, calendar_year - 1)

    return {
        "commodity": commodity,
        "month": month_abbrev,
        "year": calendar_year,
        "current": current,
        "previous": previous,
    }


# ---------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------

@bp.route("/module/RP01/report5/")
@login_required
def report5_index():
    return render_template("report5/report5.html")


@bp.route("/api/module/RP01/report5/meta")
@login_required
def report5_meta():
    try:
        today = date.today()
        current_month_abbrev = NUM_TO_MONTH_ABBREV[today.month]

        # Current year is now driven by the latest fin_year present in
        # mis_vessel_master rather than the server's local clock, per
        # user instruction. current_month still comes from today's date -
        # fin_year doesn't imply a specific month.
        fin_year_start = fetch_latest_fin_year_start()
        current_year = calendar_year_for_month(fin_year_start, current_month_abbrev)

        return jsonify({
            "months": [{"abbrev": m, "label": m} for m in MONTH_NAMES],
            "current_month": current_month_abbrev,
            "current_year": current_year,
            "fin_year_start": fin_year_start,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


@bp.route("/api/module/RP01/report5/report")
@login_required
def report5_report():
    try:
        month = request.args.get("month")
        if not month:
            return jsonify({"error": "Missing required parameter: month"}), 400

        year_param = request.args.get("year")
        if year_param:
            try:
                calendar_year = int(year_param)
            except ValueError:
                return jsonify({"error": f"Invalid 'year' parameter: {year_param}"}), 400
        else:
            # No explicit year - default to the current fiscal year as
            # recorded in mis_vessel_master.fin_year, converted to the
            # calendar year that matches the requested month.
            fin_year_start = fetch_latest_fin_year_start()
            calendar_year = calendar_year_for_month(fin_year_start, month)

        fin_year_start = fiscal_year_start_for(month, calendar_year)
        result = compute_fiscal_year_comparison(fin_year_start, month, calendar_year)

        # The frontend (report5.html) only calls this single /report
        # endpoint, not /berth-occupancy separately, so occupancy has to
        # be folded in here or the UI table cell stays blank forever.
        occupancy = compute_berth_occupancy(month, calendar_year)
        result["occupancy_pct"] = occupancy["occupancy_pct"]
        result["occupancy_detail"] = occupancy  # full breakdown, for debugging/export

        # Sanity check: confirm the key we just set is actually the same
        # value about to go out over the wire. If this log ever shows
        # occupancy_pct missing or None while occupancy_detail shows a
        # real number, something overwrote `result` between here and
        # jsonify() - which would point at a bug in this route, not in
        # compute_berth_occupancy.
        logger.debug(
            "report5_report: FINAL response keys=%s | occupancy_pct=%r | occupancy_detail debug_rows=%d",
            sorted(result.keys()), result.get("occupancy_pct"),
            len(occupancy.get("debug_rows", [])),
        )
        print("DEBUG report5 result:", result)  # TEMP — remove once fetch works

        return jsonify(result)

    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


@bp.route("/api/module/RP01/report5/commodity-turnaround")
@login_required
def report5_commodity_turnaround():
    """Backs the 'Commoditywise Average Turn Around Time (Berthing to
    Sailing) & Parcel Size' table: current + previous avg_turnaround_days
    and avg_parcel_size for one commodity (e.g. 'Liquid', 'Cement')."""
    try:
        commodity = request.args.get("commodity")
        if not commodity:
            return jsonify({"error": "Missing required parameter: commodity"}), 400

        month = request.args.get("month")
        if not month:
            return jsonify({"error": "Missing required parameter: month"}), 400

        year_param = request.args.get("year")
        if year_param:
            try:
                calendar_year = int(year_param)
            except ValueError:
                return jsonify({"error": f"Invalid 'year' parameter: {year_param}"}), 400
        else:
            fin_year_start = fetch_latest_fin_year_start()
            calendar_year = calendar_year_for_month(fin_year_start, month)

        result = compute_commodity_turnaround_report(commodity, month, calendar_year)
        return jsonify(result)

    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


@bp.route("/api/module/RP01/report5/berth-occupancy")
@login_required
def report5_berth_occupancy():
    try:
        month = request.args.get("month")
        if not month:
            return jsonify({"error": "Missing required parameter: month"}), 400

        year_param = request.args.get("year")
        if year_param:
            try:
                calendar_year = int(year_param)
            except ValueError:
                return jsonify({"error": f"Invalid 'year' parameter: {year_param}"}), 400
        else:
            fin_year_start = fetch_latest_fin_year_start()
            calendar_year = calendar_year_for_month(fin_year_start, month)

        result = compute_berth_occupancy(month, calendar_year)
        return jsonify(result)

    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500