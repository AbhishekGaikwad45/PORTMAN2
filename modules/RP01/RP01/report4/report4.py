"""
Report-4 — Commodity-wise Import Cargo Despatched by Different Modes of Transport
              + Commodity-wise Export Cargo Received by Different Modes of Transport
Flask Blueprint version.

DATA FLOW (per your latest instructions):
  1. Query vcn_header to get the set of vessel_names whose operation_type
     is "Import", and separately the set whose operation_type is "Export".
  2. For each such vessel, sum its mis_vessel_master.quantity for the
     selected fin_year/month (with cast_off populated), grouped by
     commodity bucket. This is the PRIMARY source.
  3. FALLBACK (NEW): for any vessel in the Import/Export set that has NO
     rows in mis_vessel_master for that fin_year/month, look it up via:
         ldud_header (vessel_name, cast_off_datetime)
           -> ldud_parcel_ops (ldud_id, cargo_name)
             -> lueu_parcel_log (parcel_op_id, quantity, is_deleted)
     and sum lueu_parcel_log.quantity (excluding is_deleted rows) for that
     vessel/period, grouped into the same commodity buckets via
     ldud_parcel_ops.cargo_name.
  4. A vessel found via the "Import" set contributes to the DESPATCHED
     (Import) table's Pipe Line figure; a vessel found via the "Export"
     set contributes to the RECEIVED (Export) table's Pipe Line figure.
     Pipe Line for a bucket = month_total(bucket) - matched_vessel_qty(bucket),
     where matched_vessel_qty combines the mis_vessel_master sum plus the
     fallback lueu_parcel_log sum (for vessels missing from
     mis_vessel_master only — never both, to avoid double-counting).

ASSUMPTIONS MADE (please confirm / correct these):
  1. Rail / Road / Inland-Water-Transport-or-Coastal-Movement figures have
     no data source identified yet, so they are hardcoded to 0 for every
     commodity (matches the sample screenshot, where these are all 0.00).
  2. vcn_header.operation_type values are matched case-insensitively against
     "import" / "export" (so "Import", "IMPORT", "import " etc. all match).
  3. Vessel-name matching across mis_vessel_master / ldud_header / vcn_header
     is done case-insensitively with whitespace trimmed.
  4. mis_vessel_master.category currently only contains liquid-type values
     (POL, POL Black, Other Liquid, Edible Oil, Chemical, Ph.Acid) — all
     mapped into the single "Liquid" bucket. "Cement" / "Break Bulk" /
     "Containers" category values are mapped too, in case they appear in
     the data later, but as of now there's no data for those buckets.
  5. FALLBACK-SPECIFIC: ldud_header has no fin_year/month columns, so its
     `cast_off_datetime` (text) is parsed into a real date and converted
     to fin_year/fy_month_idx the same way mis_vessel_master's fin_year/
     month work (Apr start of financial year).
  6. FALLBACK-SPECIFIC: ldud_parcel_ops.cargo_name is mapped to the same
     Liquid/Cement/Break-Bulk buckets using the SAME CATEGORY_MAP guesses
     used for mis_vessel_master.category. I don't actually know
     cargo_name's real distinct values — if this mapping is wrong, tell me
     the real values and I'll correct CATEGORY_MAP (or add a separate map
     for cargo_name specifically).
  7. FALLBACK-SPECIFIC: lueu_parcel_log rows where is_deleted is true are
     excluded from the sum. Rows with is_shortclose = true are currently
     still INCLUDED — flag if those should be excluded too.
  8. Sr. No. values (2, 3, 4) are kept exactly as shown in your screenshot.
  9. The Export table is titled "COMMODITY-WISE EXPORT CARGO RECEIVED BY
     DIFFERENT MODES OF TRANSPORT" with "Received by ..." column headers.
  10. The JSON API returns the Export table under new keys
      (export_rows / export_grand / export_total) alongside the existing
      top-level keys (rows / grand / import_total).
"""

import io
import traceback
from functools import wraps

import pandas as pd

from flask import jsonify, request, render_template, send_file, session, redirect, url_for
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

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

# Commodity buckets shown in report4, in display order, with the Sr. No.
# exactly as shown in your screenshot.
CATEGORY_ORDER = [
    {"sr": 2, "key": "DRY BULK (CEMENT)"},
    {"sr": 3, "key": "Liquid"},
    {"sr": 4, "key": "Break Bulk / Containers"},
]

