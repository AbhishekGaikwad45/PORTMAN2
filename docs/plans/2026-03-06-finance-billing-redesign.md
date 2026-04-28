# Finance Billing Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the finance billing flow so that (1) Cargo Handling Loading/Unloading are hardcoded system services not editable in FSTM01 but available in agreements and billing, (2) SRV01 records services against customer/agent (primary) with optional VCN/MBC reference, and (3) FIN01 bill generation is customer-centric with a clean card-based UI gated by LDUD vessel closure.

**Architecture:** Three coordinated changes across DB schema, backend models/views, and frontend templates. One Alembic migration covers all schema changes. FSTM01 UI hides system rows via `is_system` flag. SRV01 repurposes `source_type`/`source_id` to mean Customer/Agent and adds two nullable `ref_source_*` columns for the optional VCN/MBC context. FIN01 `generate_bill.html` is rewritten around a new `/api/module/FIN01/customer-billables` endpoint that aggregates cargo handling (gated by LDUD closure) and other services into a single response.

**Tech Stack:** Flask, PostgreSQL/psycopg2, Alembic, Jinja2, vanilla JS

---

## Task 1: Database Migration

**Files:**
- Create: `alembic/versions/a1b2c3d4e5f7_billing_redesign.py`

This is the only schema change. Everything else is code-only.

**Step 1: Create the migration file**

```python
"""billing redesign: is_system on service types, ref_source on service_records

Revision ID: a1b2c3d4e5f7
Revises: f9e8d7c6b5a4
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'f9e8d7c6b5a4'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add is_system flag to finance_service_types
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='finance_service_types' AND column_name='is_system'
            ) THEN
                ALTER TABLE finance_service_types ADD COLUMN is_system SMALLINT DEFAULT 0;
            END IF;
        END $$
    """)

    # 2. Seed the two hardcoded cargo handling service types
    #    Use INSERT ... ON CONFLICT DO NOTHING so re-runs are safe.
    op.execute("""
        INSERT INTO finance_service_types
            (service_code, service_name, service_category, uom, is_billable, is_active, is_system)
        VALUES
            ('CARGO_LOAD',   'Cargo Handling Loading',   'Cargo Handling', 'MT', 1, 1, 1),
            ('CARGO_UNLOAD', 'Cargo Handling Unloading', 'Cargo Handling', 'MT', 1, 1, 1)
        ON CONFLICT (service_code) DO UPDATE SET is_system = 1
    """)

    # 3. Add optional VCN/MBC reference columns to service_records
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='service_records' AND column_name='ref_source_type'
            ) THEN
                ALTER TABLE service_records
                    ADD COLUMN ref_source_type VARCHAR(10),
                    ADD COLUMN ref_source_id INTEGER,
                    ADD COLUMN ref_source_display VARCHAR(255);
            END IF;
        END $$
    """)


def downgrade():
    op.execute("ALTER TABLE service_records DROP COLUMN IF EXISTS ref_source_display")
    op.execute("ALTER TABLE service_records DROP COLUMN IF EXISTS ref_source_id")
    op.execute("ALTER TABLE service_records DROP COLUMN IF EXISTS ref_source_type")
    op.execute("""
        DELETE FROM finance_service_types
        WHERE service_code IN ('CARGO_LOAD', 'CARGO_UNLOAD')
    """)
    op.execute("ALTER TABLE finance_service_types DROP COLUMN IF EXISTS is_system")
```

**Step 2: Run the migration**

```bash
cd d:/PORTMAN
alembic upgrade head
```

Expected: `Running upgrade f9e8d7c6b5a4 -> a1b2c3d4e5f7, billing redesign`

**Step 3: Commit**

```bash
git add alembic/versions/a1b2c3d4e5f7_billing_redesign.py
git commit -m "feat: billing redesign migration - is_system flag, cargo handling seed, ref_source cols"
```

---

## Task 2: FSTM01 — Hide System Service Types

**Files:**
- Modify: `modules/FSTM01/model.py` (3 functions)

System rows (`is_system=1`) must never appear in the FSTM01 editor but must be available to FCAM01 and FIN01.

**Step 1: Update `get_service_type_data`** — add `WHERE (is_system IS NULL OR is_system = 0)` to the COUNT and SELECT queries.

```python
def get_service_type_data(page=1, size=20):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT COUNT(*) FROM finance_service_types WHERE COALESCE(is_system,0)=0")
    total = cur.fetchone()['count']
    cur.execute('''
        SELECT s.*, g.rate_name as gst_rate_name
        FROM finance_service_types s
        LEFT JOIN gst_rates g ON s.gst_rate_id = g.id
        WHERE COALESCE(s.is_system,0) = 0
        ORDER BY s.service_name
        LIMIT %s OFFSET %s
    ''', (size, (page-1)*size))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total
```

**Step 2: No changes needed** to `get_all_service_types` or `get_billable_service_types` — they intentionally include system rows so FCAM01 and FIN01 can see Cargo Handling.

**Step 3: Commit**

```bash
git add modules/FSTM01/model.py
git commit -m "feat: hide is_system service types from FSTM01 editor"
```

---

## Task 3: FCAM01 — Cargo Handling in Agreement Lines Dropdown

**Files:**
- Modify: `modules/FCAM01/views.py`

The service types endpoint already queries `finance_service_types` without filtering `is_system`, so Cargo Handling Loading/Unloading will automatically appear in the FCAM01 agreement lines dropdown after the migration. **No code change needed here.**

Verify by opening FCAM01 → New Agreement → Add Service line → the dropdown should include "Cargo Handling Loading" and "Cargo Handling Unloading".

**Step 1: Confirm `get_service_types` in FCAM01 views.py includes all active types**

In `modules/FCAM01/views.py`, the `entry` route passes `service_types` to the template. It comes from `model.get_all_service_types()` or similar. Check that the query does NOT filter `is_system`. If it does, remove the filter.

