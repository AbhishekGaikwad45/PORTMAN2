# FIN01 Billables Engine + Vessel-Grouped UI + FCAM rates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive the four AR charges (Cargo Handling, Infrastructure, MLA, Toll) from VCN parcels, grouped by vessel, and show them in a vessel-accordion bill-generation UI; let FCAM price Infrastructure per cargo.

**Architecture:** Extract billables derivation into a testable `FIN01/model.get_customer_billables()` that reads parcels + the `parcel_charge_billed` ledger (#2) + FCAM rates, returns a vessel-grouped structure; the FIN01 view becomes a thin wrapper; `generate_bill.html` renders vessel accordions. FCAM gets a one-line change so Infrastructure is cargo-specific.

**Tech Stack:** Flask, psycopg2, PostgreSQL, Tabulator/vanilla JS, pytest.

## Global Constraints

- Bill-to party = `parcel.importer_name` ("Payment will be made by").
- Charges gated on the VCN's latest `ldud_header.doc_status IN ('Closed','Partial Close')`.
- Charges per parcel (qty = parcel quantity): Cargo Handling `CHGU01` (import) / `CHGL01` (export) — always; Infrastructure `INFM01` — always; MLA `MLAC01` — only if `equipment_names` non-empty; Toll `TOLL01` — only if `toll_applicable` truthy.
- Rate: cargo-specific→generic for CHGU01/CHGL01/INFM01 (pass `cargo_name`); generic for MLAC01/TOLL01 (no `cargo_name`). Resolve via `modules.FCAM01.model.get_customer_rate(customer_type, customer_id, service_type_id, cargo_name=…)`.
- remaining = parcel qty − `billed_qty(cargo_source_type, cargo_source_id, service_type_id)` (FIN01 model, from #2); skip lines with remaining ≤ 0.
- `cargo_source_type` values: `'VCN_IMPORT'` (vcn_consigners) / `'VCN_EXPORT'` (vcn_export_cargo_declaration); `cargo_source_id` = parcel id.
- Bill *writing* is out of scope (#4) — the UI selects lines only.
- DB URL for local runs: `postgresql://postgres:password@localhost:5432/portman_jnpa`; run pytest as `python -m pytest`.

---

### Task 1: FCAM — Infrastructure priced per cargo

**Files:**
- Modify: `modules/FCAM01/views.py:70-72`

**Interfaces:**
- Produces: agreements can carry per-cargo `INFM01` rate lines (consumed conceptually by Task 2's rate lookup).

- [ ] **Step 1: Make the change**

In `modules/FCAM01/views.py`, extend the cargo-specific service set:

```python
    # Cargo-priced services get a per-cargo rate matrix; others get a generic line.
    cargo_service_ids = [s['id'] for s in service_types
                         if s.get('service_code') in ('CHGL01', 'CHGU01', 'INFM01')]
```

- [ ] **Step 2: Verify**

Run: `python -c "import ast; ast.parse(open('modules/FCAM01/views.py').read()); print('ok')"`
Expected: `ok`. (Manual: opening an FCAM agreement, INFM01 now shows the per-cargo rate matrix; MLAC01/TOLL01 show a single generic line.)

- [ ] **Step 3: Commit**

```bash
git add modules/FCAM01/views.py
git commit -m "feat(fcam01): price Infrastructure (INFM01) per cargo like cargo handling"
```

---

### Task 2: FIN01 engine — billables from parcels, grouped by vessel

**Files:**
- Modify: `modules/FIN01/model.py` (add `get_customer_billables`; imports at top)
- Modify: `modules/FIN01/views.py:610-` (replace the view body of `get_customer_billables` to call the model)
- Test: `tests/test_fin01_billables.py`

**Interfaces:**
- Consumes: `billed_qty(cargo_source_type, cargo_source_id, service_type_id)` (FIN01 model, from #2); `modules.FCAM01.model.get_customer_rate(...)`.
- Produces: `get_customer_billables(customer_type, customer_id) -> {'vessels': [ {vcn_id, vcn_doc_num, vessel_name, ldud_status, lines:[{cargo_source_type, cargo_source_id, parcel_no, service_type_id, service_code, service_name, cargo_name, qty, uom, rate, amount, sac_code, gst_rate_id, is_tds, tds_percent, is_tcs, tcs_percent}], total_amount} ]}`. Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fin01_billables.py`:

```python
"""FIN01 billables engine: 4 charges/parcel, vessel grouping, ledger remaining,
LDUD gate. Dev DB with a throwaway customer + VCN + LDUD + parcel, cleaned up."""
from database import get_db, get_cursor
from modules.FIN01 import model as fin


def _setup(cur, ldud_status='Closed', equipment='CRANE', toll=True):
    cur.execute("INSERT INTO vessel_customers (name) VALUES ('ENGTEST CO') RETURNING id")
    cid = cur.fetchone()['id']
    cur.execute("INSERT INTO vcn_header (operation_type, vcn_doc_num, vessel_name) "
                "VALUES ('Import','VCN-ENG-1','ENGVESSEL') RETURNING id")
    vid = cur.fetchone()['id']
    cur.execute("""INSERT INTO vcn_consigners
        (vcn_id, parcel_no, cargo_name, quantity, consigner_name, importer_name,
         pipeline_name, unload_terminal, toll_applicable, equipment_names, parcel_seq)
        VALUES (%s,'P1','OIL','100','ENGTEST CO','ENGTEST CO','PL1','T1',%s,%s,1) RETURNING id""",
        [vid, toll, equipment])
    pid = cur.fetchone()['id']
    cur.execute("INSERT INTO ldud_header (vcn_id, doc_status) VALUES (%s,%s) RETURNING id",
                [vid, ldud_status])
    return cid, vid, pid


def _teardown(cid, vid, pid):
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("DELETE FROM parcel_charge_billed WHERE cargo_source_id=%s", [pid])
    cur.execute("DELETE FROM ldud_header WHERE vcn_id=%s", [vid])
    cur.execute("DELETE FROM vcn_header WHERE id=%s", [vid])  # cascades consigner
    cur.execute("DELETE FROM vessel_customers WHERE id=%s", [cid])
    conn.commit(); conn.close()


def test_four_charges_grouped_by_vessel_and_ledger_remaining():
    conn = get_db(); cur = get_cursor(conn)
    cid, vid, pid = _setup(cur, equipment='CRANE', toll=True)
    conn.commit(); conn.close()
    try:
        out = fin.get_customer_billables('Customer', cid)
        vessels = out['vessels']
        assert len(vessels) == 1
        v = vessels[0]
        assert v['vcn_id'] == vid and v['vcn_doc_num'] == 'VCN-ENG-1'
        codes = sorted(l['service_code'] for l in v['lines'])
        assert codes == ['CHGU01', 'INFM01', 'MLAC01', 'TOLL01'], codes
        assert all(abs(l['qty'] - 100.0) < 1e-6 for l in v['lines'])
        chg = next(l for l in v['lines'] if l['service_code'] == 'CHGU01')
        assert chg['cargo_source_type'] == 'VCN_IMPORT' and chg['cargo_source_id'] == pid

        # ledger reduces remaining; fully billed CHGU01 drops out
        conn = get_db(); cur = get_cursor(conn)
        fin.record_parcel_charge(cur, 'VCN_IMPORT', pid, chg['service_type_id'],
                                 'CHGU01', 999, 100, 'tester')
        conn.commit(); conn.close()
        out2 = fin.get_customer_billables('Customer', cid)
        codes2 = sorted(l['service_code'] for l in out2['vessels'][0]['lines'])
        assert codes2 == ['INFM01', 'MLAC01', 'TOLL01'], codes2
    finally:
        _teardown(cid, vid, pid)


def test_no_equipment_no_toll_yields_two_charges():
    conn = get_db(); cur = get_cursor(conn)
    cid, vid, pid = _setup(cur, equipment='', toll=False)
    conn.commit(); conn.close()
    try:
        v = fin.get_customer_billables('Customer', cid)['vessels'][0]
        assert sorted(l['service_code'] for l in v['lines']) == ['CHGU01', 'INFM01']
    finally:
        _teardown(cid, vid, pid)


def test_draft_ldud_yields_no_vessels():
    conn = get_db(); cur = get_cursor(conn)
    cid, vid, pid = _setup(cur, ldud_status='Draft')
    conn.commit(); conn.close()
    try:
        assert fin.get_customer_billables('Customer', cid)['vessels'] == []
    finally:
        _teardown(cid, vid, pid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fin01_billables.py -q`
Expected: FAIL — `AttributeError: module 'modules.FIN01.model' has no attribute 'get_customer_billables'`.

- [ ] **Step 3: Add the import**

At the top of `modules/FIN01/model.py`, after the existing imports, add:

```python
from modules.FCAM01 import model as fcam_model
```

- [ ] **Step 4: Implement the engine**

Append to `modules/FIN01/model.py`:

```python
# ===== BILLABLES ENGINE (parcels -> 4 charges, grouped by vessel) =====

_CARGO_GATE = ('Closed', 'Partial Close')


def _to_float(v):
    try:
        return float(str(v).replace(',', '')) if v not in (None, '') else 0.0
    except (ValueError, TypeError):
        return 0.0


def get_customer_billables(customer_type, customer_id):
    """Billable charges for a customer's parcels, grouped by vessel. Read-only.
    Bills the payer (importer_name); only parcels whose VCN's latest LDUD is
    Closed/Partial Close; remaining per charge from the parcel_charge_billed ledger."""
    conn = get_db()
    cur = get_cursor(conn)

    if customer_type == 'Customer':
        cur.execute("SELECT name FROM vessel_customers WHERE id=%s", [customer_id])
    else:
        cur.execute("SELECT name FROM vessel_agents WHERE id=%s", [customer_id])
    row = cur.fetchone()
    customer_name = row['name'] if row else ''

    cur.execute("""SELECT id, service_code, service_name, sac_code, uom, gst_rate_id,
                          is_tds, tds_percent, is_tcs, tcs_percent
                   FROM finance_service_types
                   WHERE service_code IN ('CHGU01','CHGL01','INFM01','MLAC01','TOLL01')""")
    svc = {r['service_code']: dict(r) for r in cur.fetchall()}

    cur.execute("""
        WITH ldud_latest AS (
            SELECT DISTINCT ON (vcn_id) vcn_id, doc_status
            FROM ldud_header ORDER BY vcn_id, id DESC
        )
        SELECT 'VCN_IMPORT' AS src, c.id, c.parcel_no, c.cargo_name, c.quantity,
               c.equipment_names, c.toll_applicable,
               h.id AS vcn_id, h.vcn_doc_num, h.vessel_name, ll.doc_status AS ldud_status
        FROM vcn_consigners c
        JOIN vcn_header h ON h.id = c.vcn_id
        JOIN ldud_latest ll ON ll.vcn_id = h.id
        WHERE c.importer_name = %s AND ll.doc_status = ANY(%s)
        UNION ALL
        SELECT 'VCN_EXPORT' AS src, e.id, e.parcel_no, e.cargo_name, e.quantity,
               e.equipment_names, e.toll_applicable,
               h.id AS vcn_id, h.vcn_doc_num, h.vessel_name, ll.doc_status AS ldud_status
        FROM vcn_export_cargo_declaration e
        JOIN vcn_header h ON h.id = e.vcn_id
        JOIN ldud_latest ll ON ll.vcn_id = h.id
        WHERE e.importer_name = %s AND ll.doc_status = ANY(%s)
        ORDER BY vcn_doc_num, parcel_no
    """, [customer_name, list(_CARGO_GATE), customer_name, list(_CARGO_GATE)])
    parcels = [dict(r) for r in cur.fetchall()]
    conn.close()

    vessels = {}
    for p in parcels:
        src = p['src']
        qty = _to_float(p['quantity'])
        cargo_code = 'CHGU01' if src == 'VCN_IMPORT' else 'CHGL01'
        # (service_code, cargo_name_for_rate) — cargo_name only for cargo-priced services
        charges = [(cargo_code, p['cargo_name']), ('INFM01', p['cargo_name'])]
        if (p['equipment_names'] or '').strip():
            charges.append(('MLAC01', None))
        if p['toll_applicable']:
            charges.append(('TOLL01', None))

        v = vessels.setdefault(p['vcn_id'], {
            'vcn_id': p['vcn_id'], 'vcn_doc_num': p['vcn_doc_num'],
            'vessel_name': p['vessel_name'], 'ldud_status': p['ldud_status'],
            'lines': [], 'total_amount': 0.0,
        })
        for code, cargo_for_rate in charges:
            st = svc.get(code)
            if not st:
                continue
            remaining = round(qty - billed_qty(src, p['id'], st['id']), 3)
            if remaining <= 1e-6:
                continue
            rate_info = fcam_model.get_customer_rate(
                customer_type, customer_id, st['id'], cargo_name=cargo_for_rate)
            rate = float(rate_info['rate']) if rate_info and rate_info.get('rate') is not None else 0.0
            amount = round(remaining * rate, 2)
            v['lines'].append({
                'cargo_source_type': src, 'cargo_source_id': p['id'],
                'parcel_no': p['parcel_no'], 'service_type_id': st['id'],
                'service_code': code, 'service_name': st['service_name'],
                'cargo_name': p['cargo_name'] or '', 'qty': remaining,
                'uom': st['uom'] or 'MT', 'rate': rate, 'amount': amount,
                'sac_code': st['sac_code'] or '', 'gst_rate_id': st['gst_rate_id'],
                'is_tds': st['is_tds'], 'tds_percent': float(st['tds_percent'] or 0),
                'is_tcs': st['is_tcs'], 'tcs_percent': float(st['tcs_percent'] or 0),
            })
            v['total_amount'] = round(v['total_amount'] + amount, 2)

    return {'vessels': list(vessels.values())}
```

Note: `billed_qty`, `record_parcel_charge`, `get_db`, `get_cursor`, `datetime` already exist in this module (from #2). `get_customer_rate` opens its own connection per call — acceptable at this volume. ponytail: batch later if the line count grows.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_fin01_billables.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Rewire the view to the model**

In `modules/FIN01/views.py`, replace the body of the `get_customer_billables` view (route `/api/module/FIN01/customer-billables/<customer_type>/<int:customer_id>`, starting line 611) with a thin wrapper. Keep the route decorator and login check; replace everything from the docstring through the final `return jsonify(...)`:

```python
@bp.route('/api/module/FIN01/customer-billables/<customer_type>/<int:customer_id>')
def get_customer_billables(customer_type, customer_id):
    """Billables for a customer, grouped by vessel (see FIN01/model)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify(model.get_customer_billables(customer_type, customer_id))
```

Delete the old inline derivation body (the `_build_cargo_item` helper and the A/B/C queries) that this view previously contained, up to the old `return jsonify({...})`. Do not touch other views (`agreement-rate`, `cargo-rates`, `service-records`, etc.).

- [ ] **Step 7: Verify view imports resolve**

Run: `python -c "import ast; ast.parse(open('modules/FIN01/views.py').read()); print('ok')"` then `python -m pytest tests/test_fin01_billables.py -q`
Expected: `ok` and 3 passing.

- [ ] **Step 8: Commit**

```bash
git add modules/FIN01/model.py modules/FIN01/views.py tests/test_fin01_billables.py
git commit -m "feat(fin01): billables-from-parcels engine grouped by vessel"
```

---

### Task 3: FIN01 UI — vessel-accordion bill generation

**Files:**
- Modify: `modules/FIN01/generate_bill.html`

**Interfaces:**
- Consumes: `GET /api/module/FIN01/customer-billables/<type>/<id>` → `{vessels:[{vcn_id, vcn_doc_num, vessel_name, ldud_status, lines:[…], total_amount}]}` (Task 2). Each line: `cargo_source_type, cargo_source_id, service_type_id, service_code, service_name, parcel_no, cargo_name, qty, uom, rate, amount`.

- [ ] **Step 1: Render vessels as accordions**

In `modules/FIN01/generate_bill.html`, in the customer-load handler that fetches `/customer-billables/…`, replace the cargo-cards + other-services rendering with vessel accordions. Use this render function (adapt IDs to the file's existing container; the billables container is where cargo cards were rendered):

```javascript
function renderVessels(vessels) {
  const root = document.getElementById('billablesRoot'); // container that held cargo cards
  if (!vessels.length) { root.innerHTML = '<div class="empty-state">No billable vessels for this customer.</div>'; return; }
  root.innerHTML = vessels.map((v, vi) => `
    <div class="vessel-card" data-vcn="${v.vcn_id}">
      <div class="vessel-head collapsible-header" onclick="toggleVessel(${vi})">
        <span class="toggle-icon" id="vic-${vi}">▸</span>
        <b>${v.vcn_doc_num}</b> · ${v.vessel_name || ''}
        <span class="ldud-badge">LDUD: ${v.ldud_status}</span>
        <span style="margin-left:auto;font-weight:600;">Billable: ₹${(v.total_amount||0).toFixed(2)}</span>
      </div>
      <div class="vessel-body" id="vb-${vi}" style="display:none;">
        <table class="data-table"><thead><tr>
          <th></th><th>Parcel</th><th>Cargo</th><th>Service</th><th>Qty</th><th>Rate</th><th>Amount</th>
        </tr></thead><tbody>
        ${v.lines.map((l, li) => `
          <tr>
            <td><input type="checkbox" class="bl-chk" data-vi="${vi}" data-li="${li}" ${l.rate>0?'checked':''} onchange="recalcSel()"></td>
            <td>${l.parcel_no||''}</td><td>${l.cargo_name||''}</td>
            <td>${l.service_name} <small>(${l.service_code})</small></td>
            <td style="text-align:right"><input type="number" class="bl-qty" data-vi="${vi}" data-li="${li}" value="${l.qty}" max="${l.qty}" step="0.001" style="width:80px" onchange="clampQty(this,${l.qty});recalcSel()"> ${l.uom}</td>
            <td style="text-align:right"><input type="number" class="bl-rate" data-vi="${vi}" data-li="${li}" value="${l.rate||''}" step="0.01" placeholder="0.00" style="width:80px" onchange="recalcSel()">${l.rate>0?'':' <span style="color:#dc2626;font-size:10px">enter rate</span>'}</td>
            <td style="text-align:right" id="amt-${vi}-${li}">₹${(l.amount||0).toFixed(2)}</td>
          </tr>`).join('')}
        </tbody></table>
      </div>
    </div>`).join('');
  window._vessels = vessels;
  recalcSel();
}

function toggleVessel(vi) {
  const b = document.getElementById('vb-'+vi), ic = document.getElementById('vic-'+vi);
  const open = b.style.display === 'none';
  b.style.display = open ? 'block' : 'none'; ic.textContent = open ? '▾' : '▸';
}

function clampQty(inp, max) {
  let v = parseFloat(inp.value)||0; if (v > max) inp.value = max; if (v < 0) inp.value = 0;
}

function recalcSel() {
  let sel = 0;
  document.querySelectorAll('.bl-chk').forEach(chk => {
    const vi = chk.dataset.vi, li = chk.dataset.li;
    const qty = parseFloat(document.querySelector(`.bl-qty[data-vi="${vi}"][data-li="${li}"]`).value)||0;
    const rate = parseFloat(document.querySelector(`.bl-rate[data-vi="${vi}"][data-li="${li}"]`).value)||0;
    const amt = Math.round(qty*rate*100)/100;
    document.getElementById(`amt-${vi}-${li}`).textContent = '₹'+amt.toFixed(2);
    if (chk.checked) sel += amt;
  });
  const el = document.getElementById('selectedTotal'); if (el) el.textContent = '₹'+sel.toFixed(2);
}
```

Wire the customer-load handler to call `renderVessels(data.vessels || [])` instead of the old `renderCargoCards`/`renderOtherServices`. Keep a "Generate Bill" button and a `#selectedTotal` display; the button's POST handler is implemented in sub-project #4 (leave the existing handler or disable it with a note `// #4: wire generate to write bill_lines + ledger`).

- [ ] **Step 2: Add minimal styles**

Add to the page's `<style>`:

```css
.vessel-card { border:1px solid #e2e8f0; border-radius:6px; margin-bottom:10px; }
.vessel-head { display:flex; align-items:center; gap:8px; padding:8px 10px; cursor:pointer; background:#f8fafc; }
.ldud-badge { font-size:10px; background:#dbeafe; color:#1e40af; padding:1px 7px; border-radius:8px; }
.vessel-body { padding:6px 10px; }
```

- [ ] **Step 3: Manual smoke test**

Run the app; open FIN01 → Generate Bill; pick a customer who is `importer_name` on parcels of a Closed/Partial-Close LDUD vessel. Expected: vessels listed with billable totals; expand shows the 4 charge lines (2 if no equipment/toll); editing qty/rate updates line + selected totals; MLA/Toll appear only when applicable. (No automated FE test in this stack.)

- [ ] **Step 4: Commit**

```bash
git add modules/FIN01/generate_bill.html
git commit -m "feat(fin01): vessel-accordion bill generation UI over the billables engine"
```

---

## Self-Review

**Spec coverage:**
- §1 engine (grouped by vessel, 4 charges, rate resolution, ledger remaining, LDUD gate, payer=importer_name) → Task 2. ✓
- §2 FCAM Infrastructure per-cargo → Task 1. ✓
- §3 vessel-grouped UI → Task 3. ✓
- Out of scope (write path #4) → not implemented; UI selects only. ✓
- Testing (4-line parcel, 2-line parcel, ledger remaining, Draft LDUD) → Task 2 tests. ✓

**Placeholder scan:** none — full code for engine, test, FCAM, and UI render.

**Type consistency:** line keys (`cargo_source_type/id`, `service_type_id`, `service_code`, `qty`, `rate`, `amount`) identical across engine, test, and UI; `billed_qty`/`record_parcel_charge` signatures match #2.

## Notes / knowingly deferred
- Per-line rate lookup opens a connection per call; fine at this scale, batch if needed.
- "Generate Bill" write + ledger recording is #4; this plan renders + selects only.
- Old `other_services`/`service_records` billables are dropped from this view per spec.
