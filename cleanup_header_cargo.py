"""One-off cleanup: recompute vcn_header.cargo_type strictly from parcel cargo
names for every VCN that has an LDUD — wipes EV01-seeded header cargo that
never came from parcels (headers with no parcels end up blank).

Dry-run by default; pass --apply to commit.
    python cleanup_header_cargo.py          # show what would change
    python cleanup_header_cargo.py --apply  # write the changes
"""
import sys
from database import get_db, get_cursor
from modules.VCN01.model import _sync_header_cargo

apply_changes = '--apply' in sys.argv

conn = get_db()
cur = get_cursor(conn)
cur.execute('''SELECT DISTINCT h.id, h.vcn_doc_num, h.cargo_type
               FROM vcn_header h
               JOIN ldud_header l ON l.vcn_id = h.id
               ORDER BY h.id''')
rows = [dict(r) for r in cur.fetchall()]

changed = 0
for r in rows:
    _sync_header_cargo(cur, r['id'])   # rewrites cargo_type from parcels only
    cur.execute('SELECT cargo_type FROM vcn_header WHERE id=%s', [r['id']])
    new = cur.fetchone()['cargo_type']
    if (new or '') != (r['cargo_type'] or ''):
        changed += 1
        print(f"{r['vcn_doc_num']}: {r['cargo_type']!r} -> {new!r}")

if apply_changes:
    conn.commit()
    print(f"\n{len(rows)} LDUD vessels checked, {changed} headers UPDATED.")
else:
    conn.rollback()
    print(f"\nDRY RUN — {len(rows)} LDUD vessels checked, {changed} would change. "
          f"Re-run with --apply to commit.")
conn.close()
