# Accounts Modules Redesign & Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign and extend the Finance/Accounts modules (FIN01, FCAM01, FSTM01, FGRM01, FCRM01, SRV01) with GST e-invoice GSP integration, bidirectional SAP FI REST API integration (JSW DynaportInvoice API), virtual accounts per customer, SAP service codes, credit note management, EU line splitting, and integration logs.

**Architecture:** Flask + PostgreSQL + Alembic. External integrations use `requests` HTTP calls (OAuth2 + REST) to JSW SAP PI and GSP. Each feature adds new tables via Alembic migrations and new module files following `modules/MODULECODE/{views,model,html}` pattern.

**Tech Stack:** Flask, PostgreSQL, Alembic, requests (SAP REST + GST GSP), pycryptodome (AES-256/RSA for GST e-invoice encryption), Tabulator.js 6.3.0

---

## Context

The Finance/Accounts modules handle billing (FIN01), service agreements (FCAM01), service types (FSTM01), GST rates (FGRM01), and currencies (FCRM01). Critical gaps preventing production-readiness:

1. **GST e-invoice export is offline JSON only** — no actual GSP API call, no IRN generation, no QR code storage
2. **SAP integration is placeholder** — `sap_document_number` column exists but nothing posts to SAP; SAP is REST API (JSW DynaportInvoice via SAP PI), NOT BAPI/RFC
3. **Agent master (VAM01) is skeleton** — `vessel_agents` table only has `id` and `name`; agents cannot be invoiced
4. **No virtual accounts** — finance team uses multiple virtual accounts per customer; no schema or UI
5. **FSTM01 missing SAP service codes** — `sap_service_code` absent; needed for ITEM.HSN_SAC in SAP posting
6. **Credit note management absent** — no way to issue credit memos, link to original invoices
7. **No EU line split** — LUEU01 lines currently billed whole; need ability to split one line into two for billing
8. **No integration logs UI** — SAP and GST API call logs stored nowhere visible
9. **SAP/GST config has no admin UI** — company code, client_id, client_secret are not editable by admin; credentials must be manually set in DB; switching environments (dev/qas/prod) requires DB edits
10. **Internal company customers lack SAP company code** — some customers are internal entities (inter-company transactions); they need their own `company_code` stored so the SAP posting uses their company code instead of the port's company code

---

## Current Module Audit

### FIN01 - Billing & Invoicing
- **Tables:** `bill_header`, `bill_lines`, `invoice_header`, `invoice_lines`, `invoice_bill_mapping`
- **Good:** Complete bill→invoice workflow; CGST/SGST/IGST calculation; financial year numbering; approval workflow; `gst_irn`, `sap_document_number` columns already in `invoice_header`
- **Issues:** e-invoice = static JSON export only (no GSP call); SAP button exists but does nothing; no credit note path; no split for EU lines

### FCAM01 - Customer Agreement Master
- **Tables:** `customer_agreements`, `customer_agreement_lines`
- **Good:** Rate cards with validity periods; used by FIN01 for rate lookup
- **Issues:** No agent billing support

### FSTM01 - Service Type Master
- **Tables:** `finance_service_types`, `service_field_definitions`
- **Good:** EAV-based custom fields; SAC codes present
- **Issues:** No `sap_service_code` (needed for ITEM.HSN_SAC in DynaportInvoice); no SAP GL account per service type

### FGRM01 - GST Rate Master, FCRM01 - Currency Master
- Good, no major issues

### SRV01 - Service Recording
- **Tables:** `service_records`, `service_record_values`
- Good, EAV flexible

### VAM01 - Agent Master
- **Table:** `vessel_agents` (only `id`, `name`) — cannot be invoiced; no GL code, GSTIN, billing info
- **VCUM01 customers** — need virtual accounts sub-table; need `sap_customer_code` field

---

## SAP Integration Architecture

### SAP REST API (JSW DynaportInvoice via SAP PI)

**NOT BAPI/RFC. Uses OAuth2 + REST.**

**Environments:**

| Env | URL | IP |
|-----|-----|----|
| Development | `https://sapapidev.jsw.in:50001` | 10.201.2.27 |
| Quality | `https://sapapiqas.jsw.in:52401` | 10.201.3.25 |
| Production | `https://sapapi.jsw.in:54001` | 10.19.4.136 |

**API 1 — Token:**
```
POST {base_url}/RESTAdapter/OAuthServer
     ?client_id={client_id}
     &client_secret={client_secret}
     &grant_type=client_credentials
Content-Type: application/json
Body: (empty)

Response: { "access_token": "...", "token_type": "bearer", "expires_in": 3600 }
```

**API 2 — Invoice / Credit Note:**
```
POST {base_url}/RESTAdapter/DynaportInvoice
Content-Type: application/json
Authorization: Bearer {access_token}

Body: { "Record_Header": [ {...invoice...}, {...credit_note...} ] }

Response: { "Record": [{"Invoice": "...", "Status": "S"/"E", "Message": "..."}] }
```

**SAP JSON Structure — Invoice:**
```json
{
  "Record_Header": [{
    "Invoice_Credit": "I",
    "Company_code": "5171",
    "Invoice_date": "21.01.2026",
    "Posting_Date": "21.01.2026",
    "Reference": "25-26/895",
    "Document_type": "INV",
    "Customer_Code": "I510785",
    "Invoice_Amount": "4503824",
    "Business_place": "5171",
    "Section_code": "5171",
    "Text": "895 - M V CARLTON TRADER - Wharfage Charges",
    "Document_Header_Text": "895 - M V CARLTON TRADER - Wharfage Charges",
    "Payment_Term": "51",
    "Credit_Control_Area": "5171",
    "ITEM": [{
      "Reference": "25-26/895",
      "GL_account": "4101076030",
      "Amount": "3816800",
      "Tax_Code": "50",
      "Cost_Center": [],
      "Plant": "5171",
      "Text": "895 - M V CARLTON TRADER - Wharfage Charges",
      "Profit_Center": ["5171000000"],
      "HSN_SAC": "996719",
      "CGST_AMT": "343512",
      "SGST_AMT": "343512",
      "IGST_AMT": "0"
    }]
  }]
}
```

