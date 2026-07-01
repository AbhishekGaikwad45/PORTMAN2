# VCN01 Export Parcels = Import Parcels (minus BL) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a VCN01 export parcel the same form as an import parcel minus BL No / BL Date, so export carries the operational fields (pipeline, terminal, toll, equipment, consignee, payer) billing will later need.

**Architecture:** Recreate `vcn_export_cargo_declaration` via Alembic to mirror `vcn_consigners` (minus `bl_no`, `bl_date`); rewrite the three export model functions to reuse the import list-driven CRUD pattern; swap the export Tabulator column defs for a copy of the consigners columns minus the two BL columns.

**Tech Stack:** Flask, psycopg2, PostgreSQL, Alembic (`jnpaNN_*` migrations), Tabulator.js, pytest.

## Global Constraints

- **Import cycle must NOT be affected.** `vcn_consigners` and `save_consigner`/`get_consigners`/`delete_consigner` keep identical behavior. Only *read* `_CONSIGNER_COLS`.
- Column types mirror `vcn_consigners` exactly: all string columns `TEXT`, `quantity` is `TEXT` (not numeric), `toll_applicable` `BOOLEAN DEFAULT FALSE`, `parcel_seq` `INTEGER`, `id` serial PK, `vcn_id INTEGER NOT NULL REFERENCES vcn_header(id) ON DELETE CASCADE`.
- Export parcel columns (order): `igm_line_no, cargo_name, quantity, consigner_name, importer_name, pipeline_name, unload_terminal, toll_applicable, toll_reason, equipment_names`.
- Legacy columns dropped entirely: `egm_shipping_bill_number/date, customer_name, bl_quantity, quantity_uom, is_billed, bill_id, billed_quantity`.
- Migration id: `jnpa35_export_parcels_mirror_import`, `down_revision = 'jnpa34_ldud_pilot_pickup_time'`.
- No MBC. Legacy export data is dropped, not migrated (dev DB).
- DB URL for local runs: `postgresql://postgres:password@localhost:5432/portman_jnpa`.

---

### Task 1: Alembic migration — recreate export table mirroring import

**Files:**
- Create: `alembic/versions/jnpa35_export_parcels_mirror_import.py`

**Interfaces:**
- Produces: table `vcn_export_cargo_declaration` with columns listed in Global Constraints. Consumed by Task 2.

- [ ] **Step 1: Write the migration file**

Create `alembic/versions/jnpa35_export_parcels_mirror_import.py`:

```python
"""jnpa phase1 - recreate vcn_export_cargo_declaration mirroring vcn_consigners (minus BL)

Export parcels become the same shape as import parcels: they gain the
operational fields (igm_line_no, quantity, consigner_name, importer_name,
pipeline_name, unload_terminal, toll_applicable, toll_reason, equipment_names)
and drop the legacy EGM / customer / UOM / billing-tracking columns. No BL No or
BL Date on export. Legacy export rows are dropped (dev cutover, not migrated).

Revision ID: jnpa35_export_parcels_mirror_import
Revises: jnpa34_ldud_pilot_pickup_time
Create Date: 2026-07-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa35_export_parcels_mirror_import'
down_revision: Union[str, None] = 'jnpa34_ldud_pilot_pickup_time'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('DROP TABLE IF EXISTS vcn_export_cargo_declaration CASCADE;')
    op.execute('''
        CREATE TABLE vcn_export_cargo_declaration (
            id              SERIAL PRIMARY KEY,
            vcn_id          INTEGER NOT NULL REFERENCES vcn_header(id) ON DELETE CASCADE,
            parcel_seq      INTEGER,
            parcel_no       TEXT,
            igm_line_no     TEXT,
            cargo_name      TEXT,
            quantity        TEXT,
            consigner_name  TEXT,
            importer_name   TEXT,
            pipeline_name   TEXT,
            unload_terminal TEXT,
            toll_applicable BOOLEAN DEFAULT FALSE,
            toll_reason     TEXT,
            equipment_names TEXT
        );
    ''')


def downgrade() -> None:
    # Best-effort restore of the legacy shape (data is not recoverable).
    op.execute('DROP TABLE IF EXISTS vcn_export_cargo_declaration CASCADE;')
    op.execute('''
        CREATE TABLE vcn_export_cargo_declaration (
            id                       SERIAL PRIMARY KEY,
            vcn_id                   INTEGER NOT NULL REFERENCES vcn_header(id) ON DELETE CASCADE,
            egm_shipping_bill_number TEXT,
            egm_shipping_bill_date   TEXT,
            cargo_name               TEXT,
            customer_name            TEXT,
            bl_no                    TEXT,
            bl_date                  TEXT,
            bl_quantity              REAL,
            quantity_uom             TEXT,
            is_billed                INTEGER DEFAULT 0,
            bill_id                  INTEGER,
            billed_quantity          REAL DEFAULT 0,
            parcel_seq               INTEGER,
            parcel_no                TEXT
        );
    ''')
```

