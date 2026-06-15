# VCN01 Parcel System — Design

**Date:** 2026-06-15
**Module:** VCN01 (Vessel Call Number) + downstream LDUD01
**Status:** Approved for implementation (Phase 1)

## Goal

Make the **parcel** the atomic operational unit of the application. In liquid-bulk
shipping a parcel is one product, for one receiver, under one Bill of Lading, with a
nominated quantity and a tank/pipeline routing. Operations (unloading, surveys,
billing, demurrage) reference the parcel rather than re-deriving cargo/quantity.

The existing `vcn_consigners` sub-table is already one row per IGM (FORM III) line —
structurally a parcel. This design elevates it to a first-class parcel entity with a
stable identity, surfaces it in the UI as "Parcels", and links the most-used
downstream consumer (LDUD01 unloading) to it by parcel.

## Decisions (locked)

- **Scope:** cross-module parcel entity (a real `parcel_id` other modules reference).
- **Grain:** one parcel = product + receiver + BL (one per IGM line). Each
  `vcn_consigners` row already carries exactly one cargo, so no list-merging is needed.
- **Identifier:** per-VCN suffix `<vcn_doc_num>/P<seq>` (e.g. `VCN-2627-002/P1`) as the
  human label; the DB `id` is the cross-module foreign key (`parcel_id`).
- **Approach:** evolve `vcn_consigners` in place — **keep the table name**. No rename.
- **Phasing:** LDUD `parcel_id` link is in scope now; billing re-point, survey/ullage
  figures, discharged-vs-BL reconciliation, parcel lifecycle status, and
  demurrage/laytime attribution are deferred to follow-up specs.

## Data model

`vcn_consigners` (unchanged columns retained): `id`, `vcn_id`, `igm_line_no`, `bl_no`,
`bl_date`, `cargo_name`, `quantity`, `consigner_name` (receiver), `importer_name`
("Payment will be made by"), `pipeline_name`, `unload_terminal`.

New columns:

| Column | Type | Purpose |
|--------|------|---------|
| `parcel_seq` | INTEGER | Ordinal of the parcel within its vessel call (1, 2, 3 …) |
| `parcel_no`  | TEXT    | Stored display label `<vcn_doc_num>/P<seq>`, e.g. `VCN-2627-002/P1` |

Rules:
- `parcel_seq` is assigned on insert: `MAX(parcel_seq) for that vcn_id + 1`.
- `parcel_no` is computed from the parent `vcn_header.vcn_doc_num` + `parcel_seq` and
  stored (denormalized) so it is quotable on documents and stable.
- `id` remains the canonical cross-module key. Downstream tables store `parcel_id`
  (FK → `vcn_consigners.id`), not `parcel_no`.
- `igm_line_no` is retained as the IGM/FORM III reference (free text, e.g. "1-4");
  `parcel_seq` is the clean internal ordinal that drives `parcel_no`.

### LDUD link

`ldud_vessel_operations` gains a nullable `parcel_id INTEGER` referencing
`vcn_consigners.id`. New unloading-operation rows link to a specific parcel; legacy
rows keep `parcel_id` NULL and fall back to the existing cargo-name / BL-quantity
bridges already in place. No data is destroyed.

## Backend / API

- `model.get_parcels(vcn_id)` returns parcel rows including `parcel_no`/`parcel_seq`,
  ordered by `parcel_seq`. The existing `get_consigners`/`/consigners` endpoints remain
  as working aliases (back-compat) and now include the parcel fields.
- `model.save_consigner` (parcel save) assigns `parcel_seq` and `parcel_no` on insert;
  on update it preserves them. If a row's parent `vcn_doc_num` was blank at creation
  (draft) and later set, `parcel_no` is (re)generated on next save.
- A helper to (re)generate `parcel_no` from `vcn_header.vcn_doc_num` + `parcel_seq`,
  used by save and by the migration backfill.
- New endpoint `GET /api/module/VCN01/parcels/<vcn_id>` for LDUD's parcel picker,
  returning `{id, parcel_no, cargo_name, consigner_name, quantity}` per parcel.
- EV01 → VCN mover (`move_to_vcn`) already creates these rows via
  `build_consigner_rows`; numbering happens through the same save path so moved
  vessels get `parcel_no`s automatically.

## UI

VCN01 details modal, consigner sub-table:
- Section title "Consigner (Customer Details)" → **"Parcels"**.
- "+ Add Line" button → **"+ Add Parcel"**.
- New leading **Parcel No** column, read-only (system generated), showing `parcel_no`.
- All other columns unchanged, including the PLTM01 pipeline→terminal dependent
  multi-select and the IGM PDF upload/View buttons.

LDUD01 unloading sub-table (vessel operations):
- Add a **Parcel** column: a dropdown sourced from
  `GET /api/module/VCN01/parcels/<vcn_id>` showing `parcel_no — cargo — receiver`,
  storing `parcel_id`. Existing cargo-name column remains for display/back-compat.

## Migration (jnpa15)

Upgrade:
- `ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS parcel_seq INTEGER;`
- `ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS parcel_no TEXT;`
- Backfill per `vcn_id`: assign `parcel_seq` using the current display order
  (`ORDER BY (substring(igm_line_no from '^[0-9]+'))::int NULLS LAST, id`), then set
  `parcel_no = vcn_header.vcn_doc_num || '/P' || parcel_seq`.
- `ALTER TABLE ldud_vessel_operations ADD COLUMN IF NOT EXISTS parcel_id INTEGER;`

Downgrade: drop the three added columns.

## Out of scope (roadmap for later specs)

- Parcel lifecycle status (expected → discharging → completed).
- Ullage/survey ship & shore figures per parcel.
- Discharged-vs-BL quantity reconciliation (shortage/excess) per parcel.
- Demurrage / laytime attribution per parcel.
- Full billing re-point onto `parcel_id` (FIN01/FINV01/FDCN01). Billing continues to
  read import cargo as it does today until that spec lands.

## Risks / notes

- `parcel_no` denormalization: if a VCN's `vcn_doc_num` ever changes after parcels
  exist, `parcel_no`s must be regenerated. `vcn_doc_num` is assigned once and not
  edited, so this is low risk; the regenerate-on-save helper covers the draft→numbered
  transition.
- Back-compat: keeping the `vcn_consigners` name and the `/consigners` endpoints means
  no churn in the EV01 mover, the PLTM01 multi-select, or the existing LDUD/billing
  bridges. New behavior is additive.