**SAP JSON — Credit Note** (`Invoice_Credit: "C"`, `Document_type: "CRN"`):
- Same structure as invoice but `Invoice_Credit = "C"` and `Document_type = "CRN"`

**Field Mapping (PMS → SAP):**

| SAP Field | PMS Source |
|-----------|-----------|
| `Company_code` | `customer.company_code` if set (inter-company), else `sap_api_config.company_code` |
| `Invoice_date` | `invoice_header.invoice_date` (format: DD.MM.YYYY) |
| `Posting_Date` | `invoice_header.invoice_date` |
| `Reference` | `invoice_header.invoice_number` |
| `Document_type` | "INV" for invoice, "CRN" for credit note |
| `Customer_Code` | `vessel_customers.sap_customer_code` (e.g. "I510785") |
| `Invoice_Amount` | `invoice_header.total_amount` (string, no decimals for INR) |
| `Business_place` | `customer.company_code` if set, else `sap_api_config.company_code` |
| `Section_code` | `customer.company_code` if set, else `sap_api_config.company_code` |
| `Text` | `"{bill_no} - {vessel_name} - {service_name}"` |
| `Payment_Term` | `sap_api_config.default_payment_term` |
| `Credit_Control_Area` | `customer.company_code` if set, else `sap_api_config.company_code` |
| ITEM `GL_account` | `finance_service_types.sap_gl_account` |
| ITEM `Amount` | `invoice_lines.line_amount` (pre-tax) |
| ITEM `Tax_Code` | `finance_service_types.sap_tax_code` |
| ITEM `Plant` | `sap_api_config.company_code` |
| ITEM `HSN_SAC` | `invoice_lines.sac_code` |
| ITEM `CGST_AMT` | `invoice_lines.cgst_amount` |
| ITEM `SGST_AMT` | `invoice_lines.sgst_amount` |
| ITEM `IGST_AMT` | `invoice_lines.igst_amount` |
| ITEM `Profit_Center` | `finance_service_types.sap_profit_center` (as array) |
| ITEM `Cost_Center` | `finance_service_types.sap_cost_center` (as array, or [] if none) |

---

## Phase 1: Master Data Enhancements

### 1A. Expand VAM01 (Agent Master)

**Modify `vessel_agents` table** to add billing fields so agents can be invoiced.

**Migration DDL:**
```sql
ALTER TABLE vessel_agents
  ADD COLUMN sap_customer_code TEXT,
  ADD COLUMN gl_code TEXT,
  ADD COLUMN gstin TEXT,
  ADD COLUMN gst_state_code TEXT,
  ADD COLUMN gst_state_name TEXT,
  ADD COLUMN pan TEXT,
  ADD COLUMN billing_address TEXT,
  ADD COLUMN city TEXT,
  ADD COLUMN pincode TEXT,
  ADD COLUMN contact_person TEXT,
  ADD COLUMN contact_email TEXT,
  ADD COLUMN contact_phone TEXT,
  ADD COLUMN default_currency TEXT DEFAULT 'INR',
  ADD COLUMN is_active INTEGER DEFAULT 1;
```

**Files to modify:**
- `modules/VAM01/views.py` — update save/get endpoints
- `modules/VAM01/model.py` — update INSERT/UPDATE queries
- `modules/VAM01/vam01.html` — add new columns to Tabulator

**Impact on FIN01:** `FIN01/views.py` `get_customers()` endpoint queries `vessel_customers` and `vessel_importer_exporters`. Add `vessel_agents` as a third customer_type='Agent' option.

### 1B. Add `sap_customer_code` and `company_code` to Customer Masters

Both `vessel_customers` and `vessel_importer_exporters` need:
- `sap_customer_code` — SAP customer account number (format: "I510785") for DynaportInvoice API
- `company_code` — SAP company code for **internal/inter-company customers** (e.g. another JSW entity). When this is set, the SAP posting uses this company code instead of the default from `sap_api_config`. For external customers, leave blank.

```sql
ALTER TABLE vessel_customers
  ADD COLUMN sap_customer_code TEXT,
  ADD COLUMN company_code TEXT;           -- SAP company code if internal/inter-company entity

ALTER TABLE vessel_importer_exporters
  ADD COLUMN sap_customer_code TEXT,
  ADD COLUMN company_code TEXT;
```

Also add `company_code` to `vessel_agents` (add alongside other new columns in Phase 1A migration):
```sql
ALTER TABLE vessel_agents ADD COLUMN company_code TEXT;
```

**Usage in SAP posting:** In `sap_builder.py`, resolve `Company_code` as:
```python
company_code = customer.get('company_code') or sap_config['company_code']
# Business_place, Section_code, Credit_Control_Area, Plant all follow same logic
```

**UI:** In VCUM01 and VIEM01 grids, add `sap_customer_code` and `company_code` as editable columns. Show a visual indicator (badge or icon) on rows where `company_code` is set — to make internal customers easily identifiable.

**Files to modify:**
- `modules/VCUM01/views.py`, `model.py`, `vcum01.html`
- `modules/VIEM01/views.py`, `model.py`, `viem01.html`

### 1C. Expand FSTM01 with SAP Fields

**Service Type Categories (important for billing):**
- `has_custom_fields = 0` — **LUEU01-type / Fixed services** (e.g. Cargo Handling Loading, Cargo Handling Unloading, Equipment Rental). Billed directly from LUEU01 lines via `lueu_lines.service_type_id`. No custom form entry needed.
- `has_custom_fields = 1` — **SRV01-type / Form-based services**. Require manual recording in SRV01 with custom dynamic fields. Everything else (delay charges, storage, etc.)

