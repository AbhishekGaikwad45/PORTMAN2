"""
Report-13 : Vessel Movement Report  (module RP01)
File location: modules/RP01/RP01/report13/report13.py
Template location: modules/RP01/RP01/report13.html

Rebuilt against the confirmed real schema (information_schema dump +
sample data check on 2026-07-22):

    - mis_vessel_master : fin_year (text) + month (text, e.g. "April") --
      NOT month_idx. Legacy rows are filtered by matching the month name.
    - ldud_header.vcn_id (int)          -> vcn_header.id            (FK)
    - vcn_header.vessel_master_doc(text)-> vessels.doc_num (text)   (FK)
    - ldud_parcel_ops.ldud_id (int)     -> ldud_header.id            (FK)
    - vessel_cargo is a static cargo-taxonomy lookup table with NO link
      to a specific voyage -- dropped from the join entirely. Real
      per-voyage cargo name comes from ldud_parcel_ops.cargo_name.
    - vcn_header.cargo_type and ldud_parcel_ops.terminal_name are real
      columns -- no longer hardcoded post-cutover.
    - vessels.imo_num (NOT imo_no).
    - Every date/time column in the new schema is stored as `text` in
      plain ISO format ("2026-07-06"), confirmed via live sample data.
      Cast with `NULLIF(col, '')::date` to handle blank strings safely.
    - Post-cutover operational columns (anchored_datetime, pilot times,
      discharge times, cast-off) are all still blank in current data --
      that's expected for a system that just cut over, not a bug in
      this code. Report-13 will just show blank cells for those until
      real operational data is entered.

ASSUMPTIONS still open (not yet confirmed):
    1. mis_vessel_master.month values are assumed to literally match
       MONTH_LABELS strings below ("April", "May", ...). If your data
       uses abbreviations or numbers instead, the legacy WHERE clause
       needs adjusting -- run:
           SELECT DISTINCT month FROM mis_vessel_master;
       to confirm.
    2. get_db()/get_cursor(conn) convention (dict-like fetchall results,
       manual cur.close()) -- taken from report4.py's import line, not
       yet verified against report4's actual query-running code.
"""

from datetime import date
from io import BytesIO

from flask import jsonify, request, send_file, render_template

from database import get_db, get_cursor

# Shared blueprint, defined in modules/RP01/RP01/__init__.py.
from .. import bp



CUTOFF_CALENDAR = date(2026, 7, 1)

MONTH_LABELS = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March",
]



class ReportDataError(Exception):
    """Raised for any data-layer problem while building Report-13."""
    pass


def _month_idx_to_date(fin_year: str, month_idx: int) -> date:
    """(fin_year, month_idx) -> calendar date (1st of month). month_idx 0 = April."""
    start_year = int(fin_year.split("-")[0])
    if month_idx <= 8:  # Apr(0)..Dec(8)
        return date(start_year, 4 + month_idx, 1)
    return date(start_year + 1, month_idx - 8, 1)  # Jan(9)..Mar(11)


def _date_to_fin_year_month_idx(d: date) -> tuple[str, int]:
    """Calendar date -> (financial year, month index)."""

    if d.month >= 4:
        fin_year = f"{d.year}-{str(d.year + 1)[-2:]}"
        month_idx = d.month - 4
    else:
        fin_year = f"{d.year - 1}-{str(d.year)[-2:]}"
        month_idx = d.month + 8

    return fin_year, month_idx


def _period_bounds(fin_year: str, month_idx: int) -> tuple[date, date]:
    """Calendar [start, end) for the given fin_year/month_idx, end exclusive."""
    start = _month_idx_to_date(fin_year, month_idx)
    end = _month_idx_to_date(fin_year, month_idx + 1) if month_idx < 11 else date(start.year + 1, 4, 1)
    return start, end


def _uses_legacy_schema(fin_year: str, month_idx: int) -> bool:
    return _month_idx_to_date(fin_year, month_idx) < CUTOFF_CALENDAR


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------
@bp.route("/module/RP01/report13/")
def report13_page():
    return render_template("report13.html", port_name="JAWAHARLAL NEHRU PORT / JJLTPL")