# mis_vessel_master.category (and, as a fallback guess, ldud_parcel_ops.cargo_name)
# -> report4 bucket. Only the "Liquid" entries have confirmed data today (per
# `SELECT DISTINCT category FROM mis_vessel_master`). Cement / Break Bulk /
# Containers mappings are included pre-emptively — update the left-hand
# values if your actual category/cargo_name text differs from these guesses.
CATEGORY_MAP = {
    # Liquid
    "POL": "Liquid",
    "POL Black": "Liquid",
    "Other Liquid": "Liquid",
    "Edible Oil": "Liquid",
    "Chemical": "Liquid",
    "Ph.Acid": "Liquid",

    # Add these two
    "ACETONE": "Liquid",
    "FURNACE OIL": "Liquid",

    # Dry Bulk
    "Cement": "DRY BULK (CEMENT)",

    # Break Bulk
    "Break Bulk": "Break Bulk / Containers",
    "Containers": "Break Bulk / Containers",
    "General Cargo": "Break Bulk / Containers",
}


class ReportDataError(Exception):
    """Raised for any problem loading/validating the report's source data.
    Caught by the route handlers and turned into a clean JSON error response."""
    pass


def fy_start_year(fin_year: str) -> int:
    return int(fin_year.split("-")[0])


def month_options_for(fin_year: str):
    start_y = fy_start_year(fin_year)
    opts = []
    for idx, mn in enumerate(MONTH_NAMES):
        yy = start_y if idx < 9 else start_y + 1
        opts.append({"idx": idx, "label": f"{mn}-{str(yy % 100).zfill(2)}"})
    return opts


def month_str_to_idx(month_str: str) -> int:
    """'Apr-26' -> 0, 'Dec-24' -> 8, etc. Matches MONTH_NAMES order (FY Apr..Mar)."""
    abbrev = str(month_str).split("-")[0].strip()
    try:
        return MONTH_NAMES.index(abbrev)
    except ValueError:
        raise ReportDataError(
            f"Unrecognized value in mis_vessel_master.month: '{month_str}' "
            f"(expected something like 'Apr-26')"
        )


def idx_to_month_label(fin_year: str, month_idx: int) -> str:
    """Reverse of month_str_to_idx — builds e.g. 'Jun-26' for a given fin_year/idx.
    Assumes mis_vessel_master.month is stored in this exact 'Mon-YY' format."""
    opts = month_options_for(fin_year)
    match = next((o for o in opts if o["idx"] == month_idx), None)
    if not match:
        raise ReportDataError(f"Invalid month_idx {month_idx} for fin_year {fin_year}")
    return match["label"]


def calendar_date_to_fy(dt: pd.Timestamp):
    """Converts a real calendar date into (fin_year_str, fy_month_idx),
    using an Apr-start financial year — same convention as
    mis_vessel_master.fin_year/month. Returns (None, None) if dt is NaT."""
    if pd.isna(dt):
        return None, None
    y, m = dt.year, dt.month
    if m >= 4:
        fin_year = f"{y}-{str((y + 1) % 100).zfill(2)}"
        fy_month_idx = m - 4
    else:
        fin_year = f"{y - 1}-{str(y % 100).zfill(2)}"
        fy_month_idx = m + 8
    return fin_year, fy_month_idx


def _normalize_name(val) -> str:
    """Trims and casefolds a vessel_name for cross-table matching."""
    return str(val).strip().casefold()


