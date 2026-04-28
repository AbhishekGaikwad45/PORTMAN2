# PORTMAN Billing Remodel - Implementation Plan

## Overview

This plan covers 5 major changes:
1. **Fix GST rate calculation** - Use actual rates from `gst_rates` master instead of hardcoded 18%
2. **Fix intra-state vs inter-state GST** - CGST+SGST vs IGST based on customer state code
3. **FCAM01 Agreement selection at billing** - Multiple agreements per customer, selectable dropdown during billing
4. **EAV Custom Fields for Services** - Admin-configurable fields per service type + new Service Recording module (SRV01) for operations
5. **Approval workflow config for finance modules** - Ensure FIN01, SRV01, FCAM01 all use the module config approval pattern

---

## CHANGE 1: Fix GST Rate Calculation

### Problem
In `modules/FIN01/generate_bill.html`, GST is hardcoded:
```javascript
const gstRate = 0.18; // line 484
const cgst = gstAmount / 2; // line 425
const sgst = gstAmount / 2; // line 426
```
It should use the GST rate linked to each service type via `finance_service_types.gst_rate_id → gst_rates`.

### Changes Required

#### A. Backend: `modules/FIN01/views.py`
- **Modify** `/api/module/FIN01/service-types` endpoint to also return `gst_rate_id`, `cgst_rate`, `sgst_rate`, `igst_rate` for each service type (JOIN with `gst_rates` table).

#### B. Frontend: `modules/FIN01/generate_bill.html`
- When a service type is selected for an EU line, use the GST rate from that service type (fetched in step A) instead of hardcoded 0.18.
- Store `cgst_rate`, `sgst_rate`, `igst_rate` per line.
- `calculateTotals()` function must compute GST per-line (since different service types can have different GST rates) and then sum.

### Files to Modify
| File | Change |
|------|--------|
| `modules/FIN01/views.py` | Update service-types API to JOIN gst_rates |
| `modules/FIN01/generate_bill.html` | Use per-line GST rates from service type data |

---

## CHANGE 2: Intra-state vs Inter-state GST Logic

### Problem
Currently always splits GST as CGST+SGST. Should check:
- If `port_gst_state_code == customer_gst_state_code` → **CGST + SGST** (intra-state)
- If different → **IGST** (inter-state)

### Changes Required

#### A. New Config: Port GST State Code
- Add a config entry for the port's own GST state code. Options:
  - **Option 1**: Add to `module_config` table under FIN01 config JSON (e.g., `{"port_gst_state_code": "20", "port_gstin": "20XXXXX"}`)
  - **Option 2**: New `company_config` table
- **Decision**: Use Option 1 (module_config for FIN01) to keep it simple.

#### B. Backend: New API endpoint
- **Add** `/api/module/FIN01/port-config` - Returns port GST state code from FIN01 module config.

#### C. Frontend: `modules/FIN01/generate_bill.html`
- On page load, fetch port GST state code.
- When customer is selected, compare `customer.gst_state_code` with port state code.
- If same state → use `cgst_rate` and `sgst_rate` (each = half of total GST)
- If different state → use `igst_rate` (= full GST rate), set cgst/sgst to 0
- Update `calculateTotals()` and `generateBill()` functions accordingly.

#### D. Backend: Bill save logic
- The bill save endpoint already accepts per-line GST amounts, so no backend change needed - the frontend will send correct values.

### Files to Modify
| File | Change |
|------|--------|
| `modules/FIN01/views.py` | Add port-config API endpoint |
| `modules/FIN01/generate_bill.html` | Add state comparison logic, fix GST split |

### Setup Required
- Admin must configure FIN01 module config with `port_gst_state_code` via ADMIN module or a one-time seed.

---

## CHANGE 3: FCAM01 Agreement Selection During Billing

### Current Behavior
- `FCAM01` allows creating one or more agreements per customer, each with lines for different services.
- During billing, `get_agreement_rate()` auto-fetches the rate from the latest valid approved agreement.
- User has no choice of which agreement to use if multiple exist.