- [ ] **Step 2: Apply the migration**

Run: `alembic upgrade head`
Expected: output ends with `Running upgrade jnpa34_ldud_pilot_pickup_time -> jnpa35_export_parcels_mirror_import`

- [ ] **Step 3: Verify the new schema**

Run:
```bash
python -c "import psycopg2; c=psycopg2.connect('postgresql://postgres:password@localhost:5432/portman_jnpa'); cur=c.cursor(); cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='vcn_export_cargo_declaration' ORDER BY ordinal_position\"); print([r[0] for r in cur.fetchall()])"
```
Expected: `['id', 'vcn_id', 'parcel_seq', 'parcel_no', 'igm_line_no', 'cargo_name', 'quantity', 'consigner_name', 'importer_name', 'pipeline_name', 'unload_terminal', 'toll_applicable', 'toll_reason', 'equipment_names']`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/jnpa35_export_parcels_mirror_import.py
git commit -m "feat(vcn01): recreate export cargo table mirroring import parcels (minus BL)"
```

---

### Task 2: Backend model — list-driven export parcel CRUD

**Files:**
- Modify: `modules/VCN01/model.py` (the `_CONSIGNER_COLS` block ~132-135; `get_export_cargo_declarations`/`save_export_cargo_declaration`/`delete_export_cargo_declaration` ~419-473; `get_export_cargo_total_quantity` ~483-489)
- Create: `tests/test_vcn01_export_parcels.py`

**Interfaces:**
- Consumes: table from Task 1; `_CONSIGNER_COLS`, `_parcel_no`, `_clean_empty`, `_sync_header_cargo` (existing in model.py).
- Produces: `_EXPORT_PARCEL_COLS` list; `save_export_cargo_declaration(data)->int`, `get_export_cargo_declarations(vcn_id)->list[dict]`, `delete_export_cargo_declaration(row_id)->vcn_id`, `get_export_cargo_total_quantity(vcn_id)->float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vcn01_export_parcels.py`:

```python
"""Round-trip check for VCN01 export parcels after mirroring the import shape.
Uses the dev DB directly (get_db is a plain psycopg2 connection). Creates a
throwaway Export vcn_header and deletes it (ON DELETE CASCADE cleans parcels)."""
from database import get_db, get_cursor
from modules.VCN01 import model


def _make_export_vcn(cur):
    cur.execute("INSERT INTO vcn_header (operation_type) VALUES ('Export') RETURNING id")
    return cur.fetchone()['id']


def test_export_parcel_cols_mirror_import_minus_bl():
    assert model._EXPORT_PARCEL_COLS == [
        'igm_line_no', 'cargo_name', 'quantity', 'consigner_name', 'importer_name',
        'pipeline_name', 'unload_terminal', 'toll_applicable', 'toll_reason',
        'equipment_names',
    ]