Current call in FCAM01 entry view (from session summary): passes `service_types={{ service_types|tojson|safe }}` to JS. The data comes from FSTM01 `get_all_service_types()` or a direct query — confirm it returns all active types without is_system filter. Since `get_all_service_types()` in FSTM01 model has no `is_system` filter, this is already correct.

**Step 2: Commit**

```bash
git commit -m "feat: cargo handling services now visible in FCAM01 agreement lines (via migration seed)"
```

---

## Task 4: SRV01 Model — Customer/Agent as Primary Source

**Files:**
- Modify: `modules/SRV01/model.py`

**Step 1: Update `save_service_record`** — add `ref_source_type`, `ref_source_id`, `ref_source_display` to both INSERT and UPDATE.

```python
def save_service_record(header_data, field_values):
    conn = get_db()
    cur = get_cursor(conn)
    record_id = header_data.get('id')

    if record_id:
        cur.execute('''
            UPDATE service_records
            SET service_type_id=%s, source_type=%s, source_id=%s, source_display=%s,
                ref_source_type=%s, ref_source_id=%s, ref_source_display=%s,
                record_date=%s, billable_quantity=%s, billable_uom=%s,
                doc_status=%s, remarks=%s
            WHERE id=%s
        ''', [
            header_data.get('service_type_id'),
            header_data.get('source_type'),
            header_data.get('source_id'),
            header_data.get('source_display'),
            header_data.get('ref_source_type'),
            header_data.get('ref_source_id'),
            header_data.get('ref_source_display'),
            header_data.get('record_date'),
            header_data.get('billable_quantity'),
            header_data.get('billable_uom'),
            header_data.get('doc_status', 'Pending'),
            header_data.get('remarks'),
            record_id
        ])
        cur.execute('DELETE FROM service_record_values WHERE service_record_id = %s', [record_id])
    else:
        header_data['record_number'] = get_next_record_number()
        cur.execute('''
            INSERT INTO service_records
            (record_number, service_type_id, source_type, source_id, source_display,
             ref_source_type, ref_source_id, ref_source_display,
             record_date, billable_quantity, billable_uom, doc_status,
             created_by, created_date, remarks)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', [
            header_data['record_number'],
            header_data.get('service_type_id'),
            header_data.get('source_type'),
            header_data.get('source_id'),
            header_data.get('source_display'),
            header_data.get('ref_source_type'),
            header_data.get('ref_source_id'),
            header_data.get('ref_source_display'),
            header_data.get('record_date'),
            header_data.get('billable_quantity'),
            header_data.get('billable_uom'),
            header_data.get('doc_status', 'Pending'),
            header_data.get('created_by'),
            datetime.now().strftime('%Y-%m-%d'),
            header_data.get('remarks')
        ])
        record_id = cur.fetchone()['id']

    for fv in field_values:
        cur.execute('''
            INSERT INTO service_record_values
            (service_record_id, field_definition_id, field_value)
            VALUES (%s, %s, %s)
        ''', [record_id, fv['field_definition_id'], fv.get('field_value')])

    conn.commit()
    conn.close()
    return record_id, header_data.get('record_number')
```

**Step 2: Update `get_unbilled_records_for_source`** — this is called by FIN01 with customer type+id now. No SQL change needed; the function already queries generically by `source_type` + `source_id`.

**Step 3: Commit**

```bash
git add modules/SRV01/model.py
git commit -m "feat: SRV01 model supports ref_source columns for optional VCN/MBC reference"
```

---

## Task 5: SRV01 Views — Customer/Agent Source Options Endpoint

**Files:**
- Modify: `modules/SRV01/views.py`

**Step 1: Update `get_source_options` to handle Customer and Agent**

Add two new source types to the existing endpoint:

```python
@bp.route('/api/module/SRV01/source-options/<source_type>')
def get_source_options(source_type):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    conn = get_db()
    cur = get_cursor(conn)

    if source_type == 'Customer':
        cur.execute("SELECT id, name FROM vessel_customers ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        return jsonify({'data': [{'id': r['id'], 'display': r['name']} for r in rows]})

    elif source_type == 'Agent':
        cur.execute("SELECT id, name FROM vessel_agents ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        return jsonify({'data': [{'id': r['id'], 'display': r['name']} for r in rows]})

    elif source_type == 'VCN':
        cur.execute('''
            SELECT h.id, h.vcn_doc_num, h.vessel_name, a.anchorage_arrival
            FROM vcn_header h
            LEFT JOIN vcn_anchorage a ON h.id = a.vcn_id
            ORDER BY h.id DESC
        ''')
        rows = cur.fetchall()
        conn.close()
        result = []
        for r in rows:
            r = dict(r)
            anchored = str(r.get('anchorage_arrival') or '')[:16].replace('T', ' ')
            result.append({'id': r['id'], 'display': f"{r['vcn_doc_num']} / {r['vessel_name']} / {anchored}"})
        return jsonify({'data': result})

    elif source_type == 'MBC':
        cur.execute('SELECT id, doc_num, mbc_name, doc_date FROM mbc_header ORDER BY id DESC')
        rows = cur.fetchall()
        conn.close()
        return jsonify({'data': [
            {'id': r['id'], 'display': f"{r['doc_num']} / {r['mbc_name']} / {r.get('doc_date','')}"}
            for r in rows
        ]})

    conn.close()
    return jsonify({'data': []})
```

**Step 2: Update `save` route** — pass through the new ref fields from request JSON to `header_data`:

In the existing `save` route, add to the `header_data` dict:
```python
header_data['ref_source_type'] = data.get('ref_source_type')
header_data['ref_source_id'] = data.get('ref_source_id')
header_data['ref_source_display'] = data.get('ref_source_display')
```

**Step 3: Commit**

```bash
git add modules/SRV01/views.py
git commit -m "feat: SRV01 views - Customer/Agent source options, ref_source passthrough in save"
```

---

## Task 6: SRV01 HTML — Redesigned Entry Form

**Files:**
- Modify: `modules/SRV01/srv01.html`

**Step 1: Replace the source selection section in the entry form**