### Desired Behavior
- A customer can have **multiple active approved agreements** (e.g., "Standard Rate 2025", "Special Bulk Rate Q1").
- During billing in FIN01, after selecting customer, show a **dropdown of all valid agreements** for that customer.
- User picks an agreement → rates for service types are fetched from that specific agreement.

### Changes Required

#### A. Backend: New API endpoint in `modules/FIN01/views.py`
- **Add** `/api/module/FIN01/customer-agreements/<int:customer_id>`
  - Returns all active, approved agreements for this customer that are currently valid (date range check).
  - Response: `[{id, agreement_code, agreement_name, valid_from, valid_to, currency_code}, ...]`

#### B. Backend: Modify agreement rate endpoint
- **Modify** `/api/module/FIN01/agreement-rate/<int:customer_id>/<int:service_type_id>`
  - Add optional query param `?agreement_id=X`
  - If `agreement_id` is provided, fetch rate from that specific agreement only.
  - If not provided, fall back to current behavior (latest valid agreement).

#### C. Frontend: `modules/FIN01/generate_bill.html`
- After customer is selected, fetch and display an **Agreement dropdown**.
- When agreement is changed, re-fetch rates for all EU lines that have a service type selected.
- Store `agreement_id` in bill header data when saving.

#### D. Database: Add `agreement_id` to `bill_header`
- New column: `bill_header.agreement_id INTEGER REFERENCES customer_agreements(id)`
- Alembic migration needed.

### Files to Modify
| File | Change |
|------|--------|
| `modules/FIN01/views.py` | Add customer-agreements API, modify agreement-rate API |
| `modules/FIN01/generate_bill.html` | Add agreement dropdown, wire up rate fetching |
| `modules/FIN01/model.py` | Include agreement_id in save_bill_header |
| New alembic migration | Add `agreement_id` column to `bill_header` |

---

## CHANGE 4: EAV Custom Fields for Services + Service Recording Module

This is the largest change. It introduces:
1. **Admin-configurable custom fields** per service type (in FSTM01)
2. **New module SRV01** (Service Recording) for operations to record service usage
3. **FIN01 billing integration** to bill recorded services alongside EU lines

### 4A. Database Schema - New Tables

#### Table: `service_field_definitions`
Stores the custom field definitions per service type.

```sql
CREATE TABLE service_field_definitions (
    id SERIAL PRIMARY KEY,
    service_type_id INTEGER NOT NULL REFERENCES finance_service_types(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,          -- internal name (snake_case, e.g., "grab_hire_start")
    field_label TEXT NOT NULL,          -- display label (e.g., "Grab Hiring Start")
    field_type TEXT NOT NULL,           -- 'text', 'number', 'datetime', 'date', 'dropdown', 'checkbox', 'calculated'
    field_options TEXT,                 -- JSON: for dropdown = ["Option1","Option2",...], for calculated = formula string
    calculation_formula TEXT,           -- e.g., "grab_hire_end - grab_hire_start" (references other field_names)
    calculation_result_type TEXT,       -- 'hours', 'days', 'number' (how to interpret the calculation)
    is_required INTEGER DEFAULT 0,
    is_billable_qty INTEGER DEFAULT 0, -- if checked, this field's value is used as the "quantity" for billing
    display_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_by TEXT,
    created_date TEXT
);
```

**Key design decisions:**
- `field_type = 'calculated'`: Value is auto-computed from other fields in the same service record. `calculation_formula` references other `field_name`s. For datetime differences, `calculation_result_type` tells UI to compute hours/days.
- `is_billable_qty = 1`: Marks this field as the one whose value becomes the billing quantity. Only one field per service type should have this flag set to 1.
- `field_options`: JSON array for dropdown choices. E.g., `["Liebherr", "Gottwald", "Wire Rope"]` for "Grab Make".

