# FIN01 Billables-from-Parcels Engine + Vessel-Grouped UI + FCAM rates — Design

**Date:** 2026-07-02
**Status:** Approved (design), pending spec review
**Program:** Finance/AR overhaul, sub-project #3. Depends on #1 (system services) and
#2 (billed-status ledger `parcel_charge_billed`), both merged. Bill *writing* +
ledger recording is #4 (out of scope here).

## Problem

FIN01's `get_customer_billables` derives cargo handling from the legacy
cargo-declaration tables and only knows two charges (CHGU01/CHGL01). The new model
bills from **parcels** (`vcn_consigners`, `vcn_export_cargo_declaration`) and needs
four charges per parcel. The bill-generation UI also needs to present billables
grouped by vessel. And FCAM agreements must let users price the new services.

## Decisions (from brainstorming)

- **Bill-to party:** the payer — `parcel.importer_name` ("Payment will be made by").
- **Gate:** all four charges billable only when the parcel's VCN LDUD is `Closed`
  or `Partial Close`.
- **Charges per parcel** (qty = parcel quantity, MT):
  | Charge | Service code | Rate resolution | Emitted when |
  |---|---|---|---|
  | Cargo Handling | CHGU01 (import) / CHGL01 (export) | cargo-specific → generic | always |
  | Infrastructure & Misc | INFM01 | cargo-specific → generic | always |
  | MLA | MLAC01 | generic | parcel has `equipment_names` |
  | Toll | TOLL01 | generic | parcel `toll_applicable` true |
- **Partial/repeat billing:** remaining = parcel qty − ledger `billed_qty(...)`; skip ≤ 0.

## Design

### 1. Engine — `get_customer_billables(customer_type, customer_id)` (FIN01)

Rebuild to return billables **grouped by vessel**:

```
{ vessels: [
    { vcn_id, vcn_doc_num, vessel_name, ldud_status,
      lines: [ { cargo_source_type ('VCN_IMPORT'|'VCN_EXPORT'),
                 cargo_source_id (parcel id), parcel_no, service_type_id,
                 service_code, service_name, cargo_name, qty (remaining), uom,
                 rate, amount, sac_code, gst_rate_id, is_tds, tds_percent,
                 is_tcs, tcs_percent }, … ],
      total_amount },
    … ],
  billed: [ … already-billed lines for reference … ] }
```

Steps:
1. Resolve selected customer's name (`vessel_customers` / `vessel_agents`).
2. Fetch parcels where `importer_name = customer_name`, joined to `vcn_header`,
   only for VCNs whose latest `ldud_header.doc_status IN ('Closed','Partial Close')`.
   Import parcels → `VCN_IMPORT`/CHGU01; export parcels → `VCN_EXPORT`/CHGL01.
3. For each parcel, build charge lines:
   - Cargo Handling (CHGU01/CHGL01) and Infrastructure (INFM01): always.
   - MLA (MLAC01): only if `equipment_names` non-empty.
   - Toll (TOLL01): only if `toll_applicable` truthy.
4. Resolve rate via FCAM `get_customer_rate(customer_type, customer_id,
   service_type_id, cargo_name=…)` — cargo_name passed for Cargo/Infra
   (cargo-specific→generic), omitted for MLA/Toll (generic only).
5. Pull `service_type_id`, `service_code`, `sac_code`, `gst_rate_id`, TDS/TCS from
   `finance_service_types` (by the fixed service codes).
6. remaining = `parcel qty − fin_model.billed_qty(cargo_source_type,
   cargo_source_id, service_type_id)`; skip lines with remaining ≤ 0.
7. Group lines under their vessel; `amount = remaining × (rate or 0)`;
   `total_amount` per vessel = sum of line amounts.

`service_records`-based "other services" from the old engine are dropped from this
view (out of scope; the 4 parcel charges are the AR billables). Rate-lookup helper
endpoints stay.

### 2. FCAM agreement rates (accommodate the services)

`modules/FCAM01/views.py` — extend the cargo-specific service set from
`('CHGL01','CHGU01')` to `('CHGL01','CHGU01','INFM01')` so Infrastructure gets the
per-cargo rate matrix. MLA (MLAC01) and Toll (TOLL01) are **not** added → they
render as single generic rate lines. No other FCAM change: the entry UI already
switches between the per-cargo matrix (`isCargoService`) and a generic line, and
the seeded system services already appear in the service dropdown.

### 3. UI — vessel-grouped bill generation

`modules/FIN01/generate_bill.html` — replace the cargo-cards / other-services
layout with **vessel accordions**:

```
Customer: [ ACME ▼ ]
▾ VCN-2627-015 · ORION   (LDUD: Partial Close)   Billable: ₹ 1,20,000
     ☑ P1  EDIBLE OIL  Cargo Handling (CHGU01)  4950 MT × 50.00 = ₹2,47,500
     ☑ P1  EDIBLE OIL  Infrastructure (INFM01)  4950 MT × 10.00 = ₹49,500
     ☐ P2  EDIBLE OIL  Cargo Handling (CHGU01)  … (rate 0 → enter manually)
                              Selected total: ₹ …   [ Generate Bill ]
```

- One accordion per vessel; header shows VCN doc/vessel, LDUD status, vessel
  billable total. Expand → charge lines with checkboxes, editable qty (≤ remaining)
  and rate, live line/vessel/selected totals.
- "Generate Bill" posts the checked lines (each carrying cargo_source_type/id +
  service_type_id) — the write path is #4; this sub-project renders + selects.
- Lines with rate 0 (no agreement rate found) are flagged; existing "don't bill at
  0 rate" guard carries into #4.

## Testing

Engine self-check (dev DB, throwaway VCN+LDUD Closed + parcels): a parcel with
equipment + toll yields 4 lines (Cargo Handling, Infra, MLA, Toll) with correct
service codes and remaining = qty; a parcel without equipment/toll yields 2;
grouping is by vessel; after a ledger `record_parcel_charge` the remaining drops
and a fully-billed charge disappears; a VCN whose LDUD is Draft yields nothing.

## Out of scope

Bill writing + ledger recording (#4), FINV01 invoicing (#5), the frontend
billed-lock banner (VCN), `service_records`/other-services billing, MBC.
