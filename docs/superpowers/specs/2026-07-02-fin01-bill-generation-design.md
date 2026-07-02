# FIN01 Bill Generation (multi-vessel) — Design

**Date:** 2026-07-02
**Status:** Approved (design), pending spec review
**Program:** Finance/AR overhaul, sub-project #4. Depends on #1 (system services),
#2 (`parcel_charge_billed` ledger + billed-lock), #3 (billables engine + vessel UI),
all merged to main. Followed by #5 (FINV01 invoicing) and #6 (FSAP01 SAP integration).

## Problem

#3 shows billable charges per vessel but "Generate Bill" is a stub. #4 writes the
bill: the accounts user selects charge lines **across multiple vessels** and
generates **one bill**, which records the parcel ledger (activating the VCN
billed-lock from #2). Reuse the existing bill-save machinery; **exclude MBC**
(not part of this system) wherever the reference has an MBC branch.

## What already exists (reuse, don't rebuild)

- `save_bill_header(data) -> (id, bill_number)` — numbering + insert/update.
- `save_bill_line(data)` — **server-side GST/TDS calc already present**: from
  `gst_rate_id` + customer vs port state (`port_gst_state_code` in FIN01 config)
  it computes CGST+SGST (intra) or IGST (inter); `tds_amount = tds_percent% ×
  line_amount`; `line_total = line_amount + GST`. This is the "calculation logic
  that won't change" — do not reimplement.
- `record_parcel_charge(cur, cargo_source_type, cargo_source_id, service_type_id,
  service_code, bill_id, billed_quantity, created_by)` (from #2).
- Approval config + `_queue_bill_approval_request(...)`.
- `get_customer_billables(...)` (#3) — the source of selectable lines.

## Design

### 1. Data model (Alembic)

New `bill_vessels` mapping table (one bill spans many VCNs):
```
id        SERIAL PK
bill_id   INTEGER NOT NULL REFERENCES bill_header(id) ON DELETE CASCADE
vcn_id    INTEGER NOT NULL REFERENCES vcn_header(id)
```
Index on `bill_id`. Populated on generate from the distinct VCNs behind the
selected lines; consumed by #5 (invoice grouping) and to list a bill's vessels.

### 2. Backend — `generate_bill(payload)` in FIN01/model.py + endpoint

`POST /api/module/FIN01/bill/generate` with:
```
{ customer_type, customer_id, customer_name, customer_gstin,
  customer_gst_state_code, customer_gl_code, agreement_id?,
  lines: [ { cargo_source_type ('VCN_IMPORT'|'VCN_EXPORT'), cargo_source_id,
             vcn_id, service_type_id, service_code, service_name, cargo_name,
             quantity, rate, gst_rate_id, sac_code, gl_code,
             tds_applicable, tds_percent } ] }
```
Model `generate_bill(data, created_by, bill_status)` — one transaction:
1. Insert `bill_header` (`source_type='MULTI'`, `source_id=NULL`,
   `source_display` = comma-joined distinct VCN doc-nums, customer fields,
   `agreement_id`, `bill_status`) via `save_bill_header`.
2. For each line: `line_amount = quantity × rate`; pass through `save_bill_line`
   (which computes GST/TDS from `gst_rate_id` + customer/port state); accumulate
   subtotal + CGST + SGST + IGST.
3. `UPDATE bill_header` totals (`total_amount = subtotal + all GST`; TDS stored
   per line, not subtracted).
4. `record_parcel_charge(cur, line.cargo_source_type, line.cargo_source_id,
   line.service_type_id, line.service_code, bill_id, line.quantity, created_by)`
   per line → ledger.
5. Insert `bill_vessels` rows for the distinct `vcn_id`s.
Return `{id, bill_number}`.

Endpoint sets `bill_status` via approval config ('Pending Approval' vs 'Draft'),
queues the approval mail when pending, and guards permissions like `save_bill`.
Validate: reject lines with `rate <= 0` (no agreement rate) with a clear error.

**No MBC:** do not add any `MBC` cargo_source branch; only `VCN_IMPORT`/`VCN_EXPORT`.

### 3. Frontend — vessel accordions → generate

`modules/FIN01/generate_bill.html`: the checked lines across **all** expanded
vessels are collected (each already carries `cargo_source_type/id`,
`service_type_id`, `service_code`, `qty`, `rate`, `gst_rate_id`, `sac_code`, tds
from the engine; attach the line's `vcn_id`). "Generate Bill" posts them + the
customer GST context (from the existing customer/port-config lookups the page
already uses) to `/bill/generate`, shows the returned bill number, and reloads the
billables (billed lines drop out via ledger remaining). Keep the existing 0-rate
guard client-side.

## Testing

Model test (dev DB, throwaway customer + two VCNs each with a Closed LDUD + a
parcel): call `generate_bill` with lines from **both** vessels; assert one
`bill_header` (source_type='MULTI'), the right number of `bill_lines` with GST/TDS
populated by `save_bill_line`, `bill_vessels` has both VCNs, and
`is_vcn_billed(vcn)` is true for both afterwards; a second `get_customer_billables`
no longer offers the billed lines.

## Out of scope

FINV01 invoicing (#5); FSAP01 SAP push (#6); MBC (excluded entirely); editing/
cancelling generated bills beyond what `save_bill`/`void_bill_charges` already do.
