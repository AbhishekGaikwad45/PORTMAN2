# ULIP ↔ VCN01 Alignment Analysis
**Date drafted:** 2026-02-18
**Purpose:** Ensure VCN01 is ready for future ULIP integration (IGM-based import and SB-based export)

---

## ULIP APIs Relevant to VCN01

| ULIP API | Input | Returns | VCN01 Use |
|----------|-------|---------|-----------|
| **PCS/01** | IGM Number + `CHPOI03` | Full IGM cargo line data | Import Cargo Declaration auto-fill |
| **PCS/02** | SB Number + `CHPOE05` | Shipping Bill export data (basic) | Export Cargo Declaration auto-fill |
| **PCS/03** | SB Number + `CHPOE07` | Shipping Bill + rotation/LEO data | Export Cargo Declaration (extended) |
| PCS/04 | BOE Number | Bill of Entry import | Future: Customs clearance tracking |
| PCS/05 | BOE Number | BOE + out-of-charge data | Future: Customs clearance tracking |
| PCS/06 VESPRO | IMO Number | Vessel profile | VC01 (see other doc) |

---

## SECTION 1: Import (PCS/01 — IGM Number)

### ULIP PCS/01 Full Response Payload

When an IGM number is found, ULIP returns (per cargo line):

```json
{
  "custom_house_code": "INHZA6",
  "igm_no": "2272354",
  "igm_date": "...",
  "voyage_no": "...",
  "shipping_line_code": "...",
  "shipping_agent_code": "...",
  "port_of_arrival": "...",
  "expected_date_and_time_of_arrival": "...",
  "terminal_operator_code": "...",
  "cargo_imo_code": "...",
  "line_no": "...",
  "sub_line_no": "...",
  "bill_no": "...",
  "bill_date": "...",
  "port_of_loading": "...",
  "port_of_destination": "...",
  "nature_of_cargo": "...",
  "port_of_discharge": "...",
  "grossWeight": "...",
  "number_of_packages": "...",
  "goods_description": "...",
  "mode_of_transport": "...",
  "container_no": "...",
  "line_number": "...",
  "sub_line_number": "...",
  "container_seal_no": "...",
  "total_no_of_packages": "...",
  "container_weight": "...",
  "iso_code": "..."
}
```

---

### VCN01 Header — Import Alignment

| ULIP Field | VCN01 Field | DB Column | Status |
|------------|-------------|-----------|--------|
| `port_of_arrival` | Discharge Port | `discharge_port` | ✅ Aligned |
| `port_of_loading` | Load Port | `load_port` | ✅ Aligned |
| `shipping_agent_code` | Vessel Agent | `vessel_agent_name` | ⚠️ ULIP gives code, VCN01 stores name — needs mapping |
| `voyage_no` | *(not captured)* | — | ❌ Missing — should add to vcn_header |
| `shipping_line_code` | *(not captured)* | — | ❌ Missing — useful for vessel/agent identification |
| `expected_date_and_time_of_arrival` | ETA (in nominations sub-table) | `vcn_nominations.eta` | ✅ Aligned |
| `terminal_operator_code` | *(not captured)* | — | ℹ️ Low priority |
| `custom_house_code` | *(not captured)* | — | ℹ️ Low priority |

---

### VCN01 Import Cargo Declaration — Alignment

**Table:** `vcn_cargo_declaration`

| ULIP Field | VCN01 Field | DB Column | Status |
|------------|-------------|-----------|--------|
| `igm_no` | IGM Number | `igm_number` | ✅ Aligned |
| `igm_date` | IGM Date | `igm_date` | ✅ Aligned |
| `bill_no` | BL No | `bl_no` | ✅ Aligned |
| `bill_date` | BL Date | `bl_date` | ✅ Aligned |
| `grossWeight` | BL Quantity | `bl_quantity` | ✅ Aligned (weight = BL qty for bulk) |
| `nature_of_cargo` | Cargo Name | `cargo_name` | ✅ Aligned (lookup from master) |
| `line_no` | *(not captured)* | — | ❌ Missing — identifies specific cargo line in IGM |
| `sub_line_no` | *(not captured)* | — | ❌ Missing — needed for multi-line IGMs |
| `goods_description` | *(not captured)* | — | ⚠️ Useful for reference |
| `number_of_packages` | *(not captured)* | — | ⚠️ Useful for customs reconciliation |
| `container_no` | *(not captured)* | — | ℹ️ Only relevant for container cargo |
| `port_of_discharge` | *(in header)* | `vcn_header.discharge_port` | ✅ Captured at header level |
| `port_of_loading` | *(in header)* | `vcn_header.load_port` | ✅ Captured at header level |
| `mode_of_transport` | *(not captured)* | — | ℹ️ Low priority |
| customer_name | Customer | `customer_name` | ℹ️ Not in ULIP — manually entered |
| igm_manual_number | IGM Manual No | `igm_manual_number` | ℹ️ Internal only |

