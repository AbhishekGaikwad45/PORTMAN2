# PORTMAN Finance Parity — SAP Correctness, Console, Cutover, LDUD Lock — Design

**Date:** 2026-09-01
**Status:** Approved (design), pending spec review
**Reference repo:** GitHub `shubhamshnd/PORTMAN` (PORTMAN2 is a subset of it)

## Problem

PORTMAN2 has diverged from the reference PORTMAN in the finance stack. Some
divergence is deliberate and correct (the parcel/LUEU01 billing model, the pro
forma stage); some is drift that costs money or hides failure. This design
brings PORTMAN2 to parity with PORTMAN on SAP payload correctness, the SAP
monitoring console, invoice/bill UI, the billing customer picker, and the
go-live Admin Cutover — and closes the one gate PORTMAN2 was always meant to
have but never got: a billed LDUD cannot be reopened.

## Already correct in PORTMAN2 — do not touch

Verified present and working. The reference has no equivalent for the first two;
nothing here may be back-ported over them:

- **Pro forma invoice** — `modules/FIN01/views.py:414` + `proforma_print.html`.
  Display-only by decision: no number, no series, no stored snapshot. Reprints
  from live declared quantities.
- **LUEU01 actual quantities** — `modules/FIN01/model.py:701` `_actual_qty_map()`
  reads `lueu_parcel_log`, excludes short-closes, pro-rates merged ops by
  declared parcel quantity. `get_customer_billables()` switches a vessel from
  `proforma` to `actual` once its latest LDUD is Closed/Partial Close.
- **Billed ledger** — `parcel_charge_billed` (migration `jnpa38`) is the
  authoritative billed-status store. The legacy `is_billed` / `billed_quantity`
  columns on the declaration tables are **no-ops** here.
- **FDCN01 doc series** — PORTMAN2 folded the series editor into FDCN01;
  PORTMAN keeps a separate CNDS01 module. Valid divergence, left alone.
- **`sap_queue` TEXT-column time formatting** — a correct local adaptation to
  `jnpa40_sap_tables`, not drift. Keep.

**Baseline to preserve:** 92 tests pass. `test_vcn01_export_parcels.py` and
`test_vcn_billed_lock.py` each have one pre-existing failure over VCN01 closure
message wording. Both are out of scope and must still fail the same way — do
not "fix" them as a side effect.

## Constraints

- The SAP payload contract is fixed by the remote. Changes below correct
  PORTMAN2 *toward* the reference's payload; no new SAP business logic.
- MBC does not exist in PORTMAN2. Every ported artefact drops it.
- Live SAP posting is not testable here (no creds/endpoint). Test payload
  construction, queue mechanics and inbound token verification only.
- Pro forma stays display-only. No `proforma_header` table, no PI series.

---

## A. SAP payload correctness

Files: `sap_builder.py`, `einvoice_builder.py`, `sap_client.py`,
`modules/SAPCFG/model.py`, `modules/FINV01/views.py`, `modules/FDCN01/views.py`,
`modules/FINV01/finv01_invoices.html`, `modules/FDCN01/fdcn01_list.html`,
plus one migration.

### A1. One ITEM per GL account

Port `_merge_same_gl_items` with `_MERGE_SUM_FIELDS` and `_MERGE_SKIP_FIELDS`
(reference `sap_builder.py:199`). Call it in `_build_items` **before** round-off
placement, so round-off lands on the first *merged* item. Amount and
GST/TDS/TCS sum; Quantity sums only when every merged line has one; Unit_Price
survives only if uniform, else blank (Amount is authoritative).

### A2. Invoice_Amount from components

`_total_invoice_amount` currently reads `header.total_amount`. Rebuild it as
`subtotal + cgst + sgst + igst`, then add TDS, subtract TCS, add round-off.

*Honest scope note:* PORTMAN2's `total_amount` is subtotal+GST only today
(`model.py:676`; `create_invoice_record` sums bill totals and stores TCS
separately), so this is **not** a live miscalculation. It is hardening against
exactly the convention shift that already broke the reference, where
`total_amount` grew to include TCS and double-counted it here.