**Modify `finance_service_types` table:**
```sql
ALTER TABLE finance_service_types
  ADD COLUMN sap_gl_account TEXT,          -- SAP GL account e.g. "4101076030" → ITEM.GL_account
  ADD COLUMN sap_tax_code TEXT,            -- SAP tax code e.g. "50" → ITEM.Tax_Code (NOT GST rate %)
  ADD COLUMN sap_profit_center TEXT,       -- e.g. "5171000000" → ITEM.Profit_Center (as array)
  ADD COLUMN sap_cost_center TEXT;         -- optional → ITEM.Cost_Center (as array, or [])
```

Note: `sac_code` already exists in `finance_service_types` and maps to `ITEM.HSN_SAC`.
Note: `gl_code` (existing) is the general GL code; `sap_gl_account` is specifically for SAP FI posting.

**Also add `sap_tax_code` to `invoice_lines`** so it travels through the billing chain (service_type → bill_lines → invoice_lines → SAP payload):
```sql
ALTER TABLE invoice_lines ADD COLUMN sap_tax_code TEXT;
```

**And `sap_tax_code` to `bill_lines`** for traceability:
```sql
ALTER TABLE bill_lines ADD COLUMN sap_tax_code TEXT;
```

**Data flow for SAP codes:**
```
finance_service_types.sap_gl_account  → bill_lines.gl_code        → invoice_lines.gl_code       → ITEM.GL_account
finance_service_types.sap_tax_code    → bill_lines.sap_tax_code   → invoice_lines.sap_tax_code  → ITEM.Tax_Code
finance_service_types.sac_code        → bill_lines.sac_code       → invoice_lines.sac_code      → ITEM.HSN_SAC
finance_service_types.sap_profit_center → bill_lines (not stored) → invoice_lines.profit_center → ITEM.Profit_Center
finance_service_types.sap_cost_center   → bill_lines (not stored) → invoice_lines.cost_center   → ITEM.Cost_Center
```

**Update `FIN01/model.py` `create_invoice_from_bills()`:** When creating invoice_lines from bill_lines, also query `finance_service_types` for `sap_profit_center`/`sap_cost_center`/`sap_tax_code` using `bill_lines.service_type_id` to populate the new `invoice_lines` fields.

**Customer agreements (FCAM01):** No SAP codes needed in agreements. `customer_agreement_lines` references `finance_service_types` via `service_type_id` — SAP codes are automatically inherited from the service type at billing time. No changes to FCAM01.

**Files to modify:**
- `modules/FSTM01/views.py`, `model.py`, `fstm01.html` — add 4 new SAP columns
- `modules/FIN01/model.py` — update `create_invoice_from_bills()` to populate `sap_tax_code`, `profit_center`, `cost_center` from service type

### 1D. Virtual Accounts per Customer

**New table: `customer_virtual_accounts`**

```sql
CREATE TABLE customer_virtual_accounts (
    id SERIAL PRIMARY KEY,
    party_type TEXT NOT NULL,        -- 'Customer', 'Importer', 'Exporter', 'Agent'
    party_id INTEGER NOT NULL,
    party_name TEXT,
    account_number TEXT NOT NULL,
    ifsc_code TEXT NOT NULL,         -- 11 chars: BANKX000nnn
    bank_name TEXT,
    branch_name TEXT,
    account_holder_name TEXT,
    account_type TEXT DEFAULT 'Current',
    purpose TEXT,                    -- 'InvoicePayment', 'Advance', 'General'
    is_active INTEGER DEFAULT 1,
    effective_from TEXT,
    effective_to TEXT,
    gl_account_code TEXT,
    remarks TEXT,
    created_by TEXT,
    created_date TEXT
);
```

**Implementation:** Sub-panel in VAM01, VCUM01, VIEM01 showing virtual accounts for each party.

API endpoints (add to respective module views.py):
- `GET /api/module/VAM01/virtual-accounts/<party_id>` — list
- `POST /api/module/VAM01/virtual-accounts/save` — save
- `POST /api/module/VAM01/virtual-accounts/delete` — delete

---

## Phase 2: LUEU01 — EU Line Split for Billing

**Feature:** A LUEU01 (Load/Unload Equipment Utilization) line can be split into two child lines for billing purposes. For example, 100 MT shift can be billed as 60 MT to one invoice and 40 MT to another.

### 2A. Schema Change

```sql
-- Add split tracking to lueu_lines
ALTER TABLE lueu_lines
  ADD COLUMN is_split INTEGER DEFAULT 0,        -- 1 if this line was split
  ADD COLUMN parent_line_id INTEGER REFERENCES lueu_lines(id),  -- FK to original line (for child)
  ADD COLUMN split_quantity REAL,               -- portion of original quantity assigned to this split
  ADD COLUMN split_remark TEXT;
```

**Split logic:**
- Original line: `is_split = 1`, original quantity unchanged (for reference)
- Child line 1: `parent_line_id = original.id`, `split_quantity = X`
- Child line 2: `parent_line_id = original.id`, `split_quantity = original.quantity - X`
- Constraint: Split children quantities must sum to ≤ original quantity
- A split line cannot be billed directly; only its children can be billed
- Split children inherit all fields from parent except quantity (uses split_quantity)

### 2B. New API Endpoint in LUEU01

Add to `modules/LUEU01/views.py`:

```python
@bp.route('/api/module/LUEU01/split-line', methods=['POST'])
@login_required
def split_line():
    """
    Split a LUEU line into two child lines.
    Input: { line_id, split_quantity_1, split_quantity_2, remark_1, remark_2 }
    Validation: split_quantity_1 + split_quantity_2 == original.quantity
    Creates 2 child rows with parent_line_id = original.id
    Marks original as is_split = 1
    """
    ...
```

### 2C. LUEU01 UI Update (`lueu01.html`)

- Add "Split" action button/column in the Tabulator grid (only shown for unbilled, unsplit rows)
- Click "Split" → opens a modal:
  - Shows original line details (equipment, quantity, UOM)
  - Two quantity inputs that must sum to original quantity (auto-calculates second from first)
  - Optional remark for each split
  - Submit button
- After split: original row shows "Split" badge; two child rows appear in list

### 2D. Impact on FIN01