---

## SECTION 2: Export (PCS/02 + PCS/03 — Shipping Bill)

### ULIP PCS/02 Response Payload

```json
{
  "sbNo": "7005705",
  "sbDate": "05122020",
  "natureOfCargo": "C",
  "grossQuantity": 6547.0,
  "unitOfQuantity": "KGS",
  "totalNoOfPackages": "415",
  "portOfDestination": "PLGDY",
  "portOfOrigin": "INMUN1",
  "chaCode": "AGRPJ9989QCH003"
}
```

### ULIP PCS/03 Response Payload (Extended)

```json
{
  "sbNumber": "2405125",
  "sbDate": "14042020",
  "rotationNo": "193582",
  "rotationDate": "12042020",
  "leoDate": "15042020",
  "natureOfCargo": "C"
}
```

---

### VCN01 Export Cargo Declaration — Alignment

**Table:** `vcn_export_cargo_declaration`

| ULIP Field | VCN01 Field | DB Column | Status |
|------------|-------------|-----------|--------|
| `sbNo` / `sbNumber` | EGM/Shipping Bill No | `egm_shipping_bill_number` | ✅ Aligned |
| `sbDate` | EGM/Shipping Bill Date | `egm_shipping_bill_date` | ✅ Aligned |
| `natureOfCargo` | Cargo Name | `cargo_name` | ✅ Aligned |
| `grossQuantity` | BL Quantity | `bl_quantity` | ✅ Aligned |
| `unitOfQuantity` | Quantity UOM | `quantity_uom` | ✅ Aligned |
| `portOfDestination` | *(not in export cargo)* | — | ⚠️ Captured in header as `discharge_port` |
| `portOfOrigin` | *(not in export cargo)* | — | ⚠️ Captured in header as `load_port` |
| `chaCode` | *(not captured)* | — | ❌ Missing — CHA agent code |
| `totalNoOfPackages` | *(not captured)* | — | ⚠️ Useful for customs |
| `rotationNo` (PCS/03) | *(not captured)* | — | ❌ Missing — port rotation number |
| `rotationDate` (PCS/03) | *(not captured)* | — | ❌ Missing |
| `leoDate` (PCS/03) | *(not captured)* | — | ❌ Missing — Let Export Order date (critical for export) |
| `bl_no` | BL No | `bl_no` | ℹ️ Not in ULIP — manually entered |
| `bl_date` | BL Date | `bl_date` | ℹ️ Not in ULIP — manually entered |
| `customer_name` | Customer | `customer_name` | ℹ️ Not in ULIP — manually entered |

---

## SECTION 3: Summary of Gaps

### Fields Missing from VCN01 that ULIP can provide

#### HIGH PRIORITY — Add before ULIP integration

| Table | Missing Field | ULIP Source | Reason |
|-------|-------------|-------------|--------|
| `vcn_header` | `voyage_no` | PCS/01 `voyage_no` | Core vessel call identifier |
| `vcn_cargo_declaration` | `line_no` | PCS/01 `line_no` | Identifies specific cargo line in IGM |
| `vcn_cargo_declaration` | `sub_line_no` | PCS/01 `sub_line_no` | For multi-consignee IGMs |
| `vcn_export_cargo_declaration` | `leo_date` | PCS/03 `leoDate` | Let Export Order date — mandatory for export customs |
| `vcn_export_cargo_declaration` | `rotation_no` | PCS/03 `rotationNo` | Port rotation number |

#### MEDIUM PRIORITY — Useful for reconciliation

| Table | Missing Field | ULIP Source | Reason |
|-------|-------------|-------------|--------|
| `vcn_header` | `shipping_line_code` | PCS/01 `shipping_line_code` | Shipping line identifier |
| `vcn_cargo_declaration` | `number_of_packages` | PCS/01 `number_of_packages` | Customs verification |
| `vcn_cargo_declaration` | `goods_description` | PCS/01 `goods_description` | Cargo description for reference |
| `vcn_export_cargo_declaration` | `cha_code` | PCS/02 `chaCode` | Customs House Agent code |
| `vcn_export_cargo_declaration` | `total_packages` | PCS/02 `totalNoOfPackages` | Package count for customs |