### A3. CN/DN header text

`Document_Header_Text` becomes `doc_number or reference` so a credit/debit note
is identifiable in SAP even though its `Reference` is the parent invoice.

### A4. e-Invoice ValDtls — live IRP rejection

`einvoice_builder` omits TCS and round-off from `ValDtls`. The IRP validates
`TotInvVal ~= AssVal + taxes + OthChrg` and rejects the payload. Set
`OthChrg` = `tcs_amount`, `RndOffAmt` = `round_off`, and include both in
`TotInvVal`.

### A5. Split the SAP tax code

`sap_api_config.tax_code` becomes `igst_tax_code` + `cgst_tax_code`. Migration
adds both, backfills each from `tax_code`, drops `tax_code`; downgrade reverses
using `cgst_tax_code`. `modules/SAPCFG/model.py` save/read and the SAPCFG form
follow. `_build_items` picks the code by whether the line carries IGST or
CGST/SGST.

### A6. Remove fetch-IRN

The reference deleted `fetch_irn_from_sap`: SAP PI exposes no IRN GET; IRN and
ack details arrive only through the inbound callback (`sap_inbound.py`).
PORTMAN2 still ships the function, `/api/module/FINV01/invoice/fetch-irn`,
`/api/module/FDCN01/fetch-irn`, and Fetch IRN buttons in both list templates.
Remove all six — they are controls that silently fail.

---

## B. FSAP01 console + queue scheduler

Files: `modules/FSAP01/model.py`, `modules/FSAP01/views.py`,
`modules/FSAP01/fsap01.html`, `app.py`.

PORTMAN2's FSAP01 is a single invoice-log page; the reference is a four-tab
console. Port:

- **model:** `get_callback_logs`, `get_outbound_logs(type_filter)`,
  `get_sap_queue(status)`
- **views:** `/api/module/FSAP01/callback-logs`, `/outbound-logs`, `/sap-queue`,
  `/sap-queue/manual-send` (POST, `can_edit`, delegates to
  `sap_queue.manual_send`)
- **template:** the tab strip and the three missing panels — SAP Callbacks, SAP
  Outbound Log, SAP Queue — with the reference's tab CSS and JSON
  request/response modal. Header becomes "SAP Integration".

**Queue scheduler.** `app.py` registers a mail tick but no SAP tick, so
`sap_outbound_queue` only drains when somebody clicks. Add a `_sap_queue_tick`
job calling `process_sap_queue()` on the existing BackgroundScheduler, mirroring
the reference's registration.

---

## C. UI/UX match

### C1. `indian_number` filter

The filter does not exist in PORTMAN2 at all. Port the template filter into
`app.py`, then switch every money cell in `finv01_invoice_print.html` to it
(line rate/amount, subtotal, SAC summary, CGST/SGST/IGST, TDS, TCS, round-off,
total).

### C2. Invoice print

Lift the type scale to the reference's (roughly 2x throughout — the current
7-9px body is a stale pre-readability-pass version), QR 60px to 100px. Port the
"GST details not yet received" banner, the raw-base64 QR canvas fallback, and
`gst_ack_date.strftime` for the now-typed date column.

### C3. Invoice list

Inline SAP queue status per row (job type, status, retry n/max, `last_error` as
title). Status-aware actions: Send Now when queued, Manual Send when retries are
exhausted, Manual Send (job_type) for a failed non-post job. Print becomes
Print / Print (no GST) / Print (draft) by IRN and SAP-doc state. Richer confirm
text on cancel/CN explaining that linked bills are cancelled and cargo returns
to unbilled.

### C4. FIN01 bill screens

Port `quantity_totals(lines)` into the model; `view_bill` passes `qty_totals`
and `bill_view.html` renders the per-UOM quantity footer plus TDS Deducted (-)
and TCS Collected (+) rows. `bills.html` gains the TCS column.

---

## D. LDUD01 billed lock

Files: `modules/LDUD01/views.py`, `modules/LDUD01/model.py`.