Replace the current two-field source row:
```html
<!-- OLD -->
<div class="form-group">
    <label>Source Type</label>
    <select id="sourceType" onchange="loadSourceOptions()">
        <option value="">-- Select --</option>
        <option value="VCN">VCN (Vessel Call)</option>
        <option value="MBC">MBC (MBC Operation)</option>
    </select>
</div>
<div class="form-group">
    <label>Source Document</label>
    <select id="sourceId" onchange="onSourceSelected()">...</select>
</div>
```

With this new four-field row (customer required, VCN/MBC optional):
```html
<div class="form-grid" style="grid-template-columns: 1fr 2fr 1fr 2fr;">
    <div class="form-group">
        <label>Customer Type *</label>
        <select id="sourceType" onchange="loadSourceOptions()" required>
            <option value="Customer" selected>Customer</option>
            <option value="Agent">Agent</option>
        </select>
    </div>
    <div class="form-group">
        <label>Customer / Agent *</label>
        <select id="sourceId">
            <option value="">-- Loading... --</option>
        </select>
    </div>
    <div class="form-group">
        <label>Linked VCN / MBC <span style="color:#aaa;font-weight:400">(optional)</span></label>
        <select id="refSourceType" onchange="loadRefSourceOptions()">
            <option value="">-- None --</option>
            <option value="VCN">VCN</option>
            <option value="MBC">MBC</option>
        </select>
    </div>
    <div class="form-group">
        <label>&nbsp;</label>
        <select id="refSourceId" style="display:none">
            <option value="">-- Select --</option>
        </select>
        <span id="refSourcePlaceholder" style="font-size:11px;color:#aaa;padding:6px 0;display:block;">No VCN/MBC linked</span>
    </div>
</div>
```

**Step 2: Update the list table** — add a "Ref" column after the Source column:

```html
<th>Customer / Agent</th>
<th>Ref (VCN/MBC)</th>
```

And in the Jinja rows:
```html
<td>{{ row.source_display }}</td>
<td>{{ row.ref_source_display or '—' }}</td>
```

**Step 3: Update JS — `resetForm`, `loadSourceOptions`, add `loadRefSourceOptions`, update `saveRecord` payload, update `editRecord` to restore ref fields**

Key JS additions:

```javascript
// On page load, auto-load customers
document.addEventListener('DOMContentLoaded', () => {
    loadServiceTypes();
    loadSourceOptions();  // loads Customers by default
});

async function loadRefSourceOptions() {
    const type = document.getElementById('refSourceType').value;
    const sel = document.getElementById('refSourceId');
    const placeholder = document.getElementById('refSourcePlaceholder');
    if (!type) {
        sel.style.display = 'none';
        placeholder.style.display = 'block';
        return;
    }
    sel.style.display = 'block';
    placeholder.style.display = 'none';
    sel.innerHTML = '<option value="">-- Loading... --</option>';
    const resp = await fetch(`/api/module/SRV01/source-options/${type}`);
    const json = await resp.json();
    sel.innerHTML = '<option value="">-- Select --</option>';
    (json.data || []).forEach(opt => {
        sel.innerHTML += `<option value="${opt.id}">${opt.display}</option>`;
    });
}
```

In `saveRecord`, add ref fields to payload:
```javascript
const refTypeEl = document.getElementById('refSourceType');
const refIdEl = document.getElementById('refSourceId');
const refOpt = refIdEl.selectedOptions[0];
payload.ref_source_type = refTypeEl.value || null;
payload.ref_source_id = refIdEl.value ? parseInt(refIdEl.value) : null;
payload.ref_source_display = (refIdEl.value && refOpt) ? refOpt.textContent : null;
```

In `resetForm`:
```javascript
document.getElementById('refSourceType').value = '';
document.getElementById('refSourceId').style.display = 'none';
document.getElementById('refSourcePlaceholder').style.display = 'block';
```

In `editRecord`, after setting source fields, restore ref fields from `h`:
```javascript
document.getElementById('refSourceType').value = h.ref_source_type || '';
if (h.ref_source_type) {
    await loadRefSourceOptions();
    document.getElementById('refSourceId').value = h.ref_source_id || '';
}
```

Also update the `filterSource` dropdown in the filters bar:
```html
<select id="filterSource" onchange="applyFilters()">
    <option value="">All</option>
    <option value="Customer">Customer</option>
    <option value="Agent">Agent</option>
</select>
```

**Step 4: Commit**

```bash
git add modules/SRV01/srv01.html
git commit -m "feat: SRV01 UI - customer/agent as primary source, optional VCN/MBC reference"
```

---

## Task 7: FIN01 — Customer Billables API Endpoint

**Files:**
- Modify: `modules/FIN01/views.py`

This is the core new backend endpoint. It aggregates all unbilled items for a customer into one response.

**Step 1: Add the `customer-billables` endpoint**