def test_export_parcel_roundtrip():
    conn = get_db(); cur = get_cursor(conn)
    vcn_id = _make_export_vcn(cur); conn.commit(); conn.close()
    try:
        rid = model.save_export_cargo_declaration({
            'vcn_id': vcn_id, 'cargo_name': 'EDIBLE OIL', 'quantity': '100.5',
            'consigner_name': 'ABS', 'importer_name': 'ABS',
            'pipeline_name': 'PL1', 'unload_terminal': 'T1, T2',
            'toll_applicable': True, 'toll_reason': '', 'equipment_names': 'CRANE',
        })
        rows = model.get_export_cargo_declarations(vcn_id)
        assert len(rows) == 1
        r = rows[0]
        assert r['cargo_name'] == 'EDIBLE OIL'
        assert r['pipeline_name'] == 'PL1'
        assert r['unload_terminal'] == 'T1, T2'
        assert r['toll_applicable'] is True
        assert r['equipment_names'] == 'CRANE'
        assert r['parcel_seq'] == 1

        model.save_export_cargo_declaration({'id': rid, 'vcn_id': vcn_id,
            'cargo_name': 'EDIBLE OIL', 'quantity': '200', 'pipeline_name': 'PL2'})
        r2 = model.get_export_cargo_declarations(vcn_id)[0]
        assert r2['quantity'] == '200'
        assert r2['pipeline_name'] == 'PL2'
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute('DELETE FROM vcn_header WHERE id=%s', [vcn_id])
        conn.commit(); conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vcn01_export_parcels.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_EXPORT_PARCEL_COLS'` and the round-trip errors because the old save ignores the new columns.

- [ ] **Step 3: Add the derived column list**

In `modules/VCN01/model.py`, immediately after the `_CONSIGNER_COLS` definition (~line 135), add:

```python
# Export parcels mirror import parcels minus the BL fields (see spec
# 2026-07-01-vcn01-export-parcels). Same list-driven CRUD, different table.
_EXPORT_PARCEL_COLS = [c for c in _CONSIGNER_COLS if c not in ('bl_no', 'bl_date')]
```

- [ ] **Step 4: Rewrite the three export functions**

Replace `get_export_cargo_declarations`, `save_export_cargo_declaration`, and `delete_export_cargo_declaration` (currently ~419-473) with:

```python
def get_export_cargo_declarations(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM vcn_export_cargo_declaration WHERE vcn_id=%s ORDER BY parcel_seq NULLS LAST, id', (vcn_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_export_cargo_declaration(data):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute(f"UPDATE vcn_export_cargo_declaration SET {', '.join(f'{c}=%s' for c in _EXPORT_PARCEL_COLS)} WHERE id=%s",
                    [data.get(c) for c in _EXPORT_PARCEL_COLS] + [data['id']])
        row_id = data['id']
        cur.execute('SELECT parcel_seq, parcel_no FROM vcn_export_cargo_declaration WHERE id=%s', [row_id])
        cur_row = cur.fetchone()
        if cur_row and cur_row['parcel_seq'] and not cur_row['parcel_no']:
            cur.execute('UPDATE vcn_export_cargo_declaration SET parcel_no=%s WHERE id=%s',
                        [_parcel_no(cur, data['vcn_id'], cur_row['parcel_seq']), row_id])
    else:
        cur.execute('SELECT COALESCE(MAX(parcel_seq), 0) + 1 AS nxt FROM vcn_export_cargo_declaration WHERE vcn_id=%s',
                    [data['vcn_id']])
        seq = cur.fetchone()['nxt']
        parcel_no = _parcel_no(cur, data['vcn_id'], seq)
        cols = _EXPORT_PARCEL_COLS + ['parcel_seq', 'parcel_no']
        vals = [data.get(c) for c in _EXPORT_PARCEL_COLS] + [seq, parcel_no]
        cur.execute(f'''INSERT INTO vcn_export_cargo_declaration (vcn_id, {', '.join(cols)})
                       VALUES ({', '.join(['%s'] * (len(cols) + 1))}) RETURNING id''',
                    [data['vcn_id']] + vals)
        row_id = cur.fetchone()['id']
    _sync_header_cargo(cur, data.get('vcn_id'))
    conn.commit()
    conn.close()
    return row_id


def delete_export_cargo_declaration(row_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT vcn_id FROM vcn_export_cargo_declaration WHERE id=%s', (row_id,))
    r = cur.fetchone()
    vcn_id = r['vcn_id'] if r else None
    cur.execute('DELETE FROM vcn_export_cargo_declaration WHERE id=%s', (row_id,))
    _sync_header_cargo(cur, vcn_id)
    conn.commit()
    conn.close()
    return vcn_id
```

- [ ] **Step 5: Fix the quantity aggregate**

Replace `get_export_cargo_total_quantity` (~483-489). The column is now `quantity` (TEXT), so cast for summing:

```python
def get_export_cargo_total_quantity(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT COALESCE(SUM(NULLIF(quantity, '')::numeric), 0) AS s FROM vcn_export_cargo_declaration WHERE vcn_id=%s", (vcn_id,))
    result = cur.fetchone()['s']
    conn.close()
    return float(result or 0)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_vcn01_export_parcels.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Confirm import path untouched**

Run: `git diff modules/VCN01/model.py`
Expected: only the export functions, `_EXPORT_PARCEL_COLS`, and `get_export_cargo_total_quantity` changed. `save_consigner`, `get_parcels`/`get_consigners`, `delete_consigner`, and `_CONSIGNER_COLS` are unchanged.

- [ ] **Step 8: Commit**

```bash
git add modules/VCN01/model.py tests/test_vcn01_export_parcels.py
git commit -m "feat(vcn01): export parcel CRUD mirrors import (list-driven)"
```

---

### Task 3: Frontend — export Tabulator mirrors import columns

**Files:**
- Modify: `modules/VCN01/vcn01.html` (export Tabulator column defs ~1241-1264)

**Interfaces:**
- Consumes: `save_export_cargo_declaration` field names from Task 2 (`igm_line_no, cargo_name, quantity, consigner_name, importer_name, pipeline_name, unload_terminal, toll_applicable, toll_reason, equipment_names`); in-scope helpers `cargoOptions, consignerOptions, pipelineNames, terminalsForRow, equipmentNames, makeMultiSelectEditor, cargoPillFormatter, canEdit, deleteButtonFormatter, isDark, markDirty, _splitMulti`.

- [ ] **Step 1: Replace the export column definitions**

In `modules/VCN01/vcn01.html`, inside `if (operationType === 'Export')` (the `subTables[vcnId].export_cargo = new Tabulator(...)` block, ~1241), replace the `columns: [ ... ]` array with a copy of the consigners columns minus BL No and BL Date:

```javascript
                columns: [
                    {title: "Parcel No", field: "parcel_no", width: 130, headerSort: false},
                    {title: "Ln", field: "igm_line_no", width: 70, widthGrow: 0, hozAlign: "center",
                        editor: canEdit ? "input" : false
                    },
                    {title: "Cargo Name", field: "cargo_name", widthGrow: 1.2, editor: canEdit ? "list" : false,
                        editorParams: {values: cargoOptions, autocomplete: true, allowEmpty: true, listOnEmpty: true}
                    },
                    {title: "Qty (MT)", field: "quantity", widthGrow: 0.8, hozAlign: "right",
                        editor: canEdit ? "number" : false, editorParams: {min: 0, step: 0.001},
                        cellEdited: function(cell) {
                            const v = cell.getValue();
                            if (v !== '' && v !== null && !isNaN(v)) {
                                const r = Math.round(parseFloat(v) * 1000) / 1000;
                                if (r !== parseFloat(v)) cell.setValue(r);
                            }
                        }
                    },
                    {title: "Consignee", field: "consigner_name", widthGrow: 1.3, editor: canEdit ? "list" : false,
                        editorParams: {values: consignerOptions, autocomplete: true, allowEmpty: true, listOnEmpty: true}
                    },
                    {title: "Payment will be made by", field: "importer_name", widthGrow: 1.4, editor: canEdit ? "list" : false,
                        editorParams: {values: consignerOptions, autocomplete: true, allowEmpty: true, listOnEmpty: true}
                    },
                    {title: "Pipeline", field: "pipeline_name", widthGrow: 1, formatter: cargoPillFormatter,
                        editor: canEdit ? "list" : false,
                        editorParams: {values: pipelineNames, autocomplete: true, allowEmpty: true, listOnEmpty: true},
                        cellEdited: function(cell) {
                            const row = cell.getRow();
                            const allowed = terminalsForRow(row.getData());
                            const kept = _splitMulti(row.getData().unload_terminal).filter(t => allowed.includes(t));
                            row.update({unload_terminal: kept.join(', ')});
                        }
                    },
                    {title: "Unload Terminal", field: "unload_terminal", widthGrow: 1.2,
                        formatter: function(cell) {
                            if (!_splitMulti(cell.getRow().getData().pipeline_name).length)
                                return '<span style="color:#cbd5e1;font-style:italic;">select pipeline first</span>';
                            return cargoPillFormatter(cell);
                        },
                        editor: canEdit ? makeMultiSelectEditor(cell => terminalsForRow(cell.getRow().getData())) : false,
                        editable: function(cell) { return canEdit && _splitMulti(cell.getRow().getData().pipeline_name).length > 0; }
                    },
                    {title: "Toll", field: "toll_applicable", width: 70, widthGrow: 0, hozAlign: "center",
                        formatter: "tickCross", formatterParams: {allowEmpty: true},
                        editor: canEdit ? "tickCross" : false, editorParams: {tristate: false},
                        cellEdited: function(cell) {
                            const row = cell.getRow();
                            if (cell.getValue()) { row.update({toll_reason: ''}); return; }
                            const reason = (prompt('Toll not applicable — enter the reason:', row.getData().toll_reason || '') || '').trim();
                            if (!reason) { cell.setValue(true); alert('Reason required — Toll kept applicable.'); return; }
                            row.update({toll_reason: reason});
                            markDirty('export_cargo');
                        }},
                    {title: "Toll Reason", field: "toll_reason", widthGrow: 1.2, editor: canEdit ? "input" : false,
                        formatter: function(cell) {
                            return cell.getRow().getData().toll_applicable ? '<span style="color:#cbd5e1">—</span>' : (cell.getValue() || '');
                        }},
                    {title: "Equipment", field: "equipment_names", widthGrow: 1.2, formatter: cargoPillFormatter,
                        editor: canEdit ? makeMultiSelectEditor(equipmentNames) : false},
                    canEdit ? {title: "", field: "actions", formatter: deleteButtonFormatter, width: 60, widthGrow: 0, hozAlign: "center", headerSort: false,
                        cellClick: function(e, cell) { deleteSubRow('export_cargo', cell.getRow().getData().id, vcnId); }
                    } : null
                ].filter(Boolean)
```

Note: the toll `cellEdited` calls `markDirty('export_cargo')` (not `'consigners'`) so the export table's dirty state is tracked correctly.

- [ ] **Step 2: Manual smoke test (no automated FE test in this stack)**

Run the app, open an Export VCN:
```bash
python app.py   # or the project's run command
```
1. Open an Export VCN → Parcels (Export Cargo) section.
2. Add Parcel → set Cargo Name, Qty, Consignee, Payment by; pick a Pipeline, then an Unload Terminal (confirm terminal is disabled until a pipeline is chosen); toggle Toll off and confirm the reason prompt; add Equipment.
3. Save, reload the VCN → all values persist and Parcel No is assigned.
4. Confirm no BL No / BL Date columns appear on export.
5. Open an **Import** VCN and confirm its parcels table is unchanged (import-unaffected check).

Expected: export parcels behave like import minus BL; import unchanged.

- [ ] **Step 3: Commit**

```bash
git add modules/VCN01/vcn01.html
git commit -m "feat(vcn01): export parcels Tabulator mirrors import columns (minus BL)"
```

---

## Self-Review

**Spec coverage:**
- §1 Data model → Task 1. ✓
- §2 Backend (list-driven CRUD, `_EXPORT_PARCEL_COLS`, quantity aggregate fix) → Task 2. ✓
- §3 Frontend (export columns mirror import minus BL, reuse helpers, `markDirty('export_cargo')`) → Task 3. ✓
- §4 Downstream impact → explicitly deferred; no task (correct). ✓
- §Testing (model round-trip + manual smoke) → Task 2 Step 1 + Task 3 Step 2. ✓
- Constraint "import unaffected" → Task 2 Step 7 + Task 3 Step 2.5. ✓

**Placeholder scan:** none — all steps carry exact code/commands.

**Type consistency:** `_EXPORT_PARCEL_COLS` order matches the test assertion and the frontend field names; `quantity` TEXT with numeric cast only in the aggregate; function names match spec interfaces.

## Notes / knowingly deferred
- LDUD01, LUEU01, FIN01 read the old export columns (`bl_quantity`, EGM, `is_billed`) and will error on export flows until their own sub-projects. Expected.
- `_sync_header_cargo` and the terminals-derivation query (~226) are left as-is this pass.