Today `reopen()` (`views.py:242`) checks only the approver. `is_vcn_billed()`
exists and VCN01 uses it (`VCN01/views.py:22`); LDUD01 never calls it. A billed
vessel can be sent back to Draft and its parcel ops edited, silently desyncing
the quantities the bill was computed from.

Add `_billed_locked(ldud_id)` resolving the LDUD's `vcn_id` then calling
`fin_model.is_vcn_billed`. Return 409 from: `reopen`, `save`,
`parcel_ops/save`, `parcel_ops/delete`, `delete`.

The 409 message names the blocking document, resolved from the ledger rows for
this VCN's parcels: the distinct `bill_number`s behind their `bill_id`s, or
"cutover-flagged at go-live" when every blocking row has `bill_id` NULL (see
F3). Both cases can co-occur; name both.

**Admin override**, on `reopen` only: `session.get('is_admin')` may force a
reopen, but must supply a reason, and the action is logged to `approval_log` as
`'Force Reopen (Billed)'` so it surfaces in the closure log. Non-admins get the
409 regardless of approver status.

**Two unlock paths, both outside LDUD01.** A real bill: cancel its invoice —
`unbill_invoice_sources` calls `void_bill_charges`, clearing the ledger rows and
releasing the lock. A cutover flag: unmark it in the Admin Cutover tab. LDUD01
itself never clears the ledger; the admin override changes `doc_status` only and
leaves the lock in place, so the vessel stays locked against the *other* four
write paths until the ledger is actually cleared.

---

## E. Billing customer picker

Files: `modules/FIN01/views.py`, `modules/FIN01/generate_bill.html`.

The picker lists the entire customer/agent master. The reference filters to
parties with something to bill and labels each with a count.

Add `?with_billables=1` to `/api/module/FIN01/customers/<type>`. The reference's
`_BILLABLE_CARGO_COUNT` cannot be reused as-is — it counts
`vcn_cargo_declaration` and `mbc_customer_details` by `customer_name` off the
legacy `is_billed` columns. The PORTMAN2 query instead:

- counts `vcn_consigners` and `vcn_export_cargo_declaration`, joined to
  `vcn_header`, keyed on `importer_name` (the payer)
- takes remaining quantity from `parcel_charge_billed`, never the dead columns
- counts **parcels with quantity still to bill**, not parcels outright: a parcel
  is counted when its declared (pro forma) or LUEU01-actual (actual) quantity
  exceeds what the ledger already records for it, using the same `1e-6`
  tolerance as `get_customer_billables`. A partially-billed parcel therefore
  still counts; a fully-billed one does not.
- returns **two** counts per party: `actual_count` (latest LDUD Closed/Partial
  Close) and `proforma_count` (VCN Approved, LDUD open)
- keeps parties with either count > 0, ordered `actual_count DESC, name`

The counts are parcel counts, not charge counts — a parcel yielding four
charges counts once, so the number matches what the vessel list shows.

Dropdown renders `Name (3 actual · 2 pro forma)`, omitting a zero half. The
unfiltered list stays the default response: Admin Cutover's picker needs the
full master, because it works on cargo that is already flagged billed.

---

## F. Admin Cutover

Files: `modules/ADMIN/cutover.py` (new), `modules/ADMIN/views.py`,
`templates/admin.html`, `modules/FIN01/model.py`, `modules/FIN01/views.py`,
`modules/FDCN01/model.py`, plus one migration.

Absent from PORTMAN2 entirely. It is the go-live feature that lets PORTMAN2
continue document numbering from wherever the legacy system stopped, flag
already-invoiced legacy cargo so it is never re-billed, and freeze both once
go-live data is final.

### F1. Migration

`cutover_seed` (seed_type, doc_series, financial_year, start_seq, created_by,
updated_by, updated_at; unique on the three-part key) and `cutover_audit`
(action, details JSON, performed_by, performed_at). Column definitions copied
from the reference's `d5e6f7a8b9c0_cutover_tables` and `cut0seedfdcn1`.