#### Table: `service_records`
Header for each recorded service instance.

```sql
CREATE TABLE service_records (
    id SERIAL PRIMARY KEY,
    record_number TEXT UNIQUE NOT NULL,  -- auto-generated "SRV0001"
    service_type_id INTEGER NOT NULL REFERENCES finance_service_types(id),
    source_type TEXT NOT NULL,            -- 'VCN', 'MBC', 'VEX'
    source_id INTEGER NOT NULL,
    source_display TEXT,                  -- e.g., "VCN0001 - MV Pearl"
    record_date TEXT,
    billable_quantity REAL,               -- copied from the is_billable_qty field value
    billable_uom TEXT,                    -- from the service type's UOM
    doc_status TEXT DEFAULT 'Pending',    -- Pending, Approved
    is_billed INTEGER DEFAULT 0,
    bill_id INTEGER,
    created_by TEXT,
    created_date TEXT,
    approved_by TEXT,
    approved_date TEXT,
    remarks TEXT
);
```

#### Table: `service_record_values`
EAV table storing the actual field values.

```sql
CREATE TABLE service_record_values (
    id SERIAL PRIMARY KEY,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id) ON DELETE CASCADE,
    field_definition_id INTEGER NOT NULL REFERENCES service_field_definitions(id),
    field_value TEXT,                     -- all values stored as TEXT, parsed by field_type
    UNIQUE(service_record_id, field_definition_id)
);
```

### 4B. Service Type Master Enhancement (FSTM01)

#### New Feature: "Configure Fields" button per service type
- In `fstm01.html`, add a "Fields" button/link for each service type row.
- Clicking it opens a sub-section or modal to manage `service_field_definitions` for that service type.
- Admin can:
  - Add fields with label, type, options, display order
  - Mark one field as `is_billable_qty`
  - For calculated fields, define the formula referencing other field names
  - Set dropdown options as comma-separated values (stored as JSON array)

#### Field Configuration UI
A simple inline table (matching existing PORTMAN patterns):

| Field Label | Internal Name | Type | Options/Formula | Required | Billable Qty | Order | Active |
|-------------|---------------|------|-----------------|----------|--------------|-------|--------|

**Example - "Grab Hiring Charges" service:**

| Field Label | Internal Name | Type | Options/Formula | Required | Billable Qty | Order |
|-------------|---------------|------|-----------------|----------|--------------|-------|
| Grab Hiring Start | grab_hire_start | datetime | | Yes | No | 1 |
| Grab Hiring End | grab_hire_end | datetime | | Yes | No | 2 |
| Hours | hours | calculated | grab_hire_end - grab_hire_start (hours) | No | Yes | 3 |
| Grab Make | grab_make | dropdown | ["Liebherr","Gottwald","Wire Rope"] | No | No | 4 |

### Backend Changes for FSTM01

#### New endpoints in `modules/FSTM01/views.py`:
- `GET /api/module/FSTM01/fields/<int:service_type_id>` - Get all field definitions for a service type
- `POST /api/module/FSTM01/fields/save` - Save/update a field definition
- `POST /api/module/FSTM01/fields/delete` - Delete a field definition

#### New functions in `modules/FSTM01/model.py`:
- `get_field_definitions(service_type_id)` - Fetch field definitions ordered by display_order
- `save_field_definition(data)` - Insert/update
- `delete_field_definition(field_id)` - Delete

#### Also add to `finance_service_types`:
- New column: `has_custom_fields INTEGER DEFAULT 0` - Quick flag to know if this service type has custom fields configured (avoids extra queries).

### Files to Modify/Create
| File | Change |
|------|--------|
| `modules/FSTM01/model.py` | Add field definition CRUD functions |
| `modules/FSTM01/views.py` | Add field definition API endpoints |
| `modules/FSTM01/fstm01.html` | Add "Configure Fields" button + field config UI |
| New alembic migration | Create `service_field_definitions` table, add `has_custom_fields` to `finance_service_types` |