#### LOW PRIORITY — Operational/context only

| Table | Missing Field | ULIP Source | Notes |
|-------|-------------|-------------|-------|
| `vcn_header` | `custom_house_code` | PCS/01 | Internal customs code |
| `vcn_header` | `terminal_operator_code` | PCS/01 | Port terminal ID |
| `vcn_cargo_declaration` | `container_no` | PCS/01 | Only for container cargo |
| `vcn_export_cargo_declaration` | `rotation_date` | PCS/03 | Accompanies rotation_no |

---

## SECTION 4: Fields Well-Aligned (No Changes Needed)

| VCN01 Area | Assessment |
|------------|-----------|
| IGM Number + Date in cargo declaration | ✅ Perfect match |
| BL No + BL Date | ✅ Perfect match |
| BL Quantity + UOM | ✅ Good match (grossWeight/grossQuantity) |
| EGM/SB Number + SB Date | ✅ Perfect match |
| Load Port / Discharge Port (header) | ✅ Mapped correctly |
| ETA in nominations | ✅ Maps to `expected_date_and_time_of_arrival` |
| Cargo Name | ✅ Maps to `nature_of_cargo` (via lookup) |
| Operation Type (Import/Export) | ✅ Drives which ULIP API to call |

---

## SECTION 5: Recommended Alembic Migrations (when ready to implement)

### Migration 1 — Add to vcn_header
```sql
ALTER TABLE vcn_header ADD COLUMN voyage_no VARCHAR(50);
ALTER TABLE vcn_header ADD COLUMN shipping_line_code VARCHAR(50);
```

### Migration 2 — Add to vcn_cargo_declaration (Import)
```sql
ALTER TABLE vcn_cargo_declaration ADD COLUMN line_no VARCHAR(20);
ALTER TABLE vcn_cargo_declaration ADD COLUMN sub_line_no VARCHAR(20);
ALTER TABLE vcn_cargo_declaration ADD COLUMN number_of_packages VARCHAR(20);
ALTER TABLE vcn_cargo_declaration ADD COLUMN goods_description TEXT;
```

### Migration 3 — Add to vcn_export_cargo_declaration (Export)
```sql
ALTER TABLE vcn_export_cargo_declaration ADD COLUMN rotation_no VARCHAR(20);
ALTER TABLE vcn_export_cargo_declaration ADD COLUMN rotation_date VARCHAR(20);
ALTER TABLE vcn_export_cargo_declaration ADD COLUMN leo_date VARCHAR(20);
ALTER TABLE vcn_export_cargo_declaration ADD COLUMN cha_code VARCHAR(50);
ALTER TABLE vcn_export_cargo_declaration ADD COLUMN total_packages VARCHAR(20);
```

> All new columns should be nullable so existing records are unaffected.

---

## SECTION 6: Integration Trigger Points in VCN01

When ULIP integration is built, the natural trigger points will be:

### Import flow
1. User creates VCN with Operation Type = **Import**
2. User opens **Cargo Declaration** sub-table
3. User enters **IGM Number** in a row → clicks **"Fetch from ULIP (PCS/01)"**
4. PORTMAN calls PCS/01 → returns cargo lines → auto-fills:
   - `igm_date`, `bl_no`, `bl_date`, `bl_quantity`, `nature_of_cargo`, `line_no`, `sub_line_no`
5. Also auto-fills header: `voyage_no`, `load_port`, `discharge_port`

### Export flow
1. User creates VCN with Operation Type = **Export**
2. User opens **Export Cargo Declaration** sub-table
3. User enters **SB Number** → clicks **"Fetch from ULIP (PCS/02 + PCS/03)"**
4. PORTMAN calls PCS/02 → fills: `sbDate`, `natureOfCargo`, `grossQuantity`, `unitOfQuantity`, `chaCode`
5. PORTMAN calls PCS/03 → fills: `rotationNo`, `rotationDate`, `leoDate`

---

## SECTION 7: Current Assessment

> **VCN01 is approximately 75% aligned with ULIP data for both Import and Export.**
>
> The core cargo identification fields (IGM/SB numbers, BL details, quantities, ports) are already captured.
> The main gaps are operational/customs-traceability fields (`voyage_no`, `line_no`, `leo_date`, `rotation_no`) that are important for Customs reconciliation but not for day-to-day port operations.
>
> **Recommendation:** Add the HIGH PRIORITY fields in the next migration cycle. They are nullable additions — zero impact on existing data or workflow — but will make ULIP auto-fill complete when integration goes live.
