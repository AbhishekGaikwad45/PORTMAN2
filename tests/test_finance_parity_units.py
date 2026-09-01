"""Unit checks for the finance-parity work: SAP payload arithmetic, IRP value
totals, and the go-live cutover's pure helpers.

No network. `build_einvoice_from_invoice` reads the seller GSTIN from the dev
DB like the rest of this suite; everything else here is pure.
"""
import pytest

import einvoice_builder
import sap_builder
from modules.ADMIN import cutover
from modules.FIN01 import model as fin


def _item(gl, amount, **over):
    item = {
        'GL_account': gl, 'Amount': f'{amount:.2f}',
        'CGST_AMT': '', 'SGST_AMT': '', 'IGST_AMT': '',
        'TDS_amount': '', 'TCS_amount': '',
        'Quantity': '', 'Unit_Price': '', 'IGST_GL': '', 'CGST_GL': '', 'SGST_GL': '',
        'Text': 'svc', 'HSN_SAC': '996719',
    }
    item.update(over)
    return item


# ── A1: one ITEM per GL account ──────────────────────────────────────────────

def test_merge_collapses_same_gl_and_sums_amounts():
    merged = sap_builder._merge_same_gl_items([
        _item('4101076030', 10000, CGST_AMT='900.00', SGST_AMT='900.00',
              Quantity='100.000', Unit_Price='100.00'),
        _item('4101076030', 5000, CGST_AMT='450.00', SGST_AMT='450.00',
              Quantity='50.000', Unit_Price='100.00'),
    ])
    assert len(merged) == 1
    assert merged[0]['Amount'] == '15000.00'
    assert merged[0]['CGST_AMT'] == '1350.00'
    assert merged[0]['SGST_AMT'] == '1350.00'
    # Uniform rate survives; quantities present on both sides sum.
    assert merged[0]['Unit_Price'] == '100.00'
    assert merged[0]['Quantity'] == '150.000'


def test_merge_blanks_unit_price_when_rates_differ():
    merged = sap_builder._merge_same_gl_items([
        _item('4101076030', 10000, Quantity='100.000', Unit_Price='100.00'),
        _item('4101076030', 4000, Quantity='50.000', Unit_Price='80.00'),
    ])
    assert len(merged) == 1
    assert merged[0]['Unit_Price'] == ''   # Amount is authoritative
    assert merged[0]['Amount'] == '14000.00'


def test_merge_blanks_quantity_when_one_side_has_none():
    merged = sap_builder._merge_same_gl_items([
        _item('4101076030', 10000, Quantity='100.000', Unit_Price='100.00'),
        _item('4101076030', 500, Quantity='', Unit_Price='100.00'),
    ])
    assert merged[0]['Quantity'] == ''


def test_merge_keeps_different_gl_accounts_separate():
    merged = sap_builder._merge_same_gl_items([
        _item('4101076030', 10000),
        _item('4101076031', 2000),
    ])
    assert [m['GL_account'] for m in merged] == ['4101076030', '4101076031']
    assert [m['Amount'] for m in merged] == ['10000.00', '2000.00']


def test_merge_fills_gst_gl_from_the_line_that_brought_the_amount():
    """A zero-GST first line must not swallow the second line's GST GLs."""
    merged = sap_builder._merge_same_gl_items([
        _item('4101076030', 10000),
        _item('4101076030', 5000, CGST_AMT='450.00', CGST_GL='2400001000'),
    ])
    assert merged[0]['CGST_AMT'] == '450.00'
    assert merged[0]['CGST_GL'] == '2400001000'


# ── A2: Invoice_Amount rebuilt from components ───────────────────────────────

def test_total_invoice_amount_is_built_from_components_not_total_amount():
    header = {
        'subtotal': 10000, 'cgst_amount': 900, 'sgst_amount': 900, 'igst_amount': 0,
        'tds_amount': 200, 'tcs_amount': 118, 'round_off': 0.18,
        # A stale/shifted convention here must not leak into the payload.
        'total_amount': 999999,
    }
    total = sap_builder._total_invoice_amount(header, [])
    assert round(total, 2) == round(10000 + 900 + 900 + 200 - 118 + 0.18, 2)


