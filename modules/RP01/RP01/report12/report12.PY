"""
Report-12 — K-2.1 Traffic Report
Flask Blueprint version.

Covers BOTH tabs of the uploaded workbook from a single dynamic source:
  - "EXIM (Single Leg)"  -> NO DATA SOURCE in the current schema. The old
        `leg_port_type` column (which distinguished Direct Coastal / Direct
        Exim / Feeding to International Transshipment Port) does not exist
        anymore. This sheet still renders (so routes/HTML don't break) but
        every cell will be 0 until a replacement column is added.
  - "TP (Two Leg)"        -> built from mis_vessel_master.foreign_indian +
        mis_vessel_master.import_export:
            foreign_indian='COASTAL' -> "Coastal Transshipment ( Coastal Leg + Coastal Leg )"
            foreign_indian='FOREIGN' -> "Coastal + International Leg"
        import_export='IMPORT' -> Inbound
        import_export='EXPORT' -> Outbound
        There is no data source for the third two_leg bucket,
        "International Transshipment" (that needed pol_type/pod_type both
        being foreign) — it will always render as 0.

Primary source: mis_vessel_master, joined to vessel_cargo to resolve the
commodity row for each vessel call.

    mis_vessel_master
        fin_year          text   e.g. '2025-26'
        month             text   e.g. 'Jun-26'
        foreign_indian    text   'COASTAL' | 'FOREIGN'
        import_export     text   'IMPORT' | 'EXPORT'
        quantity          numeric  tonnes
        cargo             text   free-text cargo name, joined to vessel_cargo.cargo_name

    vessel_cargo
        cargo_name            text
        cargo_category        text
        cargo_sub_category    text
        cargo_sub_category_2  text   -> this is what maps to the report's row labels

`quantity` is assumed to be in plain tonnes (same convention as Report-1);
this report divides by 1,000,000 to show MMT, since every row on this
sheet is "(In MMT)" except the last ("Container (In TEUs)"), which has no
data source anymore either (the old `teu_count` column is gone) and will
render as 0 until a TEU source is identified.
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

# ---------------------------------------------------------------------
# Row layout — identical on both tabs (matches the uploaded workbook's
# B7:B39 exactly, including the 4 bold section-header rows).
# ---------------------------------------------------------------------
ROW_LAYOUT = [
    {"key": "LIQUID", "header": True},
    {"key": "POL-Crude (In MMT)", "header": False},
    {"key": "POL-Products (In MMT)", "header": False},
    {"key": "LPG or LNG (In MMT)", "header": False},
    {"key": "Edible Oil (In MMT)", "header": False},
    {"key": "FRM-Liquid (In MMT)", "header": False},
    {"key": "Chemicals (In MMT)", "header": False},
    {"key": "Other Liquids (In MMT)", "header": False},
    {"key": "DRY BULK", "header": True},
    {"key": "Iron Ore All (In MMT)", "header": False},
    {"key": "Other Ores (In MMT)", "header": False},
    {"key": "Thermal Coal (In MMT)", "header": False},
    {"key": "Coking Coal (In MMT)", "header": False},
    {"key": "Other Coal (In MMT)", "header": False},
    {"key": "Fertilizer (In MMT)", "header": False},
    {"key": "FRM Dry (In MMT)", "header": False},
    {"key": "Food Grains - excluding pulses (In MMT)", "header": False},
    {"key": "Pulses (In MMT)", "header": False},
    {"key": "Sugar (In MMT)", "header": False},
    {"key": "Tea and Coffee (In MMT)", "header": False},
    {"key": "Cement (In MMT)", "header": False},
    {"key": "Salt (In MMT)", "header": False},
    {"key": "Iron Scrap (In MMT)", "header": False},
    {"key": "Other Dry Bulk (In MMT)", "header": False},
    {"key": "Scrap-LDT (In MMT)", "header": False},
    {"key": "BREAK BULK", "header": True},
    {"key": "Iron and Steel (In MMT)", "header": False},
    {"key": "Timber and Log (In MMT)", "header": False},
    {"key": "Project Cargo (In MMT)", "header": False},
    {"key": "Other Break Bulk (In MMT)", "header": False},
    {"key": "CONTAINER", "header": True},
    {"key": "Container (In MMT)", "header": False},
    {"key": "Container (In TEUs)", "header": False, "is_teu": True},
]

# vessel_cargo.cargo_sub_category_2 (free text, upper-cased on compare) ->
# the report row label above. Extend this as real values surface —
# anything unmapped is dropped, with a console warning, rather than
# crashing the report.
CATEGORY_MAP = {
    "POL CRUDE": "POL-Crude (In MMT)",
    "POL PRODUCTS": "POL-Products (In MMT)",
    "POL": "POL-Products (In MMT)",
    "LPG": "LPG or LNG (In MMT)",
    "LNG": "LPG or LNG (In MMT)",
    "EDIBLE OIL": "Edible Oil (In MMT)",
    "FRM LIQUID": "FRM-Liquid (In MMT)",
    "FARM LIQUIDS": "FRM-Liquid (In MMT)",
    "PH.ACID": "FRM-Liquid (In MMT)",
    "PH ACID": "FRM-Liquid (In MMT)",
    "PHOSPHORIC ACID": "FRM-Liquid (In MMT)",
    "CHEMICAL": "Chemicals (In MMT)",
    "CHEMICALS": "Chemicals (In MMT)",
    "OTHER LIQUID": "Other Liquids (In MMT)",
    "OTHER LIQUIDS": "Other Liquids (In MMT)",
    "IRON ORE": "Iron Ore All (In MMT)",
    "OTHER ORES": "Other Ores (In MMT)",
    "THERMAL COAL": "Thermal Coal (In MMT)",
    "COKING COAL": "Coking Coal (In MMT)",
    "OTHER COAL": "Other Coal (In MMT)",
    "FERTILIZER": "Fertilizer (In MMT)",
    "FRM DRY": "FRM Dry (In MMT)",
    "FOOD GRAINS": "Food Grains - excluding pulses (In MMT)",
    "PULSES": "Pulses (In MMT)",
    "SUGAR": "Sugar (In MMT)",
    "TEA AND COFFEE": "Tea and Coffee (In MMT)",
    "CEMENT": "Cement (In MMT)",
    "SALT": "Salt (In MMT)",
    "IRON SCRAP": "Iron Scrap (In MMT)",
    "OTHER DRY BULK": "Other Dry Bulk (In MMT)",
    "SCRAP-LDT": "Scrap-LDT (In MMT)",
    "IRON AND STEEL": "Iron and Steel (In MMT)",
    "TIMBER AND LOG": "Timber and Log (In MMT)",
    "PROJECT CARGO": "Project Cargo (In MMT)",
    "OTHER BREAK BULK": "Other Break Bulk (In MMT)",
    "CONTAINER": "Container (In MMT)",
}

# The 3 column-group buckets per sheet, in on-screen order, plus the
# note text the sheet prints under the table (kept verbatim from the
# uploaded workbook so the export matches exactly). Note: for "single",
# and for the "International Transshipment" group of "two_leg", there is
# no longer a data source — those columns will always show 0 (see the
# module docstring above).
SHEET_DEFS = {
    "single": {
        "title": "EXIM (Single Leg)",
        "groups": ["Direct Coastal", "Direct Exim", "Feeding to International Transshipment Port"],
        "notes": [
            "1. Direct Coastal (Excluding Transhipment) - Inbound / Outbound leg is coastal movement (POL / POD is coastal port)",
            "2. Direct EXIM (Excluding Transhipment) - Inbound / Outbound leg is international movement (POL / POD is foreign port)",
            "3. Feeding to International Transhipment port (Excluding Transhipment) - Inbound / Outbound leg is from/to international transhipment port (POL / POD is a international transhipment port)",
        ],
    },
    "two_leg": {
        "title": "TP (Two Leg)",
        "groups": ["Coastal Transshipment ( Coastal Leg + Coastal Leg )", "Coastal + International Leg", "International Transshipment"],
        "notes": [
            "1. Coastal Transshipment ( Coastal Leg + Coastal Leg) - Both inbound / outbound legs are from / to coastal ports (POL & POL are coastal ports)",
            "2. Coastal + International Leg - One of the inbound & outbound legs is from / to coastal port (Either POL or POD is coastal port)",
            "3. International Transshipment - Both inbound / outbound legs are from / to international ports (POL & POL are international ports)",
        ],
    },
}

DIRECTIONS = ["Inbound", "Outbound"]


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
    abbrev = str(month_str).split("-")[0].strip()
    try:
        return MONTH_NAMES.index(abbrev)
    except ValueError:
        raise ReportDataError(
            f"Unrecognized value in mis_vessel_master.month: '{month_str}' "
            f"(expected something like 'Jun-26')"
        )


def _two_leg_bucket(value):
    value = str(value or "").strip().upper()

    if value in ("COASTAL", "COSTAL"):
        return "Coastal Transshipment ( Coastal Leg + Coastal Leg )"

    if value in ("OVERSEAS", "FOREIGN"):
        return "Coastal + International Leg"

    return None


def _direction(import_export):
    ie = str(import_export or "").strip().upper()
    if ie == "IMPORT":
        return "Inbound"
    if ie == "EXPORT":
        return "Outbound"
    return None

def get_report_category(cargo):
    cargo = str(cargo or "").strip().upper()

    # ---------------- POL PRODUCTS ----------------
    if cargo in (
        "FO",
        "FO [E]",
        "CBFS",
        "FURNACE OIL",
    ):
        return "POL-Products (In MMT)"

    # ---------------- POL CRUDE ----------------
    if cargo == "POL CRUDE":
        return "POL-Crude (In MMT)"

    # ---------------- LPG ----------------
    if "LPG" in cargo or "LNG" in cargo:
        return "LPG or LNG (In MMT)"

    # ---------------- EDIBLE OIL ----------------
    if cargo in (
        "CPO",
        "CPKO",
        "CPO/CPKO",
        "CPO/RBDPO",
        "RBD PALM OLEIN",
        "EDIBLE OIL",
        "SUNFLOWER OIL",
        "CDSBO",
        "CSBO",
        "CSFO",
    ):
        return "Edible Oil (In MMT)"

    # ---------------- CHEMICALS ----------------
    if cargo in (
        "CHEMICAL",
        "ACETIC ACID",
        "A. ACID",
        "A.ACID",
        "AACID",
        "VAM",
        "PHENOL/ACETON/VAM",
        "PHENOL",
        "MDC",
        "MEK",
        "IPA",
        "ISOPROPYL ALCOHOL",
        "SM",
        "STRENE MONOMER",
        "STYRENE MONOMER",
        "N BUTONAL/TOLUNE",
    ):
        return "Chemicals (In MMT)"

    # ---------------- FRM LIQUID ----------------
    if cargo in (
        "PHOSPHORIC ACID",
        "PH.ACID",
        "PH ACID",
    ):
        return "FRM-Liquid (In MMT)"

    # ---------------- OTHER LIQUID ----------------
    if (
        "BASE OIL" in cargo
        or "LUBE" in cargo
        or "SHELL" in cargo
        or cargo == "CHEMICALS"
    ):
        return "Other Liquids (In MMT)"

    return None

def load_data() -> pd.DataFrame:
    """Pulls every mis_vessel_master row (joined to vessel_cargo for the
    commodity), tags each row with (sheet, row_key, direction, bucket),
    and returns a long-format dataframe ready for pivoting in
    compute_table()."""
    conn = get_db()
    try:
        cur = get_cursor(conn)
        cur.execute("""
            SELECT
                fin_year,
                month,
                overseas_coastal,
                foreign_indian,
                import_export,
                cargo,
                quantity
            FROM mis_vessel_master
            WHERE fin_year IS NOT NULL
            AND month IS NOT NULL
        """)
        mis_rows = cur.fetchall()

        # --------------------------------------------------
        # Check if MIS already has the current month.
        # If it does NOT, pull the current month from the
        # live VCN tables and APPEND it to the MIS rows
        # (do not replace the historical MIS data).
        # --------------------------------------------------
        current_month = pd.Timestamp.today().strftime("%b-%y")

        mis_current = [
            r for r in mis_rows
            if str(r["month"]).strip() == current_month
        ]

        live_rows = []
        if not mis_current:

            print("REPORT12: Current month not found in mis_vessel_master")
            print("REPORT12: Loading live VCN data...")

            cur.execute("""
                SELECT
                    to_char(current_date,'YYYY')||'-'||right(to_char(current_date + interval '1 year','YYYY'),2) AS fin_year,
                    to_char(current_date,'Mon-YY') AS month,
                    h.vessel_run_type AS overseas_coastal,
                    'Import' AS import_export,
                    c.cargo_name AS cargo,
                    c.quantity
                FROM vcn_header h
                JOIN vcn_consigners c
                    ON c.vcn_id=h.id

                UNION ALL

                SELECT
                    to_char(current_date,'YYYY')||'-'||right(to_char(current_date + interval '1 year','YYYY'),2),
                    to_char(current_date,'Mon-YY'),
                    h.vessel_run_type,
                    'Export',
                    e.cargo_name,
                    e.quantity
                FROM vcn_header h
                JOIN vcn_export_cargo_declaration e
                    ON e.vcn_id=h.id
            """)

            live_rows = cur.fetchall()
        else:
            print("REPORT12: Current month already present in mis_vessel_master — skipping live VCN load")

        # Combine historical MIS rows with live rows (if any). Never
        # discard mis_rows.
        rows = list(mis_rows) + list(live_rows)
    finally:
        conn.close()

    empty = pd.DataFrame(columns=["fin_year", "fy_month_idx", "sheet", "row_key", "direction", "bucket", "value"])
    if not rows:
        return empty

    df = pd.DataFrame(rows)
    print(f"REPORT12 DEBUG: columns returned by query: {list(df.columns)}")
    print(f"REPORT12 DEBUG: rows fetched from DB: {len(df)}")

    missing_cols = [c for c in (
        "fin_year",
        "month",
        "overseas_coastal",
        "import_export",
        "quantity"
    ) if c not in df.columns]
    if missing_cols:
        raise ReportDataError(f"Query result is missing column(s): {', '.join(missing_cols)}")

    df["fin_year"] = df["fin_year"].str.strip()
    df["fy_month_idx"] = df["month"].apply(month_str_to_idx)

    # Convert quantity to numeric
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)

    # Map cargo to report category
    df["row_key"] = df["cargo"].apply(get_report_category)

    # Show unmapped cargo values
    unmapped = sorted(
        df.loc[df["row_key"].isna(), "cargo"]
        .dropna()
        .unique()
        .tolist()
    )

    if unmapped:
        print("REPORT12 WARNING: Unmapped cargo values:")
        for c in unmapped:
            print("   ", c)

    # Drop unmapped rows
    df = df.dropna(subset=["row_key"])

    print(f"REPORT12 DEBUG: rows remaining after cargo mapping: {len(df)}")

    # ----------------------------------------------------
    # Import / Export -> Direction
    # ----------------------------------------------------
    df["direction"] = df["import_export"].apply(_direction)

    unknown_ie = sorted(
        df.loc[df["direction"].isna(), "import_export"]
        .dropna()
        .unique()
        .tolist()
    )

    if unknown_ie:
        print("REPORT12 WARNING: rows with unrecognized import_export dropped:", unknown_ie)

    df = df.dropna(subset=["direction"])

    print(f"REPORT12 DEBUG: rows remaining after import_export mapping: {len(df)}")

    # ----------------------------------------------------
    # Foreign / Coastal -> Bucket
    # ----------------------------------------------------
    df["bucket"] = df["overseas_coastal"].apply(_two_leg_bucket)

    unknown_fi = sorted(
        df.loc[df["bucket"].isna(), "overseas_coastal"]
        .dropna()
        .unique()
        .tolist()
    )

    if unknown_fi:
        print("REPORT12 WARNING: rows with unrecognized foreign_indian dropped:", unknown_fi)

    df = df.dropna(subset=["bucket"])

    print(f"REPORT12 DEBUG: rows remaining after foreign_indian mapping: {len(df)}")

    # No TEU source in the current schema; TEU row is always 0.
    is_teu_row = df["row_key"] == "Container (In TEUs)"
    # Database already stores the values you want to display.
    df["value"] = df["quantity"]
    df.loc[is_teu_row, "value"] = 0.0

    # Everything here belongs on the "two_leg" sheet — there is no data
    # source for the "single" (EXIM Single Leg) sheet anymore.
    df["sheet"] = "two_leg"

    combined = (
        df.groupby(["fin_year", "fy_month_idx", "sheet", "row_key", "direction", "bucket"], as_index=False)["value"]
        .sum()
    )
    return combined


def _get_df_and_years():
    df = load_data()
    years = sorted(df["fin_year"].unique().tolist())
    return df, years


def compute_table(df, sheet, fin_year, month_idx):
    sdef = SHEET_DEFS[sheet]
    subset = df[(df["sheet"] == sheet) & (df["fin_year"] == fin_year) & (df["fy_month_idx"] == month_idx)]

    values = {}
    for grp in sdef["groups"]:
        for direction in DIRECTIONS:
            cell = subset[(subset["bucket"] == grp) & (subset["direction"] == direction)]
            sums = cell.groupby("row_key")["value"].sum().to_dict()
            values[(grp, direction)] = sums

    rows = []
    for r in ROW_LAYOUT:
        if r["header"]:
            rows.append({"label": r["key"], "header": True, "cells": {}})
            continue
        cells = {}
        for grp in sdef["groups"]:
            for direction in DIRECTIONS:
                v = values[(grp, direction)].get(r["key"], 0.0)
                cells[f"{grp}||{direction}"] = round(v, 3) if v else 0.0
        rows.append({"label": r["key"], "header": False, "cells": cells})
    return rows


@bp.route("/module/RP01/report12/")
@login_required
def report12_index():
    return render_template("report12/report12.html", port_name="JJLTPL")


@bp.route("/api/module/RP01/report12/meta")
@login_required
def report12_api_meta():
    try:
        _, years = _get_df_and_years()
        months = {fy: month_options_for(fy) for fy in years}
        return jsonify({
            "years": years,
            "months": months,
            "port_name": "JJLTPL",
            "sheets": {k: {"title": v["title"], "groups": v["groups"]} for k, v in SHEET_DEFS.items()},
        })
    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


@bp.route("/api/module/RP01/report12/report")
@login_required
def report12_api_report():
    try:
        df, years = _get_df_and_years()
        sheet = request.args.get("sheet", "two_leg")
        fin_year = request.args.get("fin_year", years[-1] if years else None)
        month_idx = int(request.args.get("month_idx", 2))

        if sheet not in SHEET_DEFS:
            return jsonify({"error": f"Unknown sheet '{sheet}'. Expected 'single' or 'two_leg'."}), 400
        if fin_year not in years:
            return jsonify({"error": f"Unknown fin_year '{fin_year}'. Available: {', '.join(years)}"}), 400

        rows = compute_table(df, sheet, fin_year, month_idx)
        month_label = next(o["label"] for o in month_options_for(fin_year) if o["idx"] == month_idx)

        return jsonify({
            "sheet": sheet,
            "sheet_title": SHEET_DEFS[sheet]["title"],
            "groups": SHEET_DEFS[sheet]["groups"],
            "directions": DIRECTIONS,
            "notes": SHEET_DEFS[sheet]["notes"],
            "port_name": "JJLTPL",
            "fin_year": fin_year,
            "month_label": month_label,
            "rows": rows,
        })
    except ReportDataError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected server error: {e}"}), 500


@bp.route("/api/module/RP01/report12/export")
@login_required
def report12_api_export():
    try:
        df, years = _get_df_and_years()
        fin_year = request.args.get("fin_year", years[-1] if years else None)
        month_idx = int(request.args.get("month_idx", 2))
        port_name = request.args.get("port_name", "JJLTPL")

        if fin_year not in years:
            return jsonify({"error": f"Unknown fin_year '{fin_year}'. Available: {', '.join(years)}"}), 400

        month_label = next(o["label"] for o in month_options_for(fin_year) if o["idx"] == month_idx)

        wb = Workbook()
        wb.remove(wb.active)  # remove default blank sheet

        bold = Font(bold=True)
        title_font = Font(bold=True, size=12)
        header_font = Font(bold=True)
        section_font = Font(bold=True)

        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left = Alignment(horizontal="left", vertical="center")
        right = Alignment(horizontal="right", vertical="center")

        thin = Side(style="thin", color="000000")
        thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)

        yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

        # ---- sheet order: TP (Two Leg) FIRST, then EXIM (Single Leg) ----
        sheet_order = ["two_leg", "single"]

        for sheet_key in sheet_order:
            sdef = SHEET_DEFS[sheet_key]
            groups = sdef["groups"]
            rows = compute_table(df, sheet_key, fin_year, month_idx)

            ws = wb.create_sheet(title=sdef["title"][:31])

            n_groups = len(groups)
            last_col_idx = 2 + n_groups * 2  # col B is labels, then 2 cols (Inbound/Outbound) per group
            last_col = get_column_letter(last_col_idx)

            # ---- header block --------------------------------------------
            ws["B2"] = "Financial Year *"
            ws["B2"].font = bold
            ws[f"{get_column_letter(last_col_idx)}2"] = "K-2.1  Traffic"
            ws[f"{get_column_letter(last_col_idx)}2"].font = title_font
            ws[f"{get_column_letter(last_col_idx)}2"].alignment = right

            ws["B3"] = "Month*"
            ws["B3"].font = bold
            ws["C3"] = f"-  {month_label}"

            ws["B4"] = "Port / Terminal"
            ws["B4"].font = bold
            ws["C4"] = f"-  {port_name}"

            # ---- group headers (row 5) + Inbound/Outbound (row 6) ----------
            group_header_row = 5
            sub_header_row = 6
            col = 3  # column C
            for grp in groups:
                start_letter = get_column_letter(col)
                end_letter = get_column_letter(col + 1)
                ws.merge_cells(f"{start_letter}{group_header_row}:{end_letter}{group_header_row}")
                cell = ws[f"{start_letter}{group_header_row}"]
                cell.value = grp
                cell.font = header_font
                cell.alignment = center
                for c in (start_letter, end_letter):
                    ws[f"{c}{group_header_row}"].border = thin_border

                ws[f"{start_letter}{sub_header_row}"] = "Inbound"
                ws[f"{end_letter}{sub_header_row}"] = "Outbound"
                for c in (start_letter, end_letter):
                    ws[f"{c}{sub_header_row}"].font = header_font
                    ws[f"{c}{sub_header_row}"].alignment = center
                    ws[f"{c}{sub_header_row}"].border = thin_border
                col += 2

            ws[f"B{sub_header_row}"] = "Commodity"
            ws[f"B{sub_header_row}"].font = header_font
            ws[f"B{sub_header_row}"].alignment = center
            ws[f"B{sub_header_row}"].border = thin_border

            # ---- data rows ---------------------------------------------------
            row_i = sub_header_row + 1
            for r in rows:
                b_cell = ws[f"B{row_i}"]
                b_cell.value = r["label"]
                if r["header"]:
                    b_cell.font = section_font
                    b_cell.alignment = left
                    b_cell.border = thin_border
                    ws.merge_cells(f"B{row_i}:{last_col}{row_i}")
                else:
                    b_cell.font = Font()
                    b_cell.alignment = left
                    b_cell.border = thin_border
                    col = 3
                    for grp in groups:
                        for direction in DIRECTIONS:
                            v = r["cells"].get(f"{grp}||{direction}", 0.0)
                            c_letter = get_column_letter(col)
                            cell = ws[f"{c_letter}{row_i}"]
                            cell.value = v if v else None
                            cell.number_format = "0.000"
                            cell.alignment = right
                            cell.border = thin_border
                            if v:
                                cell.fill = yellow_fill
                                b_cell.fill = yellow_fill
                            col += 1
                row_i += 1

            # ---- notes ---------------------------------------------------------
            note_row = row_i + 1
            ws[f"B{note_row}"] = "Note :"
            ws[f"B{note_row}"].font = bold
            note_row += 1
            for line in sdef["notes"]:
                ws.merge_cells(f"B{note_row}:{last_col}{note_row}")
                ws[f"B{note_row}"] = line
                ws[f"B{note_row}"].alignment = left
                note_row += 1

            # ---- column widths -------------------------------------------------
            ws.column_dimensions["A"].width = 3
            ws.column_dimensions["B"].width = 42
            for c in range(3, last_col_idx + 1):
                ws.column_dimensions[get_column_letter(c)].width = 14

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f"Report-12_{fin_year}_{month_label}.xlsx"
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