# ---------------------------------------------------------------------------
# Meta endpoint -- available years / months, combining both eras
# ---------------------------------------------------------------------------
@bp.route("/api/module/RP01/report13/meta", methods=["GET"])
def report13_meta():
    conn = get_db()
    cur = get_cursor(conn)
    try:
        # Legacy years/months: real columns on mis_vessel_master.
        cur.execute("SELECT DISTINCT fin_year, month FROM mis_vessel_master")
        legacy_rows = cur.fetchall()

        # Post-cutover years/months: derived from ldud_header.created_date,
        # since the new schema has no fin_year/month columns at all.
        cur.execute("""
            SELECT DISTINCT NULLIF(created_date, '')::date AS d
            FROM ldud_header
            WHERE NULLIF(created_date, '') IS NOT NULL
        """)
        new_rows = cur.fetchall()

        month_lookup = {
            "apr": 0,
            "may": 1,
            "jun": 2,
            "jul": 3,
            "aug": 4,
            "sep": 5,
            "oct": 6,
            "nov": 7,
            "dec": 8,
            "jan": 9,
            "feb": 10,
            "mar": 11,
        }

        year_month_idx: dict[str, set[int]] = {}

        # Legacy months (before July 2026)
        for r in legacy_rows:
            fy = r["fin_year"]
            m = (r["month"] or "").strip()[:3].lower()
            idx = month_lookup.get(m)

            if fy and idx is not None:
                year_month_idx.setdefault(fy, set()).add(idx)

        # New schema months (July 2026 onwards)
        for r in new_rows:
            d = r["d"]
            if d is None:
                continue

            fy, idx = _date_to_fin_year_month_idx(d)
            year_month_idx.setdefault(fy, set()).add(idx)

        print("year_month_idx =", year_month_idx)
        years = sorted(year_month_idx.keys())
        months = {
            y: [{"idx": i, "label": MONTH_LABELS[i]} for i in sorted(year_month_idx[y])]
            for y in years
        }
        return jsonify({"years": years, "months": months})
    except Exception as exc:
        return jsonify({"error": f"Failed to load year/month options: {exc}"}), 500
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Report endpoint
# ---------------------------------------------------------------------------
@bp.route("/api/module/RP01/report13/report", methods=["GET"])
def report13_report():
    fin_year = request.args.get("fin_year")
    month_idx = request.args.get("month_idx", type=int)

    if not fin_year or month_idx is None:
        return jsonify({"error": "fin_year and month_idx are required"}), 400

    try:
        print("fin_year =", fin_year)
        print("month_idx =", month_idx)
        print("Uses legacy =", _uses_legacy_schema(fin_year, month_idx))
        if _uses_legacy_schema(fin_year, month_idx):
            rows = _fetch_legacy(fin_year, month_idx)
        else:
            rows = _fetch_new_schema(fin_year, month_idx)

        return jsonify({
            "month_label": f"{MONTH_LABELS[month_idx]} {fin_year}",
            "rows": rows,
        })
    except ReportDataError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        return jsonify({"error": f"Failed to load report: {exc}"}), 500


def _fetch_legacy(fin_year: str, month_idx: int) -> list[dict]:
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute("""
            SELECT
                fin_year                    AS month,
                NULL                        AS via_no,
                imo_no,
                vessel_name,
                agent,
                grt,
                loa,
                category                    AS cargo_type,
                cargo,
                unloading_terminal          AS terminal,
                berth_no                    AS berth,
                anchorage_time              AS anchored_time,
                pilot_pickup                AS pilot_boarded,
                alongside                   AS alongside_time,
                ops_commenced               AS cargo_commenced,
                cargo_completion            AS cargo_completed,
                cast_off                    AS cast_off_time,
                pilot_board_departure       AS pilot_disembarked,
                quantity
            FROM mis_vessel_master
            WHERE fin_year = %(fin_year)s
            AND LEFT(LOWER(month), 3) = LEFT(LOWER(%(month_label)s), 3)
            ORDER BY anchorage_time
        """, {"fin_year": fin_year, "month_label": MONTH_LABELS[month_idx]})
        rows = cur.fetchall()
        if rows is None:
            raise ReportDataError("No legacy vessel data returned.")
        return [dict(r) for r in rows]
    finally:
        cur.close()


