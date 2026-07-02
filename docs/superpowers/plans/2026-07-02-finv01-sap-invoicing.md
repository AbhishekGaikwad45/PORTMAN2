# FINV01 Invoicing + SAP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild FINV01 (invoice from bills, list, doc-series, print) and complete the SAP integration (async posting queue + inbound IRN webhook), copy-adapted from the reference PORTMAN repo, MBC removed.

**Architecture:** The SAP payload core already exists locally (`sap_builder.py`, `sap_client.py`, `modules/SAPCFG`, `modules/FSAP01`); this adds the missing `sap_queue.py` (async post + retry) and `sap_inbound.py` (token-auth SAP callback), their tables, and a rebuilt FINV01 that enqueues invoices to SAP and prints them (services front / supporting docs back). Ports are copy-adapt from the reference; live SAP round-trips are verified manually.

**Tech Stack:** Flask, psycopg2, PostgreSQL, Alembic, `requests`, threading, pytest.

## Global Constraints

- **The SAP payload/interface does not change** — do not alter `sap_builder`/`sap_client` payload shapes; only reconcile genuine non-MBC drift.
- **Drop MBC everywhere** (reference FINV01 ~31 refs; sap_builder/queue may have some).
- Invoices are created from **bills** via `invoice_bill_mapping`; bills may span vessels (`bill_vessels` from #4) — print groups supporting docs by vessel.
- Reference source: GitHub `shubhamshnd/PORTMAN`. Fetch any reference file with:
  `curl -s "https://api.github.com/repos/shubhamshnd/PORTMAN/contents/PATH" | python -c "import sys,json,base64; sys.stdout.buffer.write(base64.b64decode(json.load(sys.stdin)['content']))" > OUT` (raw.githubusercontent is unreliable in this env; the API base64 form works). Copies may already be staged in `/tmp/ref/`.
- Table names: async queue = `sap_outbound_queue`; SAP call log = `integration_logs`; inbound tokens = `sap_inbound_tokens` (self-created by `ensure_token_table()`).
- Run tests with `python -m pytest`. DB: `postgresql://postgres:password@localhost:5432/portman_jnpa`.
- Live SAP OAuth/post/IRN is NOT automatable here — unit-test payload building, queue claim/retry (mock `sap_client`), inbound token verify, and invoice create/print only.

---

### Task 1: Migrations — sap_outbound_queue + integration_logs

**Files:**
- Create: `alembic/versions/jnpa40_sap_tables.py`

**Interfaces:**
- Produces: tables `sap_outbound_queue` and `integration_logs`. Consumed by Tasks 3, 5, 6.

- [ ] **Step 1: Read the reference to confirm every column**

Fetch/read `/tmp/ref/sap_queue.py` and `/tmp/ref/sap_client.py` (or fetch from GitHub per Global Constraints). Enumerate every column each references on `sap_outbound_queue` (enqueue INSERT + `_claim`/`_mark_sent`/`_mark_failed`/`manual_send`/status queries) and `integration_logs` (`_write_log`).

- [ ] **Step 2: Write the migration**

Create `alembic/versions/jnpa40_sap_tables.py`. Columns below cover the reference's usage; if Step 1 finds an additional referenced column, add it.

```python
"""jnpa phase1 - SAP async queue + integration logs

Revision ID: jnpa40_sap_tables
Revises: jnpa39_bill_vessels
Create Date: 2026-07-02
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'jnpa40_sap_tables'
down_revision: Union[str, None] = 'jnpa39_bill_vessels'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS sap_outbound_queue (
            id              SERIAL PRIMARY KEY,
            job_type        TEXT,
            invoice_id      INTEGER,
            reference_type  TEXT,
            reference_id    INTEGER,
            reference_number TEXT,
            payload         TEXT,
            status          TEXT DEFAULT 'pending',
            retry_count     INTEGER DEFAULT 0,
            max_retries     INTEGER DEFAULT 5,
            next_attempt_at TEXT,
            last_error      TEXT,
            sap_document    TEXT,
            created_by      TEXT,
            created_date    TEXT,
            updated_date    TEXT
        );
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_sap_outq_status ON sap_outbound_queue (status);')
    op.execute('CREATE INDEX IF NOT EXISTS ix_sap_outq_invoice ON sap_outbound_queue (invoice_id);')
    op.execute('''
        CREATE TABLE IF NOT EXISTS integration_logs (
            id                   SERIAL PRIMARY KEY,
            integration_type     TEXT,
            source_type          TEXT,
            source_id            INTEGER,
            source_reference     TEXT,
            request_url          TEXT,
            request_body         TEXT,
            response_status_code INTEGER,
            response_body        TEXT,
            status               TEXT,
            error_message        TEXT,
            duration_ms          INTEGER,
            created_by           TEXT,
            created_date         TEXT
        );
    ''')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS integration_logs;')
    op.execute('DROP TABLE IF EXISTS sap_outbound_queue;')
```

If Step 1 revealed a column not listed above, add it to the CREATE (and note it in the report).

- [ ] **Step 3: Apply + verify**

Run: `alembic upgrade head`
Then: `python -c "import psycopg2; c=psycopg2.connect('postgresql://postgres:password@localhost:5432/portman_jnpa'); cur=c.cursor(); cur.execute(\"SELECT to_regclass('public.sap_outbound_queue'), to_regclass('public.integration_logs')\"); print(cur.fetchone())"`
Expected: `('sap_outbound_queue', 'integration_logs')`.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/jnpa40_sap_tables.py
git commit -m "feat(sap): sap_outbound_queue + integration_logs tables"
```

---

### Task 2: Reconcile sap_builder / sap_client (payload core)

**Files:**
- Modify: `sap_builder.py`, `sap_client.py` (only where drift is real + non-MBC)
- Test: `tests/test_sap_builder.py`

**Interfaces:**
- Consumes: `modules.SAPCFG.model.get_active_config`, `finance_service_types` GL columns.
- Produces: `sap_builder.build_invoice_payload(invoice_header, invoice_lines) -> dict`; also `build_invoice_reversal_payload`, `build_invoice_credit_note_payload`, `build_fdcn_payload` if the reference has them and local lacks them. Consumed by Tasks 3, 6.

- [ ] **Step 1: Diff local vs reference**

Fetch `/tmp/ref/sap_builder.py` and `/tmp/ref/sap_client.py`. Diff against local `sap_builder.py` (496L) / `sap_client.py` (250L vs ref):
`diff --strip-trailing-cr d:/PMS/JNPA/PORTMAN2/sap_builder.py /tmp/ref/sap_builder.py` (and for sap_client). Classify each hunk: (a) MBC → do NOT bring over; (b) genuine payload/logic addition present in reference but missing locally (e.g. `build_invoice_reversal_payload`, `build_invoice_credit_note_payload`, `build_fdcn_payload`, or a changed field in `build_invoice_payload`) → bring over; (c) local-only or cosmetic → leave.

- [ ] **Step 2: Write the failing test**

Create `tests/test_sap_builder.py`:

```python
"""sap_builder.build_invoice_payload produces the expected SAP payload shape.
No network. Uses a config via SAPCFG if present, else tolerates its absence."""
import sap_builder


def test_build_invoice_payload_shape():
    header = {
        'invoice_number': 'INV-TST-1', 'invoice_date': '2026-07-02',
        'customer_type': 'Customer', 'customer_id': 1, 'customer_name': 'ACME',
        'customer_gstin': '27ABCDE1234F1Z5', 'customer_gst_state_code': '27',
        'subtotal': 10000, 'cgst_amount': 900, 'sgst_amount': 900, 'igst_amount': 0,
        'total_amount': 11800,
    }
    lines = [{
        'service_code': 'CHGU01', 'service_name': 'Cargo Handling Unloading',
        'quantity': 100, 'rate': 100, 'line_amount': 10000, 'sac_code': '996719',
        'gst_rate_id': 4, 'cgst_amount': 900, 'sgst_amount': 900, 'igst_amount': 0,
        'gl_code': '4101076030',
    }]
    payload = sap_builder.build_invoice_payload(header, lines)
    assert isinstance(payload, dict)
    # top-level shape is stable (adapt keys to the reference's actual builder output)
    assert payload, 'payload must not be empty'
    # items must reflect the single line
    items = payload.get('items') or payload.get('Items') or payload.get('lineItems')
    assert items and len(items) == 1
```

Adapt the assertion keys in Step 2 to the reference builder's ACTUAL output keys (read `build_invoice_payload` in the reference). The test must assert the real shape, not invented keys.

- [ ] **Step 3: Run test (RED if a needed builder change is missing; else it may already pass)**

Run: `python -m pytest tests/test_sap_builder.py -q`
If it fails because local `build_invoice_payload` differs from the reference contract, apply the Step-1 (b) changes; if it passes as-is, the local builder already matches — record that.

- [ ] **Step 4: Apply reconciliation (only real, non-MBC drift)**

Bring the Step-1 (b) hunks into local `sap_builder.py`/`sap_client.py`. Do NOT bring MBC code. Keep the payload contract identical to the reference.

- [ ] **Step 5: Run test to verify pass**

Run: `python -m pytest tests/test_sap_builder.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sap_builder.py sap_client.py tests/test_sap_builder.py
git commit -m "chore(sap): reconcile sap_builder/sap_client with reference (no MBC)"
```

---

### Task 3: sap_queue.py (async posting + retry)

**Files:**
- Create: `sap_queue.py`
- Test: `tests/test_sap_queue.py`

**Interfaces:**
- Consumes: `sap_client.post_invoice_to_sap`, `sap_outbound_queue` (Task 1).
- Produces: `enqueue(job_type, reference_type, reference_id, reference_number, payload, invoice_id=None, created_by=None) -> qid`; `trigger()`; `process_sap_queue()`; `manual_send(queue_id)`. Consumed by Tasks 5, 6.

- [ ] **Step 1: Port the file**

Fetch `/tmp/ref/sap_queue.py`; copy to `sap_queue.py`, adapting: imports (`from database import get_db, get_cursor`, `import sap_client`), remove any MBC branch, ensure it targets `sap_outbound_queue` with the columns from Task 1. Keep the threading model (`trigger()` spawns a daemon `process_sap_queue`).

- [ ] **Step 2: Write the failing test**

Create `tests/test_sap_queue.py`:

```python
"""sap_queue enqueue + claim + retry, with sap_client mocked (no network)."""
import sap_queue
from database import get_db, get_cursor


def test_enqueue_and_claim_and_fail(monkeypatch):
    # prevent the real background thread + network
    monkeypatch.setattr(sap_queue, 'trigger', lambda: None)
    qid = sap_queue.enqueue('invoice_post', 'INVOICE', 999999, 'INV-Q-1',
                            {'x': 1}, invoice_id=None, created_by='t')
    try:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT status, retry_count, payload FROM sap_outbound_queue WHERE id=%s", [qid])
        row = cur.fetchone(); conn.close()
        assert row['status'] == 'pending' and row['retry_count'] == 0
        assert '"x": 1' in row['payload'] or "'x': 1" in row['payload']
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("DELETE FROM sap_outbound_queue WHERE id=%s", [qid])
        conn.commit(); conn.close()
```

If the reference `enqueue` signature differs, adapt the call to match the ported signature (and update the Produces block accordingly in your report).

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_sap_queue.py -q`
Expected: FAIL (module/function missing) before the port, PASS after.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sap_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sap_queue.py tests/test_sap_queue.py
git commit -m "feat(sap): async sap_outbound_queue posting + retry"
```

---

### Task 4: sap_inbound.py + webhook registration

**Files:**
- Create: `sap_inbound.py`
- Modify: `app.py` (register the callback route + call `ensure_token_table()` at startup)
- Test: `tests/test_sap_inbound.py`

**Interfaces:**
- Consumes: `sap_inbound_tokens` (self-created by `ensure_token_table()`); `invoice_header` (writes IRN/status).
- Produces: `ensure_token_table()`, `generate_token/list_tokens/revoke_token/reactivate_token`, `_verify_token(auth_header)`, `sap_callback_view()`.

- [ ] **Step 1: Port the file**

Fetch `/tmp/ref/sap_inbound.py`; copy to `sap_inbound.py`, adapting imports; remove MBC. Keep `ensure_token_table()` (creates `sap_inbound_tokens`).

- [ ] **Step 2: Register in app.py**

In `app.py`, near the other route/blueprint registration, add the inbound callback route and ensure the token table exists at startup. Read `app.py` to match its registration style; add:

```python
import sap_inbound
sap_inbound.ensure_token_table()
app.add_url_rule('/api/sap/inbound', view_func=sap_inbound.sap_callback_view, methods=['POST'])
```

Adapt the route path to match the reference's expected callback path if it differs (read the reference `sap_callback_view`/docstring for the path SAP calls).

- [ ] **Step 3: Write the failing test**

Create `tests/test_sap_inbound.py`:

```python
"""sap_inbound token lifecycle + verification (no Flask app needed)."""
import sap_inbound
from database import get_db, get_cursor


def test_token_generate_verify_revoke():
    sap_inbound.ensure_token_table()
    tok = sap_inbound.generate_token('pytest-token', created_by='t')
    raw = tok['token'] if isinstance(tok, dict) else tok
    try:
        assert sap_inbound._verify_token('Bearer ' + raw) is not None
        assert sap_inbound._verify_token('Bearer wrong-' + raw) is None
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("DELETE FROM sap_inbound_tokens WHERE token=%s", [raw])
        conn.commit(); conn.close()
```

Adapt to the reference's actual `generate_token` return type and `_verify_token` return contract (read the file).

- [ ] **Step 4: Run test (RED then GREEN)**

Run: `python -m pytest tests/test_sap_inbound.py -q`
Expected: FAIL before the port, PASS after; then `python -c "import ast; ast.parse(open('app.py').read()); print('ok')"`.

- [ ] **Step 5: Commit**

```bash
git add sap_inbound.py app.py tests/test_sap_inbound.py
git commit -m "feat(sap): inbound IRN/status webhook + token auth"
```

---

### Task 5: FINV01 rebuild — invoice create / list / doc-series / print

**Files:**
- Modify/Create: `modules/FINV01/views.py`, `modules/FINV01/finv01_invoices.html`, `modules/FINV01/finv01_generate_invoice.html`, `modules/FINV01/finv01_invoice_print.html`, `modules/FINV01/finv01_doc_series.html`, `modules/FINV01/__init__.py`
- Modify: `app.py` (ensure FINV01 blueprint registered)
- Test: `tests/test_finv01_invoice.py`

**Interfaces:**
- Consumes: `invoice_header`, `invoice_lines`, `invoice_bill_mapping`, `invoice_doc_series`, `bill_header`, `bill_lines`, `bill_vessels` (#4); `sap_builder`, `sap_queue` (Tasks 2–3).
- Produces: FINV01 blueprint with `/module/FINV01/`, `/module/FINV01/generate`, `/module/FINV01/invoices`, `/module/FINV01/doc-series`, `/module/FINV01/invoice/print/<id>`, `POST /api/module/FINV01/invoice/create`, doc-series endpoints. Consumed by Task 6 (SAP wiring lives here too).

- [ ] **Step 1: Port views + templates (strip MBC)**

Fetch the reference `modules/FINV01/views.py` and the four templates (and `__init__.py`) from GitHub. Copy into `modules/FINV01/`, adapting: imports to local modules; remove every MBC reference (~31); keep the invoice-from-bills flow (`invoice_bill_mapping`), doc-series numbering (`invoice_doc_series`), customer snapshot, and print (`_build_display_lines` = service lines on the front; `_get_cargo_handling_details` + bill breakdown grouped by `bill_vessels` on the back). For SAP-facing endpoints in this file, leave the calls to `sap_queue`/`sap_client`/`sap_builder` in place (wired fully in Task 6) — but the invoice create/list/print must work now. If `_enqueue_invoice_post` would run at create, keep it calling `sap_queue.enqueue` (Task 3 exists).

- [ ] **Step 2: Ensure blueprint registration**

Confirm `modules/FINV01/__init__.py` exposes `bp` + `MODULE_INFO` and that `app.py` registers it (it may already; if the stale registration was removed, re-add following the FSAP01 registration pattern). Verify: `python -c "import ast; ast.parse(open('modules/FINV01/views.py').read()); print('ok')"`.

- [ ] **Step 3: Write the failing test**

Create `tests/test_finv01_invoice.py`:

```python
"""FINV01 invoice create from a bill: header + lines + bill mapping, numbered.
Uses a throwaway customer + bill; no SAP network (enqueue is fine — it only
inserts a queue row; monkeypatch trigger to avoid the thread)."""
import pytest
from database import get_db, get_cursor
from modules.FINV01 import views as finv


def _mk_bill(cur):
    cur.execute("INSERT INTO vessel_customers (name) VALUES ('INVC') RETURNING id")
    cid = cur.fetchone()['id']
    cur.execute("""INSERT INTO bill_header (bill_number, bill_date, source_type, customer_type,
                   customer_id, customer_name, subtotal, total_amount, bill_status)
                   VALUES ('BILL-INV-1','2026-07-02','MULTI','Customer',%s,'INVC',10000,11800,'Approved')
                   RETURNING id""", [cid])
    bid = cur.fetchone()['id']
    cur.execute("""INSERT INTO bill_lines (bill_id, service_type_id, service_code, service_name,
                   quantity, uom, rate, line_amount, line_total)
                   VALUES (%s, NULL,'CHGU01','Cargo Handling Unloading',100,'MT',100,10000,11800)""", [bid])
    return cid, bid


def test_create_invoice_from_bill(monkeypatch):
    import sap_queue
    monkeypatch.setattr(sap_queue, 'trigger', lambda: None)
    conn = get_db(); cur = get_cursor(conn)
    cid, bid = _mk_bill(cur); conn.commit(); conn.close()
    inv_id = None
    try:
        # call the model-level create used by the /invoice/create endpoint.
        # If the reference keeps creation logic inline in the view, extract the
        # smallest callable (e.g. finv.create_invoice_record(...)) during the port
        # so it is testable, and call it here with (customer + [bid]).
        inv_id = finv.create_invoice_record('Customer', cid, [bid], created_by='t')
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT invoice_number FROM invoice_header WHERE id=%s", [inv_id])
        assert cur.fetchone()['invoice_number']
        cur.execute("SELECT COUNT(*) c FROM invoice_bill_mapping WHERE invoice_id=%s", [inv_id])
        assert cur.fetchone()['c'] == 1
        cur.execute("SELECT COUNT(*) c FROM invoice_lines WHERE invoice_id=%s", [inv_id])
        assert cur.fetchone()['c'] >= 1
        conn.close()
    finally:
        conn = get_db(); cur = get_cursor(conn)
        if inv_id:
            cur.execute("DELETE FROM invoice_lines WHERE invoice_id=%s", [inv_id])
            cur.execute("DELETE FROM invoice_bill_mapping WHERE invoice_id=%s", [inv_id])
            cur.execute("DELETE FROM sap_outbound_queue WHERE invoice_id=%s", [inv_id])
            cur.execute("DELETE FROM invoice_header WHERE id=%s", [inv_id])
        cur.execute("DELETE FROM bill_lines WHERE bill_id=%s", [bid])
        cur.execute("DELETE FROM bill_header WHERE id=%s", [bid])
        cur.execute("DELETE FROM vessel_customers WHERE id=%s", [cid])
        conn.commit(); conn.close()
```

During the port, extract the invoice-creation logic into a callable `create_invoice_record(customer_type, customer_id, bill_ids, created_by)` (in `modules/FINV01/views.py` or a small helper) that the `/invoice/create` endpoint also calls, so it is unit-testable. Adapt the test to the real signature.

- [ ] **Step 4: Run test (RED → GREEN)**

Run: `python -m pytest tests/test_finv01_invoice.py -q`
Expected: FAIL before the port/extraction, PASS after.

- [ ] **Step 5: Commit**

```bash
git add modules/FINV01/ app.py tests/test_finv01_invoice.py
git commit -m "feat(finv01): rebuild invoicing (create from bills, list, doc-series, print) — no MBC"
```

---

### Task 6: Wire FINV01 → SAP endpoints

**Files:**
- Modify: `modules/FINV01/views.py`
- Test: `tests/test_finv01_invoice.py` (extend)

**Interfaces:**
- Consumes: `sap_queue.enqueue/manual_send`, `sap_client.fetch_irn_from_sap`, `sap_builder.build_invoice_payload` / reversal / credit-note.
- Produces: endpoints `retry-sap`, `fetch-irn`, `cancel-sap`, `create-cancellation-cn`, `sap-queue/manual-send`, `export-sap-json`, GSTR1 export; `_enqueue_invoice_post` calling `sap_queue.enqueue`.

- [ ] **Step 1: Wire the SAP endpoints (port from reference, strip MBC)**

Ensure `_enqueue_invoice_post(invoice_id, invoice_number)` builds the payload via `sap_builder.build_invoice_payload(header, lines)` and calls `sap_queue.enqueue('invoice_post','INVOICE',invoice_id,invoice_number,payload,invoice_id=invoice_id,created_by=...)`. Port the remaining SAP endpoints from the reference `modules/FINV01/views.py`, adapting imports and removing MBC. Keep payloads unchanged.

- [ ] **Step 2: Extend the test — create enqueues a queue row**

Add to `tests/test_finv01_invoice.py`:

```python
def test_create_invoice_enqueues_sap(monkeypatch):
    import sap_queue
    monkeypatch.setattr(sap_queue, 'trigger', lambda: None)
    from database import get_db, get_cursor
    from modules.FINV01 import views as finv
    conn = get_db(); cur = get_cursor(conn)
    cur.execute("INSERT INTO vessel_customers (name) VALUES ('INVC2') RETURNING id")
    cid = cur.fetchone()['id']
    cur.execute("""INSERT INTO bill_header (bill_number, bill_date, source_type, customer_type,
                   customer_id, customer_name, subtotal, total_amount, bill_status)
                   VALUES ('BILL-INV-2','2026-07-02','MULTI','Customer',%s,'INVC2',10000,11800,'Approved')
                   RETURNING id""", [cid])
    bid = cur.fetchone()['id']
    cur.execute("""INSERT INTO bill_lines (bill_id, service_code, service_name, quantity, uom, rate, line_amount, line_total)
                   VALUES (%s,'CHGU01','Cargo Handling Unloading',100,'MT',100,10000,11800)""", [bid])
    conn.commit(); conn.close()
    inv_id = None
    try:
        inv_id = finv.create_invoice_record('Customer', cid, [bid], created_by='t')
        finv._enqueue_invoice_post(inv_id, None)  # or the name used; adapt
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("SELECT COUNT(*) c FROM sap_outbound_queue WHERE invoice_id=%s", [inv_id])
        assert cur.fetchone()['c'] >= 1
        conn.close()
    finally:
        conn = get_db(); cur = get_cursor(conn)
        if inv_id:
            cur.execute("DELETE FROM sap_outbound_queue WHERE invoice_id=%s", [inv_id])
            cur.execute("DELETE FROM invoice_lines WHERE invoice_id=%s", [inv_id])
            cur.execute("DELETE FROM invoice_bill_mapping WHERE invoice_id=%s", [inv_id])
            cur.execute("DELETE FROM invoice_header WHERE id=%s", [inv_id])
        cur.execute("DELETE FROM bill_lines WHERE bill_id=%s", [bid])
        cur.execute("DELETE FROM bill_header WHERE id=%s", [bid])
        cur.execute("DELETE FROM vessel_customers WHERE id=%s", [cid])
        conn.commit(); conn.close()
```

Adapt `_enqueue_invoice_post` name/signature to the actual port. If create already enqueues internally, drop the explicit call and just assert the row exists after `create_invoice_record`.

- [ ] **Step 3: Run tests + full suite**

Run: `python -m pytest tests/test_finv01_invoice.py -q` then `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add modules/FINV01/views.py tests/test_finv01_invoice.py
git commit -m "feat(finv01): wire invoice SAP posting + IRN/cancel/export endpoints (no MBC)"
```

---

## Self-Review

**Spec coverage:**
- §A reconcile SAP core → Task 2. ✓
- §B async queue + inbound webhook + tables → Tasks 1, 3, 4. ✓
- §C FINV01 rebuild + print → Task 5. ✓
- §D wire FINV01 → SAP → Task 6. ✓
- No MBC → stated in every port task's Global Constraints + steps. ✓
- Live-SAP-not-testable → tests mock `sap_client`/`trigger`; no live round-trip asserted. ✓

**Placeholder scan:** This is a port; large reference files are named with exact fetch instructions + concrete adaptations (strip MBC, exact table/column names, import fixes) rather than inline-copied — appropriate for a copy-adapt. Migrations + tests carry full code. The reviewer verifies against the reference + the diff.

**Type consistency:** table names (`sap_outbound_queue`, `integration_logs`, `sap_inbound_tokens`) consistent across tasks; `enqueue`/`_enqueue_invoice_post`/`create_invoice_record` names referenced consistently (implementers confirm exact reference signatures and update their report if they differ).

## Notes / knowingly deferred
- Live SAP OAuth/post/IRN + the inbound webhook end-to-end are verified manually in the user's environment (no SAP endpoint here).
- If reference signatures differ from the names used in tests, implementers adapt the test to the real signature (noted per task).
- GL-code on bill lines (empty from #4's engine) may need populating for correct SAP GL mapping — surface if the builder requires it.