- In bill creation, when fetching LUEU lines: `WHERE is_split = 0 OR parent_line_id IS NOT NULL` — show only non-split originals and split children, exclude split parents
- `bill_lines.eu_line_id` will reference the child split line (not the parent)
- Display split badge on bill line description when line is a split child

---

## Phase 3: SAP Integration (REST API)

### 3A. SAP Config Table + Admin UI

**New table: `sap_api_config`**

One row per environment (dev/qas/prod). `is_active = 1` marks the currently selected environment.

```sql
CREATE TABLE sap_api_config (
    id SERIAL PRIMARY KEY,
    environment TEXT NOT NULL,            -- 'development', 'quality', 'production'
    base_url TEXT NOT NULL,               -- e.g. https://sapapidev.jsw.in:50001
    client_id TEXT NOT NULL,
    client_secret TEXT NOT NULL,
    company_code TEXT NOT NULL,           -- e.g. '5171' (port/plant company code)
    default_payment_term TEXT DEFAULT '51',
    access_token TEXT,
    token_expiry TEXT,                    -- ISO datetime when token expires
    is_active INTEGER DEFAULT 0,          -- only one row should be 1 at a time
    created_date TEXT,
    updated_by TEXT,
    updated_date TEXT
);
```

**Admin UI for SAP Config** — new route in `modules/ADMIN/views.py`:

- `GET /module/ADMIN/sap-config` — renders `sap_config.html`
- `POST /api/module/ADMIN/sap-config/save` — upsert config row for an environment
- `POST /api/module/ADMIN/sap-config/set-active` — set `is_active = 1` for chosen environment (set others to 0)
- `POST /api/module/ADMIN/sap-config/test` — fetch token using stored credentials → return success/failure

**UI layout (`sap_config.html`):**
- Three tabs: Development | Quality | Production
- Each tab shows editable form fields:
  - Base URL, Client ID, Client Secret (masked input, eye icon to reveal), Company Code, Default Payment Term
  - Current Status badge: "Active" (green) or "Inactive" (grey)
  - Last token refresh time
- **"Set as Active Environment"** button (admin only) — switches active environment
- **"Test Connection"** button — calls token API → shows access_token truncated + expiry
- **"Save"** button — saves changes to that environment row
- All fields admin-only; non-admin sees read-only view with secrets masked

**`sap_client.py` loads active config:**
```python
def get_active_sap_config() -> dict:
    """SELECT * FROM sap_api_config WHERE is_active = 1 LIMIT 1"""
```

### 3B. Integration Logs Table

**New table: `integration_logs`**

```sql
CREATE TABLE integration_logs (
    id SERIAL PRIMARY KEY,
    integration_type TEXT NOT NULL,  -- 'SAP_INVOICE', 'SAP_CREDIT_NOTE', 'SAP_REVERSAL',
                                     --  'GST_IRN_GENERATE', 'GST_IRN_CANCEL', 'SAP_TOKEN'
    source_type TEXT,                -- 'invoice', 'credit_note', 'irn'
    source_id INTEGER,               -- FK to relevant table
    source_reference TEXT,           -- invoice number or IRN for quick display
    request_url TEXT,
    request_method TEXT DEFAULT 'POST',
    request_headers TEXT,            -- JSON (sanitized — no secrets)
    request_body TEXT,               -- JSON payload sent
    response_status_code INTEGER,
    response_body TEXT,              -- JSON response received
    status TEXT NOT NULL,            -- 'SUCCESS', 'FAILED', 'PENDING'
    error_message TEXT,
    duration_ms INTEGER,             -- Response time in milliseconds
    created_by TEXT,
    created_date TEXT
);

CREATE INDEX idx_integration_logs_source ON integration_logs(source_type, source_id);
CREATE INDEX idx_integration_logs_type ON integration_logs(integration_type);
CREATE INDEX idx_integration_logs_date ON integration_logs(created_date);
```

### 3C. SAP Client Library

**New file: `modules/FIN01/sap_client.py`**

```python
"""
JSW SAP PI REST API client.
Auth: OAuth2 client_credentials → Bearer token (expires 3600s)
API: POST /RESTAdapter/DynaportInvoice
"""
import json, time, requests
from datetime import datetime, timedelta
from database import get_db, get_cursor

class SAPClient:
    def __init__(self, config: dict):
        self.base_url = config['base_url']
        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.company_code = config['company_code']
        self.payment_term = config.get('default_payment_term', '51')
        self._token = config.get('access_token')
        self._token_expiry = config.get('token_expiry')

    def _get_token(self) -> str:
        """Return cached token or fetch new one if expired."""
        if self._token and self._token_expiry:
            # refresh 5 min before expiry
            if datetime.now() < datetime.fromisoformat(self._token_expiry) - timedelta(minutes=5):
                return self._token
        return self._refresh_token()

    def _refresh_token(self) -> str:
        url = (f"{self.base_url}/RESTAdapter/OAuthServer"
               f"?client_id={self.client_id}"
               f"&client_secret={self.client_secret}"
               f"&grant_type=client_credentials")
        r = requests.post(url, json={}, timeout=30)
        r.raise_for_status()
        data = r.json()
        self._token = data['access_token']
        expiry = datetime.now() + timedelta(seconds=data.get('expires_in', 3600))
        self._token_expiry = expiry.isoformat()
        # Update DB token cache
        self._save_token_to_db()
        return self._token

    def post_invoices(self, record_headers: list) -> list:
        """
        POST to /RESTAdapter/DynaportInvoice
        record_headers: list of invoice/credit_note dicts in SAP format
        Returns: list of {"Invoice": "...", "Status": "S"/"E", "Message": "..."}
        """
        token = self._get_token()
        url = f"{self.base_url}/RESTAdapter/DynaportInvoice"
        payload = {"Record_Header": record_headers}
        start = time.time()
        r = requests.post(url, json=payload,
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"},
                         timeout=60)
        duration = int((time.time() - start) * 1000)
        r.raise_for_status()
        return r.json().get("Record", []), payload, r.text, duration
```

### 3D. SAP JSON Builder