```python
@bp.route('/api/module/FIN01/customer-billables/<customer_type>/<int:customer_id>')
def get_customer_billables(customer_type, customer_id):
    """Aggregate all billable items for a customer:
       - cargo_handling: grouped by VCN/MBC, gated by LDUD/MBC closure
       - other_services: approved unbilled service_records for this customer
       - billed: previously billed items for reference
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    conn = get_db()
    cur = get_cursor(conn)

    # ── 1. Cargo Handling from lueu_lines ──────────────────────────────────
    # Get all lueu_lines grouped by source doc, check LDUD/MBC closure status
    cur.execute('''
        SELECT
            ll.source_type,
            ll.source_id,
            ll.operation_type,
            COALESCE(SUM(ll.quantity), 0) AS total_qty,
            ll.quantity_uom,
            -- VCN source: join to ldud_header for closure status
            CASE WHEN ll.source_type = 'VCN' THEN
                (SELECT lh.doc_status FROM ldud_header lh WHERE lh.vcn_id = ll.source_id LIMIT 1)
            WHEN ll.source_type = 'MBC' THEN
                (SELECT mh.doc_status FROM mbc_header mh WHERE mh.id = ll.source_id LIMIT 1)
            END AS doc_status,
            CASE WHEN ll.source_type = 'VCN' THEN
                (SELECT h.vcn_doc_num || ' / ' || h.vessel_name FROM vcn_header h WHERE h.id = ll.source_id)
            WHEN ll.source_type = 'MBC' THEN
                (SELECT h.doc_num || ' / ' || h.mbc_name FROM mbc_header h WHERE h.id = ll.source_id)
            END AS source_display,
            CASE WHEN ll.source_type = 'VCN' THEN
                (SELECT h.doc_date FROM vcn_header h WHERE h.id = ll.source_id)
            WHEN ll.source_type = 'MBC' THEN
                (SELECT h.doc_date FROM mbc_header h WHERE h.id = ll.source_id)
            END AS source_date
        FROM lueu_lines ll
        WHERE ll.is_billed = FALSE OR ll.is_billed IS NULL
        GROUP BY ll.source_type, ll.source_id, ll.operation_type, ll.quantity_uom
        ORDER BY source_date DESC NULLS LAST
    ''')
    eu_rows = [dict(r) for r in cur.fetchall()]

    # Look up cargo handling service type IDs
    cur.execute("""
        SELECT id, service_code, sac_code, gl_code, gst_rate_id,
               COALESCE(g.cgst_rate,0) as cgst_rate,
               COALESCE(g.sgst_rate,0) as sgst_rate,
               COALESCE(g.igst_rate,0) as igst_rate
        FROM finance_service_types s
        LEFT JOIN gst_rates g ON s.gst_rate_id = g.id
        WHERE s.service_code IN ('CARGO_LOAD', 'CARGO_UNLOAD')
    """)
    cargo_service_map = {r['service_code']: dict(r) for r in cur.fetchall()}

    cargo_handling = []
    for row in eu_rows:
        op_type = (row.get('operation_type') or '').lower()
        svc_code = 'CARGO_LOAD' if op_type == 'export' else 'CARGO_UNLOAD'
        svc = cargo_service_map.get(svc_code, {})
        status = row.get('doc_status') or 'Draft'
        is_billable = status in ('Closed', 'Partial Close')
        cargo_handling.append({
            'source_type': row['source_type'],
            'source_id': row['source_id'],
            'source_display': row['source_display'] or '',
            'source_date': str(row['source_date']) if row['source_date'] else '',
            'operation_type': row.get('operation_type', ''),
            'service_name': svc.get('service_name', 'Cargo Handling'),
            'service_type_id': svc.get('id'),
            'service_code': svc_code,
            'quantity': float(row['total_qty'] or 0),
            'uom': row.get('quantity_uom', 'MT'),
            'doc_status': status,
            'is_billable': is_billable,
            'sac_code': svc.get('sac_code'),
            'gl_code': svc.get('gl_code'),
            'gst_rate_id': svc.get('gst_rate_id'),
            'cgst_rate': svc.get('cgst_rate', 0),
            'sgst_rate': svc.get('sgst_rate', 0),
            'igst_rate': svc.get('igst_rate', 0),
        })

    # ── 2. Other Services (service_records for this customer) ───────────────
    cur.execute('''
        SELECT sr.id, sr.record_number, sr.record_date, sr.billable_quantity,
               sr.billable_uom, sr.remarks, sr.ref_source_display,
               st.id as service_type_id, st.service_name, st.sac_code, st.gl_code,
               st.gst_rate_id,
               COALESCE(g.cgst_rate,0) as cgst_rate,
               COALESCE(g.sgst_rate,0) as sgst_rate,
               COALESCE(g.igst_rate,0) as igst_rate
        FROM service_records sr
        JOIN finance_service_types st ON sr.service_type_id = st.id
        LEFT JOIN gst_rates g ON st.gst_rate_id = g.id
        WHERE sr.source_type = %s AND sr.source_id = %s
          AND sr.doc_status = 'Approved' AND sr.is_billed = 0
        ORDER BY sr.record_date DESC, sr.id DESC
    ''', [customer_type, customer_id])
    other_services = [dict(r) for r in cur.fetchall()]

    # ── 3. Already Billed (for reference) ───────────────────────────────────
    cur.execute('''
        SELECT bh.id as bill_id, bh.bill_number, bh.bill_date, bh.total_amount,
               bh.bill_status, bl.service_name, bl.quantity, bl.uom, bl.line_amount
        FROM bill_header bh
        JOIN bill_lines bl ON bl.bill_id = bh.id
        WHERE bh.customer_type = %s AND bh.customer_id = %s
        ORDER BY bh.id DESC
        LIMIT 50
    ''', [customer_type, customer_id])
    billed = [dict(r) for r in cur.fetchall()]

    conn.close()

    return jsonify({
        'cargo_handling': cargo_handling,
        'other_services': other_services,
        'billed': billed
    })
```

**Step 2: Commit**

```bash
git add modules/FIN01/views.py
git commit -m "feat: FIN01 customer-billables endpoint aggregating cargo handling + services + billed"
```

---

## Task 8: FIN01 — Customer/Agent Rate Lookup

**Files:**
- Modify: `modules/FIN01/views.py`

The existing `/api/module/FIN01/agreement-rate/<customer_id>/<service_type_id>` uses `customer_id` but not `customer_type`. Update it to accept customer_type as a query param so cargo handling rate lookup works.

**Step 1: Update the endpoint signature** to also accept `customer_type` query param:

```python
@bp.route('/api/module/FIN01/agreement-rate/<int:customer_id>/<int:service_type_id>')
def get_agreement_rate(customer_id, service_type_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    from datetime import datetime
    conn = get_db()
    cur = get_cursor(conn)
    today = datetime.now().strftime('%Y-%m-%d')
    agreement_id = request.args.get('agreement_id')
    customer_type = request.args.get('customer_type', 'Customer')

    if agreement_id:
        cur.execute('''
            SELECT cal.rate, cal.uom, cal.currency_code,
                   ca.agreement_code, ca.agreement_name
            FROM customer_agreement_lines cal
            INNER JOIN customer_agreements ca ON cal.agreement_id = ca.id
            WHERE ca.id = %s AND cal.service_type_id = %s
        ''', [agreement_id, service_type_id])
    else:
        cur.execute('''
            SELECT cal.rate, cal.uom, cal.currency_code,
                   ca.agreement_code, ca.agreement_name
            FROM customer_agreement_lines cal
            INNER JOIN customer_agreements ca ON cal.agreement_id = ca.id
            WHERE ca.customer_type = %s AND ca.customer_id = %s
              AND cal.service_type_id = %s
              AND ca.is_active = 1 AND ca.agreement_status = 'Approved'
              AND ca.valid_from <= %s
              AND (ca.valid_to IS NULL OR ca.valid_to >= %s)
            ORDER BY ca.valid_from DESC
            LIMIT 1
        ''', [customer_type, customer_id, service_type_id, today, today])

    row = cur.fetchone()
    conn.close()
    return jsonify({'success': True, 'data': dict(row)}) if row else jsonify({'success': False, 'error': 'No valid agreement found'})
```

**Step 2: Commit**

```bash
git add modules/FIN01/views.py
git commit -m "feat: agreement-rate endpoint now respects customer_type for cargo handling lookup"
```

---

## Task 9: FIN01 — Rewrite generate_bill.html

**Files:**
- Modify: `modules/FIN01/generate_bill.html`

This is the largest frontend change. The entire bill generation flow is rewritten around the customer-centric card UI.

**Step 1: Replace the Bill Header section**

Remove `Source Type` and `Source Document` fields. Keep only:
- Customer Type (Customer / Agent, default Customer)
- Customer Name dropdown
- Bill Date
- Agreement (auto-loaded when customer selected)
- [Load Billables] button

```html
<div class="form-section">
    <h3>Bill Header</h3>
    <div class="form-grid" style="grid-template-columns: 1fr 2fr 1fr 1fr auto;">
        <div class="form-field">
            <label>Customer Type</label>
            <select id="customerType" onchange="loadCustomers()">
                <option value="Customer" selected>Customer</option>
                <option value="Agent">Agent</option>
            </select>
        </div>
        <div class="form-field">
            <label>Customer *</label>
            <select id="customerName" onchange="onCustomerChange()">
                <option value="">-- Select --</option>
            </select>
        </div>
        <div class="form-field">
            <label>Agreement</label>
            <select id="agreementId">
                <option value="">-- Auto / Latest --</option>
            </select>
        </div>
        <div class="form-field">
            <label>Bill Date</label>
            <input type="date" id="billDate" value="{{ current_date }}" required>
        </div>
        <div class="form-field" style="justify-content:flex-end;padding-top:18px;">
            <button type="button" class="btn btn-primary" onclick="loadBillables()">Load Billables</button>
        </div>
    </div>
</div>
```

**Step 2: Add the three billable sections below the header**

```html
<div id="billablesPanel" style="display:none;">

    <!-- Section A: Cargo Handling -->
    <div class="form-section">
        <h3 style="cursor:pointer;" onclick="toggleSection('cargoSection')">
            ▼ Cargo Handling
            <span id="cargoCount" style="font-weight:400;font-size:11px;color:#718096;margin-left:8px;"></span>
        </h3>
        <div id="cargoSection">
            <div id="cargoCards"></div>
        </div>
    </div>

    <!-- Section B: Other Services -->
    <div class="form-section">
        <h3 style="cursor:pointer;" onclick="toggleSection('servicesSection')">
            ▶ Other Services
            <span id="servicesCount" style="font-weight:400;font-size:11px;color:#718096;margin-left:8px;"></span>
        </h3>
        <div id="servicesSection" style="display:none;">
            <div id="servicesTable"></div>
        </div>
    </div>

    <!-- Section C: Already Billed -->
    <div class="form-section" style="opacity:0.7;">
        <h3 style="cursor:pointer;color:#718096;" onclick="toggleSection('billedSection')">
            ▶ Already Billed
            <span id="billedCount" style="font-weight:400;font-size:11px;margin-left:8px;"></span>
        </h3>
        <div id="billedSection" style="display:none;">
            <div id="billedTable"></div>
        </div>
    </div>

</div>

<!-- Sticky total bar -->
<div id="totalBar" style="display:none;position:sticky;bottom:0;background:white;border-top:2px solid #e2e8f0;
     padding:12px 20px;display:flex;align-items:center;gap:20px;z-index:100;box-shadow:0 -2px 8px rgba(0,0,0,0.1);">
    <span style="font-size:12px;color:#555;">Selected: <strong id="selectedCount">0</strong> items</span>
    <span style="font-size:12px;color:#555;">Subtotal: <strong id="subtotalDisplay">₹0.00</strong></span>
    <span style="font-size:12px;color:#555;">GST: <strong id="gstDisplay">₹0.00</strong></span>
    <span style="font-size:14px;font-weight:700;">Total: <strong id="totalDisplay">₹0.00</strong></span>
    <button type="button" class="btn btn-success" onclick="generateBill()" style="margin-left:auto;">Generate Bill</button>
</div>
```

**Step 3: Add the JavaScript**

Key functions to implement in the `<script>` block:

```javascript
// State
let billablesData = { cargo_handling: [], other_services: [], billed: [] };
let customersList = [];
let portConfig = {};

// On page load
document.addEventListener('DOMContentLoaded', async () => {
    await loadCustomers();
    portConfig = await fetch('/api/module/FIN01/port-config').then(r => r.json());
});

async function loadCustomers() {
    const type = document.getElementById('customerType').value;
    const res = await fetch(`/api/module/FIN01/customers/${type}`);
    const json = await res.json();
    customersList = json.data || [];
    const sel = document.getElementById('customerName');
    sel.innerHTML = '<option value="">-- Select --</option>';
    customersList.forEach(c => {
        sel.innerHTML += `<option value="${c.id}" data-gstin="${c.gstin||''}"
            data-state="${c.gst_state_code||''}" data-address="${c.billing_address||''}">${c.name}</option>`;
    });
    document.getElementById('billablesPanel').style.display = 'none';
    document.getElementById('totalBar').style.display = 'none';
}

async function onCustomerChange() {
    const customerId = document.getElementById('customerName').value;
    const customerType = document.getElementById('customerType').value;
    if (!customerId) return;
    // Load agreements
    const res = await fetch(`/api/module/FIN01/customer-agreements/${customerId}`);
    const json = await res.json();
    const sel = document.getElementById('agreementId');
    sel.innerHTML = '<option value="">-- Auto / Latest --</option>';
    (json.data || []).forEach(a => {
        sel.innerHTML += `<option value="${a.id}">${a.agreement_code} - ${a.agreement_name}</option>`;
    });
}

async function loadBillables() {
    const customerId = document.getElementById('customerName').value;
    const customerType = document.getElementById('customerType').value;
    if (!customerId) { alert('Please select a customer first'); return; }

    const res = await fetch(`/api/module/FIN01/customer-billables/${customerType}/${customerId}`);
    billablesData = await res.json();

    renderCargoCards(billablesData.cargo_handling);
    renderServicesTable(billablesData.other_services);
    renderBilledTable(billablesData.billed);

    document.getElementById('billablesPanel').style.display = 'block';
    document.getElementById('totalBar').style.display = 'flex';
    recalcTotals();
}

function renderCargoCards(items) {
    const container = document.getElementById('cargoCards');
    const billable = items.filter(i => i.is_billable);
    const locked = items.filter(i => !i.is_billable);
    document.getElementById('cargoCount').textContent =
        `${billable.length} billable, ${locked.length} locked`;

    container.innerHTML = [...billable, ...locked].map((item, idx) => {
        const statusBadge = item.is_billable
            ? `<span style="background:#c6f6d5;color:#276749;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;">${item.doc_status}</span>`
            : `<span style="background:#fed7d7;color:#c53030;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;">${item.doc_status || 'Not Closed'}</span>`;
        const lockIcon = item.is_billable ? '' : '🔒 ';
        const cardStyle = item.is_billable
            ? 'border:1px solid #e2e8f0;border-radius:6px;padding:12px 16px;margin-bottom:8px;background:white;display:flex;align-items:center;gap:12px;'
            : 'border:1px solid #e2e8f0;border-radius:6px;padding:12px 16px;margin-bottom:8px;background:#f7fafc;display:flex;align-items:center;gap:12px;opacity:0.7;';

        return `<div style="${cardStyle}">
            ${item.is_billable
                ? `<input type="checkbox" class="cargo-sel" data-idx="${idx}" onchange="recalcTotals()" style="width:18px;height:18px;">`
                : `<div style="width:18px;"></div>`
            }
            <div style="flex:1;">
                <div style="font-weight:600;font-size:12px;">${lockIcon}${item.source_display}
                    &nbsp;${statusBadge}
                    <span style="color:#718096;font-size:10px;margin-left:6px;">${item.source_date}</span>
                </div>
                <div style="font-size:11px;color:#4a5568;margin-top:3px;">
                    ${item.service_name} — ${item.quantity.toLocaleString()} ${item.uom}
                    ${item.is_billable ? '' : '<br><span style="color:#e53e3e;font-size:10px;">⚠ Vessel/barge operations not yet closed — billing locked</span>'}
                </div>
            </div>
            ${item.is_billable ? `
            <div style="text-align:right;min-width:180px;">
                <div style="font-size:10px;color:#718096;margin-bottom:2px;">Rate (per ${item.uom})</div>
                <input type="number" step="0.01" class="cargo-rate" data-idx="${idx}"
                    value="" placeholder="Load from agreement"
                    style="width:120px;padding:4px 6px;font-size:12px;border:1px solid #cbd5e0;border-radius:3px;text-align:right;"
                    onchange="recalcTotals()">
                <div class="cargo-amount" data-idx="${idx}" style="font-weight:700;font-size:13px;margin-top:4px;color:#2d3748;">₹0.00</div>
            </div>` : ''}
        </div>`;
    }).join('');

    // Auto-load rates from agreement for billable items
    billable.forEach((item, idx) => loadCargoRate(item, idx));
}

async function loadCargoRate(item, idx) {
    const customerId = document.getElementById('customerName').value;
    const customerType = document.getElementById('customerType').value;
    const agreementId = document.getElementById('agreementId').value;
    if (!item.service_type_id) return;

    let url = `/api/module/FIN01/agreement-rate/${customerId}/${item.service_type_id}?customer_type=${customerType}`;
    if (agreementId) url += `&agreement_id=${agreementId}`;

    const res = await fetch(url);
    const json = await res.json();
    if (json.success && json.data.rate) {
        const rateInput = document.querySelector(`.cargo-rate[data-idx="${idx}"]`);
        if (rateInput) {
            rateInput.value = json.data.rate;
            recalcTotals();
        }
    }
}

function renderServicesTable(items) {
    document.getElementById('servicesCount').textContent = `${items.length} unbilled`;
    if (!items.length) {
        document.getElementById('servicesTable').innerHTML =
            '<p style="color:#718096;font-size:12px;padding:8px 0;">No unbilled service records for this customer.</p>';
        return;
    }
    document.getElementById('servicesTable').innerHTML = `
        <table class="data-table">
            <thead><tr>
                <th style="width:30px"><input type="checkbox" onclick="document.querySelectorAll('.svc-sel').forEach(c=>c.checked=this.checked);recalcTotals()"></th>
                <th>Record #</th><th>Date</th><th>Service</th><th>Qty</th><th>UOM</th>
                <th>Rate</th><th>Amount</th><th>Ref VCN/MBC</th>
            </tr></thead>
            <tbody>
                ${items.map((item, idx) => `
                <tr>
                    <td><input type="checkbox" class="svc-sel" data-idx="${idx}" onchange="recalcTotals()"></td>
                    <td>${item.record_number}</td>
                    <td>${item.record_date || ''}</td>
                    <td>${item.service_name}</td>
                    <td>${item.billable_quantity || ''}</td>
                    <td>${item.billable_uom || ''}</td>
                    <td><input type="number" step="0.01" class="svc-rate" data-idx="${idx}"
                        value="" placeholder="—"
                        style="width:90px;padding:3px 5px;font-size:11px;border:1px solid #cbd5e0;border-radius:3px;"
                        onchange="recalcTotals()"></td>
                    <td class="svc-amount" data-idx="${idx}">₹0.00</td>
                    <td style="color:#718096;font-size:10px;">${item.ref_source_display || '—'}</td>
                </tr>`).join('')}
            </tbody>
        </table>`;

    // Auto-load rates
    items.forEach((item, idx) => loadServiceRate(item, idx));
}

async function loadServiceRate(item, idx) {
    const customerId = document.getElementById('customerName').value;
    const customerType = document.getElementById('customerType').value;
    const agreementId = document.getElementById('agreementId').value;
    if (!item.service_type_id) return;

    let url = `/api/module/FIN01/agreement-rate/${customerId}/${item.service_type_id}?customer_type=${customerType}`;
    if (agreementId) url += `&agreement_id=${agreementId}`;

    const res = await fetch(url);
    const json = await res.json();
    if (json.success && json.data.rate) {
        const rateInput = document.querySelector(`.svc-rate[data-idx="${idx}"]`);
        if (rateInput) { rateInput.value = json.data.rate; recalcTotals(); }
    }
}

function renderBilledTable(items) {
    document.getElementById('billedCount').textContent = `${items.length} items`;
    if (!items.length) {
        document.getElementById('billedTable').innerHTML =
            '<p style="color:#718096;font-size:12px;padding:8px 0;">No previously billed items.</p>';
        return;
    }
    document.getElementById('billedTable').innerHTML = `
        <table class="data-table" style="opacity:0.8;">
            <thead><tr><th>Bill #</th><th>Date</th><th>Service</th><th>Qty</th><th>Amount</th><th>Status</th></tr></thead>
            <tbody>
                ${items.map(item => `
                <tr style="color:#718096;">
                    <td>${item.bill_number}</td>
                    <td>${item.bill_date || ''}</td>
                    <td>${item.service_name}</td>
                    <td>${item.quantity || ''}</td>
                    <td>₹${parseFloat(item.line_amount||0).toFixed(2)}</td>
                    <td>${item.bill_status}</td>
                </tr>`).join('')}
            </tbody>
        </table>`;
}

function recalcTotals() {
    let subtotal = 0, cgst = 0, sgst = 0, igst = 0, count = 0;

    // Cargo
    document.querySelectorAll('.cargo-sel:checked').forEach(cb => {
        const idx = parseInt(cb.dataset.idx);
        const item = billablesData.cargo_handling.filter(i => i.is_billable)[idx];
        const rate = parseFloat(document.querySelector(`.cargo-rate[data-idx="${idx}"]`)?.value) || 0;
        const amount = rate * (item?.quantity || 0);
        subtotal += amount;
        const amountEl = document.querySelector(`.cargo-amount[data-idx="${idx}"]`);
        if (amountEl) amountEl.textContent = `₹${amount.toFixed(2)}`;
        if (item) {
            cgst += amount * (item.cgst_rate / 100);
            sgst += amount * (item.sgst_rate / 100);
            igst += amount * (item.igst_rate / 100);
        }
        count++;
    });

    // Services
    document.querySelectorAll('.svc-sel:checked').forEach(cb => {
        const idx = parseInt(cb.dataset.idx);
        const item = billablesData.other_services[idx];
        const qty = parseFloat(item?.billable_quantity) || 1;
        const rate = parseFloat(document.querySelector(`.svc-rate[data-idx="${idx}"]`)?.value) || 0;
        const amount = rate * qty;
        subtotal += amount;
        const amountEl = document.querySelector(`.svc-amount[data-idx="${idx}"]`);
        if (amountEl) amountEl.textContent = `₹${amount.toFixed(2)}`;
        if (item) {
            cgst += amount * (item.cgst_rate / 100);
            sgst += amount * (item.sgst_rate / 100);
            igst += amount * (item.igst_rate / 100);
        }
        count++;
    });

    const totalGst = cgst + sgst + igst;
    const total = subtotal + totalGst;
    document.getElementById('selectedCount').textContent = count;
    document.getElementById('subtotalDisplay').textContent = `₹${subtotal.toFixed(2)}`;
    document.getElementById('gstDisplay').textContent = `₹${totalGst.toFixed(2)}`;
    document.getElementById('totalDisplay').textContent = `₹${total.toFixed(2)}`;
}

function toggleSection(id) {
    const el = document.getElementById(id);
    const h3 = el.previousElementSibling;
    if (el.style.display === 'none') {
        el.style.display = 'block';
        h3.textContent = h3.textContent.replace('▶', '▼');
    } else {
        el.style.display = 'none';
        h3.textContent = h3.textContent.replace('▼', '▶');
    }
}

async function generateBill() {
    const customerId = document.getElementById('customerName').value;
    const customerType = document.getElementById('customerType').value;
    const customerOpt = document.getElementById('customerName').selectedOptions[0];
    const billDate = document.getElementById('billDate').value;
    const agreementId = document.getElementById('agreementId').value || null;

    if (!customerId) { alert('Please select a customer'); return; }

    const lines = [];

    // Collect selected cargo handling lines
    document.querySelectorAll('.cargo-sel:checked').forEach(cb => {
        const idx = parseInt(cb.dataset.idx);
        const item = billablesData.cargo_handling.filter(i => i.is_billable)[idx];
        const rate = parseFloat(document.querySelector(`.cargo-rate[data-idx="${idx}"]`)?.value) || 0;
        const amount = rate * (item?.quantity || 0);
        lines.push({
            line_type: 'cargo',
            service_type_id: item.service_type_id,
            service_name: item.service_name,
            quantity: item.quantity,
            uom: item.uom,
            rate: rate,
            line_amount: amount,
            cgst_amount: amount * ((item.cgst_rate||0) / 100),
            sgst_amount: amount * ((item.sgst_rate||0) / 100),
            igst_amount: amount * ((item.igst_rate||0) / 100),
            sac_code: item.sac_code,
            gl_code: item.gl_code,
            source_type: item.source_type,
            source_id: item.source_id,
            source_display: item.source_display,
            eu_source_type: item.source_type,
            eu_source_id: item.source_id
        });
    });

    // Collect selected service record lines
    document.querySelectorAll('.svc-sel:checked').forEach(cb => {
        const idx = parseInt(cb.dataset.idx);
        const item = billablesData.other_services[idx];
        const qty = parseFloat(item?.billable_quantity) || 1;
        const rate = parseFloat(document.querySelector(`.svc-rate[data-idx="${idx}"]`)?.value) || 0;
        const amount = rate * qty;
        lines.push({
            line_type: 'service',
            service_record_id: item.id,
            service_type_id: item.service_type_id,
            service_name: item.service_name,
            quantity: qty,
            uom: item.billable_uom,
            rate: rate,
            line_amount: amount,
            cgst_amount: amount * ((item.cgst_rate||0) / 100),
            sgst_amount: amount * ((item.sgst_rate||0) / 100),
            igst_amount: amount * ((item.igst_rate||0) / 100),
            sac_code: item.sac_code,
            gl_code: item.gl_code
        });
    });

    if (!lines.length) { alert('Please select at least one item to bill'); return; }

    const payload = {
        customer_type: customerType,
        customer_id: parseInt(customerId),
        customer_name: customerOpt ? customerOpt.textContent : '',
        customer_gstin: customerOpt ? customerOpt.dataset.gstin : '',
        customer_state_code: customerOpt ? customerOpt.dataset.state : '',
        billing_address: customerOpt ? customerOpt.dataset.address : '',
        bill_date: billDate,
        agreement_id: agreementId,
        lines: lines
    };

    const res = await fetch('/api/module/FIN01/bill/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (result.success) {
        alert(`Bill ${result.bill_number} generated successfully!`);
        window.location.href = '/module/FIN01/bills';
    } else {
        alert('Error: ' + (result.error || 'Unknown error'));
    }
}
```

