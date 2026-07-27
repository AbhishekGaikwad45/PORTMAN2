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
======================================================================
"""

import traceback
from datetime import date
from functools import wraps

from dateutil import parser as dateutil_parser

from flask import jsonify, request, render_template, session, redirect, url_for

from database import get_db, get_cursor

from .. import bp


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



    """Raised for any problem loading/validating the report's source data.
    Caught by the route handlers and turned into a clean JSON error response."""
    pass


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
    whole report)."""
    if not raw:
        return None
    try:
        return dateutil_parser.parse(str(raw), dayfirst=True).date()
    except (ValueError, TypeError):
        return None


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

    return round(total,3)

# def fetch_fiscal_year_jjltpl_total(fin_year_start: int) -> float:
#     total = 0.0

#     for month_abbrev in MONTH_NAMES:
#         calendar_year = calendar_year_for_month(fin_year_start, month_abbrev)

#         if uses_legacy_source(month_abbrev, calendar_year):
#             qty = fetch_jjltpl_from_mis(month_abbrev, calendar_year)
#         else:
#             qty = fetch_jjltpl_from_parcel_log(month_abbrev, calendar_year)

#         total += qty

#     return round(total, 3)


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


def compute_fiscal_year_comparison(fin_year_start: int):
    """Current fiscal year vs the prior fiscal year, each summed across
    its own 12 months (mis + lueu combined per month, per year)."""
    current_jjltpl = fetch_fiscal_year_quantity_total(fin_year_start)
    previous_jjltpl = fetch_fiscal_year_quantity_total(fin_year_start - 1)

    result = compute_report(month, calendar_year)

    result["current_jjltpl"] = current_jjltpl
    result["previous_jjltpl"] = previous_jjltpl

    return jsonify(result)

    increase_pct = (
        ((current_total - previous_total) / previous_total * 100)
        if previous_total else None
    )

    return {
        "fin_year_start": fin_year_start,
        "fin_year_label": f"{fin_year_start}-{str(fin_year_start + 1)[-2:]}",
        "prev_fin_year_label": f"{fin_year_start - 1}-{str(fin_year_start)[-2:]}",
        "current_total": current_total,
        "previous_total": previous_total,
        "increase_pct": round(increase_pct, 2) if increase_pct is not None else None,
    }


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

        result = compute_report(month, calendar_year)
        print("DEBUG report5 result:", result)  # TEMP — remove once fetch works
        fin_year_start = fiscal_year_start_for(month, calendar_year)

        result["current_jjltpl"] = fetch_fiscal_year_quantity_total(fin_year_start)
        result["previous_jjltpl"] = fetch_fiscal_year_quantity_total(fin_year_start - 1)
        return jsonify(result)

    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500