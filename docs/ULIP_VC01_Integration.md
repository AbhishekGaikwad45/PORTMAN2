# ULIP Integration — Vessel Auto-Fill for VC01

**Date drafted:** 2026-02-18
**Status:** Pending ULIP account approval
**ULIP Doc reference:** ULIP Integration Requirement Document v3.0 (NLDSL, 30/09/2024)

---

## Goal

When a user creates a new vessel in **VC01 (Vessel Master)**, they should be able to enter just the **IMO number** and click **"Fetch from ULIP"** to auto-populate vessel details from the ULIP PCS API — instead of manually typing every field.

---

## Which ULIP API to Use

Out of the 6 APIs in the document:

| API | Input | Purpose |
|-----|-------|---------|
| PCS/01 | IGM Number | Import cargo data |
| PCS/02 | Shipping Bill Number | Export SB data |
| PCS/03 | Shipping Bill Number | Export rotation data |
| PCS/04 | BOE Number | Bill of Entry import data |
| PCS/05 | BOE Number | BOE import data (extended) |
| **PCS/06** | **MSG_NAME + MSG_IDENTIFIER** | **Multi-purpose — supports IMO** |

### Use PCS/06 with MSG_NAME = "VESPRO"

```
POST https://www.ulip.dpiit.gov.in/ulip/v1.0.0/PCS/06

Headers:
  Authorization: Bearer <token>
  Content-Type: application/json
  Accept: application/json

Body:
{
  "MSG_NAME": "MSG_IDENTIFIER",
  "MSG_IDENTIFIER": "<IMO_NUMBER>"
}
```

> Note: For staging/testing use:
> `https://www.ulipstaging.dpiit.gov.in/ulip/v1.0.0/PCS/06`

### Other PCS/06 message types that use IMO number

| MSG_NAME | MSG_IDENTIFIER | Returns |
|----------|---------------|---------|
| **VESPRO** | IMO Number | Vessel Profile (name, flag, GT, DWT, LOA, etc.) |
| **CALINV** | IMO Number | Vessel Call / Invitation data |

---

## Authentication Flow

ULIP uses Bearer token auth with 30-minute session expiry.

### Step 1 — Get Token (first time / after expiry)

```
POST https://www.ulip.dpiit.gov.in/ulip/v1.0.0/user/login
Headers:
  accept: application/json
  content-type: application/json
Body:
{
  "username": "<your_ulip_username>",
  "password": "<your_ulip_password>"
}
```

Response gives a Bearer token. Cache this token server-side.

### Step 2 — Use token for API calls

Pass as: `Authorization: Bearer <token>`

Token expires after **30 minutes of inactivity**. Re-authenticate when a 401/403 is returned.

---

## Fields: VC01 vs VESPRO Response

VC01 currently stores these vessel fields. VESPRO should return most of them:

| VC01 Field | DB Column | Expected from VESPRO? |
|------------|-----------|----------------------|
| Vessel Name | vessel_name | ✅ Yes |
| IMO Number | imo_num | ✅ (used as input) |
| Call Sign | call_sign | ✅ Yes |
| Flag / Nationality | nationality | ✅ Yes |
| MMSI Number | mmsi_num | Possibly |
| Gross Tonnage (GT) | gt | ✅ Yes |
| DWT | dwt | ✅ Yes |
| LOA | loa | ✅ Yes |
| Beam | beam | Possibly |
| No. of Hatches | no_of_hatches | Unlikely (port-specific) |
| No. of Holds | no_of_holds | Unlikely (port-specific) |
| Year of Build | year_of_built | ✅ Yes |
| Vessel Type | vessel_type_name | Possibly (type/category) |

> **Note:** The exact VESPRO response fields are not fully listed in the PDF (they appear as Word doc attachments). Confirm exact field names after ULIP account is approved and you can test against staging.

---

## Implementation Plan

### Backend — `modules/VC01/`

#### 1. Add ULIP credentials to config

Store in DB module config or environment variables (NOT hardcoded):
- `ULIP_USERNAME`
- `ULIP_PASSWORD`
- `ULIP_TOKEN` (cached, with expiry timestamp)

#### 2. New file: `modules/VC01/ulip.py`