def test_total_invoice_amount_falls_back_to_the_lines():
    lines = [
        {'line_amount': 6000, 'cgst_amount': 540, 'sgst_amount': 540, 'tcs_amount': 60},
        {'line_amount': 4000, 'cgst_amount': 360, 'sgst_amount': 360, 'tcs_amount': 40},
    ]
    total = sap_builder._total_invoice_amount({}, lines)
    assert round(total, 2) == round(10000 + 900 + 900 - 100, 2)


# ── A4: IRP rejects a ValDtls that does not balance ──────────────────────────

def test_einvoice_valdtls_balances_with_tcs_and_round_off():
    header = {
        'invoice_number': 'INV-EIN-1', 'invoice_date': '2026-09-01',
        'customer_name': 'ACME', 'customer_gstin': '27ABCDE1234F1Z5',
        'customer_gst_state_code': '27', 'tcs_amount': 118.0, 'round_off': 0.35,
    }
    lines = [{
        'service_name': 'Cargo Handling', 'sac_code': '996719', 'quantity': 100,
        'uom': 'MT', 'rate': 100, 'line_amount': 10000,
        'cgst_rate': 9, 'sgst_rate': 9, 'igst_rate': 0,
        'cgst_amount': 900, 'sgst_amount': 900, 'igst_amount': 0,
        'line_total': 11800,
    }]
    val = einvoice_builder.build_einvoice_from_invoice(header, lines)['ValDtls']
    assert val['OthChrg'] == 118.0
    assert val['RndOffAmt'] == 0.35
    assert val['TotInvVal'] == round(
        val['AssVal'] + val['CgstVal'] + val['SgstVal'] + val['IgstVal']
        + val['OthChrg'] + val['RndOffAmt'], 2)


# ── F2: seeds are a floor, never an assignment ───────────────────────────────

def test_next_from_seed_floors_then_gets_out_of_the_way():
    assert fin.next_from_seed(0, 500) == 500      # nothing issued yet
    assert fin.next_from_seed(499, 500) == 500    # still below the seed
    assert fin.next_from_seed(500, 500) == 501    # seed reached — normal increment
    assert fin.next_from_seed(900, 500) == 901    # stale seed ignored
    assert fin.next_from_seed(7, None) == 8       # no seed configured


# ── F3: cutover pure helpers ─────────────────────────────────────────────────

def test_validate_start_seq_rejects_bad_input():
    with pytest.raises(ValueError):
        cutover.validate_start_seq('abc', 0)
    with pytest.raises(ValueError):
        cutover.validate_start_seq(0, 0)
    with pytest.raises(ValueError):
        cutover.validate_start_seq(10, 10)     # equal to current max
    with pytest.raises(ValueError):
        cutover.validate_start_seq(5, 10)      # below current max
    assert cutover.validate_start_seq(' 11 ', 10) == 11


def test_compute_partial_billed():
    assert cutover.compute_partial_billed(100, 0, 40) == 40.0       # partial
    assert cutover.compute_partial_billed(100, 0, None) == 100.0    # all of it
    assert cutover.compute_partial_billed(100, 60, None) == 40.0    # what is left
    assert cutover.compute_partial_billed(100, 60, 90) == 40.0      # over-cap clamps
    assert cutover.compute_partial_billed(100, 100, None) == 0.0    # nothing left
    assert cutover.compute_partial_billed(100, 0, 12.34567) == 12.346  # 3dp
    with pytest.raises(ValueError):
        cutover.compute_partial_billed(100, 0, 0)


def test_would_overbill_tolerance_boundary():
    assert fin.would_overbill(0, 100, 100) is False       # exactly the cap
    assert fin.would_overbill(60, 40, 100) is False       # legitimate partial
    assert fin.would_overbill(100, 100, 100) is True      # replayed submit
    assert fin.would_overbill(0, 100.0000001, 100) is False   # inside tolerance
    assert fin.would_overbill(0, 100.001, 100) is True        # outside it
