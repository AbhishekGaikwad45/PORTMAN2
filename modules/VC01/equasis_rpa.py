"""
Equasis Headless RPA — Fetch vessel particulars by IMO number.

Setup:
    pip install selenium webdriver-manager

Credentials (set ONE of these ways):
    1. Environment variables (recommended):
           set EQUASIS_USER=your@email.com
           set EQUASIS_PASS=yourpassword

    2. PORTMAN module config — store as VC01 config keys
           equasis_user  /  equasis_pass

Flow:
    Login → Home page search → Search results table
    → Submit formShip → Ship detail page → parse fields
"""

import os
import time
import logging
import re

logger = logging.getLogger(__name__)

EQUASIS_BASE = "https://www.equasis.org/EquasisWeb"

# ── Singleton browser state ────────────────────────────────────────────────────
_driver = None
_logged_in = False


def set_credentials(user, password):
    """Override credentials at runtime (e.g. from DB config)."""
    global EQUASIS_USER, EQUASIS_PASS
    EQUASIS_USER = user
    EQUASIS_PASS = password


EQUASIS_USER = os.environ.get("EQUASIS_USER", "")
EQUASIS_PASS = os.environ.get("EQUASIS_PASS", "")


# ── Driver management ──────────────────────────────────────────────────────────

def _get_driver():
    global _driver
    if _driver is not None:
        try:
            _ = _driver.title  # ping to check alive
            return _driver
        except Exception:
            _driver = None

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    _driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )
    _driver.set_page_load_timeout(30)
    logger.info("Equasis: Chrome driver started")
    return _driver


# ── Login ──────────────────────────────────────────────────────────────────────

def _login(driver):
    """
    Login to Equasis.
    Form fields confirmed from HTML:
        name="j_email"    (email)
        name="j_password" (password)
        name="submit"     type="submit" value="Login"
    Form action: ../authen/HomePage?fs=HomePage
    """
    global _logged_in
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    logger.info("Equasis: navigating to login page")
    driver.get(f"{EQUASIS_BASE}/public/HomePage")

    wait = WebDriverWait(driver, 15)
    wait.until(EC.presence_of_element_located((By.NAME, "j_email")))

    driver.find_element(By.NAME, "j_email").clear()
    driver.find_element(By.NAME, "j_email").send_keys(EQUASIS_USER)
    driver.find_element(By.NAME, "j_password").clear()
    driver.find_element(By.NAME, "j_password").send_keys(EQUASIS_PASS)
    driver.find_element(By.CSS_SELECTOR, "input[name='submit'][type='submit']").click()

    # Wait until the logged-in home page loads
    # Confirmed: after login the #access section gets class "connected"
    try:
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#access.connected, #P_ENTREE_HOME")
        ))
        _logged_in = True
        logger.info("Equasis: login successful")
    except Exception:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "invalid" in body or "incorrect" in body or "error" in body:
            raise RuntimeError("Equasis login failed — check credentials (EQUASIS_USER / EQUASIS_PASS)")
        _logged_in = True  # may have logged in without matching the exact selector
        logger.warning("Equasis: login selector not found, assuming success")


def _ensure_session(driver):
    """Ensure we are logged in; re-login if session expired."""
    global _logged_in
    if not _logged_in:
        _login(driver)
        return

    # Quick session check — if redirected to public page, re-login
    driver.get(f"{EQUASIS_BASE}/restricted/ShipSubcription?fs=HomePage")
    time.sleep(0.5)
    if "public" in driver.current_url or "login" in driver.current_url.lower():
        logger.info("Equasis: session expired, re-logging in")
        _logged_in = False
        _login(driver)


# ── Search & parse ─────────────────────────────────────────────────────────────