```python
# Helper to manage ULIP auth token and API calls

ULIP_BASE = "https://www.ulip.dpiit.gov.in/ulip/v1.0.0"
# ULIP_BASE = "https://www.ulipstaging.dpiit.gov.in/ulip/v1.0.0"  # staging

_token = None
_token_expiry = None

def get_token():
    """Get cached token or fetch a new one."""
    # Check if cached token is still valid
    # POST to /user/login with username/password
    # Cache and return token

def fetch_vessel_by_imo(imo_number):
    """Call PCS/06 VESPRO with IMO number."""
    token = get_token()
    # POST to /PCS/06 with MSG_NAME=VESPRO, MSG_IDENTIFIER=imo_number
    # Parse and return vessel fields
    # Return dict with: vessel_name, call_sign, nationality, gt, dwt, loa, beam, year_of_built, mmsi_num
```

#### 3. New endpoint in `modules/VC01/views.py`

```python
@bp.route('/api/module/VC01/ulip_lookup', methods=['POST'])
@login_required
def ulip_lookup():
    imo = request.json.get('imo_num')
    if not imo:
        return jsonify({'error': 'IMO number required'}), 400
    result = ulip.fetch_vessel_by_imo(imo)
    return jsonify(result)
```

### Frontend — `modules/VC01/vc01.html`

#### 1. Add "Fetch from ULIP" button to toolbar

Only show when a row is selected/being edited and IMO field is filled.

#### 2. JS function

```javascript
async function fetchFromULIP() {
    const rows = table.getSelectedRows();
    if (!rows.length) { alert('Select a row first'); return; }
    const row = rows[0];
    const imo = row.getData().imo_num;
    if (!imo) { alert('Enter IMO number first'); return; }

    const res = await fetch('/api/module/VC01/ulip_lookup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({imo_num: imo})
    });
    const data = await res.json();
    if (data.error) { alert('ULIP error: ' + data.error); return; }

    // Auto-fill the row fields
    row.update({
        vessel_name: data.vessel_name || row.getData().vessel_name,
        call_sign: data.call_sign || row.getData().call_sign,
        nationality: data.nationality || row.getData().nationality,
        mmsi_num: data.mmsi_num || row.getData().mmsi_num,
        gt: data.gt || row.getData().gt,
        dwt: data.dwt || row.getData().dwt,
        loa: data.loa || row.getData().loa,
        beam: data.beam || row.getData().beam,
        year_of_built: data.year_of_built || row.getData().year_of_built,
    });
    alert('Vessel details fetched from ULIP. Review and Save.');
}
```

---

## Caveats / Limitations

1. **Port-centric data**: ULIP pulls from Indian PCS/Customs. Vessel must have previously called an Indian port. Brand-new vessels or foreign-only vessels may not have records.

2. **Token expiry**: Token expires after 30 min of inactivity. Backend must handle 401 responses by re-authenticating automatically.

3. **Staging first**: Test against `ulipstaging.dpiit.gov.in` before going to production. The staging credentials may differ from production.

4. **VESPRO field mapping**: The exact JSON field names in the VESPRO response are not documented in the PDF (the response examples are Word doc attachments). Need to test with a real IMO number on staging to discover actual field names.

5. **Partial fill**: Not all VC01 fields may be available from ULIP (e.g., No. of Hatches, No. of Holds). Those should remain manually editable.

---

## Next Steps (when ULIP account is approved)

- [ ] Log into ULIP portal and get API credentials
- [ ] Test PCS/06 VESPRO call on **staging** with a known IMO number (e.g., a vessel that has called Mumbai/Chennai port)
- [ ] Note exact JSON field names from the response
- [ ] Implement `ulip.py` helper with token caching
- [ ] Add `/api/module/VC01/ulip_lookup` endpoint
- [ ] Add "Fetch from ULIP" button in vc01.html
- [ ] Test end-to-end on staging, then switch to production URL

---

## Reference URLs

- Production API base: `https://www.ulip.dpiit.gov.in/ulip/v1.0.0/`
- Staging API base: `https://www.ulipstaging.dpiit.gov.in/ulip/v1.0.0/`
- Login endpoint: `POST /user/login`
- Vessel lookup: `POST /PCS/06`