def load_data() -> pd.DataFrame:
    """Loads mis_vessel_master rows with cast_off present."""

    conn = get_db()

    try:
        cur = get_cursor(conn)

        cur.execute("""
            SELECT
                fin_year,
                month,
                category,
                quantity,
                vessel_name
            FROM mis_vessel_master
            WHERE fin_year IS NOT NULL
              AND month IS NOT NULL
              AND NULLIF(TRIM(cast_off), '') IS NOT NULL
        """)

        rows = cur.fetchall()

    finally:
        conn.close()

    if not rows:
        raise ReportDataError("No rows found in mis_vessel_master.")

    df = pd.DataFrame(rows)

    df["fin_year"] = df["fin_year"].astype(str).str.strip()
    df["month"] = df["month"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip()
    df["vessel_name"] = df["vessel_name"].astype(str).str.strip()

    df["quantity"] = (
        pd.to_numeric(df["quantity"], errors="coerce")
        .fillna(0.0)
    )

    df["fy_month_idx"] = df["month"].apply(month_str_to_idx)

    df["bucket"] = df["category"].map(CATEGORY_MAP)

    df = df.dropna(subset=["bucket"])

    df["vessel_name_norm"] = df["vessel_name"].apply(_normalize_name)

    df["quantity_000t"] = df["quantity"] / 1000.0

    print("=" * 80)
    print("MIS DATA")
    print(df[[
        "fin_year",
        "month",
        "bucket",
        "vessel_name",
        "quantity_000t"
    ]])
    print("=" * 80)

    return df[[
        "fin_year",
        "fy_month_idx",
        "bucket",
        "quantity_000t",
        "vessel_name_norm"
    ]]


def load_fallback_data() -> pd.DataFrame:

    conn = get_db()

    try:
        cur = get_cursor(conn)

        cur.execute("""
            SELECT
                lh.vessel_name,
                lpo.cargo_name,
                SUM(COALESCE(lpo.quantity,0)) AS quantity
            FROM ldud_header lh
            JOIN ldud_parcel_ops lpo
                ON lpo.ldud_id = lh.id
            WHERE lh.vessel_name IS NOT NULL
            GROUP BY
                lh.vessel_name,
                lpo.cargo_name
        """)

        rows = cur.fetchall()

    finally:
        conn.close()

    if not rows:
        return pd.DataFrame(columns=[
            "bucket",
            "quantity_000t",
            "vessel_name_norm"
        ])

    df = pd.DataFrame(rows)

    df["quantity"] = pd.to_numeric(
        df["quantity"],
        errors="coerce"
    ).fillna(0)

    df["cargo_name"] = df["cargo_name"].str.strip()

    df["vessel_name_norm"] = df["vessel_name"].apply(_normalize_name)

    df["bucket"] = df["cargo_name"].map(CATEGORY_MAP)

    df = df.dropna(subset=["bucket"])

    df["quantity_000t"] = df["quantity"] / 1000.0

    print("=" * 80)
    print(df)
    print("=" * 80)

    return df[[
        "bucket",
        "quantity_000t",
        "vessel_name_norm"
    ]]

def _get_df_and_years():
    df = load_data()
    years = sorted(df["fin_year"].unique().tolist())
    return df, years


def get_operation_vessel_names(operation_type: str) -> set:
    """Returns the set of (normalized) vessel_names in vcn_header whose
    operation_type matches 'import' or 'export' (case-insensitive)."""
    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute("""
    SELECT DISTINCT vessel_name
    FROM vcn_header
    WHERE vessel_name IS NOT NULL
      AND LOWER(TRIM(operation_type)) = %s
""", (operation_type.lower(),))
        rows = cur.fetchall()
    finally:
        conn.close()

    return {_normalize_name(r["vessel_name"]) for r in rows if r.get("vessel_name")}


def compute_report4(df: pd.DataFrame, fallback_df: pd.DataFrame, fin_year: str,
                    month_idx: int, op_vessel_names: set,
                    total_key: str = "import_total"):

    subset = df[
        (df["fin_year"] == fin_year) &
        (df["fy_month_idx"] == month_idx)
    ]

    # Overall monthly commodity totals
    month_sums = subset.groupby("bucket")["quantity_000t"].sum().to_dict()

    # ---------------- PRIMARY SOURCE ----------------
    op_subset = subset[
        subset["vessel_name_norm"].isin(op_vessel_names)
    ]

    op_sums = (
        op_subset.groupby("bucket")["quantity_000t"]
        .sum()
        .to_dict()
    )

    # ------------------------------------------------
    # Fallback for vessels missing in mis_vessel_master
    # ------------------------------------------------
    vessels_found_in_ms = set(op_subset["vessel_name_norm"].unique())

    missing_vessels = op_vessel_names - vessels_found_in_ms

    fallback_sums = {}

    if missing_vessels and not fallback_df.empty:

        fb_subset = fallback_df[
            fallback_df["vessel_name_norm"].isin(missing_vessels)
        ]

        fallback_sums = (
            fb_subset
            .groupby("bucket")["quantity_000t"]
            .sum()
            .to_dict()
        )

    # ------------------------------------------------
    # Combine MIS + LDUD quantities
    # ------------------------------------------------
    month_totals = {
        c["key"]: month_sums.get(c["key"], 0.0)
        for c in CATEGORY_ORDER
    }

    op_totals = {}

    for c in CATEGORY_ORDER:
        bucket = c["key"]

        op_totals[bucket] = (
            op_sums.get(bucket, 0.0)
            + fallback_sums.get(bucket, 0.0)
        )

        print("=" * 80)
        print(total_key)
        print("Operation vessels :", op_vessel_names)
        print("Found in MIS      :", vessels_found_in_ms)
        print("Missing vessels   :", missing_vessels)
        print("MIS sums          :", op_sums)
        print("Fallback sums     :", fallback_sums)
        print("Month totals      :", month_totals)
        print("=" * 80)

    rail = {c["key"]: 0.0 for c in CATEGORY_ORDER}
    road = {c["key"]: 0.0 for c in CATEGORY_ORDER}
    inland = {c["key"]: 0.0 for c in CATEGORY_ORDER}

    pipeline = {}

    for c in CATEGORY_ORDER:
        bucket = c["key"]
        pipeline[bucket] = max(
            0.0,
            month_totals[bucket] - op_totals[bucket]
        )

    total_col = {}

    for c in CATEGORY_ORDER:
        bucket = c["key"]

        total_col[bucket] = (
            rail[bucket]
            + road[bucket]
            + inland[bucket]
            + pipeline[bucket]
        )

    grand = {
        "rail": sum(rail.values()),
        "road": sum(road.values()),
        "inland": sum(inland.values()),
        "pipeline": sum(pipeline.values()),
        "total": sum(total_col.values()),
    }

    def pct(val, g):
        return round(val / g * 100.0, 2) if g else 0.0

    rows = []

    for c in CATEGORY_ORDER:
        bucket = c["key"]

        rows.append({
            "sr": c["sr"],
            "label": bucket,
            "rail": round(rail[bucket], 3),
            "rail_pct": pct(rail[bucket], grand["rail"]),
            "road": round(road[bucket], 3),
            "road_pct": pct(road[bucket], grand["road"]),
            "inland": round(inland[bucket], 3),
            "inland_pct": pct(inland[bucket], grand["inland"]),
            "pipeline": round(pipeline[bucket], 3),
            "pipeline_pct": pct(pipeline[bucket], grand["pipeline"]),
            "total": round(total_col[bucket], 3),
            "total_pct": pct(total_col[bucket], grand["total"]),
        })

    return {
        "rows": rows,
        "grand": {
            "rail": round(grand["rail"], 3),
            "road": round(grand["road"], 3),
            "inland": round(grand["inland"], 3),
            "pipeline": round(grand["pipeline"], 3),
            "total": round(grand["total"], 3),
        },
        total_key: round(sum(op_totals.values()), 3),
    }

    def pct(val, g):
        return round(val / g * 100.0, 2) if g else 0.0

    rows = []
    for c in CATEGORY_ORDER:
        key = c["key"]
        rows.append({
            "sr": c["sr"],
            "label": key,
            "rail": round(rail[key], 3),
            "rail_pct": pct(rail[key], grand["rail"]),
            "road": round(road[key], 3),
            "road_pct": pct(road[key], grand["road"]),
            "inland": round(inland[key], 3),
            "inland_pct": pct(inland[key], grand["inland"]),
            "pipeline": round(pipeline[key], 3),
            "pipeline_pct": pct(pipeline[key], grand["pipeline"]),
            "total": round(total_col[key], 3),
            "total_pct": pct(total_col[key], grand["total"]),
        })

    return {
        "rows": rows,
        "grand": {
            "rail": round(grand["rail"], 3),
            "road": round(grand["road"], 3),
            "inland": round(grand["inland"], 3),
            "pipeline": round(grand["pipeline"], 3),
            "total": round(grand["total"], 3),
        },
        total_key: round(sum(op_totals.values()), 3),
    }


@bp.route("/module/RP01/report4/")
@login_required
def report4_index():
    return render_template("report4/report4.html", port_name="Jawahalal Nehru Port Authority")


@bp.route("/api/module/RP01/report4/meta")
@login_required
def report4_api_meta():
    try:
        _, years = _get_df_and_years()
        months = {fy: month_options_for(fy) for fy in years}
        return jsonify({"years": years, "months": months})
    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


@bp.route("/api/module/RP01/report4/report")
@login_required
def report4_api_report():
    try:
        df, years = _get_df_and_years()
        fin_year = request.args.get("fin_year", years[-1])
        month_idx = int(request.args.get("month_idx", 2))
        if fin_year not in years:
            return jsonify({"error": f"Unknown fin_year '{fin_year}'. Available: {', '.join(years)}"}), 400

        fallback_df = load_fallback_data()

        import_vessels = get_operation_vessel_names("import")
        export_vessels = get_operation_vessel_names("export")

        import_result = compute_report4(df, fallback_df, fin_year, month_idx, import_vessels, total_key="import_total")
        export_result = compute_report4(df, fallback_df, fin_year, month_idx, export_vessels, total_key="export_total")

        month_label = idx_to_month_label(fin_year, month_idx)

        return jsonify({
            "fin_year": fin_year,
            "month_label": month_label,
            # ---- Table 1: existing Import (Despatched) table ----
            "rows": import_result["rows"],
            "grand": import_result["grand"],
            "import_total": import_result["import_total"],
            # ---- Table 2: Export (Received) table ----
            "export_rows": export_result["rows"],
            "export_grand": export_result["grand"],
            "export_total": export_result["export_total"],
        })
    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


def _write_report_table(ws, start_row: int, title_line: str, verb: str,
                         month_label: str, result: dict, styles: dict) -> int:
    """Writes one full table (title + terminal/month line + header rows +
    data rows + total row) starting at `start_row`. `verb` is either
    "Despatched" or "Received" and is used to build the column group
    labels. Returns the next free row after this table."""

    bold = styles["bold"]
    title_font = styles["title_font"]
    header_font = styles["header_font"]
    red_font = styles["red_font"]
    center = styles["center"]
    left = styles["left"]
    right = styles["right"]
    thin_border = styles["thin_border"]
    yellow_fill = styles["yellow_fill"]

    row = start_row

    ws.merge_cells(f"C{row}:M{row}")
    ws[f"C{row}"] = "Jawahalal Nehru Port Authority"
    ws[f"C{row}"].font = title_font
    ws[f"C{row}"].alignment = center
    row += 1

    ws.merge_cells(f"C{row}:M{row}")
    ws[f"C{row}"] = title_line
    ws[f"C{row}"].font = title_font
    ws[f"C{row}"].alignment = center
    row += 2  # blank row like the original layout

    ws[f"B{row}"] = "Terminal:"
    ws[f"B{row}"].font = bold
    ws[f"C{row}"] = "Bulk Terminal"
    ws[f"C{row}"].font = bold

    ws[f"F{row}"] = "Month"
    ws[f"F{row}"].font = bold
    ws[f"G{row}"] = month_label
    ws[f"G{row}"].font = bold
    ws[f"G{row}"].alignment = center

    ws[f"L{row}"] = "( In Tonnes )"
    ws[f"L{row}"].font = bold
    ws[f"L{row}"].alignment = right
    row += 2  # blank row before header

    header_row1 = row
    header_row2 = row + 1
    ws.merge_cells(f"B{header_row1}:B{header_row2}")
    ws[f"B{header_row1}"] = "Sr.\nNo."
    ws.merge_cells(f"C{header_row1}:C{header_row2}")
    ws[f"C{header_row1}"] = "Commodities"

    group_headers = [
        ("D", "E", f"{verb} by Rail"),
        ("F", "G", f"{verb} by Road"),
        ("H", "I", f"{verb} by Inland water\nTransport or\nby Coastal Movement"),
        ("J", "K", f"{verb} through Pipe Line"),
        ("L", "M", "Total"),
    ]
    for gstart, gend, label in group_headers:
        ws.merge_cells(f"{gstart}{header_row1}:{gend}{header_row1}")
        ws[f"{gstart}{header_row1}"] = label
        for col in (gstart, gend):
            ws[f"{col}{header_row2}"] = "Tonnes" if col == gstart else "Percentage"

    for hrow in (header_row1, header_row2):
        for col in ("B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"):
            cell = ws[f"{col}{hrow}"]
            cell.font = header_font
            cell.alignment = center
            cell.border = thin_border

    ws.row_dimensions[header_row1].height = 45

    row_i = header_row2 + 1
    for r in result["rows"]:
        values = {
            "B": r["sr"],
            "C": r["label"],
            "D": r["rail"], "E": r["rail_pct"] / 100.0,
            "F": r["road"], "G": r["road_pct"] / 100.0,
            "H": r["inland"], "I": r["inland_pct"] / 100.0,
            "J": r["pipeline"], "K": r["pipeline_pct"] / 100.0,
            "L": r["total"], "M": r["total_pct"] / 100.0,
        }
        for col, val in values.items():
            cell = ws[f"{col}{row_i}"]
            cell.value = val
            cell.border = thin_border
            if col in ("E", "G", "I", "K", "M"):
                cell.number_format = "0.00%"
                cell.alignment = center
            elif col in ("D", "F", "H", "J", "L"):
                cell.number_format = "0.000"
                cell.alignment = right
            elif col == "B":
                cell.alignment = center
                cell.font = red_font
            else:
                cell.alignment = left
                cell.font = red_font

        if r["label"] == "Liquid":
            for col in ("J", "K"):
                ws[f"{col}{row_i}"].fill = yellow_fill

        row_i += 1

    total_row = row_i
    ws.merge_cells(f"B{total_row}:C{total_row}")
    ws[f"B{total_row}"] = "TOTAL"
    ws[f"B{total_row}"].font = bold
    ws[f"B{total_row}"].alignment = center

    totals_values = {
        "D": result["grand"]["rail"], "E": 1.0 if result["grand"]["rail"] else 0.0,
        "F": result["grand"]["road"], "G": 1.0 if result["grand"]["road"] else 0.0,
        "H": result["grand"]["inland"], "I": 1.0 if result["grand"]["inland"] else 0.0,
        "J": result["grand"]["pipeline"], "K": 1.0 if result["grand"]["pipeline"] else 0.0,
        "L": result["grand"]["total"], "M": 1.0 if result["grand"]["total"] else 0.0,
    }
    for col, val in totals_values.items():
        cell = ws[f"{col}{total_row}"]
        cell.value = val
        cell.font = bold
        cell.border = thin_border
        if col in ("E", "G", "I", "K", "M"):
            cell.number_format = "0.00%"
            cell.alignment = center
        else:
            cell.number_format = "0.000"
            cell.alignment = right

    return total_row + 1


@bp.route("/api/module/RP01/report4/export")
@login_required
def report4_api_export():
    try:
        df, years = _get_df_and_years()
        fin_year = request.args.get("fin_year", years[-1])
        month_idx = int(request.args.get("month_idx", 2))
        if fin_year not in years:
            return jsonify({"error": f"Unknown fin_year '{fin_year}'. Available: {', '.join(years)}"}), 400

        fallback_df = load_fallback_data()

        import_vessels = get_operation_vessel_names("import")
        export_vessels = get_operation_vessel_names("export")

        import_result = compute_report4(df, fallback_df, fin_year, month_idx, import_vessels, total_key="import_total")
        export_result = compute_report4(df, fallback_df, fin_year, month_idx, export_vessels, total_key="export_total")

        month_label = idx_to_month_label(fin_year, month_idx)

        wb = Workbook()
        ws_import = wb.active
        ws_import.title = "Import"
        ws_export = wb.create_sheet(title="Export")

        styles = {
            "bold": Font(bold=True),
            "title_font": Font(bold=True, size=13),
            "header_font": Font(bold=True),
            "red_font": Font(bold=True, color="C00000"),
            "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
            "left": Alignment(horizontal="left", vertical="center"),
            "right": Alignment(horizontal="right", vertical="center"),
            "thin_border": Border(
                left=Side(style="thin", color="000000"),
                right=Side(style="thin", color="000000"),
                top=Side(style="thin", color="000000"),
                bottom=Side(style="thin", color="000000"),
            ),
            "yellow_fill": PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid"),
        }

        # ---- Sheet 1: existing Import table ----
        _write_report_table(
            ws_import,
            start_row=3,
            title_line="COMMODITY-WISE IMPORT CARGO DESPATCHED BY DIFFERENT MODES OF TRANSPORT FROM THE PORT",
            verb="Despatched",
            month_label=month_label,
            result=import_result,
            styles=styles,
        )

        # ---- Sheet 2: Export table, on its own page ----
        _write_report_table(
            ws_export,
            start_row=3,
            title_line="COMMODITY-WISE EXPORT CARGO RECEIVED BY DIFFERENT MODES OF TRANSPORT FROM THE PORT",
            verb="Received",
            month_label=month_label,
            result=export_result,
            styles=styles,
        )

        widths = {"A": 3, "B": 8, "C": 26, "D": 12, "E": 12, "F": 12, "G": 12,
                  "H": 12, "I": 12, "J": 14, "K": 12, "L": 14, "M": 12}
        for ws in (ws_import, ws_export):
            for col, w in widths.items():
                ws.column_dimensions[col].width = w

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f"Report-4_{fin_year}_{month_label}.xlsx"
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500