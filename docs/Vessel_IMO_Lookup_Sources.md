# Vessel IMO Lookup — Free Sources & RPA Feasibility
**Date drafted:** 2026-02-18
**Purpose:** Research free/low-cost sources to auto-fetch vessel details by IMO number for VC01, as an alternative/fallback to ULIP VESPRO

---

## Quick Verdict

| Source | Cost | Fields | RPA Viable? | Recommendation |
|--------|------|--------|-------------|----------------|
| **Equasis** | Free (register) | Best — owner, manager, P&I, dimensions, ISM | ✅ Yes (session-based) | **#1 Pick** |
| **Marine Vessel Traffic** | Free | Owner, Manager, ISM, Flag, Type | ✅ Yes (URL pattern) | **#2 Pick** |
| **VesselFinder** | Free page / Paid API | Full particulars | ⚠️ Possible (anti-bot) | Fallback |
| **MarineTraffic** | Free page / Paid API | Full particulars + AIS | ❌ CAPTCHA | Avoid for RPA |
| **AllTrack.org** | Free | Basic (type, GT, built year) | ✅ Yes | Limited data |
| **ITF Seafarers Lookup** | Free | Name, IMO, Flag, Type, Company | ✅ Possibly | Niche use |
| **Datalastic API** | 50 req/month free | Full particulars | ✅ (API key) | Good for prod |
| **AISExplorer (PyPI)** | Free (library) | AIS + basic dims | ❌ CAPTCHA issues | Deprecated |

---

## 1. Equasis — BEST FREE SOURCE

**URL:** https://www.equasis.org
**Cost:** Free — just requires email registration
**Data from:** IMO / Classification societies / P&I clubs

### Fields available:
- Vessel Name, IMO Number, Flag, Call Sign, MMSI
- **Gross Tonnage (GT), Deadweight (DWT)**
- Year Built, Ship Type, Status
- **Registered Owner** (name + address)
- **ISM Manager** (safety management company)
- **Ship Manager / Technical Manager**
- **P&I Insurance** (club name + coverage period)
- **Classification Society** (DNV, Bureau Veritas, etc.)
- Port State Control (PSC) **inspection & deficiency history**
- Ownership/flag change **history**

### RPA Approach:
1. One-time registration with your port's email
2. RPA logs in with stored credentials (session cookie)
3. POST search with IMO number → scrape result page
4. Parse vessel particulars block

### Limitations:
- **No official API** — no bulk data export (max 20 ships saved)
- Terms of service: no bulk harvesting — but individual lookups per user action are fine
- Session expires — RPA needs to handle re-login

---

## 2. Marine Vessel Traffic — Good for ISM Data

**URL:** https://www.marinevesseltraffic.com
**Cost:** Free

### URL Pattern (from the example you shared):
```
https://www.marinevesseltraffic.com/ship-owner-manager-ism-data/{VESSEL-NAME}/{IMO}/{MMSI}
```
Example:
```
https://www.marinevesseltraffic.com/ship-owner-manager-ism-data/GANGA-K/9482110/419001227
```

### Fields available (from URL path structure + site):
- Vessel Name
- IMO Number
- MMSI
- **Ship Owner**
- **Ship Manager (ISM)**
- Flag
- Vessel Type
- Live position / last known port

### RPA Approach:
- Construct URL directly from IMO + vessel name (or just use IMO to search)
- GET request → parse the HTML page
- No login required for basic details
- **Returned 403 on direct fetch** — needs browser-based RPA (Playwright/Puppeteer) with realistic headers and delays

### IMO-only search page:
```
https://www.marinevesseltraffic.com/2013/06/imo-number-search.html
```
Enter IMO → redirects to vessel detail page → parse result

---

## 3. VesselFinder — Good Full Particulars

**URL:** https://www.vesselfinder.com
**Cost:** Free web pages / Paid API

### URL Pattern:
```
https://www.vesselfinder.com/vessels/details/{VESSEL-NAME-SLUG}-IMO-{IMO}
```
Example:
```
https://www.vesselfinder.com/vessels/details/GANGA-K-IMO-9482110
```

### Fields available:
- Name, IMO, MMSI, Call Sign, Flag
- Ship Type, Vessel Category
- GT (Gross Tonnage), DWT, LOA, Beam
- Year Built, Shipyard, Build Country
- Current Speed, Draught
- Owner / Operator (sometimes)

### RPA Approach:
- URL can be guessed from IMO alone once you have vessel name
- Anti-bot measures exist — use Playwright with human-like delays
- Paid **Vessel Particulars API** costs credits per lookup — worth considering for production

---

## 4. MarineTraffic — Data-rich but RPA-unfriendly

**URL:** https://www.marinetraffic.com
**Cost:** Free pages / Paid API (expensive)

### URL Pattern:
```
https://www.marinetraffic.com/en/ais/details/ships/shipid:{id}/mmsi:{mmsi}/imo:{IMO}/vessel:{NAME}
```

### Fields: Full particulars + live AIS position, voyage history, port calls

### RPA Feasibility: ❌
- Aggressive CAPTCHA protection on vessel detail pages
- Requires dynamic `shipid` (internal ID) — not derivable from IMO alone
- Official API is very expensive (paid credits per query)
- Not recommended for RPA

---

## 5. Datalastic API — Best Paid Option (Free Tier Available)

**URL:** https://datalastic.com
**Cost:** Free tier: ~50 lookups/month | Paid plans for more

### Endpoint:
```
GET https://api.datalastic.com/api/v0/vessel?api-key={KEY}&imo={IMO_NUMBER}
```

