# UX: Dirty Tracking, Autosave & Server-side Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add unsaved-changes warnings, per-section dirty tracking, 30-second autosave, and Redmine-style server-side filtering to VCN01, LDUD01, and MBC01.

**Architecture:**
- Dirty state tracked in `dirtySubSections` object keyed by section name; Tabulator `cellEdited` events mark sections dirty; `saveSubTable()` clears on success.
- Autosave via `setInterval(autoSave, 30000)`; rows that fail show ⚠ via `_autosave_error` field + rowFormatter; sub-sections saved silently if dirty.
- Filters sent as JSON in `?filters=` query param; backend `get_data()` builds parameterised `WHERE` clause dynamically; Tabulator `ajaxParams` function injects current filters on every fetch.

**Tech Stack:** Flask/PostgreSQL (backend), Tabulator 6.3.0 (frontend), Vanilla JS, Jinja2 templates.

---

## Shared Reference: Module Mapping

| Module | HTML file | model.py | views.py | header table | id var |
|--------|-----------|----------|----------|--------------|--------|
| VCN01 | `modules/VCN01/vcn01.html` | `modules/VCN01/model.py` | `modules/VCN01/views.py` | `vcn_header` | `currentVcnId` |
| MBC01 | `modules/MBC01/mbc01.html` | `modules/MBC01/model.py` | `modules/MBC01/views.py` | `mbc_header` | `currentMbcId` |
| LDUD01 | `modules/LDUD01/ldud01.html` | `modules/LDUD01/model.py` | `modules/LDUD01/views.py` | `ldud_header` | `currentLdudId` |

---

## Task 1: Backend — Filter Support in All 3 Models + Views

**Files:**
- Modify: `modules/VCN01/model.py:28-36` (get_data)
- Modify: `modules/VCN01/views.py:30-36` (get_data route)
- Modify: `modules/MBC01/model.py:20-28` (get_data)
- Modify: `modules/MBC01/views.py` (get_data route)
- Modify: `modules/LDUD01/model.py:55-62` (get_data)
- Modify: `modules/LDUD01/views.py` (get_data route)

**Step 1: Replace `get_data()` in VCN01 model.py**

```python
import json

def get_data(page=1, size=20, filters=None):
    conn = get_db()
    cur = get_cursor(conn)

    where_clauses, params = [], []
    for f in (filters or []):
        field = f.get('field', '')
        # Allowlist to prevent injection
        allowed = {'operation_type','vcn_doc_num','vessel_name','vessel_agent_name',
                   'cargo_type','doc_status','doc_date','importer_exporter_name',
                   'customer_name','load_port','discharge_port'}
        if field not in allowed:
            continue
        ftype = f.get('type')
        if ftype == 'contains' and f.get('value'):
            where_clauses.append(f"{field} ILIKE %s")
            params.append(f"%{f['value']}%")
        elif ftype == 'multi' and f.get('values'):
            ph = ','.join(['%s'] * len(f['values']))
            where_clauses.append(f"{field} IN ({ph})")
            params.extend(f['values'])
        elif ftype == 'range':
            if f.get('from'):
                where_clauses.append(f"{field} >= %s")
                params.append(f['from'])
            if f.get('to'):
                where_clauses.append(f"{field} <= %s")
                params.append(f['to'])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    cur.execute(f'SELECT COUNT(*) FROM vcn_header {where_sql}', params)
    total = cur.fetchone()['count']
    cur.execute(f'SELECT * FROM vcn_header {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s',
                params + [size, (page - 1) * size])
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows], total
```

**Step 2: Replace `get_data` view in VCN01 views.py**

```python
import json as json_lib

@bp.route('/api/module/VCN01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    try:
        filters = json_lib.loads(request.args.get('filters', '[]'))
    except Exception:
        filters = []
    data, total = model.get_data(page, size, filters)
    return jsonify({'data': data, 'last_page': (total + size - 1) // size, 'total': total})
```

**Step 3: Apply same pattern for MBC01 model.py**

Allowed fields for MBC01:
```python
allowed = {'operation_type','doc_num','mbc_name','cargo_type','doc_status',
           'doc_date','bl_quantity','doc_series'}
```
Table name: `mbc_header`

**Step 4: Apply same pattern for LDUD01 model.py**

Allowed fields for LDUD01:
```python
allowed = {'doc_num','vessel_name','doc_status','doc_date','vcn_doc_num',
           'operation_type','cargo_type'}
```
Table name: `ldud_header`

Note: LDUD01 `get_data` uses a JOIN query — wrap the WHERE clause around the full SELECT.
Current LDUD01 get_data (check line 55-62): simple `SELECT * FROM ldud_header`. Apply same pattern.

**Step 5: Update MBC01 and LDUD01 views.py get_data routes** — same pattern as VCN01.

**Step 6: Test**

```bash
curl "http://localhost:5000/api/module/VCN01/data?filters=%5B%7B%22field%22%3A%22doc_status%22%2C%22type%22%3A%22multi%22%2C%22values%22%3A%5B%22Draft%22%5D%7D%5D"
# Expected: JSON with only Draft rows
```

---

## Task 2: CSS — Shared Styles for All 3 Modules

**Files:** `modules/VCN01/vcn01.html`, `modules/MBC01/mbc01.html`, `modules/LDUD01/ldud01.html`

**Step 1: Add to `{% block head %}` style section in each module**

```css
/* Dirty section indicator */
.sub-section-header.dirty-section::after {
    content: ' ●';
    color: #e53e3e;
    font-size: 12px;
    margin-left: 4px;
}

/* Unsaved warning modal */
.unsaved-modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 19999;
    align-items: center;
    justify-content: center;
}
.unsaved-modal-overlay.active { display: flex; }
.unsaved-modal-box {
    background: white;
    border-radius: 8px;
    padding: 20px 24px;
    max-width: 380px;
    width: 90%;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.dark-theme .unsaved-modal-box { background: #1e293b; color: #e2e8f0; }
.unsaved-modal-box h4 { margin: 0 0 8px; font-size: 15px; }
.unsaved-modal-box ul { margin: 0 0 16px; padding-left: 18px; font-size: 13px; }
.unsaved-modal-actions { display: flex; gap: 8px; justify-content: flex-end; }

/* Header unsaved banner */
.unsaved-banner {
    display: none;
    background: #fffbeb;
    border: 1px solid #f6e05e;
    color: #744210;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
    border-radius: 4px;
    align-items: center;
    gap: 8px;
}
.unsaved-banner.visible { display: flex; }

/* Autosave toast */
.autosave-toast {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #2d3748;
    color: white;
    padding: 10px 16px;
    border-radius: 6px;
    font-size: 12px;
    z-index: 99999;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
}
.autosave-toast.show { opacity: 1; }

/* Filter panel */
.filter-panel {
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 8px;
}
.dark-theme .filter-panel { background: #1e293b; border-color: #334155; }
.filter-row {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 6px;
    flex-wrap: wrap;
}
.filter-col-select, .filter-text-input, .filter-from, .filter-to {
    padding: 4px 8px;
    border: 1px solid #cbd5e0;
    border-radius: 4px;
    font-size: 12px;
    background: white;
}
.dark-theme .filter-col-select,
.dark-theme .filter-text-input,
.dark-theme .filter-from,
.dark-theme .filter-to { background: #0f172a; color: #e2e8f0; border-color: #334155; }
.filter-multi-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
}
.filter-multi-list label { display: flex; gap: 4px; align-items: center; font-size: 12px; }
.filter-remove {
    background: none;
    border: none;
    color: #e53e3e;
    cursor: pointer;
    font-size: 16px;
    padding: 0 4px;
    line-height: 1;
}
.filter-actions { display: flex; gap: 8px; margin-top: 6px; }
.btn-filter-apply { background: #3182ce; color: white; border: none; padding: 5px 14px; border-radius: 4px; font-size: 12px; cursor: pointer; }
.btn-filter-clear { background: #e2e8f0; color: #2d3748; border: none; padding: 5px 14px; border-radius: 4px; font-size: 12px; cursor: pointer; }
```

---

## Task 3: HTML — Add Modal + Filter Panel HTML to Each Module

**Files:** `modules/VCN01/vcn01.html`, `modules/MBC01/mbc01.html`, `modules/LDUD01/ldud01.html`

**Step 1: In each module, find `{% block content %}`. After the toolbar `<div class="toolbar">...</div>`, add:**

```html
<!-- Header dirty banner -->
<div id="unsavedBanner" class="unsaved-banner">
    ⚠ You have unsaved header changes — <button class="btn btn-save" onclick="saveAll()" style="margin:0;padding:3px 10px;font-size:12px;">Save Now</button>
</div>

<!-- Filter panel -->
<div style="margin-bottom:4px;">
    <button class="btn" style="font-size:12px;padding:4px 12px;" onclick="toggleFilterPanel()">⚙ Filters <span id="filterBadge" style="display:none;background:#3182ce;color:white;border-radius:10px;padding:1px 6px;font-size:11px;margin-left:4px;">0</span></button>
</div>
<div id="filterPanel" class="filter-panel" style="display:none;">
    <div id="filterRows"></div>
    <div class="filter-actions">
        <button class="btn-filter-apply" onclick="addFilterRow()">+ Add Filter</button>
        <button class="btn-filter-apply" onclick="applyFilters()">Apply</button>
        <button class="btn-filter-clear" onclick="clearFilters()">Clear All</button>
    </div>
</div>
```

**Step 2: In `#detailsModal`, update the modal header to add dirty badge. Find:**
```html
<h3 id="modalTitle">VCN Details</h3>
```
Replace with:
```html
<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <h3 id="modalTitle" style="margin:0;">VCN Details</h3>
    <span id="modalDirtyBadge" style="display:none;background:#fed7d7;color:#c53030;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;">⚠ Unsaved changes</span>
</div>
```
(MBC01: "MBC Details", LDUD01: "LDUD Details" — adjust as appropriate, or keep generic)

**Step 3: Add unsaved-changes warning modal HTML** (before `{% endblock %}` content, after the existing rejectModal or detailsModal):

```html
<!-- Unsaved Changes Warning Modal -->
<div id="unsavedModal" class="unsaved-modal-overlay">
    <div class="unsaved-modal-box">
        <h4>⚠ Unsaved Changes</h4>
        <p style="font-size:13px;margin:0 0 8px;">The following sections have unsaved changes:</p>
        <ul id="unsavedSectionList"></ul>
        <div class="unsaved-modal-actions">
            <button onclick="unsavedGoBack()" style="padding:6px 14px;border:1px solid #cbd5e0;background:white;border-radius:4px;cursor:pointer;font-size:13px;">Go Back</button>
            <button onclick="unsavedDiscard()" style="padding:6px 14px;background:#e53e3e;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px;">Discard & Close</button>
            <button onclick="unsavedSaveAll()" style="padding:6px 14px;background:#38a169;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px;font-weight:600;">Save All & Close</button>
        </div>
    </div>
</div>

<!-- Autosave Toast -->
<div id="autosaveToast" class="autosave-toast"></div>
```

---

## Task 4: JS — Dirty Tracking + Unsaved Warning (VCN01)

**File:** `modules/VCN01/vcn01.html`

**Step 1: Add state variables** near the top of `{% block scripts %}` (after existing `let subTables = {}; let currentVcnId = null;`):

```javascript
// Dirty tracking
let dirtySubSections = {};   // { 'nominations': true, 'cargo': false, ... }
let pendingClose = false;    // true when close was intercepted for warning
```

**Step 2: Add helper functions** (add after `showStatus()` function):

```javascript
function markDirty(section) {
    dirtySubSections[section] = true;
    const header = document.querySelector(`[data-section="${section}"]`);
    if (header) header.classList.add('dirty-section');
    updateModalDirtyBadge();
}

function clearDirty(section) {
    dirtySubSections[section] = false;
    const header = document.querySelector(`[data-section="${section}"]`);
    if (header) header.classList.remove('dirty-section');
    updateModalDirtyBadge();
}

function clearAllDirty() {
    dirtySubSections = {};
    document.querySelectorAll('.sub-section-header.dirty-section').forEach(el => el.classList.remove('dirty-section'));
    updateModalDirtyBadge();
}

function updateModalDirtyBadge() {
    const hasDirty = Object.values(dirtySubSections).some(Boolean);
    const badge = document.getElementById('modalDirtyBadge');
    if (badge) badge.style.display = hasDirty ? 'inline-block' : 'none';
}

function getDirtySections() {
    return Object.entries(dirtySubSections).filter(([,v]) => v).map(([k]) => k);
}
```

**Step 3: Mark section headers with `data-section` attribute**

In the `openDetailsModal()` HTML template strings, each `.sub-section-header` `<span>` needs a sibling or parent with `data-section`. The cleanest approach: add `data-section="nominations"` to the `.sub-section-header` div itself.

Find in `openDetailsModal()` each sub-section HTML block like:
```javascript
`<div class="sub-section-header">
    <span>Nominations</span>`
```
Replace with:
```javascript
`<div class="sub-section-header" data-section="nominations">
    <span>Nominations</span>`
```
Do this for all sections: `nominations`, `cargo` or `export_cargo`, `stowage`, `delays`.

**Step 4: Add `cellEdited` to each Tabulator sub-table in `initSubTables()`**

In each `new Tabulator(...)` call, add `cellEdited: () => markDirty('nominations')` (change section name per table). Example:

```javascript
subTables[vcnId].nominations = new Tabulator(`#nominations-table-${vcnId}`, {
    // ...existing config...
    cellEdited: () => markDirty('nominations'),
});
```

Do this for all sub-tables: nominations, cargo, export_cargo, stowage, delays.

**Step 5: Modify `saveSubTable()` to clear dirty on success**

Find the end of `saveSubTable()` where it calls `alert(...)`:
```javascript
if (!hasError) {
    alert(`Saved ${savedCount} row(s)`);
}
```
Replace with:
```javascript
if (!hasError) {
    clearDirty(type);
    showSubStatus(type, vcnId, `Saved ${savedCount} row(s)`);
}
```

Also add `showSubStatus` helper (shows temporary text next to the Save button instead of alert):
```javascript
function showSubStatus(type, parentId, msg) {
    const header = document.querySelector(`[data-section="${type}"]`);
    if (!header) { return; }
    let status = header.querySelector('.sub-save-status');
    if (!status) {
        status = document.createElement('span');
        status.className = 'sub-save-status';
        status.style.cssText = 'font-size:11px;color:#38a169;margin-left:8px;';
        header.querySelector('.sub-section-actions').appendChild(status);
    }
    status.textContent = msg;
    setTimeout(() => { status.textContent = ''; }, 3000);
}
```

**Step 6: Modify `closeDetailsModal()` to intercept when dirty**

Replace the existing `closeDetailsModal()`:
```javascript
function closeDetailsModal(force = false) {
    const dirty = getDirtySections();
    if (!force && dirty.length > 0) {
        // Show warning modal
        const list = document.getElementById('unsavedSectionList');
        list.innerHTML = dirty.map(s => `<li>${s.replace(/_/g,' ')}</li>`).join('');
        document.getElementById('unsavedModal').classList.add('active');
        return;
    }
    // Actually close
    const modal = document.getElementById('detailsModal');
    modal.classList.remove('active');
    if (currentVcnId && subTables[currentVcnId]) {
        Object.values(subTables[currentVcnId]).forEach(t => {
            if (t && typeof t.destroy === 'function') t.destroy();
        });
        delete subTables[currentVcnId];
    }
    document.getElementById('modalSubTables').innerHTML = '';
    clearAllDirty();
    currentVcnId = null;
}
```

**Step 7: Add unsaved modal action functions**

```javascript
function unsavedGoBack() {
    document.getElementById('unsavedModal').classList.remove('active');
}

function unsavedDiscard() {
    document.getElementById('unsavedModal').classList.remove('active');
    closeDetailsModal(true);
}

async function unsavedSaveAll() {
    const dirty = getDirtySections();
    for (const section of dirty) {
        await saveSubTable(section, currentVcnId);
    }
    document.getElementById('unsavedModal').classList.remove('active');
    // Only close if all dirty are now cleared
    if (getDirtySections().length === 0) {
        closeDetailsModal(true);
    }
}
```

**Step 8: Also reset dirty when modal opens**

At the top of `openDetailsModal()`, add:
```javascript
clearAllDirty();
dirtySubSections = {};
```

---

## Task 5: JS — Dirty Tracking + Unsaved Warning (MBC01)

**File:** `modules/MBC01/mbc01.html`

Apply exactly the same changes as Task 4, but:
- Replace `currentVcnId` → `currentMbcId`
- Replace `vcnId` → `mbcId`
- Section names: `export_load_port`, `load_port`, `discharge_port`, `mbc_cleaning`, `customer_details`
- Tabulator key: `subTables[mbcId].export_load_port`, etc.

---

## Task 6: JS — Dirty Tracking + Unsaved Warning (LDUD01)

**File:** `modules/LDUD01/ldud01.html`

Apply same changes, with:
- Replace `currentVcnId` → `currentLdudId`, `vcnId` → `ldudId`
- Section names: `delays`, `anchorage`, `vessel_ops`, `barge_lines`, `barge_cleaning`, `hold_completion`
- Note: LDUD01 `saveSubTable` has custom logic for hold_completion — only call `clearDirty(type)` after success (same pattern)

---

## Task 7: JS — Header Banner + Autosave (VCN01)

**File:** `modules/VCN01/vcn01.html`

**Step 1: Add state variable**

```javascript
let headerDirty = false;
let autosaveInterval = null;
```

**Step 2: Add banner functions**

```javascript
function showUnsavedBanner() {
    document.getElementById('unsavedBanner').classList.add('visible');
}
function hideUnsavedBanner() {
    document.getElementById('unsavedBanner').classList.remove('visible');
    headerDirty = false;
}
```

**Step 3: Hook Tabulator `cellEdited` on main table** — in `initTable()`, after `table = new Tabulator(...)`:

```javascript
table.on('cellEdited', function() {
    headerDirty = true;
    showUnsavedBanner();
});
table.on('rowAdded', function() {
    headerDirty = true;
    showUnsavedBanner();
});
```

**Step 4: Modify `saveAll()` to clear banner**

At end of `saveAll()`, after `showStatus(...)`:
```javascript
hideUnsavedBanner();
```

**Step 5: Add autosave toast helper**

```javascript
function showAutosaveToast(saved, skipped) {
    const toast = document.getElementById('autosaveToast');
    let msg = `Autosaved ${saved} row(s)`;
    if (skipped > 0) msg += ` — ${skipped} skipped (check highlighted rows)`;
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 4000);
}
```

**Step 6: Add `autoSave()` function**

```javascript
async function autoSave() {
    if (!headerDirty && getDirtySections().length === 0) return; // nothing to do

    const rows = table.getRows();
    let savedCount = 0, skippedCount = 0;

    for (const row of rows) {
        const data = row.getData();
        if (data.doc_status === 'Approved') continue;
        try {
            const res = await fetch("/api/module/VCN01/save", {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            const result = await res.json();
            if (result.id) {
                row.update({id: result.id, vcn_doc_num: result.vcn_doc_num,
                             doc_status: result.doc_status, _autosave_error: null});
                row.reformat();
                savedCount++;
            } else {
                row.update({_autosave_error: result.error || 'Save failed'});
                row.reformat();
                skippedCount++;
            }
        } catch(e) {
            row.update({_autosave_error: 'Network error'});
            row.reformat();
            skippedCount++;
        }
    }
    if (savedCount > 0) hideUnsavedBanner();

    // Autosave dirty sub-sections (silent - no alert)
    const dirtySections = getDirtySections();
    for (const section of dirtySections) {
        if (currentVcnId) {
            await saveSubTable(section, currentVcnId, true); // pass silent=true
        }
    }

    showAutosaveToast(savedCount, skippedCount);
}
```

**Step 7: Update `saveSubTable` to accept `silent` param**

Change signature: `async function saveSubTable(type, vcnId, silent = false)`
Replace `alert(...)` call at end with:
```javascript
if (!hasError && !silent) {
    clearDirty(type);
    showSubStatus(type, vcnId, `Saved ${savedCount} row(s)`);
} else if (!hasError && silent) {
    clearDirty(type);
}
```

**Step 8: Update `rowFormatter` on main table to show autosave error**

```javascript
rowFormatter: function(row) {
    const data = row.getData();
    const status = data.doc_status;
    const el = row.getElement();
    if (status === 'Approved') el.style.backgroundColor = '#f0fff4';
    else if (status === 'Rejected') el.style.backgroundColor = '#fff5f5';
    else el.style.backgroundColor = '#fffff0';
    if (data._autosave_error) {
        el.style.outline = '2px solid #e53e3e';
        el.title = `Autosave failed: ${data._autosave_error}`;
    } else {
        el.style.outline = '';
        el.title = '';
    }
}
```

**Step 9: Start autosave interval** (after `loadMasterData()` call):

```javascript
loadMasterData();
autosaveInterval = setInterval(autoSave, 30000);
```

---

## Task 8: JS — Header Banner + Autosave (MBC01)

Apply same as Task 7 but:
- API URL: `/api/module/MBC01/save`
- Row update fields: `{id: result.id, doc_num: result.doc_num, doc_status: result.doc_status, _autosave_error: null}`
- Current ID var: `currentMbcId`
- Table reload: `table.setData("/api/module/MBC01/data")`

---

## Task 9: JS — Header Banner + Autosave (LDUD01)

Apply same as Task 7 but:
- API URL: `/api/module/LDUD01/save`
- Row update: `{id: result.id, doc_num: result.doc_num, doc_status: result.doc_status, _autosave_error: null}`
- Current ID var: `currentLdudId`
- Note: LDUD01 `saveAll()` does NOT skip Approved rows — keep that behavior in `autoSave()` too (remove the `if (data.doc_status === 'Approved') continue;` check for LDUD01)

---

## Task 10: JS — Filter Panel (VCN01)

**File:** `modules/VCN01/vcn01.html`

**Step 1: Add filter config** (add near top of script, after master data vars):

```javascript
// Filter configuration — defines which columns appear in filter panel and how
// Values for 'multi' type: populated from master data in initFilterConfig()
let FILTER_CONFIG = {};
let currentFilters = [];

function initFilterConfig() {
    const statusValues = ['Draft', 'Approved', 'Rejected'];
    const opValues = ['Import', 'Export'];
    FILTER_CONFIG = {
        operation_type:         { label: 'Operation Type', type: 'multi',    values: opValues },
        vcn_doc_num:            { label: 'VCN Doc',        type: 'contains' },
        vessel_name:            { label: 'Vessel Name',    type: 'contains' },
        vessel_agent_name:      { label: 'Vessel Agent',   type: 'contains' },
        importer_exporter_name: { label: 'Stevedore',      type: 'contains' },
        customer_name:          { label: 'Customer',       type: 'contains' },
        cargo_type:             { label: 'Cargo Type',     type: 'multi',    values: cargoTypes },
        load_port:              { label: 'Load Port',      type: 'contains' },
        discharge_port:         { label: 'Discharge Port', type: 'contains' },
        doc_date:               { label: 'Doc Date',       type: 'range' },
        doc_status:             { label: 'Status',         type: 'multi',    values: statusValues },
    };
}
```

Call `initFilterConfig()` at end of `loadMasterData()` (after all master data loaded), before `initTable()`.

**Step 2: Update table init to use `ajaxParams`**

In `initTable()`, when building the Tabulator config, add:
```javascript
ajaxParams: function() {
    return currentFilters.length ? { filters: JSON.stringify(currentFilters) } : {};
},
```

**Step 3: Add filter UI functions**

```javascript
function toggleFilterPanel() {
    const panel = document.getElementById('filterPanel');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

function addFilterRow() {
    const container = document.getElementById('filterRows');
    const idx = Date.now();
    const colOptions = Object.entries(FILTER_CONFIG)
        .map(([k, v]) => `<option value="${k}">${v.label}</option>`)
        .join('');
    const row = document.createElement('div');
    row.className = 'filter-row';
    row.dataset.idx = idx;
    row.innerHTML = `
        <select class="filter-col-select" onchange="onFilterColChange(this)">
            <option value="">-- Column --</option>
            ${colOptions}
        </select>
        <div class="filter-value-container"></div>
        <button class="filter-remove" onclick="this.closest('.filter-row').remove(); updateFilterBadge();">×</button>
    `;
    container.appendChild(row);
}

function onFilterColChange(sel) {
    const row = sel.closest('.filter-row');
    const container = row.querySelector('.filter-value-container');
    const col = sel.value;
    if (!col) { container.innerHTML = ''; return; }
    const config = FILTER_CONFIG[col];
    if (config.type === 'contains') {
        container.innerHTML = `<input class="filter-text-input" placeholder="contains..." type="text">`;
    } else if (config.type === 'multi') {
        const checks = config.values.map(v =>
            `<label><input type="checkbox" class="filter-checkbox" value="${v}"> ${v}</label>`
        ).join('');
        container.innerHTML = `<div class="filter-multi-list">${checks}</div>`;
    } else if (config.type === 'range') {
        container.innerHTML = `
            <input class="filter-from" type="date" placeholder="From">
            <span style="font-size:12px;">to</span>
            <input class="filter-to" type="date" placeholder="To">
        `;
    }
}

function collectFilters() {
    const filters = [];
    document.querySelectorAll('.filter-row').forEach(row => {
        const col = row.querySelector('.filter-col-select').value;
        if (!col) return;
        const config = FILTER_CONFIG[col];
        if (config.type === 'contains') {
            const val = (row.querySelector('.filter-text-input') || {}).value || '';
            if (val.trim()) filters.push({ field: col, type: 'contains', value: val.trim() });
        } else if (config.type === 'multi') {
            const checked = [...row.querySelectorAll('.filter-checkbox:checked')].map(cb => cb.value);
            if (checked.length) filters.push({ field: col, type: 'multi', values: checked });
        } else if (config.type === 'range') {
            const from = (row.querySelector('.filter-from') || {}).value || '';
            const to = (row.querySelector('.filter-to') || {}).value || '';
            if (from || to) filters.push({ field: col, type: 'range', from, to });
        }
    });
    return filters;
}

function applyFilters() {
    currentFilters = collectFilters();
    updateFilterBadge();
    table.replaceData();  // re-fetches with updated ajaxParams
}

function clearFilters() {
    document.getElementById('filterRows').innerHTML = '';
    currentFilters = [];
    updateFilterBadge();
    table.replaceData();
}

function updateFilterBadge() {
    const active = collectFilters().length;
    const badge = document.getElementById('filterBadge');
    if (badge) {
        badge.textContent = active;
        badge.style.display = active > 0 ? 'inline' : 'none';
    }
}
```

---

## Task 11: JS — Filter Panel (MBC01)

Apply same as Task 10, with FILTER_CONFIG:

```javascript
FILTER_CONFIG = {
    operation_type: { label: 'Operation Type', type: 'multi',    values: ['Import', 'Export'] },
    doc_num:        { label: 'MBC Doc',         type: 'contains' },
    mbc_name:       { label: 'MBC Name',        type: 'contains' },
    cargo_type:     { label: 'Cargo Type',      type: 'multi',    values: cargoTypes },
    doc_date:       { label: 'Doc Date',        type: 'range' },
    doc_status:     { label: 'Status',          type: 'multi',    values: ['Draft', 'Approved', 'Rejected'] },
};
```

Table reload URL: `/api/module/MBC01/data`.

---

## Task 12: JS — Filter Panel (LDUD01)

Apply same as Task 10, with FILTER_CONFIG:

```javascript
FILTER_CONFIG = {
    doc_num:      { label: 'LDUD Doc',      type: 'contains' },
    vessel_name:  { label: 'Vessel Name',   type: 'contains' },
    vcn_doc_num:  { label: 'VCN Doc',       type: 'contains' },
    operation_type: { label: 'Operation',   type: 'multi',  values: ['Import', 'Export'] },
    cargo_type:   { label: 'Cargo Type',    type: 'multi',  values: cargoTypes },
    doc_date:     { label: 'Doc Date',      type: 'range' },
    doc_status:   { label: 'Status',        type: 'multi',  values: ['Draft', 'Approved', 'Rejected', 'Pending'] },
};
```

Note: LDUD01 `loadMasterData()` populates `cargoTypes` — check the exact variable name used.

Table reload URL: `/api/module/LDUD01/data`.

---

## Implementation Order

1. Task 1 (backend) → test with curl
2. Task 2 (CSS — all 3 modules in one shot)
3. Task 3 (HTML additions — all 3 modules)
4. Tasks 4, 5, 6 (dirty tracking — one module at a time, test each)
5. Tasks 7, 8, 9 (autosave — one module at a time, test each)
6. Tasks 10, 11, 12 (filter panel — one module at a time, test each)

## Quick Test Checklist

- [ ] Edit a header cell → unsaved banner appears → Save clears it
- [ ] Open modal → edit a cell in Nominations → red dot on header → close without saving → warning modal appears
- [ ] Warning modal: Go Back → modal stays open; Discard → modal closes; Save All → saves and closes
- [ ] Wait 30s (or call `autoSave()` from console) → toast appears with saved count
- [ ] Introduce a required-field error → row gets red outline after autosave
- [ ] Filter panel: add operation_type = Import → Apply → table shows only Import rows (server confirmed)
- [ ] Multiple filters stack correctly
- [ ] Clear All → all rows return