def _search_and_get_basic(driver, imo_number):
    """
    Submit home-page search form with the IMO number.
    Returns basic fields from the search result table:
      vessel_name, gt, vessel_type_name, year_of_built, nationality
    Also returns True/False on whether the vessel was found.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    # Home page after login has the search form
    driver.get(f"{EQUASIS_BASE}/public/HomePage")
    wait = WebDriverWait(driver, 15)

    # Wait for the logged-in search form: input#P_ENTREE_HOME
    wait.until(EC.presence_of_element_located((By.ID, "P_ENTREE_HOME")))

    search_box = driver.find_element(By.ID, "P_ENTREE_HOME")
    search_box.clear()
    search_box.send_keys(imo_number)

    # Make sure only "Ship" is checked (uncheck Company if checked)
    try:
        company_cb = driver.find_element(By.ID, "checkbox-company")
        if company_cb.is_selected():
            company_cb.click()
    except Exception:
        pass

    # Submit search form (id="searchForm")
    driver.find_element(By.CSS_SELECTOR, "#searchForm button[type='submit']").click()

    # Wait for results section to appear
    wait.until(EC.visibility_of_element_located((By.ID, "resultShip")))
    time.sleep(0.4)

    result_section = driver.find_element(By.ID, "resultShip")
    page_text = result_section.text.strip()

    if not page_text or "no result" in page_text.lower():
        return None, False

    # Parse the results table (desktop rows, class hidden-sm hidden-xs)
    # Table headers: IMO number | Name of ship | Gross tonnage | Type of ship | Year of build | Flag
    basic = {}
    try:
        rows = result_section.find_elements(
            By.CSS_SELECTOR, "tbody tr.hidden-sm.hidden-xs"
        )
        if rows:
            row = rows[0]
            cells = row.find_elements(By.TAG_NAME, "th") + row.find_elements(By.TAG_NAME, "td")
            # cells[0]=IMO, cells[1]=Name, cells[2]=GT, cells[3]=Type, cells[4]=Year, cells[5]=Flag
            if len(cells) >= 6:
                basic["vessel_name"]     = cells[1].text.strip()
                basic["gt"]              = _clean_num(cells[2].text.strip())
                basic["vessel_type_name"]= cells[3].text.strip()
                basic["year_of_built"]   = _clean_num(cells[4].text.strip())
                # Flag cell: "India\n(IND)" → take first line
                flag_text = cells[5].text.strip().split("\n")[0].strip()
                basic["nationality"] = flag_text
    except Exception as e:
        logger.warning(f"Equasis: could not parse search result table — {e}")

    return basic, True


def _navigate_to_ship_detail(driver, imo_number):
    """
    From the search results page, submit the formShip to open ship detail.
    Uses JS to set P_IMO and submit (mirrors the onclick behaviour).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        driver.execute_script(
            f"document.formShip.P_IMO.value='{imo_number}'; document.formShip.submit();"
        )
    except Exception:
        # Fallback: click the IMO link directly
        link = driver.find_element(
            By.XPATH,
            f"//a[contains(@onclick, \"{imo_number}\")]"
        )
        link.click()

    wait = WebDriverWait(driver, 15)
    # Ship detail page contains at minimum a table with vessel info
    wait.until(EC.url_contains("ShipInfo"))
    time.sleep(0.8)


def _parse_ship_detail(driver):
    """
    Parse the ship detail page on Equasis.
    The page has multiple tables/sections with key-value pairs.
    Returns a dict of field_label (lowercased) → value.
    """
    from selenium.webdriver.common.by import By

    raw = {}

    # Pull all table rows with two or more cells
    tables = driver.find_elements(By.TAG_NAME, "table")
    for tbl in tables:
        rows = tbl.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            # Try th + td pattern (label + value)
            ths = row.find_elements(By.TAG_NAME, "th")
            tds = row.find_elements(By.TAG_NAME, "td")
            if ths and tds:
                label = ths[0].text.strip().lower().rstrip(":")
                value = tds[0].text.strip()
                if label and value:
                    raw[label] = value
            elif len(tds) >= 2:
                label = tds[0].text.strip().lower().rstrip(":")
                value = tds[1].text.strip()
                if label and value:
                    raw[label] = value

    # Also try dl/dt/dd definitions
    dts = driver.find_elements(By.TAG_NAME, "dt")
    dds = driver.find_elements(By.TAG_NAME, "dd")
    for dt, dd in zip(dts, dds):
        label = dt.text.strip().lower().rstrip(":")
        value = dd.text.strip()
        if label and value:
            raw[label] = value

    return raw


def _get(raw, *keys):
    """Try multiple label variants, return first match."""
    for k in keys:
        if k in raw:
            return raw[k]
    return None


def _clean_num(val):
    if not val:
        return None
    val = str(val)
    cleaned = re.sub(r"[^\d.]", "", val.replace(",", ""))
    if not cleaned:
        return None
    try:
        return int(cleaned) if "." not in cleaned else float(cleaned)
    except Exception:
        return None


def _build_vc01_result(basic, detail_raw):
    """Merge basic (search result) and detail page data into VC01 fields."""
    result = dict(basic or {})

    # Map detail page labels → VC01 field names
    mappings = {
        "nationality":   ["flag", "flag of registry", "flag state", "country of registry"],
        "call_sign":     ["call sign", "callsign", "radio call sign", "call letters"],
        "mmsi_num":      ["mmsi", "mmsi number", "mmsi no."],
        "gt":            ["gross tonnage", "gt", "gross registered tonnage", "grt"],
        "dwt":           ["deadweight", "dwt", "dead weight", "summer deadweight", "deadweight tonnage"],
        "loa":           ["length", "loa", "length overall", "length o.a.", "length (m)"],
        "beam":          ["breadth", "beam", "breadth moulded", "width"],
        "year_of_built": ["year of build", "year built", "build year", "year of construction",
                          "date of build", "keel laid"],
        "vessel_name":   ["name", "ship name", "vessel name"],
    }

    for vc01_field, labels in mappings.items():
        val = _get(detail_raw, *labels)
        if val and vc01_field not in result:
            if vc01_field in ("gt", "dwt", "loa", "beam", "year_of_built"):
                result[vc01_field] = _clean_num(val)
            else:
                # Take only first line for multi-line values (e.g. flag "India\n(IND)")
                result[vc01_field] = val.split("\n")[0].strip()

    # Remove None / empty
    result = {k: v for k, v in result.items() if v is not None and v != ""}

    # Attach raw for debug
    result["_raw"] = detail_raw
    return result


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_by_imo(imo_number, equasis_user=None, equasis_pass=None):
    """
    Fetch vessel particulars from Equasis by IMO number.

    Args:
        imo_number   : 7-digit IMO number (str or int)
        equasis_user : override env var EQUASIS_USER (optional)
        equasis_pass : override env var EQUASIS_PASS (optional)

    Returns:
        dict with keys matching VC01 column names, e.g.:
            vessel_name, nationality, call_sign, mmsi_num,
            gt, dwt, loa, beam, year_of_built, vessel_type_name
        OR {"error": "message"} on failure.
    """
    global _logged_in, EQUASIS_USER, EQUASIS_PASS

    if equasis_user:
        EQUASIS_USER = equasis_user
    if equasis_pass:
        EQUASIS_PASS = equasis_pass

    if not EQUASIS_USER or not EQUASIS_PASS:
        return {"error": "Equasis credentials not configured. Set EQUASIS_USER and EQUASIS_PASS."}

    imo_number = str(imo_number).strip()
    if not re.match(r"^\d{7}$", imo_number):
        return {"error": f"Invalid IMO number '{imo_number}' — must be exactly 7 digits."}

    try:
        driver = _get_driver()
        _ensure_session(driver)

        # Step 1: Search by IMO → get basic fields + navigate to detail
        basic, found = _search_and_get_basic(driver, imo_number)
        if not found:
            return {"error": f"IMO {imo_number} not found in Equasis."}

        # Step 2: Navigate to full ship detail page
        _navigate_to_ship_detail(driver, imo_number)

        # Step 3: Parse detail page
        detail_raw = _parse_ship_detail(driver)

        # Step 4: Merge and map to VC01 fields
        result = _build_vc01_result(basic, detail_raw)

        fields_found = [k for k in result if not k.startswith("_")]
        logger.info(f"Equasis: IMO {imo_number} → fields: {fields_found}")
        return result

    except Exception as e:
        logger.error(f"Equasis RPA error for IMO {imo_number}: {e}", exc_info=True)
        _logged_in = False  # Force re-login next time
        return {"error": str(e)}


def close():
    """Quit the browser. Call on app shutdown."""
    global _driver, _logged_in
    if _driver:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
        _logged_in = False