**New file: `modules/FIN01/sap_builder.py`**

```python
def build_invoice_payload(invoice_id: int) -> dict:
    """
    Fetches invoice_header + invoice_lines from DB and builds
    the DynaportInvoice Record_Header dict for a single invoice.

    invoice_lines.sac_code → ITEM.HSN_SAC
    invoice_lines.gl_code (from finance_service_types.sap_gl_account) → ITEM.GL_account
    invoice_lines.cgst_amount → ITEM.CGST_AMT (format as string, no decimals for INR)
    """
    ...

def build_credit_note_payload(credit_note_id: int) -> dict:
    """
    Same as above but Invoice_Credit='C', Document_type='CRN'
    Amounts are still positive in the payload
    """
    ...

def format_date_for_sap(date_str: str) -> str:
    """Convert YYYY-MM-DD to DD.MM.YYYY"""
    ...

def format_amount_for_sap(amount: float) -> str:
    """Convert float to string, no trailing zeros for INR amounts"""
    return str(int(amount)) if amount == int(amount) else str(round(amount, 2))
```

### 3E. New API Endpoints in FIN01

Add to `modules/FIN01/views.py`:

```python
@bp.route('/api/module/FIN01/invoice/post-sap/<int:invoice_id>', methods=['POST'])
@login_required
def post_invoice_to_sap(invoice_id):
    """
    1. Build SAP payload via sap_builder.build_invoice_payload()
    2. Call sap_client.post_invoices([payload])
    3. Log to integration_logs
    4. On success: update invoice_header.sap_document_number, invoice_status='SAP Posted'
    5. Return result to UI
    """
    ...

@bp.route('/api/module/FIN01/invoice/cancel-sap/<int:invoice_id>', methods=['POST'])
@login_required
def cancel_invoice_in_sap(invoice_id):
    """
    SAP cancellation/reversal — post reverse invoice (Invoice_Credit='C', Document_type='CRN')
    referencing original sap_document_number in Text/Reference
    """
    ...
```

### 3F. SAP→PMS: Advance Receipts and Incoming Payments

While the primary integration is PMS→SAP (posting invoices), the SAP→PMS direction (advances, payments, JVs) represents data flowing back from SAP into PMS. This is typically done by:
- SAP sends payment/advance data via webhook or scheduled export to PMS
- OR PMS fetches data from SAP via a separate query API (if JSW provides one)

**For now, design the receiving tables and manual entry UI; webhook/auto-sync in later phase.**

**New tables:**

```sql
CREATE TABLE advance_receipts (
    id SERIAL PRIMARY KEY,
    receipt_number TEXT UNIQUE NOT NULL,
    party_type TEXT NOT NULL,
    party_id INTEGER NOT NULL,
    party_name TEXT,
    receipt_date TEXT NOT NULL,
    amount REAL NOT NULL,
    currency_code TEXT DEFAULT 'INR',
    exchange_rate REAL DEFAULT 1.0,
    virtual_account_id INTEGER REFERENCES customer_virtual_accounts(id),
    utr_number TEXT,
    payment_method TEXT,
    sap_document_number TEXT,
    sap_posting_date TEXT,
    status TEXT DEFAULT 'Pending',    -- Pending, Confirmed, Adjusted, Refunded
    adjusted_against TEXT,            -- JSON [{invoice_id, amount_adjusted}]
    created_by TEXT,
    created_date TEXT,
    remarks TEXT
);

CREATE TABLE customer_incoming_payments (
    id SERIAL PRIMARY KEY,
    payment_number TEXT UNIQUE NOT NULL,
    party_type TEXT NOT NULL,
    party_id INTEGER NOT NULL,
    party_name TEXT,
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL,
    currency_code TEXT DEFAULT 'INR',
    exchange_rate REAL DEFAULT 1.0,
    virtual_account_id INTEGER REFERENCES customer_virtual_accounts(id),
    utr_number TEXT,
    payment_method TEXT,
    sap_document_number TEXT,
    sap_clearing_date TEXT,
    invoices_cleared TEXT,           -- JSON [{invoice_number, amount_cleared}]
    status TEXT DEFAULT 'Pending',
    created_by TEXT,
    created_date TEXT,
    remarks TEXT
);

CREATE TABLE gl_journal_vouchers (
    id SERIAL PRIMARY KEY,
    jv_number TEXT UNIQUE NOT NULL,
    jv_date TEXT NOT NULL,
    financial_year TEXT,
    jv_type TEXT DEFAULT 'JV',       -- 'JV' or 'Reversal'
    original_jv_id INTEGER REFERENCES gl_journal_vouchers(id),
    narration TEXT,
    total_debit REAL DEFAULT 0,
    total_credit REAL DEFAULT 0,
    jv_status TEXT DEFAULT 'Pending',
    sap_document_number TEXT,
    sap_posting_date TEXT,
    created_by TEXT,
    created_date TEXT
);

CREATE TABLE gl_jv_lines (
    id SERIAL PRIMARY KEY,
    jv_id INTEGER NOT NULL REFERENCES gl_journal_vouchers(id) ON DELETE CASCADE,
    line_number INTEGER,
    gl_account TEXT NOT NULL,
    gl_description TEXT,
    cost_center TEXT,
    profit_center TEXT,
    debit_amount REAL DEFAULT 0,
    credit_amount REAL DEFAULT 0,
    tax_code TEXT,
    line_narration TEXT
);
```

---

## Phase 4: GST E-Invoice GSP Integration

### 4A. GST Config Table + Admin UI (already exists: `gst_api_config`)

**Existing columns are sufficient** (`api_base_url`, `api_username`, `api_password`, `gstin`, `client_id`, `client_secret`, `environment`). Add `updated_by`, `updated_date` columns.

```sql
ALTER TABLE gst_api_config
  ADD COLUMN updated_by TEXT,
  ADD COLUMN updated_date TEXT;
```

**Admin UI for GST Config** — new route in `modules/ADMIN/views.py`:

- `GET /module/ADMIN/gst-config` — renders `gst_config.html`
- `POST /api/module/ADMIN/gst-config/save` — save/update credentials
- `POST /api/module/ADMIN/gst-config/set-env` — switch `environment` between 'sandbox' and 'production'
- `POST /api/module/ADMIN/gst-config/test` — call GSP auth endpoint → return token validity

**UI layout (`gst_config.html`):**
- Two tabs: Sandbox | Production
- Each tab: editable form with Base URL, GSP Username, GSP Password (masked), GSTIN, Client ID, Client Secret (masked)
- Environment badge showing which is currently active
- **"Set as Active"** button
- **"Test Connection"** button → shows auth token expiry on success
- **"Save"** button
- Audit: "Last updated by {user} on {date}"

### 4B. GSP Client Library

**New file: `modules/FIN01/gsp_client.py`**

```python
"""
GST GSP (Government Service Provider) API client.
Auth → Generate IRN → Get QR Code → Cancel IRN.
Encryption: AES-256 (payload) + RSA-2048 (SEK) per IRP spec.
Token validity: 6 hours. Refresh 10 min before expiry.
"""
import json, base64, requests
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

class GSPClient:
    def authenticate(self) -> dict:
        """POST /auth — returns access_token + SEK. Store in gst_api_config."""

    def generate_irn(self, invoice_payload: dict) -> dict:
        """
        POST /invoice — AES-encrypt payload with SEK, RSA-encrypt SEK.
        Returns: {irn, ack_number, ack_date, signed_invoice, qr_code_jwt}
        All responses are AES-decrypted using SEK.
        """

    def cancel_irn(self, irn: str, cancel_reason: int, remarks: str = '') -> dict:
        """
        POST /invoice/cancel
        cancel_reason: 1=Duplicate, 2=Data Error, 3=Order Cancelled, 4=Other
        24-hour cancellation window only.
        """
```

### 4C. IRP JSON Payload Builder

**New file: `modules/FIN01/einvoice_builder.py`**

```python
def build_irp_payload(invoice_id: int) -> dict:
    """
    Builds IRP-compliant JSON for IRN generation.
    Key mappings:
    - Suppl.Gstin ← port_config GSTIN (seller)
    - BuyDtls.Gstin ← invoice_header.customer_gstin
    - ItemList[n].IsServc = 'Y' (all port services)
    - ItemList[n].HsnCd ← invoice_lines.sac_code (SAC = HSN for services)
    - ItemList[n].TaxRate ← IGST rate if interstate, else CGST rate
    - Tax type: if supplier_state_code == buyer_state_code → CGST+SGST, else IGST
    """
```

### 4D. New Endpoints in FIN01

```python
@bp.route('/api/module/FIN01/invoice/generate-irn/<int:invoice_id>', methods=['POST'])
@login_required
def generate_irn(invoice_id):
    """Build IRP payload → authenticate GSP → generate IRN → store irn/ack/qr → log"""

@bp.route('/api/module/FIN01/invoice/cancel-irn/<int:invoice_id>', methods=['POST'])
@login_required
def cancel_irn(invoice_id):
    """Cancel IRN within 24h → update invoice_status → log"""
```

### 4E. Invoice UI Updates

- Replace static "e-Invoice JSON" export button with **"Generate IRN"** button
- Show IRN badge (truncated 8 chars) where `gst_irn IS NOT NULL`
- Add "Cancel IRN" in invoice actions (with reason dropdown modal)
- Invoice print view: display QR code from `gst_qr_code` JWT via qrcode.js

---

## Phase 5: Credit Note Management (FCN01)

### 5A. New Tables

```sql
CREATE TABLE credit_note_header (
    id SERIAL PRIMARY KEY,
    credit_note_number TEXT UNIQUE NOT NULL,  -- Format: CN{YYYY}-{SEQ}
    credit_note_date TEXT NOT NULL,
    financial_year TEXT NOT NULL,
    original_invoice_id INTEGER REFERENCES invoice_header(id),
    original_invoice_number TEXT,
    party_type TEXT NOT NULL,
    party_id INTEGER NOT NULL,
    party_name TEXT,
    party_gstin TEXT,
    party_gst_state_code TEXT,
    currency_code TEXT DEFAULT 'INR',
    exchange_rate REAL DEFAULT 1.0,
    subtotal REAL DEFAULT 0,
    cgst_amount REAL DEFAULT 0,
    sgst_amount REAL DEFAULT 0,
    igst_amount REAL DEFAULT 0,
    total_amount REAL DEFAULT 0,
    reason TEXT NOT NULL,
    credit_note_status TEXT DEFAULT 'Draft',  -- Draft, Approved, SAP Posted, IRN Generated, Cancelled
    sap_document_number TEXT,
    sap_posting_date TEXT,
    gst_irn TEXT,
    gst_ack_number TEXT,
    gst_ack_date TEXT,
    created_by TEXT,
    created_date TEXT,
    approved_by TEXT,
    approved_date TEXT,
    remarks TEXT
);

CREATE TABLE credit_note_lines (
    id SERIAL PRIMARY KEY,
    credit_note_id INTEGER NOT NULL REFERENCES credit_note_header(id) ON DELETE CASCADE,
    original_invoice_line_id INTEGER REFERENCES invoice_lines(id),
    line_number INTEGER,
    service_name TEXT,
    service_description TEXT,
    quantity REAL,
    uom TEXT,
    rate REAL,
    line_amount REAL NOT NULL,
    cgst_rate REAL DEFAULT 0,
    sgst_rate REAL DEFAULT 0,
    igst_rate REAL DEFAULT 0,
    cgst_amount REAL DEFAULT 0,
    sgst_amount REAL DEFAULT 0,
    igst_amount REAL DEFAULT 0,
    line_total REAL NOT NULL,
    gl_code TEXT,
    sac_code TEXT
);
```

### 5B. New Module: FCN01

**Register in `app.py`** and add to sidebar Accounts section.