def _fetch_new_schema(fin_year: str, month_idx: int) -> list[dict]:
    period_start, period_end = _period_bounds(fin_year, month_idx)
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute("""
            SELECT
                lh.created_date                                  AS month,
                vh.via_number                                    AS via_no,
                v.imo_num                                        AS imo_no,
                lh.vessel_name                                   AS vessel_name,
                vh.vessel_agent_name                              AS agent,
                v.gt                                              AS grt,
                v.loa                                             AS loa,
                vh.cargo_type                                     AS cargo_type,
                po.cargo_name                                     AS cargo,
                po.terminal_name                                  AS terminal,
                vh.berth_name                                     AS berth,
                lh.anchored_datetime                              AS anchored_time,
                lh.pilot_pickup_time                              AS pilot_boarded,
                lh.alongside_datetime                             AS alongside_time,
                lh.discharge_commenced                            AS cargo_commenced,
                lh.discharge_completed                            AS cargo_completed,
                lh.cast_off_datetime                              AS cast_off_time,
                lh.pilot_disembarked                              AS pilot_disembarked,
                po.quantity                                       AS quantity
            FROM ldud_header lh
            LEFT JOIN vcn_header vh    ON vh.id = lh.vcn_id
            LEFT JOIN vessels v        ON v.doc_num = vh.vessel_master_doc
            LEFT JOIN ldud_parcel_ops po ON po.ldud_id = lh.id
            WHERE NULLIF(lh.created_date, '') IS NOT NULL
              AND NULLIF(lh.created_date, '')::date >= %(period_start)s
              AND NULLIF(lh.created_date, '')::date <  %(period_end)s
            ORDER BY lh.created_date
        """, {"period_start": period_start, "period_end": period_end})
        rows = cur.fetchall()
        if rows is None:
            raise ReportDataError("No post-cutover vessel data returned.")
        return [dict(r) for r in rows]
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------
@bp.route("/api/module/RP01/report13/export", methods=["GET"])
def report13_export():
    fin_year = request.args.get("fin_year")
    month_idx = request.args.get("month_idx", type=int)

    if not fin_year or month_idx is None:
        return jsonify({"error": "fin_year and month_idx are required"}), 400

    try:
        rows = (_fetch_legacy(fin_year, month_idx)
                if _uses_legacy_schema(fin_year, month_idx)
                else _fetch_new_schema(fin_year, month_idx))
    except ReportDataError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        return jsonify({"error": f"Failed to build export: {exc}"}), 500

    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Report-13"

    headers = [
        "Month", "VIA No.", "IMO Number", "Vessel Name", "Agent", "GRT", "LOA",
        "Cargo Type", "Cargo", "Terminal", "Berth", "Anchored Time",
        "Pilot Boarded", "Alongside Time", "Cargo Commenced", "Cargo Completed",
        "Cast Off Time", "Pilot Disembarked", "Quantity (Tonnes)",
    ]
    header_fill = PatternFill("solid", fgColor="F6F8FA")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(name="Arial", bold=True, size=11)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    field_order = [
        "month", "via_no", "imo_no", "vessel_name", "agent", "grt", "loa",
        "cargo_type", "cargo", "terminal", "berth", "anchored_time",
        "pilot_boarded", "alongside_time", "cargo_commenced", "cargo_completed",
        "cast_off_time", "pilot_disembarked", "quantity",
    ]
    for row in rows:
        ws.append([row.get(f) for f in field_order])

    for col_cells in ws.columns:
        length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 30)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"Report13_VesselMovement_{fin_year}_{MONTH_LABELS[month_idx]}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )