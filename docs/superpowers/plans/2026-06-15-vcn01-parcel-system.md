# VCN01 Parcel System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate each `vcn_consigners` row to a first-class **parcel** with a stable per-VCN number (`VCN-2627-002/P1`), surface the sub-table as "Parcels", and link LDUD unloading operations to a parcel by `parcel_id`.

**Architecture:** Approach A — evolve `vcn_consigners` in place (keep the table name). Add `parcel_seq`/`parcel_no` to it and a nullable `parcel_id` FK on `ldud_vessel_operations`. The DB `id` is the cross-module key; `parcel_no` is the human label. All changes are additive/back-compatible — the EV01→VCN mover, PLTM01 multi-select, and existing LDUD/billing bridges keep working. Billing/survey/demurrage are out of scope (deferred specs).

**Tech Stack:** Flask + psycopg2 (RealDictCursor), Alembic migrations, Tabulator (vanilla JS in Jinja templates). PostgreSQL. No pytest suite — verification is via `alembic upgrade/downgrade`, `python -m py_compile`, and short authenticated HTTP round-trip scripts run against the dev app on `http://127.0.0.1:5000` (admin/admin), created then deleted.

**Spec:** `docs/superpowers/specs/2026-06-15-vcn01-parcel-system-design.md`

---

## Task 1: Migration jnpa15 — parcel columns + LDUD parcel_id + backfill

**Files:**
- Create: `alembic/versions/jnpa15_vcn_parcel_identity.py`

- [ ] **Step 1: Confirm current alembic head**

Run: `python -m alembic heads`
Expected: `jnpa14_vcn_via_remarks (head)`

- [ ] **Step 2: Write the migration**

Create `alembic/versions/jnpa15_vcn_parcel_identity.py`:

```python
"""jnpa phase1 - parcel identity on vcn_consigners; parcel_id on ldud ops

Each vcn_consigners row becomes a first-class parcel:
  - parcel_seq : ordinal within the vessel call (1,2,3...)
  - parcel_no  : stored label '<vcn_doc_num>/P<seq>' e.g. 'VCN-2627-002/P1'
ldud_vessel_operations gains a nullable parcel_id (FK -> vcn_consigners.id).

Revision ID: jnpa15_vcn_parcel_identity
Revises: jnpa14_vcn_via_remarks
Create Date: 2026-06-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa15_vcn_parcel_identity'
down_revision: Union[str, None] = 'jnpa14_vcn_via_remarks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS parcel_seq INTEGER;
        ALTER TABLE vcn_consigners ADD COLUMN IF NOT EXISTS parcel_no TEXT;

        -- assign per-VCN sequence using the existing display order
        WITH ordered AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY vcn_id
                       ORDER BY (substring(igm_line_no from '^[0-9]+'))::int NULLS LAST, id
                   ) AS seq
            FROM vcn_consigners
        )
        UPDATE vcn_consigners c
        SET parcel_seq = o.seq
        FROM ordered o
        WHERE o.id = c.id;

        -- build the stored label from the parent VCN doc number
        UPDATE vcn_consigners c
        SET parcel_no = h.vcn_doc_num || '/P' || c.parcel_seq
        FROM vcn_header h
        WHERE h.id = c.vcn_id AND c.parcel_seq IS NOT NULL;

        ALTER TABLE ldud_vessel_operations ADD COLUMN IF NOT EXISTS parcel_id INTEGER;
    ''')


def downgrade() -> None:
    op.execute('''
        ALTER TABLE ldud_vessel_operations DROP COLUMN IF EXISTS parcel_id;
        ALTER TABLE vcn_consigners DROP COLUMN IF EXISTS parcel_no;
        ALTER TABLE vcn_consigners DROP COLUMN IF EXISTS parcel_seq;
    ''')
```

- [ ] **Step 3: Apply the migration**

Run: `python -m alembic upgrade head`
Expected: log line `Running upgrade jnpa14_vcn_via_remarks -> jnpa15_vcn_parcel_identity`

- [ ] **Step 4: Verify schema + backfill**

Create `_v1.py`, run `python _v1.py`, then delete it:

```python
import sys; sys.path.insert(0, '.')
from database import get_db, get_cursor
conn = get_db(); cur = get_cursor(conn)
for tbl, col in [('vcn_consigners','parcel_seq'), ('vcn_consigners','parcel_no'), ('ldud_vessel_operations','parcel_id')]:
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", [tbl, col])
    print(tbl, col, 'OK' if cur.fetchone() else 'MISSING')
cur.execute("SELECT parcel_no, parcel_seq FROM vcn_consigners WHERE parcel_no IS NOT NULL LIMIT 5")
print('sample parcel_no:', [dict(r) for r in cur.fetchall()])
conn.close()
```
Expected: three `OK` lines; sample parcel_no values look like `VCN-2627-.../P1`.

- [ ] **Step 5: Verify downgrade is clean, then re-upgrade**

Run: `python -m alembic downgrade jnpa14_vcn_via_remarks; python -m alembic upgrade head`
Expected: downgrade then upgrade both succeed with no error.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/jnpa15_vcn_parcel_identity.py
git commit -m "feat(jnpa): parcel identity on vcn_consigners + ldud parcel_id (jnpa15)"
```

---

## Task 2: VCN01 model — parcel numbering on save + get_parcels

**Files:**
- Modify: `modules/VCN01/model.py` (the consigner section, ~lines 112-143)

- [ ] **Step 1: Add parcel-number helper + numbering on save**

In `modules/VCN01/model.py`, replace the consigner block (the `_CONSIGNER_COLS`,
`get_consigners`, `save_consigner` functions) with:

```python
# Consigner (customer details) sub-table — each row is one PARCEL (one IGM/FORM III
# line: product + receiver + BL). vessel agent is captured on the header.
_CONSIGNER_COLS = ['igm_line_no', 'bl_no', 'bl_date', 'cargo_name', 'quantity',
                   'consigner_name', 'importer_name',
                   'pipeline_name', 'unload_terminal']


def _parcel_no(cur, vcn_id, seq):
    """Build the stored parcel label '<vcn_doc_num>/P<seq>' (or 'P<seq>' if the
    parent VCN has no doc number yet — e.g. a brand-new draft)."""
    cur.execute('SELECT vcn_doc_num FROM vcn_header WHERE id=%s', [vcn_id])
    row = cur.fetchone()
    doc = (row or {}).get('vcn_doc_num') if row else None
    return f"{doc}/P{seq}" if doc else f"P{seq}"


def get_parcels(vcn_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM vcn_consigners WHERE vcn_id=%s ORDER BY parcel_seq NULLS LAST, id',
                (vcn_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# back-compat alias — existing callers/endpoints use get_consigners
get_consigners = get_parcels


def save_consigner(data):
    _clean_empty(data)
    conn = get_db()
    cur = get_cursor(conn)
    if data.get('id'):
        cur.execute(f"UPDATE vcn_consigners SET {', '.join(f'{c}=%s' for c in _CONSIGNER_COLS)} WHERE id=%s",
                   [data.get(c) for c in _CONSIGNER_COLS] + [data['id']])
        row_id = data['id']
        # backfill parcel_no if it was created on a draft before the VCN had a doc number
        cur.execute('SELECT parcel_seq, parcel_no FROM vcn_consigners WHERE id=%s', [row_id])
        cur_row = cur.fetchone()
        if cur_row and cur_row['parcel_seq'] and not cur_row['parcel_no']:
            cur.execute('UPDATE vcn_consigners SET parcel_no=%s WHERE id=%s',
                        [_parcel_no(cur, data['vcn_id'], cur_row['parcel_seq']), row_id])
    else:
        cur.execute('SELECT COALESCE(MAX(parcel_seq), 0) + 1 AS nxt FROM vcn_consigners WHERE vcn_id=%s',
                    [data['vcn_id']])
        seq = cur.fetchone()['nxt']
        parcel_no = _parcel_no(cur, data['vcn_id'], seq)
        cols = _CONSIGNER_COLS + ['parcel_seq', 'parcel_no']
        vals = [data.get(c) for c in _CONSIGNER_COLS] + [seq, parcel_no]
        cur.execute(f'''INSERT INTO vcn_consigners (vcn_id, {', '.join(cols)})
                       VALUES ({', '.join(['%s'] * (len(cols) + 1))}) RETURNING id''',
                   [data['vcn_id']] + vals)
        row_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return row_id

# back-compat alias
save_parcel = save_consigner
```

- [ ] **Step 2: Compile-check**

Run: `python -m py_compile modules/VCN01/model.py`
Expected: no output (success).

- [ ] **Step 3: Verify numbering via HTTP round-trip**

Create `_v2.py`, run `python _v2.py`, then delete it:

```python
import sys; sys.path.insert(0, '.')
import requests
from database import get_db, get_cursor
BASE='http://127.0.0.1:5000'; s=requests.Session()
s.post(f'{BASE}/login', data={'username':'admin','password':'admin'})
conn=get_db(); cur=get_cursor(conn)
cur.execute("INSERT INTO vcn_header (vcn_doc_num, vessel_name, doc_status) VALUES ('ZZP-001','ZZ PARCEL','Draft') RETURNING id")
vcn=cur.fetchone()['id']; conn.commit()
for cargo in ['ACETIC ACID','GLACIAL AA']:
    s.post(f'{BASE}/api/module/VCN01/consigners/save', json={'vcn_id':vcn,'cargo_name':cargo,'quantity':'100'})
rows=s.get(f'{BASE}/api/module/VCN01/consigners/{vcn}').json()
print('parcels:', [(r['parcel_seq'], r['parcel_no'], r['cargo_name']) for r in rows])
cur.execute('DELETE FROM vcn_header WHERE id=%s',[vcn]); conn.commit(); conn.close()
```
Expected: two parcels with seq 1,2 and `parcel_no` `ZZP-001/P1`, `ZZP-001/P2`.

- [ ] **Step 4: Commit**

```bash
git add modules/VCN01/model.py
git commit -m "feat(vcn01): assign parcel_seq/parcel_no on parcel save"
```

---

## Task 3: VCN01 views — parcels list endpoint for LDUD picker

**Files:**
- Modify: `modules/VCN01/views.py` (near the consigner endpoints)

- [ ] **Step 1: Add the parcels endpoint**

In `modules/VCN01/views.py`, immediately after the existing
`get_consigners` route (`/api/module/VCN01/consigners/<int:vcn_id>`), add:

```python
@bp.route('/api/module/VCN01/parcels/<int:vcn_id>')
@login_required
def get_parcels(vcn_id):
    """Compact parcel list for cross-module pickers (e.g. LDUD unloading)."""
    parcels = [{
        'id': p['id'],
        'parcel_no': p.get('parcel_no'),
        'cargo_name': p.get('cargo_name'),
        'consigner_name': p.get('consigner_name'),
        'quantity': p.get('quantity'),
    } for p in model.get_parcels(vcn_id)]
    return jsonify(parcels)
```

- [ ] **Step 2: Compile-check**

Run: `python -m py_compile modules/VCN01/views.py`
Expected: no output (success).

- [ ] **Step 3: Verify endpoint**

Create `_v3.py`, run `python _v3.py`, then delete it:

```python
import sys; sys.path.insert(0, '.')
import requests
from database import get_db, get_cursor
BASE='http://127.0.0.1:5000'; s=requests.Session()
s.post(f'{BASE}/login', data={'username':'admin','password':'admin'})
conn=get_db(); cur=get_cursor(conn)
cur.execute("INSERT INTO vcn_header (vcn_doc_num, vessel_name, doc_status) VALUES ('ZZP-002','ZZ','Draft') RETURNING id")
vcn=cur.fetchone()['id']; conn.commit()
s.post(f'{BASE}/api/module/VCN01/consigners/save', json={'vcn_id':vcn,'cargo_name':'ACETIC ACID','quantity':'100','consigner_name':'JUBILANT'})
print('parcels endpoint:', s.get(f'{BASE}/api/module/VCN01/parcels/{vcn}').json())
cur.execute('DELETE FROM vcn_header WHERE id=%s',[vcn]); conn.commit(); conn.close()
```
Expected: a list with one object having `parcel_no` `ZZP-002/P1`, `cargo_name`, `consigner_name`, `quantity`.

- [ ] **Step 4: Commit**

```bash
git add modules/VCN01/views.py
git commit -m "feat(vcn01): add /parcels list endpoint for cross-module pickers"
```

---

## Task 4: VCN01 UI — relabel sub-table to "Parcels" + Parcel No column

**Files:**
- Modify: `modules/VCN01/vcn01.html`

- [ ] **Step 1: Relabel the section header and add button**

In `modules/VCN01/vcn01.html`, find the consigner sub-section header (search for
`data-section="consigners"`). Change the visible title text
`Consigner (Customer Details) — IGM Lines` (or current text) to `Parcels`, and change
the add button label from `+ Add Line` to `+ Add Parcel`. Leave the IGM PDF
upload/View buttons and all `onclick` handlers/`data-section="consigners"` unchanged.

- [ ] **Step 2: Add the read-only Parcel No column**

In the consigners Tabulator column list (search for `field: "igm_line_no"`), add this
column as the **first** data column, immediately before the `Ln` (`igm_line_no`) column:

```javascript
                {title: "Parcel No", field: "parcel_no", width: 130, headerSort: false},
```

- [ ] **Step 3: Verify in the page HTML**

Create `_v4.py`, run `python _v4.py`, then delete it:

```python
import sys; sys.path.insert(0, '.')
import requests
BASE='http://127.0.0.1:5000'; s=requests.Session()
s.post(f'{BASE}/login', data={'username':'admin','password':'admin'})
t=s.get(f'{BASE}/module/VCN01/').text
print('Parcels title:', '>Parcels<' in t or 'Parcels' in t)
print('Parcel No column:', 'field: "parcel_no"' in t)
print('Add Parcel button:', '+ Add Parcel' in t)
```
Expected: all three `True`.

- [ ] **Step 4: Commit**

```bash
git add modules/VCN01/vcn01.html
git commit -m "feat(vcn01): surface consigner sub-table as Parcels with Parcel No column"
```

---

## Task 5: LDUD01 — link unloading operations to a parcel

**Files:**
- Modify: `modules/LDUD01/model.py` (the vessel-operations save/get)
- Modify: `modules/LDUD01/ldud01.html` (vessel ops sub-table: parcel column + loader)

- [ ] **Step 1: Find the vessel-ops save/get in the model**

Run: `grep -n "ldud_vessel_operations" modules/LDUD01/model.py`
Expected: locate the INSERT/UPDATE/SELECT for vessel operations. Note the exact column
list used by the save function (needed for the next step).

- [ ] **Step 2: Persist parcel_id in vessel-ops save**

In `modules/LDUD01/model.py`, in the function that INSERTs/UPDATEs
`ldud_vessel_operations`, add `parcel_id` to the written columns. For the INSERT add
`parcel_id` to the column list and `data.get('parcel_id')` to the values; for the
UPDATE add `parcel_id=%s` with `data.get('parcel_id')`. Ensure `parcel_id` is also
returned by the SELECT in the vessel-ops getter (if it uses `SELECT *` it is already
returned — confirm and only change if it lists explicit columns).

- [ ] **Step 3: Compile-check**

Run: `python -m py_compile modules/LDUD01/model.py`
Expected: no output (success).

- [ ] **Step 4: Load the VCN's parcels in the LDUD page**

In `modules/LDUD01/ldud01.html`, find where vessel-ops sub-table data/options are
prepared for a given LDUD record (it already knows `vcnId` — search for
`all_cargo_names/` which is fetched per record). Alongside that fetch, add:

```javascript
            const parcelRes = await fetch(`/api/module/VCN01/parcels/${vcnId}`);
            const parcelList = await parcelRes.json();      // [{id, parcel_no, cargo_name, consigner_name, quantity}]
            const parcelOptions = {};
            parcelList.forEach(p => {
                parcelOptions[p.id] = `${p.parcel_no || ('#'+p.id)} — ${p.cargo_name || ''}${p.consigner_name ? ' / ' + p.consigner_name : ''}`;
            });
```

(If parcel loading must live where `vcnId` is available, place it in the same
`async` function that builds the vessel-ops sub-table for that record.)

- [ ] **Step 5: Add the Parcel column to the vessel-ops sub-table**

In the vessel-ops Tabulator column definitions in `modules/LDUD01/ldud01.html`, add a
Parcel column. It stores `parcel_id` and shows the label via `parcelOptions`:

```javascript
                {title: "Parcel", field: "parcel_id", widthGrow: 1.4,
                    editor: canEdit ? "list" : false,
                    editorParams: {values: parcelOptions, autocomplete: true, allowEmpty: true},
                    formatter: function(cell) {
                        const v = cell.getValue();
                        return v != null && parcelOptions[v] ? parcelOptions[v] : '';
                    }
                },
```

- [ ] **Step 6: Verify end-to-end (LDUD op references a parcel)**

Create `_v5.py`, run `python _v5.py`, then delete it:

```python
import sys; sys.path.insert(0, '.')
import requests
from database import get_db, get_cursor
BASE='http://127.0.0.1:5000'; s=requests.Session()
s.post(f'{BASE}/login', data={'username':'admin','password':'admin'})
conn=get_db(); cur=get_cursor(conn)
# VCN + parcel
cur.execute("INSERT INTO vcn_header (vcn_doc_num, vessel_name, doc_status, operation_type) VALUES ('ZZP-003','ZZ','Draft','Import') RETURNING id")
vcn=cur.fetchone()['id']; conn.commit()
pid=s.post(f'{BASE}/api/module/VCN01/consigners/save', json={'vcn_id':vcn,'cargo_name':'ACETIC ACID','quantity':'100'}).json()['id']
parcels=s.get(f'{BASE}/api/module/VCN01/parcels/{vcn}').json()
print('parcel for picker:', parcels)
# LDUD header for this VCN
cur.execute("INSERT INTO ldud_header (vcn_id) VALUES (%s) RETURNING id", [vcn]); ldud=cur.fetchone()['id']; conn.commit()
# save a vessel op carrying parcel_id (mirror the LDUD save payload shape)
r=s.post(f'{BASE}/api/module/LDUD01/vessel_ops/save', json={'ldud_id':ldud,'parcel_id':pid,'cargo_name':'ACETIC ACID','quantity':'50'})
print('vessel_ops save:', r.status_code, r.json())
cur.execute("SELECT parcel_id FROM ldud_vessel_operations WHERE ldud_id=%s", [ldud])
print('stored parcel_id:', cur.fetchone())
# cleanup
cur.execute("DELETE FROM ldud_vessel_operations WHERE ldud_id=%s", [ldud])
cur.execute("DELETE FROM ldud_header WHERE id=%s", [ldud])
cur.execute("DELETE FROM vcn_header WHERE id=%s", [vcn])
conn.commit(); conn.close()
```
Expected: `vessel_ops save` returns success with an id; `stored parcel_id` equals the parcel id `pid`.

- [ ] **Step 7: Commit**

```bash
git add modules/LDUD01/model.py modules/LDUD01/ldud01.html
git commit -m "feat(ldud01): link vessel operations to a VCN parcel (parcel_id)"
```

---

## Task 6: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Restart the app and confirm clean boot**

Run: stop any running `python app.py`, then start it; confirm the log shows
`Running on http://127.0.0.1:5000` with no traceback.

- [ ] **Step 2: EV01 → VCN move numbers parcels**

Create `_v6.py`, run `python _v6.py`, then delete it:

```python
import sys; sys.path.insert(0, '.')
import requests
from database import get_db, get_cursor
BASE='http://127.0.0.1:5000'; s=requests.Session()
s.post(f'{BASE}/login', data={'username':'admin','password':'admin'})
conn=get_db(); cur=get_cursor(conn)
cur.execute("""INSERT INTO expected_vessels (vessel_name, via_number, terminal_name, doc_status, cargo_name, consignees, quantity)
               VALUES ('ZZ PARCEL EV','VIA-P1','BPCL','Pending','ACETIC ACID,GLACIAL AA','JUBILANT','100,200') RETURNING id""")
ev=cur.fetchone()['id']; conn.commit()
r=s.post(f'{BASE}/api/module/EV01/move_to_vcn/{ev}', json={}); vcn=r.json()['vcn_id']
rows=s.get(f'{BASE}/api/module/VCN01/parcels/{vcn}').json()
print('moved parcels:', [(p['parcel_no'], p['cargo_name']) for p in rows])
cur.execute('DELETE FROM vcn_header WHERE id=%s',[vcn])
cur.execute("DELETE FROM vessels WHERE vessel_name ILIKE 'MT ZZ PARCEL EV%'")
cur.execute("DELETE FROM expected_vessels WHERE vessel_name='ZZ PARCEL EV'")
conn.commit(); conn.close()
```
Expected: parcels carry `parcel_no` values like `VCN-..../P1`, `/P2`.

- [ ] **Step 3: Confirm no regressions in existing VCN sub-table**

Manual check in browser (admin/admin): open a Draft VCN's details → the Parcels
sub-table shows the Parcel No column, pipeline→terminal dependent multi-select still
filters, IGM upload/View still present, qty still 3-decimal. Add a parcel → it gets the
next `/P<n>`.

- [ ] **Step 4: Final commit (docs/status if anything pending)**

```bash
git add -A
git commit -m "chore(jnpa): parcel system phase 1 complete" || echo "nothing to commit"
```

---

## Notes for the implementer

- **DB access pattern:** every model function opens its own connection via
  `get_db()` / `get_cursor(conn)` (RealDictCursor → rows are dicts) and closes it.
  Follow that pattern exactly; do not hold connections across functions.
- **Back-compat is mandatory:** keep the `/consigners` endpoints and the
  `get_consigners`/`save_consigner` names (aliased) — the EV01 mover and the existing
  UI call them. New names (`get_parcels`, `/parcels`) are additive.
- **`parcel_id` is nullable** on `ldud_vessel_operations`; legacy ops stay NULL and the
  existing cargo-name / BL-quantity bridges remain the fallback. Do not backfill or
  require it.
- **Out of scope (do not build):** parcel lifecycle status, ullage/survey figures,
  discharged-vs-BL reconciliation, demurrage attribution, billing re-point. These are
  separate specs.