**Routes:**
- `GET /module/FCN01/` — Tabulator list of credit notes
- `GET /module/FCN01/entry` — Create/edit form
- `POST /api/module/FCN01/save` — Save credit note header + lines
- `POST /api/module/FCN01/approve` — Approve credit note
- `POST /api/module/FCN01/post-sap` — Post to SAP as CRN (`Invoice_Credit='C'`, `Document_type='CRN'`)
- `POST /api/module/FCN01/generate-irn` — Generate IRN via GSP
- `POST /api/module/FCN01/cancel-irn` — Cancel IRN

**Credit Note Creation Flow:**
1. From FIN01 invoice list → click "Create Credit Note" on a Posted invoice
2. FCN01 form pre-fills from original invoice lines
3. User selects lines to credit (full or partial quantities)
4. Enter reason → Submit → Draft
5. Approve → Approved
6. Post to SAP (uses `sap_client.post_invoices()` with `Invoice_Credit='C'`)
7. Generate IRN → IRP credit note IRN

---

## Phase 6: Integration Logs UI (FLOG01 or ADMIN panel)

### 6A. New Module: FLOG01 — Integration Logs

Simple read-only Tabulator view of `integration_logs` table.

**Routes:**
- `GET /module/FLOG01/` — renders log viewer
- `GET /api/module/FLOG01/data` — paginated logs with filters

**Tabulator Columns:**
- Date/Time, Integration Type, Source Reference, Status (badge), Duration (ms), Actions (View Detail)

**Filters:**
- Integration Type dropdown (SAP_INVOICE, GST_IRN_GENERATE, etc.)
- Status dropdown (SUCCESS, FAILED, PENDING)
- Date range filter
- Source reference search

**Detail View (modal):**
- Show full Request Body (JSON pretty-printed)
- Show full Response Body (JSON pretty-printed)
- Error message if failed
- Re-trigger button (for FAILED records only — admin only)

**Every integration call (SAP + GST) logs to `integration_logs`:**

```python
def log_integration(integration_type, source_type, source_id, source_reference,
                    request_url, request_body, response_code, response_body,
                    status, error_message=None, duration_ms=None, created_by=None):
    # INSERT into integration_logs
    ...
```

This function should be called from both `sap_client.py` and `gsp_client.py`.

---

## Schema Migration Summary

**One Alembic revision** (or split into logical groups for easier rollback):

**Modified Tables:**
1. `vessel_agents` — add 15 columns (billing + SAP + `company_code`)
2. `vessel_customers` — add `sap_customer_code`, `company_code`
3. `vessel_importer_exporters` — add `sap_customer_code`, `company_code`
4. `finance_service_types` — add 4 SAP columns (`sap_gl_account`, `sap_tax_code`, `sap_profit_center`, `sap_cost_center`)
5. `bill_lines` — add `sap_tax_code`
6. `invoice_lines` — add `sap_tax_code`
7. `lueu_lines` — add 4 split tracking columns
8. `gst_api_config` — add `updated_by`, `updated_date`

**New Tables (in FK dependency order):**
1. `customer_virtual_accounts`
2. `sap_api_config`
3. `integration_logs`
4. `credit_note_header`
5. `credit_note_lines`
6. `advance_receipts`
7. `customer_incoming_payments`
8. `gl_journal_vouchers`
9. `gl_jv_lines`

**New Modules (register in `app.py` + add to `templates/base.html` sidebar):**
- `FCN01` — Credit Note Management
- `FSAP01` — SAP Financial Integration (Advances, Payments, JVs)
- `FLOG01` — Integration Logs

---

## Critical File Paths

| File | Change |
|------|--------|
| `alembic/versions/<new>.py` | All DDL above |
| `modules/VAM01/views.py`, `model.py`, `vam01.html` | Add billing + SAP fields |
| `modules/VCUM01/views.py`, `model.py`, `vcum01.html` | Add `sap_customer_code`, `company_code` |
| `modules/VIEM01/views.py`, `model.py`, `viem01.html` | Add `sap_customer_code`, `company_code` |
| `modules/ADMIN/views.py` | Add SAP config + GST config admin routes |
| `modules/ADMIN/sap_config.html` | **NEW** — SAP environment config UI (3 tabs) |
| `modules/ADMIN/gst_config.html` | **NEW** — GST GSP config UI (2 tabs) |
| `modules/FSTM01/views.py`, `model.py`, `fstm01.html` | Add 4 SAP columns |
| `modules/LUEU01/views.py` | Add split-line endpoint |
| `modules/LUEU01/model.py` | Add split_line(), get_splittable_lines() |
| `modules/LUEU01/lueu01.html` | Add Split button + modal |
| `modules/FIN01/views.py` | Add post-sap, cancel-sap, generate-irn, cancel-irn endpoints |
| `modules/FIN01/model.py` | Add update_sap_posting(), update_irn(); update create_invoice_from_bills() to populate sap_tax_code + profit/cost center from service type |
| `modules/FIN01/sap_client.py` | **NEW** — JSW SAP REST API client |
| `modules/FIN01/sap_builder.py` | **NEW** — DynaportInvoice JSON builder |
| `modules/FIN01/gsp_client.py` | **NEW** — GST GSP API client |
| `modules/FIN01/einvoice_builder.py` | **NEW** — IRP JSON payload builder |
| `modules/FIN01/integration_logger.py` | **NEW** — shared logging helper |
| `modules/FIN01/invoices.html` | Update buttons: Generate IRN, Cancel IRN, Post SAP |
| `modules/FCN01/__init__.py` | **NEW** |
| `modules/FCN01/views.py`, `model.py`, `fcn01.html` | **NEW** — credit notes |
| `modules/FSAP01/__init__.py` | **NEW** |
| `modules/FSAP01/views.py`, `model.py`, `fsap01.html` | **NEW** — advances, payments, JVs |
| `modules/FLOG01/__init__.py` | **NEW** |
| `modules/FLOG01/views.py`, `model.py`, `flog01.html` | **NEW** — integration logs |
| `app.py` | Register FCN01, FSAP01, FLOG01 blueprints |
| `templates/base.html` | Add FCN01, FSAP01, FLOG01 to Accounts sidebar |