### F2. Seed helpers in FIN01 model

Port `would_overbill`, `next_from_seed`, `lookup_seed`, `next_invoice_seq`.
`lookup_seed` must tolerate a missing table (pre-migration) by rolling back and
returning None. Wire the seed as a **floor only** into `get_next_bill_number`
(which gains an optional `cur` parameter), invoice numbering, and FDCN
numbering — once real documents pass the seed, normal incrementing wins, so a
stale seed can never collide.

`would_overbill` additionally becomes a guard in bill generation, blocking a
stale page or double-submit from billing the same parcel twice while still
permitting legitimate partial billing. PORTMAN2 has no such guard today.

### F3. cutover.py — the parcel adaptation

`validate_start_seq`, `compute_partial_billed`, `is_locked`/`set_lock`,
`write_audit`, `get_seeds`, `set_invoice_seed`/`set_bill_seed`/`set_fdcn_seed`,
`mark_items_billed` port with two substantive changes:

1. `CARGO_SOURCES` retargets to `vcn_consigners` and
   `vcn_export_cargo_declaration` (quantity column `quantity`), no MBC entry.
2. `mark_items_billed` must **not** write `is_billed`/`billed_quantity` — they
   are no-ops here. It writes `parcel_charge_billed` rows with `bill_id` NULL,
   which is what makes a row "cutover-flagged: billed with no bill behind it".
   Unmarking deletes exactly those NULL-`bill_id` rows, so a cutover reopen can
   never delete a genuine bill's ledger entry.

Since the ledger is what `is_vcn_billed()` reads, cutover-flagging a parcel also
locks its VCN and LDUD — which is the intended go-live behaviour.

`is_locked()` gates every write in this module.

### F4. Admin UI

A Cutover tab in `admin.html`: locked banner, three seed forms (invoice / bill /
FDCN, each showing the current max and rejecting a start <= it), the
billed-cargo picker with its "Cutover-flagged (no bill) — reopen to make
billable again" section scoped to its own button, and the lock toggle. Routes
`/admin/api/cutover/{state,invoice-seed,bill-seed,fdcn-seed,mark-billed,lock}`,
admin-only.

---

## Testing

**Unit (no DB, no network):**

- `_merge_same_gl_items`: two same-GL items collapse with summed amounts;
  differing `Unit_Price` blanks it; a missing Quantity on either side blanks it;
  different GL stays separate.
- `_total_invoice_amount`: header with TCS present yields taxable+GST+TDS-TCS+RO.
- `einvoice_builder`:
  `TotInvVal == AssVal + CgstVal + SgstVal + IgstVal + OthChrg + RndOffAmt`.
- `next_from_seed` (seed as floor, stale seed ignored), `validate_start_seq`
  (non-int, zero, <= current max), `compute_partial_billed` (partial, full,
  over-cap, >3dp quantity), `would_overbill` (tolerance boundary).

**Integration (throwaway rows, rolled back):**

- Billed vessel: LDUD `reopen` returns 409; each guarded write returns 409;
  admin override with a reason succeeds and writes `'Force Reopen (Billed)'`.
- Picker: a customer with no parcels is absent; one with an open LDUD returns
  `proforma_count > 0, actual_count == 0`; one with a closed LDUD reverses that;
  a fully-billed customer drops out.
- Cutover: `mark_items_billed` writes a NULL-`bill_id` ledger row that
  `is_vcn_billed()` sees; unmark removes it and leaves a real bill's row intact;
  every write refuses while locked.
- Seeded numbering: with a bill seed of N, the next bill number is N; after
  documents pass N, incrementing resumes normally.
- FSAP01: each new endpoint returns a paginated envelope; `manual-send` refuses
  without `can_edit`.

**Manual, in your environment (documented, not automated):** live SAP OAuth,
post, reversal, and an inbound callback delivering an IRN.

## Out of scope

MBC in any form; the two pre-existing VCN01 closure-message test failures; a
persisted pro forma; RP01's reports against the dropped LDUD/LUEU tables;
changes to the SAP payload contract itself.