### 4C. New Module: SRV01 (Service Recording)

Operations staff use this module to record service usage against a VCN/MBC/VEX.

#### Module Structure
```
modules/SRV01/
├── __init__.py
├── model.py
├── views.py
└── srv01.html
```

#### SRV01 UI Flow
1. User opens SRV01.
2. Selects **Source Type** (VCN/MBC/VEX) → **Source Document** (dropdown with doc numbers).
3. Selects **Service Type** from dropdown (only shows services that have `has_custom_fields = 1`).
4. On service type selection, the configured custom fields render dynamically:
   - `text` → text input
   - `number` → number input
   - `datetime` → datetime-local input
   - `date` → date input
   - `dropdown` → select with options from `field_options`
   - `checkbox` → checkbox
   - `calculated` → read-only field, auto-computed on change of dependent fields
5. User fills in the fields → Saves the record.
6. List view shows all service records with filters by source, service type, billed status.

#### Calculated Field Logic (Frontend)
For `field_type = 'calculated'`:
- Parse `calculation_formula` - for the MVP, support datetime difference:
  - Format: `{field_name_end} - {field_name_start}` with `calculation_result_type = 'hours'`
  - Frontend computes: `(end_datetime - start_datetime) / 3600000` → hours (rounded to 2 decimals)
- Attach `onchange` listeners to referenced fields, recompute when they change.
- If `is_billable_qty = 1`, copy the computed value to `service_records.billable_quantity`.

#### Backend - model.py
```
get_next_record_number()
get_service_records(page, size, filters)    -- paginated list with filters
get_service_record_by_id(record_id)         -- header + values
save_service_record(header_data, values)    -- save header + EAV values
delete_service_record(record_id)
get_service_types_with_fields()             -- service types that have custom fields
get_field_definitions(service_type_id)      -- reuse from FSTM01 or direct query
```

#### Backend - views.py
```
GET  /module/SRV01/                              -- main view
GET  /api/module/SRV01/data                      -- paginated list
GET  /api/module/SRV01/service-types             -- service types with has_custom_fields=1
GET  /api/module/SRV01/fields/<service_type_id>  -- field definitions for selected service
GET  /api/module/SRV01/record/<record_id>        -- get record with values
POST /api/module/SRV01/save                      -- save record + values
POST /api/module/SRV01/delete                    -- delete record
GET  /api/module/SRV01/source-options/<type>     -- VCN/MBC/VEX dropdown options (reuse EU01 pattern)
```

#### Registration in app.py
```python
from modules.SRV01 import bp as srv01_bp, MODULE_INFO as srv01_info
register_module(srv01_info['code'], srv01_info['name'], srv01_bp)
```

### Files to Create
| File | Purpose |
|------|---------|
| `modules/SRV01/__init__.py` | Blueprint + MODULE_INFO |
| `modules/SRV01/model.py` | Database operations |
| `modules/SRV01/views.py` | Routes + APIs |
| `modules/SRV01/srv01.html` | Main template with dynamic field rendering |

### Files to Modify
| File | Change |
|------|--------|
| `app.py` | Import and register SRV01 |
| New alembic migration | Create `service_records` and `service_record_values` tables |

### 4D. FIN01 Billing Integration with Service Records

During bill generation, the user should see **both**:
1. EU lines (equipment utilization) - existing behavior
2. Service records (from SRV01) - new

#### Changes to Generate Bill Flow

##### Backend: New API endpoint in `modules/FIN01/views.py`
- **Add** `/api/module/FIN01/service-records/<source_type>/<int:source_id>`
  - Returns all service records for this source that are `doc_status = 'Approved'` and `is_billed = 0`.
  - Include service type name, billable quantity, UOM, and the custom field values (for display).