**Step 4: Commit**

```bash
git add modules/FIN01/generate_bill.html
git commit -m "feat: FIN01 generate_bill rewritten as customer-centric card UI with LDUD closure gate"
```

---

## Task 10: FIN01 — Update bill/save to mark EU Lines as Billed

**Files:**
- Modify: `modules/FIN01/views.py`

When a bill is saved with cargo handling lines, the corresponding `lueu_lines` must be marked `is_billed = TRUE`. Similarly, `service_records` lines must be marked `is_billed = 1`.

**Step 1: In the `save_bill` route, after saving lines, add mark-as-billed logic**

After the `for line in lines:` loop:

```python
    # Mark EU lines as billed for cargo handling lines
    for line in lines:
        if line.get('line_type') == 'cargo' and line.get('eu_source_type') and line.get('eu_source_id'):
            conn = get_db()
            cur = get_cursor(conn)
            cur.execute('''
                UPDATE lueu_lines SET is_billed = TRUE
                WHERE source_type = %s AND source_id = %s
                  AND (is_billed = FALSE OR is_billed IS NULL)
            ''', [line['eu_source_type'], line['eu_source_id']])
            conn.commit()
            conn.close()

        elif line.get('line_type') == 'service' and line.get('service_record_id'):
            conn = get_db()
            cur = get_cursor(conn)
            cur.execute('UPDATE service_records SET is_billed = 1 WHERE id = %s', [line['service_record_id']])
            conn.commit()
            conn.close()
```