---

## Python Dependencies to Add

```
# requirements.txt additions
pycryptodome>=3.20.0    # AES-256 + RSA for GST e-invoice encryption
# requests — likely already installed (for GST GSP + SAP REST)
# NO pyrfc needed — SAP uses REST API via JSW SAP PI
```

---

## Implementation Order (Priority)

**Batch 1 — Schema + Master Data (no external dependencies, quick wins):**
1. Run Alembic migration for all new/modified tables
2. Phase 1A: VAM01 billing + SAP + company_code fields
3. Phase 1B: sap_customer_code + company_code in VCUM01 + VIEM01
4. Phase 1C: FSTM01 SAP GL/tax/cost/profit fields
5. Phase 1D: Virtual accounts table + sub-panels

**Batch 2 — Admin Config UI (needed before any integration testing):**
6. ADMIN: SAP config page (3-tab: dev/qas/prod, editable credentials, Set Active, Test Connection)
7. ADMIN: GST config page (2-tab: sandbox/production, editable credentials, Set Active, Test Connection)

**Batch 3 — LUEU01 Split:**
8. Phase 2: EU line split (model + views + UI modal)

**Batch 4 — New Modules (no external API yet):**
9. Phase 5: FCN01 Credit Note (DB CRUD + UI, no SAP/GST calls yet)
10. Phase 3F: FSAP01 module (advance receipts, payments, JVs — manual entry)
11. Phase 6: FLOG01 Integration Logs viewer

**Batch 5 — SAP Integration (needs JSW SAP PI credentials + firewall):**
12. Phase 3C-3E: sap_client.py + sap_builder.py + FIN01 post-sap endpoint + FCN01 SAP posting

**Batch 6 — GST E-Invoice (needs GSP credentials):**
13. Phase 4B-4D: gsp_client.py + einvoice_builder.py + FIN01 IRN endpoints + FCN01 IRN

---

## SAP API Credentials Reference

| Env | URL | client_id | client_secret |
|-----|-----|-----------|---------------|
| Dev | https://sapapidev.jsw.in:50001 | jsw_api | k1A_6gvcfIXc3ev-UpuXsfGYXFUW610ZJzPrbIi4Ogc |
| QAS | https://sapapiqas.jsw.in:52401 | jsw_api | fL6GOT9zuiY3LtiJHSr8R0w5CeQObG6Gy2J4f832i5I |
| Prod | https://sapapi.jsw.in:54001 | jsw_steel | mHJgvipjDPcAiO4H0PZZQXj-aZ4KRq4yXpbFr7jn1BM |

Company Code: **5171** | Default Payment Term: **51** | Business/Section/Credit_Control_Area: **5171**

---

## Verification & Testing

### Phase 1 (Master Data)
1. `alembic upgrade head` — verify no errors
2. Open VAM01 → add agent with GSTIN + sap_customer_code; verify saved in DB
3. Open FSTM01 → add SAP GL account "4101076030" to a service; verify saved
4. Open VCUM01 → verify `sap_customer_code` field appears; save a customer with "I510785"
5. Open any customer in VAM01/VCUM01 → add virtual account; verify sub-panel works

### Phase 2 (LUEU01 Split)
1. Open LUEU01 → find an unbilled, unsplit line with quantity > 1
2. Click Split → enter quantity_1 + quantity_2 (must sum to original)
3. Submit → verify: original row shows "Split" badge; two child rows appear
4. Open FIN01 → create bill from this source → verify split children appear (not parent)
5. Try to split an already-billed line → verify button is hidden/disabled

### Phase 2 (Admin Config UI)
1. Open `/module/ADMIN/sap-config` → verify 3 tabs shown with all credential fields
2. Enter Dev credentials → click "Test Connection" → verify access token received
3. Click "Set as Active" → verify `is_active = 1` in `sap_api_config` for that row, others = 0
4. Test masking: client_secret shown as `••••••••` with eye icon to reveal
5. Save changes → verify `updated_by` + `updated_date` recorded in DB
6. Repeat steps 1-5 for GST config page (`/module/ADMIN/gst-config`)

### Phase 3b (SAP Integration)
1. Set active environment to Development via Admin Config UI
2. Test token: verify "Test Connection" shows access_token truncated + expiry time
3. Create and approve a test invoice for customer with sap_customer_code set
4. Click "Post to SAP" → check `integration_logs` for request/response
5. Verify `invoice_header.sap_document_number` populated on success
6. Open FLOG01 → verify log entry visible with full request/response JSON

### Phase 4 (GST E-Invoice)
1. Configure GST API credentials (NIC sandbox: `https://einv-apisandbox.nic.in/`)
2. Create invoice with valid customer GSTIN and all lines having SAC codes
3. Click "Generate IRN" → check `integration_logs` for encrypted request + decrypted response
4. Verify `invoice_header.gst_irn` populated (64-char string)
5. Test cancel within 24h → verify IRN cancelled

### Phase 5 (Credit Notes)
1. Open a Posted invoice in FIN01 → click "Create Credit Note"
2. FCN01 form pre-fills with original invoice lines
3. Select partial credit (reduce quantity of one line)
4. Save → verify credit_note_header with CN{YYYY}-{SEQ} number
5. Approve → post to SAP (`Invoice_Credit='C'`, `Document_type='CRN'`)
6. Check FLOG01 for SAP call log

### Database Integrity Check
```sql
-- All new tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'customer_virtual_accounts', 'sap_api_config', 'integration_logs',
    'credit_note_header', 'credit_note_lines', 'advance_receipts',
    'customer_incoming_payments', 'gl_journal_vouchers', 'gl_jv_lines'
  );

-- LUEU split columns
SELECT column_name FROM information_schema.columns
WHERE table_name = 'lueu_lines' AND column_name IN ('is_split','parent_line_id');

-- SAP fields on service types
SELECT column_name FROM information_schema.columns
WHERE table_name = 'finance_service_types'
  AND column_name IN ('sap_gl_account','sap_tax_code','sap_profit_center','sap_cost_center');
```