##### Frontend: `modules/FIN01/generate_bill.html`
- After loading EU lines, also load service records for the same source.
- Display them in a **separate table section** below EU lines: "Service Records".
- Each service record row shows:
  - Checkbox (select for billing)
  - Record number
  - Service type name
  - Key field values (rendered from EAV data)
  - Billable quantity (from `service_records.billable_quantity`)
  - UOM
  - Rate (auto-fetched from selected agreement, same as EU lines)
  - Amount (qty × rate)
  - Already billed badge if applicable
- On "Generate Bill", selected service records become `bill_lines` entries too.

##### Backend: Modify bill save
- **Modify** `/api/module/FIN01/bill/save` to handle service record lines.
- When saving a bill line that comes from a service record:
  - Set `bill_lines.eu_line_id = NULL` (it's not from EU).
  - Add new column `bill_lines.service_record_id INTEGER REFERENCES service_records(id)`.
  - Mark the service record as `is_billed = 1, bill_id = <bill_id>`.

##### Backend: Modify bill delete
- **Modify** `delete_bill()` in model.py to also unmark service records when a bill is deleted.

#### Database Change
- Add column `bill_lines.service_record_id INTEGER REFERENCES service_records(id)`

### Files to Modify
| File | Change |
|------|--------|
| `modules/FIN01/views.py` | Add service-records API, modify bill save |
| `modules/FIN01/model.py` | Add service_record_id handling in bill line save/delete |
| `modules/FIN01/generate_bill.html` | Add service records section, integrate with billing |
| New alembic migration | Add `service_record_id` to `bill_lines`, `agreement_id` to `bill_header` |

---

## Summary: All Database Changes (Single Alembic Migration)

### New Tables
1. `service_field_definitions` - Custom field definitions per service type
2. `service_records` - Service recording headers
3. `service_record_values` - EAV values for service records

### New Columns on Existing Tables
1. `finance_service_types.has_custom_fields` INTEGER DEFAULT 0
2. `bill_header.agreement_id` INTEGER (FK → customer_agreements)
3. `bill_lines.service_record_id` INTEGER (FK → service_records)

---

## Summary: All Files to Create

| File | Purpose |
|------|---------|
| `modules/SRV01/__init__.py` | Module init |
| `modules/SRV01/model.py` | Service recording DB operations |
| `modules/SRV01/views.py` | Service recording routes |
| `modules/SRV01/srv01.html` | Service recording UI with dynamic fields |
| `alembic/versions/xxxx_billing_remodel.py` | Migration for all DB changes |

## Summary: All Files to Modify

| File | Changes |
|------|---------|
| `modules/FIN01/views.py` | GST fix, port-config API, customer-agreements API, modify agreement-rate API, service-records API, modify bill save, approval workflow checks |
| `modules/FIN01/model.py` | agreement_id in bill header, service_record_id in bill lines, unmark service records on bill delete |
| `modules/FIN01/generate_bill.html` | GST from master, state-based CGST/SGST vs IGST, agreement dropdown, service records section |
| `modules/FIN01/bills.html` | Approve/reject buttons conditional on approver role |
| `modules/FIN01/bill_view.html` | Approve/reject buttons conditional on approver role |
| `modules/FCAM01/views.py` | Approval workflow checks using module_config |
| `modules/FCAM01/entry.html` | Approve button conditional on approver role |
| `modules/FSTM01/model.py` | Field definition CRUD functions |
| `modules/FSTM01/views.py` | Field definition API endpoints |
| `modules/FSTM01/fstm01.html` | Configure Fields UI per service type |
| `app.py` | Register SRV01 module |

---

## Implementation Order

### Phase 1: GST Fixes (Changes 1 & 2)
1. Update FIN01 service-types API to include GST rates
2. Add port-config API endpoint
3. Fix `generate_bill.html` GST calculation (per-line rates, state-based split)

### Phase 2: Agreement Selection (Change 3)
4. Add customer-agreements API
5. Modify agreement-rate API for specific agreement lookup
6. Add agreement dropdown to generate_bill.html
7. Alembic migration for `bill_header.agreement_id`

### Phase 3: Custom Fields System (Change 4A + 4B)
8. Alembic migration for `service_field_definitions`, `has_custom_fields`
9. FSTM01 backend: field definition CRUD
10. FSTM01 frontend: Configure Fields UI

### Phase 4: Service Recording Module (Change 4C)
11. Alembic migration for `service_records`, `service_record_values`
12. Create SRV01 module (init, model, views, template)
13. Register in app.py

### Phase 5: Billing Integration (Change 4D)
14. Alembic migration for `bill_lines.service_record_id`
15. FIN01 service-records API
16. Modify bill save/delete for service records
17. Update generate_bill.html to show service records

---

## Example: End-to-End Flow After Implementation

### Setup (Admin)
1. **FSTM01**: Create service "Grab Hiring Charges" with SAC code, GST rate 18%.
2. **FSTM01 → Configure Fields**: Add fields:
   - Grab Hiring Start (datetime, required)
   - Grab Hiring End (datetime, required)
   - Hours (calculated: end - start in hours, billable qty)
   - Grab Make (dropdown: Liebherr/Gottwald/Wire Rope)
3. **FCAM01**: Create agreement for Customer "ABC Shipping":
   - Grab Hiring Charges: Rate 5000/hour

### Operations
4. **VCN01**: Create vessel call VCN0042 for MV Pearl.
5. **EU01**: Record equipment utilization lines (crane hours, etc.)
6. **SRV01**: Record grab hiring:
   - Source: VCN → VCN0042
   - Service: Grab Hiring Charges
   - Fill: Start=2025-01-20 08:00, End=2025-01-20 14:00
   - Auto-computed: Hours=6.00, Billable Qty=6.00
   - Fill: Grab Make=Liebherr

### Billing
7. **FIN01 → Generate Bill**:
   - Source: VCN → VCN0042
   - Customer: ABC Shipping
   - Agreement: "Standard Rate 2025" (dropdown)
   - EU Lines section: select crane usage lines (rate from agreement)
   - Service Records section: shows grab hiring record (6 hrs × ₹5000 = ₹30,000)
   - GST: 18% → CGST 9% + SGST 9% (same state) or IGST 18% (different state)
   - Total computed and bill generated.

---

## CHANGE 5: Approval Workflow Config for Finance Modules

### Current Pattern
The ADMIN module has a **Module Config** tab (`/admin` → Module Config) that stores per-module JSON config in `module_config` table. The config supports:
- `approval_add` (boolean) - Require approval when creating records
- `approval_edit` (boolean) - Require approval when editing records
- `approver_id` (user ID) - The designated approver

Existing modules like VCN01 use this pattern:
```python
# In views.py save endpoint:
config = get_module_config('VCN01')
is_approver = str(config.get('approver_id')) == str(user_id)
if is_approver:
    data['doc_status'] = 'Approved'
elif config.get('approval_add'):
    data['doc_status'] = 'Pending'
```

### Problem
- **FIN01**: Bill approval (`approve_bill`, `submit_bill`, `reject_bill`) exists but does NOT check `module_config` for approver. Anyone can approve.
- **FCAM01**: Has an `approve` endpoint but doesn't check module_config approver either.
- **SRV01** (new): Needs approval workflow from the start.

### Changes Required

#### A. FIN01 - Bill Approval
- **Modify** `save_bill` in `views.py`: Check `get_module_config('FIN01')` for `approval_add`/`approval_edit`. If approver saves → status = 'Approved'. If non-approver saves and approval required → status = 'Pending Approval'.
- **Modify** `approve_bill` endpoint: Only allow if user is the configured approver (or is admin).
- **Modify** `generate_bill.html`: Show/hide approve button based on whether user is approver.

#### B. FCAM01 - Agreement Approval
- **Modify** `save_header` in `views.py`: Check `get_module_config('FCAM01')` for approval config. Set `agreement_status` based on whether user is approver.
- **Modify** `approve` endpoint: Only allow configured approver or admin.
- **Modify** `entry.html`: Show approve button only for approver.

#### C. SRV01 - Service Record Approval
- **Implement from the start**: In `save` endpoint, check `get_module_config('SRV01')`. Set `doc_status` accordingly.
- Add `approve` endpoint that checks approver config.
- In `srv01.html`: Show approve button only for configured approver.

#### D. ADMIN Module Config Enhancement
The existing config UI only has `approval_add`, `approval_edit`, `approver_id`. This is sufficient for all modules. No ADMIN changes needed — just ensure FIN01, FCAM01, and SRV01 modules appear in the module dropdown (they will, since they're registered).

**Optional enhancement**: The ADMIN config could also store `port_gst_state_code` and `port_gstin` under FIN01 config. This ties into Change 2.

### Files to Modify
| File | Change |
|------|--------|
| `modules/FIN01/views.py` | Add module_config checks to save/approve/reject endpoints |
| `modules/FIN01/generate_bill.html` | Pass approver status to template, show/hide approve |
| `modules/FIN01/bills.html` | Show approve/reject buttons only for approver |
| `modules/FIN01/bill_view.html` | Show approve/reject buttons only for approver |
| `modules/FCAM01/views.py` | Add module_config checks to save/approve endpoints |
| `modules/FCAM01/entry.html` | Show approve button only for approver |
| `modules/SRV01/views.py` | Implement with module_config checks from the start |
| `modules/SRV01/srv01.html` | Implement with approver-aware UI |

---

## Updated Implementation Order

### Phase 1: GST Fixes (Changes 1 & 2)
1. Update FIN01 service-types API to include GST rates
2. Add port-config API endpoint (or add to FIN01 module config via ADMIN)
3. Fix `generate_bill.html` GST calculation (per-line rates, state-based split)

### Phase 2: Approval Workflow (Change 5)
4. Fix FIN01 bill approval to use module_config
5. Fix FCAM01 agreement approval to use module_config
6. (SRV01 will be built with this from the start in Phase 4)

### Phase 3: Agreement Selection (Change 3)
7. Add customer-agreements API
8. Modify agreement-rate API for specific agreement lookup
9. Add agreement dropdown to generate_bill.html
10. Alembic migration for `bill_header.agreement_id`

### Phase 4: Custom Fields System (Change 4A + 4B)
11. Alembic migration for `service_field_definitions`, `has_custom_fields`
12. FSTM01 backend: field definition CRUD
13. FSTM01 frontend: Configure Fields UI

### Phase 5: Service Recording Module (Change 4C)
14. Alembic migration for `service_records`, `service_record_values`
15. Create SRV01 module (init, model, views, template) — with approval workflow built-in
16. Register in app.py

### Phase 6: Billing Integration (Change 4D)
17. Alembic migration for `bill_lines.service_record_id`
18. FIN01 service-records API
19. Modify bill save/delete for service records
20. Update generate_bill.html to show service records

---

## Questions / Decisions Needed

1. **Port GST State Code**: Should this be configured via FIN01 module config (simple) or a dedicated company settings table?
   - **Recommendation**: FIN01 module config (keeps it simple).

2. **Calculated field formulas**: For MVP, support only datetime difference (hours/days). Expand later if needed?
   - **Recommendation**: Yes, MVP = datetime difference only. Add more formula types later.

3. **Should SRV01 records need approval before billing?** Currently planned as `doc_status = Pending → Approved`.
   - **Recommendation**: Yes, same approval workflow as other modules.

4. **Can a service type have BOTH EU lines and custom fields?** Or are they mutually exclusive?
   - **Recommendation**: They are independent. EU01 tracks equipment utilization. SRV01 tracks service-specific data. A VCN can have both EU lines and service records billed together.

5. **Sidebar placement for SRV01**: Under Operations section alongside EU01? Or under Finance?
   - **Recommendation**: Under Operations (it's used by operations staff, not finance).