### Fields returned:
```json
{
  "uuid": "...",
  "name": "...",
  "imo": "9482110",
  "mmsi": "419001227",
  "call_sign": "...",
  "flag": "India",
  "type": "Bulk Carrier",
  "subtype": "...",
  "deadweight": 28000,
  "length": 169,
  "breadth": 27,
  "average_draught": 9.5,
  "maximum_draught": 10.2,
  "year_built": 2010,
  "homeport": "...",
  "status": "Active"
}
```

### RPA Approach:
- Clean REST API with API key — no RPA needed
- Free tier sufficient for manual "Fetch from ULIP" button trigger (one call per vessel creation)
- Python: `requests.get(url, params={'api-key': key, 'imo': imo_number})`

---

## 6. AllTrack.org — Simple Free Lookup

**URL:** https://alltrack.org/vessel-tracking
**Cost:** Free
**Fields:** IMO, Ship Type, Year Built, Vessel Size, GT
**RPA:** Straightforward — limited data

---

## Recommended Implementation Strategy for VC01

### Phase 1 — While waiting for ULIP approval (now)
Use **Datalastic free tier** (50 req/month) as the immediate solution:
- Get API key at datalastic.com (free registration)
- Simple GET request, no RPA needed
- Returns GT, DWT, LOA, Beam, Flag, Year Built, Type — covers most VC01 fields

### Phase 2 — For richer data (Owner/Manager)
Build **Equasis RPA** using Playwright:
- Equasis adds Owner, Manager, P&I, Classification Society — fields Datalastic may miss
- Store Equasis credentials in PORTMAN config
- Trigger on "Fetch Details" button alongside Datalastic call

### Phase 3 — When ULIP approved
Switch vessel particulars to **ULIP PCS/06 VESPRO** (IMO → vessel profile)
- Data is India-port-centric but authoritative for vessels calling your port
- Keep Datalastic/Equasis as fallback for vessels not in ULIP

---

## Python Implementation Sketch (Datalastic)

```python
# modules/VC01/vessel_lookup.py

import requests

DATALASTIC_KEY = "your_api_key_here"  # store in config/env

def fetch_by_imo(imo_number):
    """Fetch vessel particulars from Datalastic by IMO number."""
    try:
        res = requests.get(
            "https://api.datalastic.com/api/v0/vessel",
            params={"api-key": DATALASTIC_KEY, "imo": imo_number},
            timeout=10
        )
        if res.status_code == 200:
            data = res.json().get("data", {})
            return {
                "vessel_name":   data.get("name"),
                "call_sign":     data.get("call_sign"),
                "nationality":   data.get("flag"),
                "mmsi_num":      data.get("mmsi"),
                "gt":            data.get("gross_tonnage") or data.get("length"),  # map correctly after testing
                "dwt":           data.get("deadweight"),
                "loa":           data.get("length"),
                "beam":          data.get("breadth"),
                "year_of_built": data.get("year_built"),
            }
    except Exception as e:
        return {"error": str(e)}
    return {"error": "Not found"}
```

---

## Playwright RPA Sketch (Equasis — for Owner/Manager)

```python
# modules/VC01/equasis_rpa.py
# Requires: pip install playwright && playwright install chromium

from playwright.sync_api import sync_playwright

EQUASIS_USER = "your@email.com"
EQUASIS_PASS = "yourpassword"

def fetch_equasis_by_imo(imo_number):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        page.goto("https://www.equasis.org/EquasisWeb/public/HomePage")
        page.fill("#j_username", EQUASIS_USER)
        page.fill("#j_password", EQUASIS_PASS)
        page.click("input[type=submit]")
        page.wait_for_load_state("networkidle")

        # Search by IMO
        page.goto(f"https://www.equasis.org/EquasisWeb/restricted/ShipInfo?fs=Search&P_IMO={imo_number}")
        page.wait_for_load_state("networkidle")

        # Parse fields
        result = {
            "vessel_name":   page.inner_text(".shipName") if page.query_selector(".shipName") else None,
            "flag":          page.inner_text(".flag") if page.query_selector(".flag") else None,
            "gt":            page.inner_text(".grossTonnage") if page.query_selector(".grossTonnage") else None,
            # etc. — exact selectors to be confirmed by inspecting Equasis HTML
        }
        browser.close()
        return result
```
> **Note:** Equasis HTML selectors above are illustrative — confirm actual class names by inspecting the page after login.

---

## Summary Table — Fields by Source

| Field | Datalastic | Equasis | Marine Vessel Traffic | ULIP VESPRO |
|-------|-----------|---------|----------------------|-------------|
| Vessel Name | ✅ | ✅ | ✅ | ✅ |
| Flag | ✅ | ✅ | ✅ | ✅ |
| Call Sign | ✅ | ✅ | ✅ | ✅ |
| MMSI | ✅ | ✅ | ✅ | Maybe |
| GT (Gross Tonnage) | ✅ | ✅ | ✅ | ✅ |
| DWT | ✅ | ✅ | ✅ | ✅ |
| LOA | ✅ | ❌ | ❌ | ✅ |
| Beam | ✅ | ❌ | ❌ | ✅ |
| Year Built | ✅ | ✅ | ✅ | ✅ |
| Ship Type | ✅ | ✅ | ✅ | ✅ |
| Registered Owner | ❌ | ✅ | ✅ | ❌ |
| Ship Manager | ❌ | ✅ | ✅ | ❌ |
| ISM Manager | ❌ | ✅ | ✅ | ❌ |
| P&I Club | ❌ | ✅ | ❌ | ❌ |
| Classification Society | ❌ | ✅ | ❌ | ❌ |
| PSC Inspection History | ❌ | ✅ | ❌ | ❌ |
| Requires Login | API key | Email reg | No | ULIP account |
| RPA needed? | No (REST API) | Yes (session) | Yes (browser) | No (REST API) |
