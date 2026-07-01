# VCN01 Export Parcels = Import Parcels (minus BL) — Design

**Date:** 2026-07-01
**Status:** Approved (design), pending spec review
**Scope:** VCN01 export parcels only. This is sub-project #1 of a larger program
(replicate the Import parcel process for Export across VCN01, LDUD01, LUEU01;
plus an FSTM01 service-master overhaul). Those other sub-projects are **out of
scope** here and get their own spec → plan → build.

## Problem

Export parcels in VCN01 use a different, legacy shape than import parcels. The
import parcels table (`vcn_consigners`) carries the operational fields billing
needs — pipeline, unload terminal, toll, equipment, consignee, payer — while the
export table (`vcn_export_cargo_declaration`) only has legacy EGM/shipping-bill
fields, customer, and a bare quantity. Downstream (LUEU01, LDUD01) hardcode
`NULL` for the missing export columns.

Goal: make an export parcel the **same form as an import parcel, minus BL No and
BL Date** (both legacy EGM/shipping-bill fields are dropped entirely).

## Constraints

- **The import cycle must not be affected.** `vcn_consigners` and its
  save/load/delete path are read-only reference here (we reuse its column list);
  no import code path changes behavior.
- Migrations are done via **Alembic** (`alembic.ini`, `alembic/env.py` present).
- Dev database: legacy export rows are **dropped**, not migrated.
- No MBC anywhere.

## Reference: import parcel columns

`_CONSIGNER_COLS` in [modules/VCN01/model.py](../../../modules/VCN01/model.py) lines 132–135:

```
igm_line_no, bl_no, bl_date, cargo_name, quantity,
consigner_name, importer_name,
pipeline_name, unload_terminal,
toll_applicable, toll_reason, equipment_names
```

Plus system columns: `id, vcn_id, parcel_seq, parcel_no`.

## Design

### 1. Data model — Alembic migration

Drop `vcn_export_cargo_declaration` and recreate it **under the same name** with
the import column set minus BL fields. Same name = downstream `FROM` clauses
still resolve (only their column expectations break, which is their own later
pass).

New `vcn_export_cargo_declaration` columns:

```
id            (PK, serial)
vcn_id        (FK → vcn_header.id)   -- match existing FK/on-delete behavior of vcn_consigners
parcel_seq    integer
parcel_no     text
igm_line_no   text
cargo_name    text
quantity      numeric               -- mirror import name (NOT bl_quantity)
consigner_name text
importer_name text
pipeline_name text
unload_terminal text
toll_applicable boolean/int          -- match vcn_consigners type
toll_reason   text
equipment_names text
```

Column names, types, and FK/on-delete match `vcn_consigners` (minus `bl_no`,
`bl_date`). Confirm actual types by inspecting the `vcn_consigners` DDL during
implementation so the two tables stay type-identical.

### 2. Backend — [modules/VCN01/model.py](../../../modules/VCN01/model.py)

Add a shared, derived column list next to `_CONSIGNER_COLS`:

```python
_EXPORT_PARCEL_COLS = [c for c in _CONSIGNER_COLS if c not in ('bl_no', 'bl_date')]
```

Rewrite `save_export_cargo_declaration`, `get_export_cargo_declarations`, and
`delete_export_cargo_declaration` to use the same list-driven insert/update and
`parcel_seq`/`parcel_no` numbering logic as `save_consigner` — just against
`vcn_export_cargo_declaration` and `_EXPORT_PARCEL_COLS`. This removes the
bespoke EGM/customer/UOM SQL.

Fix any other model queries that reference dropped export columns
(`bl_quantity`, `egm_shipping_bill_*`, `customer_name`, `quantity_uom`) **within
VCN01 only**:
- `get_export_cargo_total_quantity` → `SUM(quantity)` instead of `SUM(bl_quantity)`.
- The terminals-derivation query (~line 226) that reads export as
  `NULL AS unload_terminal`: **leave as-is** this pass (it feeds LDUD terminal
  derivation, which is a later sub-project). Only fix what breaks VCN export CRUD.
- `_sync_header_cargo` already keys off `cargo_name`; unaffected.

Views (`modules/VCN01/views.py`) endpoints stay unchanged — they already proxy
to these three model functions.

### 3. Frontend — [modules/VCN01/vcn01.html](../../../modules/VCN01/vcn01.html)

The export Tabulator is defined at ~line 1234 inside `initSubTables`, in the same
scope as the consigners table (~line 1099). Replace the export column defs with a
copy of the consigners columns **minus BL No and BL Date**:

```
Parcel No | Ln | Cargo Name | Qty (MT) | Consignee | Payment will be made by |
Pipeline | Unload Terminal | Toll | Toll Reason | Equipment | (delete)
```

Reuse the exact same editors/helpers already in scope: `cargoOptions`,
`consignerOptions`, `pipelineNames`, `terminalsForRow`, `equipmentNames`,
`makeMultiSelectEditor`, `cargoPillFormatter`, the toll `tickCross` + prompt
cascade, and the pipeline→terminal `cellEdited` reset. Field names match
`_EXPORT_PARCEL_COLS` so saves post the right keys. Labels stay identical to
import ("Ln", "Consignee", "Payment will be made by") per "same form."

The export section header/div (~line 977) can keep its markup; only the column
config changes. `renderCargoQuotas` is import-only and stays gated to consigners.

### 4. Downstream impact (deferred — do NOT touch now)

- **LUEU01** [model.py:73-77](../../../modules/LUEU01/model.py) reads
  `bl_quantity` and NULLs equipment/pipeline/terminal for export → breaks on
  export until its pass.
- **LDUD01** reads `vcn_export_cargo_declaration` for export sources → same.
- **FIN01** export reads → same.

All acceptable per "fix export operations only in VCN first." Call out to the
user that export in those modules is knowingly broken between passes.

## Testing

One model-level self-check (no framework): within a transaction/dev DB, create an
export parcel via `save_export_cargo_declaration` with pipeline, toll, and
equipment set; read it back via `get_export_cargo_declarations`; assert those
columns round-trip; then update and re-assert. Fails if the new columns aren't
wired.

Manual smoke: open an Export VCN, add a parcel, set pipeline → terminal → toll →
equipment, Save, reload — values persist. Confirm an Import VCN's parcels behave
exactly as before (import-unaffected check).

## Out of scope

FSTM01 overhaul; LDUD01/LUEU01 export replication; bill/invoice generation;
MBC; migrating legacy export data.
