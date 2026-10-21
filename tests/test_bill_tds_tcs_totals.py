"""Bill and invoice headers carry the TDS/TCS their lines computed.

Reproduces prod BILL/101: one 502000.00 line at 18% GST with TCS 2%. The TCS
was computed onto the line and then dropped, because the header total was
summed as subtotal + GST only — so the printed invoice came out 11847.20 short
of what SAP (Invoice_Amount) and the IRP (TotInvVal) were told.

Mostly pure arithmetic over in-memory dicts; the last two checks read the
column types out of the database.
"""
import sap_builder
from modules.FIN01.model import bill_totals, compute_aggregate_gst, amount_in_words


# The line as save_bill_line stores it: GST on the basic, TCS on basic + GST.
LINE_101 = {'line_amount': 502000.00, 'cgst_amount': 45180.00,
            'sgst_amount': 45180.00, 'igst_amount': 0.0,
            'tds_amount': 0.0, 'tcs_amount': 11847.20}


# ── Bill header totals ───────────────────────────────────────────────────────

def test_tcs_is_two_percent_of_basic_plus_gst():
    # What save_bill_line computes — the basis, not just the basic.
    assert round((502000.00 + 45180.00 + 45180.00) * 2 / 100, 2) == 11847.20


def test_tds_is_computed_on_the_basic_only():
    # 2% TDS on 502000 basic — GST is not part of the TDS base.
    assert round(502000.00 * 2 / 100, 2) == 10040.00


def test_tcs_reaches_the_header():
    t = bill_totals([LINE_101])
    assert t['subtotal'] == 502000.00
    assert t['cgst_amount'] == 45180.00
    assert t['sgst_amount'] == 45180.00
    assert t['tcs_amount'] == 11847.20      # was silently absent


def test_total_amount_includes_tcs():
    # TCS is collected from the customer, so it is part of what they owe.
    assert bill_totals([LINE_101])['total_amount'] == 604207.20


def test_tds_sums_but_never_reduces_the_bill():
    line = dict(LINE_101, tds_amount=10040.00, tcs_amount=0.0)
    t = bill_totals([line])
    assert t['tds_amount'] == 10040.00
    assert t['total_amount'] == 592360.00    # gross — TDS is withheld at payment


def test_lines_without_tax_flags_are_zero():
    t = bill_totals([{'line_amount': 100, 'cgst_amount': 9, 'sgst_amount': 9}])
    assert t['tds_amount'] == 0 and t['tcs_amount'] == 0


# ── The three documents must agree ───────────────────────────────────────────

def test_bill_total_matches_the_irp_and_sap_nets_tcs():
    """The printed total and the IRP's TotInvVal include TCS. SAP's
    Invoice_Amount does not: its FIIF059 check balances it as base - TCS
    (see test_sap_invoice_amount), so it sits exactly 2x TCS below them."""
    header = {'subtotal': 502000.00, 'cgst_amount': 45180.00, 'sgst_amount': 45180.00,
              'igst_amount': 0.0, 'tds_amount': 0.0, 'tcs_amount': 11847.20,
              'round_off': 0.0}
    printed = bill_totals([LINE_101])['total_amount']
    sap = round(sap_builder._total_invoice_amount(header, [LINE_101]), 2)
    irp = round(502000.00 + 45180.00 + 45180.00 + 11847.20, 2)  # TotInvVal
    assert printed == irp == 604207.20
    assert sap == round(irp - 2 * 11847.20, 2) == 580512.80


# ── Aggregate-per-rate GST (what lets SAP auto-post) ─────────────────────────

def test_gst_is_rounded_once_on_the_aggregate():
    """SAP re-derives tax as round(base x rate) on the merged ITEM, so the sum
    of per-line-rounded tax must not be what we send."""
    lines = [{'id': 1, 'line_amount': 47398.48, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 2, 'line_amount': 19801.69, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 3, 'line_amount': 2509.49,  'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 4, 'line_amount': 41081.59, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0}]
    _, totals = compute_aggregate_gst(lines)
    taxable = round(sum(l['line_amount'] for l in lines), 2)
    assert totals['subtotal'] == taxable
    # Naive per-line rounding gives 9971.20 here; SAP computes 9971.21.
    assert totals['cgst_amount'] == round(taxable * 9 / 100, 2) == 9971.21


def test_redistributed_lines_still_sum_to_the_header():
    lines = [{'id': 1, 'line_amount': 47398.48, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 2, 'line_amount': 19801.69, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 3, 'line_amount': 2509.49,  'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 4, 'line_amount': 41081.59, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0}]
    line_gst, totals = compute_aggregate_gst(lines)
    assert round(sum(g['cgst_amount'] for g in line_gst.values()), 2) == totals['cgst_amount']
    assert round(sum(g['sgst_amount'] for g in line_gst.values()), 2) == totals['sgst_amount']


def test_two_rate_groups_are_rounded_independently():
    # 18% cargo handling beside 0%-rated toll: the zero group contributes
    # nothing and must not drag a paisa off the taxed group.
    lines = [{'id': 1, 'line_amount': 1000.05, 'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0},
             {'id': 2, 'line_amount': 500.00,  'cgst_rate': 0, 'sgst_rate': 0, 'igst_rate': 0}]
    line_gst, totals = compute_aggregate_gst(lines)
    assert totals['cgst_amount'] == round(1000.05 * 9 / 100, 2)
    assert line_gst[2]['cgst_amount'] == 0.0
    assert totals['subtotal'] == 1500.05


def test_words_match_the_frontend_format_including_paise():
    # finv01_generate_invoice.html's amountInWords() ends "Only" with no period
    # and spells paise out — a server rewrite must not change the house style.
    assert amount_in_words(604207.20) == \
        'Rupees Six Lakh Four Thousand Two Hundred Seven and Twenty Paise Only'
    assert amount_in_words(592360.00) == \
        'Rupees Five Lakh Ninety Two Thousand Three Hundred Sixty Only'


# ── Storage precision (hits the DB) ─────────────────────────────────────────

def test_money_columns_are_numeric_not_real():
    """float4 cannot hold a rupee amount to the paisa above ~1 lakh.

    Measured before jnpa71: 142580.87::real -> 142580.88 and
    1609935.70::real -> 1609935.8. Both are real invoice totals, and either
    one makes the SAP payload fail its own balance check — the header total
    and the ITEM amounts are read from different columns.
    """
    from database import get_db, get_cursor
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE data_type = 'real'
              AND table_name IN ('bill_header', 'bill_lines', 'invoice_header',
                                 'invoice_lines', 'invoice_bill_mapping',
                                 'customer_agreement_lines', 'service_records')
            ORDER BY table_name, column_name""")
        leftover = [f"{r['table_name']}.{r['column_name']}" for r in cur.fetchall()]
    finally:
        conn.close()
    assert leftover == [], f'still real (float4), will lose paisa: {leftover}'


def test_a_lakh_scale_amount_survives_a_round_trip():
    from database import get_db, get_cursor
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT 1609935.70::numeric(18,2) AS n, 1609935.70::real AS r")
        row = cur.fetchone()
        assert float(row['n']) == 1609935.70        # what the columns are now
        assert float(row['r']) != 1609935.70        # what they used to be
    finally:
        conn.close()