**Step 2: Commit**

```bash
git add modules/FIN01/views.py
git commit -m "feat: FIN01 bill/save marks lueu_lines and service_records as billed"
```

---

## Task 11: Smoke Test

**Manual verification steps:**

1. **FSTM01**: Open Service Type Master — Cargo Handling Loading and Unloading should NOT appear in the table.

2. **FCAM01**: Open a Customer Agreement → Add Service line → dropdown should include "Cargo Handling Loading" and "Cargo Handling Unloading". Set a rate and save.

3. **SRV01**: Click "+ New Record" — Customer Type defaults to "Customer", Customer dropdown loads. Select a customer. Select a service type with custom fields. Fill fields. Optionally link a VCN. Save. Verify record appears in list with customer name in Source column.

4. **FIN01 Generate Bill**:
   - Select Customer Type + Customer → click Load Billables
   - Cargo Handling section shows cards. VCNs/MBCs with `doc_status IN ('Closed', 'Partial Close')` have checkboxes. Others show lock icon.
   - Other Services section shows SRV01 records for that customer.
   - Already Billed section shows prior bills.
   - Check a cargo card + a service record → total bar updates.
   - Click Generate Bill → bill created, redirects to bill list.

5. **Post-bill**: Reload Generate Bill for same customer → the billed items should now appear in "Already Billed", not in the top sections.

---

## Summary of Files Changed

| File | Change |
|------|--------|
| `alembic/versions/a1b2c3d4e5f7_billing_redesign.py` | New migration |
| `modules/FSTM01/model.py` | Filter `is_system` from paginated query |
| `modules/SRV01/model.py` | Add `ref_source_*` fields to save/update |
| `modules/SRV01/views.py` | Customer/Agent source options; ref fields in save |
| `modules/SRV01/srv01.html` | Customer-first entry form with optional VCN/MBC |
| `modules/FIN01/views.py` | New `customer-billables` endpoint; update `agreement-rate`; update `bill/save` |
| `modules/FIN01/generate_bill.html` | Full rewrite as card-based customer-centric UI |
