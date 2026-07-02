# FIN01 Multi-Vessel Bill Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the accounts user select billable charge lines across multiple vessels and generate one bill, recording the parcel ledger (which activates the VCN billed-lock).

**Architecture:** A new `model.generate_bill()` reuses the existing `save_bill_header` (numbering) and `save_bill_line` (server-side GST/TDS calc), then in one final connection writes totals, `bill_vessels` mapping rows, and `record_parcel_charge` ledger rows. A `/bill/generate` endpoint wraps it; the vessel-accordion UI posts the checked lines across all vessels.

**Tech Stack:** Flask, psycopg2, PostgreSQL, Alembic, vanilla JS, pytest.

## Global Constraints

- One bill spans the selected vessels: `bill_header.source_type='MULTI'`, `source_id=NULL`, `source_display` = comma-joined distinct VCN doc-nums.
- Reuse `save_bill_header(data)->(id,bill_number)` and `save_bill_line(data)` — the latter already computes GST (CGST+SGST intra / IGST inter, from `gst_rate_id` + customer vs `port_gst_state_code`), `tds_amount = tds_percent%×line_amount`, and `line_total`; it MUTATES its dict with the computed amounts. Do NOT reimplement the calc.
- `record_parcel_charge(cur, cargo_source_type, cargo_source_id, service_type_id, service_code, bill_id, billed_quantity, created_by)` (from #2) is called per line into the ledger.
- Only `cargo_source_type` values `'VCN_IMPORT'` / `'VCN_EXPORT'`. **No MBC** anywhere.
- Reject a generate where any line has `rate <= 0`.
- TDS is stored per line, NOT subtracted from `total_amount` (`total_amount = subtotal + CGST + SGST + IGST`).
- New view function must NOT be named `generate_bill` (that name is the existing page route at views.py:110) — name it `bill_generate`.
- Run tests with `python -m pytest`. DB: `postgresql://postgres:password@localhost:5432/portman_jnpa`.

---

### Task 1: Alembic migration — bill_vessels mapping table

**Files:**
- Create: `alembic/versions/jnpa39_bill_vessels.py`

**Interfaces:**
- Produces: table `bill_vessels(id, bill_id, vcn_id)`. Consumed by Task 2 and #5.

- [ ] **Step 1: Write the migration**

Create `alembic/versions/jnpa39_bill_vessels.py`:

```python
"""jnpa phase1 - bill_vessels mapping (a bill can span multiple VCNs)

Revision ID: jnpa39_bill_vessels
Revises: jnpa38_parcel_charge_billed
Create Date: 2026-07-02
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa39_bill_vessels'
down_revision: Union[str, None] = 'jnpa38_parcel_charge_billed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS bill_vessels (
            id      SERIAL PRIMARY KEY,
            bill_id INTEGER NOT NULL REFERENCES bill_header(id) ON DELETE CASCADE,
            vcn_id  INTEGER NOT NULL REFERENCES vcn_header(id)
        );
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_bill_vessels_bill ON bill_vessels (bill_id);')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS bill_vessels;')
```

- [ ] **Step 2: Apply**

Run: `alembic upgrade head`
Expected: ends `Running upgrade jnpa38_parcel_charge_billed -> jnpa39_bill_vessels`.

- [ ] **Step 3: Verify**

Run:
```bash
python -c "import psycopg2; c=psycopg2.connect('postgresql://postgres:password@localhost:5432/portman_jnpa'); cur=c.cursor(); cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='bill_vessels' ORDER BY ordinal_position\"); print([r[0] for r in cur.fetchall()])"
```
Expected: `['id', 'bill_id', 'vcn_id']`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/jnpa39_bill_vessels.py
git commit -m "feat(fin01): bill_vessels mapping table (bill spans multiple VCNs)"
```

---

### Task 2: Model `generate_bill` + `/bill/generate` endpoint

**Files:**
- Modify: `modules/FIN01/model.py` (add `generate_bill`)
- Modify: `modules/FIN01/views.py` (add `bill_generate` endpoint)
- Test: `tests/test_fin01_generate_bill.py`

**Interfaces:**
- Consumes: `save_bill_header`, `save_bill_line`, `record_parcel_charge`, `is_vcn_billed`, `get_db`, `get_cursor`, `datetime` (all in FIN01/model.py); table `bill_vessels` (Task 1).
- Produces: `generate_bill(data, created_by, bill_status) -> (bill_id, bill_number)`; `POST /api/module/FIN01/bill/generate`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fin01_generate_bill.py`:

```python
"""Multi-vessel bill generation: one bill across two vessels, lines with GST/TDS
computed by save_bill_line, bill_vessels populated, ledger recorded (billed-lock)."""
from database import get_db, get_cursor
from modules.FIN01 import model as fin


def _mk_vessel(cur, doc):
    cur.execute("INSERT INTO vcn_header (operation_type, vcn_doc_num, vessel_name) "
                "VALUES ('Import',%s,'V') RETURNING id", [doc])
    vid = cur.fetchone()['id']
    cur.execute("""INSERT INTO vcn_consigners
        (vcn_id, parcel_no, cargo_name, quantity, consigner_name, importer_name,
         pipeline_name, unload_terminal, parcel_seq)
        VALUES (%s,'P1','OIL','100','GENC','GENC','PL','T',1) RETURNING id""", [vid])
    pid = cur.fetchone()['id']
    cur.execute("INSERT INTO ldud_header (vcn_id, doc_status) VALUES (%s,'Closed')", [vid])
    return vid, pid


def _svc_id(cur, code):
    cur.execute("SELECT id FROM finance_service_types WHERE service_code=%s", [code])
    return cur.fetchone()['id']


def test_generate_multi_vessel_bill_records_ledger_and_vessels():
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vessel_customers (name) VALUES ('GENC') RETURNING id")
    cid = cur.fetchone()['id']
    v1, p1 = _mk_vessel(cur, 'VCN-GEN-1')
    v2, p2 = _mk_vessel(cur, 'VCN-GEN-2')
    chg = _svc_id(cur, 'CHGU01')
    conn.commit(); conn.close()

    payload = {
        'customer_type': 'Customer', 'customer_id': cid, 'customer_name': 'GENC',
        'customer_gstin': '', 'customer_gst_state_code': '', 'customer_gl_code': '',
        'lines': [
            {'cargo_source_type': 'VCN_IMPORT', 'cargo_source_id': p1, 'vcn_id': v1,
             'service_type_id': chg, 'service_code': 'CHGU01', 'service_name': 'Cargo Handling Unloading',
             'quantity': 100, 'rate': 50, 'uom': 'MT', 'gst_rate_id': 4, 'sac_code': '996719',
             'gl_code': '4101076030', 'tds_applicable': 1, 'tds_percent': 2},
            {'cargo_source_type': 'VCN_IMPORT', 'cargo_source_id': p2, 'vcn_id': v2,
             'service_type_id': chg, 'service_code': 'CHGU01', 'service_name': 'Cargo Handling Unloading',
             'quantity': 100, 'rate': 50, 'uom': 'MT', 'gst_rate_id': 4, 'sac_code': '996719',
             'gl_code': '4101076030', 'tds_applicable': 1, 'tds_percent': 2},
        ],
    }
    bill_id = bill_number = None
    try:
        bill_id, bill_number = fin.generate_bill(payload, 'tester', 'Draft')
        assert bill_id and bill_number

        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT source_type, source_id, source_display, subtotal FROM bill_header WHERE id=%s", [bill_id])
        h = cur.fetchone()
        assert h['source_type'] == 'MULTI' and h['source_id'] is None
        assert 'VCN-GEN-1' in h['source_display'] and 'VCN-GEN-2' in h['source_display']
        assert abs(float(h['subtotal']) - 10000.0) < 1e-6   # 2 x 100 x 50

        cur.execute("SELECT COUNT(*) AS c FROM bill_lines WHERE bill_id=%s", [bill_id])
        assert cur.fetchone()['c'] == 2
        cur.execute("SELECT COUNT(*) AS c FROM bill_vessels WHERE bill_id=%s", [bill_id])
        assert cur.fetchone()['c'] == 2
        conn.close()

        assert fin.is_vcn_billed(v1) is True
        assert fin.is_vcn_billed(v2) is True
    finally:
        conn = get_db(); cur = get_cursor(conn)
        if bill_id:
            cur.execute("DELETE FROM parcel_charge_billed WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_vessels WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_lines WHERE bill_id=%s", [bill_id])
            cur.execute("DELETE FROM bill_header WHERE id=%s", [bill_id])
        cur.execute("DELETE FROM ldud_header WHERE vcn_id IN (%s,%s)", [v1, v2])
        cur.execute("DELETE FROM vcn_header WHERE id IN (%s,%s)", [v1, v2])  # cascades consigner
        cur.execute("DELETE FROM vessel_customers WHERE id=%s", [cid])
        conn.commit(); conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fin01_generate_bill.py -q`
Expected: FAIL — `AttributeError: module 'modules.FIN01.model' has no attribute 'generate_bill'`.

- [ ] **Step 3: Implement `generate_bill`**

Append to `modules/FIN01/model.py`:

```python
def generate_bill(data, created_by, bill_status):
    """Create ONE bill across the selected vessels. Reuses save_bill_header
    (numbering) and save_bill_line (GST/TDS calc, mutates the line dict with the
    computed amounts), then records totals, bill_vessels, and the parcel ledger.
    Returns (bill_id, bill_number). No MBC — only VCN_IMPORT/VCN_EXPORT lines."""
    lines = data.get('lines') or []
    vcn_ids = sorted({l['vcn_id'] for l in lines if l.get('vcn_id')})

    conn = get_db()
    cur = get_cursor(conn)
    docs = []
    if vcn_ids:
        cur.execute("SELECT vcn_doc_num FROM vcn_header WHERE id = ANY(%s) ORDER BY vcn_doc_num", [vcn_ids])
        docs = [r['vcn_doc_num'] for r in cur.fetchall() if r['vcn_doc_num']]
    conn.close()

    header = {
        'source_type': 'MULTI', 'source_id': None,
        'source_display': ', '.join(docs),
        'customer_type': data.get('customer_type'), 'customer_id': data.get('customer_id'),
        'customer_name': data.get('customer_name'), 'customer_gstin': data.get('customer_gstin'),
        'customer_gst_state_code': data.get('customer_gst_state_code'),
        'customer_gl_code': data.get('customer_gl_code'),
        'currency_code': data.get('currency_code') or 'INR',
        'agreement_id': data.get('agreement_id') or None,
        'bill_status': bill_status,
        'created_by': created_by,
        'created_date': datetime.now().strftime('%Y-%m-%d'),
    }
    bill_id, bill_number = save_bill_header(header)

    subtotal = cgst = sgst = igst = 0.0
    for l in lines:
        line_amount = round(float(l.get('quantity') or 0) * float(l.get('rate') or 0), 2)
        ld = {
            'bill_id': bill_id, 'service_type_id': l.get('service_type_id'),
            'service_code': l.get('service_code'), 'service_name': l.get('service_name'),
            'service_description': l.get('service_name'),
            'quantity': l.get('quantity'), 'uom': l.get('uom'), 'rate': l.get('rate'),
            'line_amount': line_amount, 'gst_rate_id': l.get('gst_rate_id'),
            'sac_code': l.get('sac_code'), 'gl_code': l.get('gl_code'),
            'tds_applicable': l.get('tds_applicable'), 'tds_percent': l.get('tds_percent'),
            'cargo_source_type': l.get('cargo_source_type'), 'cargo_source_id': l.get('cargo_source_id'),
            'customer_gstin': data.get('customer_gstin'),
            'customer_state_code': data.get('customer_gst_state_code'),
        }
        save_bill_line(ld)  # computes + stores cgst/sgst/igst/tds/line_total on ld and the row
        subtotal += line_amount
        cgst += float(ld.get('cgst_amount') or 0)
        sgst += float(ld.get('sgst_amount') or 0)
        igst += float(ld.get('igst_amount') or 0)

    total = round(subtotal + cgst + sgst + igst, 2)
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''UPDATE bill_header
        SET subtotal=%s, cgst_amount=%s, sgst_amount=%s, igst_amount=%s, total_amount=%s
        WHERE id=%s''', [subtotal, cgst, sgst, igst, total, bill_id])
    for vid in vcn_ids:
        cur.execute('INSERT INTO bill_vessels (bill_id, vcn_id) VALUES (%s, %s)', [bill_id, vid])
    for l in lines:
        record_parcel_charge(cur, l.get('cargo_source_type'), l.get('cargo_source_id'),
                             l.get('service_type_id'), l.get('service_code'), bill_id,
                             float(l.get('quantity') or 0), created_by)
    conn.commit()
    conn.close()
    return bill_id, bill_number
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fin01_generate_bill.py -q`
Expected: PASS (1 test).

- [ ] **Step 5: Add the endpoint**

In `modules/FIN01/views.py`, after the `save_bill` view (ends ~line 309), add:

```python
@bp.route('/api/module/FIN01/bill/generate', methods=['POST'])
def bill_generate():
    """Generate one bill across selected vessels from picked billable lines."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    perms = get_user_permissions(session['user_id'], 'FIN01')
    if not perms['can_add']:
        return jsonify({'success': False, 'error': 'No add permission'})

    data = request.json or {}
    lines = data.get('lines') or []
    if not lines:
        return jsonify({'success': False, 'error': 'No lines selected'})
    if any(float(l.get('rate') or 0) <= 0 for l in lines):
        return jsonify({'success': False, 'error': 'Every selected line needs a rate greater than 0'})

    config = get_module_config('FIN01')
    bill_status = 'Pending Approval' if config.get('approval_add') else 'Draft'
    try:
        bill_id, bill_number = model.generate_bill(data, session.get('username'), bill_status)
    except Exception as e:
        return jsonify({'success': False, 'error': 'Generate failed: ' + str(e)})

    if bill_status == 'Pending Approval':
        _queue_bill_approval_request(bill_id, bill_number, data.get('customer_name'), None)
    return jsonify({'success': True, 'id': bill_id, 'bill_number': bill_number})
```

- [ ] **Step 6: Verify endpoint parses + test still green**

Run: `python -c "import ast; ast.parse(open('modules/FIN01/views.py').read()); print('ok')"` then `python -m pytest tests/test_fin01_generate_bill.py -q`
Expected: `ok` and 1 passing.

- [ ] **Step 7: Commit**

```bash
git add modules/FIN01/model.py modules/FIN01/views.py tests/test_fin01_generate_bill.py
git commit -m "feat(fin01): generate multi-vessel bill + parcel ledger recording"
```

---

### Task 3: Frontend — wire vessel-accordion "Generate Bill" to /bill/generate

**Files:**
- Modify: `modules/FIN01/generate_bill.html`

**Interfaces:**
- Consumes: `POST /api/module/FIN01/bill/generate` (Task 2). Line objects come from the engine (`window._vessels[vi].lines[li]`), each with `cargo_source_type, cargo_source_id, service_type_id, service_code, service_name, cargo_name, qty, uom, rate, gst_rate_id, sac_code`; add `vcn_id` from the parent vessel and read the (possibly edited) qty/rate from the row inputs.

- [ ] **Step 1: Implement generateBill()**

In `modules/FIN01/generate_bill.html`, replace the stub `generateBill()` with the collector below. It gathers checked lines across all vessels, attaches each line's `vcn_id`, reads edited qty/rate, and posts. Customer id/type + GST context come from the page's existing customer selector and port-config load (reuse the existing variables the page already holds — `customerType`, `customerId`, `customerName`, `customerGstin`, `customerStateCode`, `customerGlCode`; if a name differs in the file, use the file's existing variable).

```javascript
async function generateBill() {
  const vessels = window._vessels || [];
  const picked = [];
  document.querySelectorAll('.bl-chk:checked').forEach(chk => {
    const vi = +chk.dataset.vi, li = +chk.dataset.li;
    const v = vessels[vi]; const l = v && v.lines[li];
    if (!l) return;
    const qty = parseFloat(document.querySelector(`.bl-qty[data-vi="${vi}"][data-li="${li}"]`).value) || 0;
    const rate = parseFloat(document.querySelector(`.bl-rate[data-vi="${vi}"][data-li="${li}"]`).value) || 0;
    picked.push({
      vcn_id: v.vcn_id,
      cargo_source_type: l.cargo_source_type, cargo_source_id: l.cargo_source_id,
      service_type_id: l.service_type_id, service_code: l.service_code,
      service_name: l.service_name, cargo_name: l.cargo_name,
      quantity: qty, rate: rate, uom: l.uom, gst_rate_id: l.gst_rate_id,
      sac_code: l.sac_code, gl_code: l.gl_code,
      tds_applicable: l.is_tds, tds_percent: l.tds_percent,
    });
  });
  if (!picked.length) { alert('Select at least one line to bill.'); return; }
  if (picked.some(p => !(p.rate > 0))) { alert('Every selected line needs a rate greater than 0.'); return; }

  const payload = {
    customer_type: customerType, customer_id: customerId, customer_name: customerName,
    customer_gstin: (typeof customerGstin !== 'undefined' ? customerGstin : ''),
    customer_gst_state_code: (typeof customerStateCode !== 'undefined' ? customerStateCode : ''),
    customer_gl_code: (typeof customerGlCode !== 'undefined' ? customerGlCode : ''),
    lines: picked,
  };
  const res = await fetch('/api/module/FIN01/bill/generate', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const j = await res.json();
  if (!j.success) { alert(j.error || 'Bill generation failed'); return; }
  alert('Bill ' + j.bill_number + ' generated.');
  loadBillables();   // reload; billed lines drop out via ledger remaining
}
```

If the page's customer/GST variable names differ, adapt them; if the page lacks the GST context vars, send empty strings (the server computes GST from `gst_rate_id` and treats missing state as intra-state). If the reload function is named differently than `loadBillables`, call the file's existing reload/refresh function.

- [ ] **Step 2: Static verify**

Run:
```bash
python - <<'PY'
import re
s=open('modules/FIN01/generate_bill.html',encoding='utf-8').read()
assert '/api/module/FIN01/bill/generate' in s, 'endpoint not wired'
assert 'function generateBill' in s
print('braces', s.count('{'), s.count('}'), '| generate wired ok')
PY
```
Expected: prints balanced-ish counts and `generate wired ok`. (No automated FE test in this stack.)

- [ ] **Step 3: Manual smoke test**

Run the app; FIN01 → Generate Bill; pick a customer; check lines across two vessels; Generate Bill → a bill number appears and the billed lines disappear on reload. Open FIN01 Bills to confirm the bill exists with `source_type=MULTI` and lines from both vessels.

- [ ] **Step 4: Commit**

```bash
git add modules/FIN01/generate_bill.html
git commit -m "feat(fin01): wire vessel-accordion Generate Bill to /bill/generate"
```

---

## Self-Review

**Spec coverage:**
- §1 bill_vessels table → Task 1. ✓
- §2 generate_bill model (MULTI header, save_bill_header/line reuse, totals, ledger, bill_vessels) + endpoint (status, 0-rate guard, approval) → Task 2. ✓
- §3 frontend cross-vessel selection → generate → Task 3. ✓
- Testing (one bill across two vessels, bill_vessels, ledger/billed-lock) → Task 2 test. ✓
- No MBC → only VCN_IMPORT/VCN_EXPORT handled; no MBC branch added. ✓

**Placeholder scan:** none — full code for migration, model, endpoint, test, frontend.

**Type consistency:** line keys posted by the frontend (`quantity`, `rate`, `cargo_source_type/id`, `service_type_id`, `service_code`, `gst_rate_id`, `sac_code`, `gl_code`, `tds_applicable`, `tds_percent`, `vcn_id`) match what `generate_bill` reads; `save_bill_line` dict keys (`line_amount`, `customer_state_code`, `customer_gstin`) match its calc inputs; `record_parcel_charge` args match #2's signature.

## Notes / knowingly deferred
- Not single-transaction across header+lines (matches existing `save_bill` style); the ledger + bill_vessels + totals are grouped in the final connection.
- FINV01 invoicing (#5) and SAP push (#6) consume `bill_vessels`/bills later.
- `_queue_bill_approval_request` passed `None` for amount; the mail formats a dash.
