# EU01 → LUEU01 Module Rename Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename module code EU01 → LUEU01, folder, all routes, and database table eu_lines → lueu_lines without breaking any existing functionality.

**Architecture:** Rename the module directory, update all Python/HTML/JS references, add an Alembic migration to rename the table and update the FK in bill_lines, and update the module_permissions seed row.

**Tech Stack:** Flask, Tabulator, PostgreSQL, Alembic

---

### Task 1: Rename the module directory

**Files:**
- Rename: `modules/EU01/` → `modules/LUEU01/`
- Rename: `modules/LUEU01/eu01.html` → `modules/LUEU01/lueu01.html`

**Steps:**

1. Run:
```bash
cp -r d:/PORTMAN/modules/EU01 d:/PORTMAN/modules/LUEU01
mv d:/PORTMAN/modules/LUEU01/eu01.html d:/PORTMAN/modules/LUEU01/lueu01.html
```
*(Keep the old EU01 folder in place until all references are updated — remove it in Task 7)*

---

### Task 2: Update `modules/LUEU01/views.py`

**Files:**
- Modify: `modules/LUEU01/views.py`

Replace every occurrence of `EU01` → `LUEU01` AND `eu01.html` → `lueu01.html`:

- Line 6: `bp = Blueprint('LUEU01', ...)`
- Line 7: `MODULE_CODE = 'LUEU01'`
- Line 8: `MODULE_INFO = {'code': 'LUEU01', 'name': 'Load Unload Equipment Utilization'}`
- Line 23: `@bp.route('/module/LUEU01/')`
- All 20+ `@bp.route('/api/module/EU01/...')` → `/api/module/LUEU01/...`
- `render_template('eu01.html', ...)` → `render_template('lueu01.html', ...)`

---

### Task 3: Update `modules/LUEU01/model.py`

**Files:**
- Modify: `modules/LUEU01/model.py`

Replace SQL table name: `eu_lines` → `lueu_lines` (all occurrences, ~8 lines)

---

### Task 4: Update `modules/LUEU01/lueu01.html`

**Files:**
- Modify: `modules/LUEU01/lueu01.html`

Replace occurrences:
- `<span class="module-code">EU01</span>` → `LUEU01`
- `addToRecent('EU01', ...)` → `addToRecent('LUEU01', ...)`
- All `fetch('/api/module/EU01/...')` → `fetch('/api/module/LUEU01/...')`
- `ajaxURL: "/api/module/EU01/data"` → `/api/module/LUEU01/data`

---

### Task 5: Update `app.py`

**Files:**
- Modify: `app.py`

```python
# Line 45 - change:
from modules.EU01 import bp as eu01_bp, MODULE_INFO as eu01_info
# to:
from modules.LUEU01 import bp as eu01_bp, MODULE_INFO as eu01_info
```
*(Variable names eu01_bp / eu01_info can stay — they're just local aliases)*

---

### Task 6: Update cross-module references

**Files:**
- Modify: `modules/FIN01/views.py` — change `from modules.EU01 import model as eu_model` → `from modules.LUEU01 import model as eu_model`
- Modify: `modules/FIN01/model.py` — replace `eu_lines` → `lueu_lines` (all occurrences)
- Modify: `modules/MBC01/mbc01.html` — change `fetch('/api/module/EU01/operation-types')` → `fetch('/api/module/LUEU01/operation-types')`

---

### Task 7: Write Alembic migration

**Files:**
- Create: `alembic/versions/<new_hash>_rename_eu01_to_lueu01.py`

```python
"""rename eu01 to lueu01: table eu_lines -> lueu_lines

Revision ID: <generate>
Revises: <latest_revision>
Create Date: 2026-02-26

"""
from alembic import op

revision = '<generate>'
down_revision = '<latest_revision>'
branch_labels = None
depends_on = None

def upgrade():
    # Rename the table
    op.execute('ALTER TABLE eu_lines RENAME TO lueu_lines')
    # Rename the FK column reference in bill_lines (column stays eu_line_id, only table changes)
    # Update module_permissions code
    op.execute("UPDATE module_permissions SET module_code = 'LUEU01' WHERE module_code = 'EU01'")

def downgrade():
    op.execute('ALTER TABLE lueu_lines RENAME TO eu_lines')
    op.execute("UPDATE module_permissions SET module_code = 'EU01' WHERE module_code = 'LUEU01'")
```

Run: `alembic upgrade head`

---

### Task 8: Update `alembic/versions/5cc47bd6c31d_initial_schema.py`

**Files:**
- Modify: `alembic/versions/5cc47bd6c31d_initial_schema.py`

Update comments/table names in the initial schema so `alembic downgrade` works:
- `CREATE TABLE IF NOT EXISTS eu_lines` → `lueu_lines`
- `REFERENCES eu_lines(id)` in bill_lines FK → `lueu_lines(id)`
- `DROP TABLE IF EXISTS eu_lines` → `lueu_lines`
- Comment `=== EU01 (Equipment Utilization) ===` → `=== LUEU01 (Load Unload Equipment Utilization) ===`

---

### Task 9: Update `populate_mock_data.py`

**Files:**
- Modify: `populate_mock_data.py`

- `'eu_lines'` in table list → `'lueu_lines'`
- All `INSERT INTO eu_lines` → `INSERT INTO lueu_lines`

---

### Task 10: Update `templates/base.html`

*(Already done — sidebar now shows `LUEU01` and `Load Unload Equipment Utilization`. Verify and skip if correct.)*

---

### Task 11: Remove old EU01 directory

After verifying everything works:
```bash
rm -rf d:/PORTMAN/modules/EU01
```

---

### Verification

- Navigate to `/module/LUEU01/` — page loads with correct title and code
- Add/save a row — no errors
- Open MBCDS01 (MBC01) — operation-types dropdown loads
- Open FIN01 — EU lines still appear in billing
- `alembic current` shows head revision
- `SELECT COUNT(*) FROM lueu_lines` returns same count as before
