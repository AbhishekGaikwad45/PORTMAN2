"""Hotpatch: repair lueu_parcel_log.entry_date rows typed day-first (YYYY-DD-MM).

The old free-text Date editor let operators type e.g. '2026-08-07' meaning
8 July 2026; the column is TEXT so it was stored verbatim. A log's entry date
can never be after the day the row was created, so rows are flagged when:

  R1  month part is 13-31            -> certainly swapped (invalid month)
  R2  date is after created_date     -> swapped, if the swap lands on/before it
  R3  date is >3 days before created -> swapped, if the swap lands within
                                        2 days before created (same-shift log)

Ambiguous rows (both readings plausible, e.g. 2026-07-06 vs 6 July) are left
alone and not reported. Dry-run by default; pass --apply to write.

Usage:  python hotfix_lueu_entry_dates.py [--apply]
"""
import sys
from datetime import date, timedelta

TODAY = date(2026, 7, 9)  # pin "now" so re-runs stay deterministic


def _parse(s):
    try:
        y, m, d = (int(x) for x in str(s).strip().split('-'))
        return date(y, m, d)
    except (ValueError, TypeError, AttributeError):
        return None


def _swap(s):
    """'YYYY-DD-MM' -> date(YYYY, MM, DD) or None."""
    try:
        y, d, m = (int(x) for x in str(s).strip().split('-'))
        return date(y, m, d)
    except (ValueError, TypeError, AttributeError):
        return None


def fix_date(entry, created):
    """Return (rule, corrected_iso) if entry_date needs the day/month swap."""
    ref = _parse(created) or TODAY
    swapped = _swap(entry)
    if not swapped:
        return None
    parsed = _parse(entry)
    if not parsed:
        return ('R1', swapped.isoformat())  # month 13-31: only swapped reading is valid
    if parsed > ref and swapped <= ref:
        return ('R2', swapped.isoformat())
    if parsed < ref - timedelta(days=3) and ref - timedelta(days=2) <= swapped <= ref:
        return ('R3', swapped.isoformat())
    return None


def selftest():
    assert fix_date('2026-13-07', '2026-07-13') == ('R1', '2026-07-13')
    assert fix_date('2026-08-07', '2026-07-08') == ('R2', '2026-07-08')
    assert fix_date('2026-09-07', '2026-07-09') == ('R2', '2026-07-09')
    assert fix_date('2026-01-07', '2026-07-02') == ('R3', '2026-07-01')
    assert fix_date('2026-07-08', '2026-07-08') is None   # correct date, untouched
    assert fix_date('2026-07-07', '2026-07-07') is None   # ambiguous but plausible
    assert fix_date('2026-08-07', None) == ('R2', '2026-07-08')  # no created_date -> today
    assert fix_date('garbage', '2026-07-08') is None
    print('selftest OK')


def main(apply_changes):
    from database import get_db, get_cursor
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT id, parcel_op_id, entry_date, created_date FROM lueu_parcel_log ORDER BY id')
    rows = cur.fetchall()
    fixes = []
    for r in rows:
        hit = fix_date(r['entry_date'], r['created_date'])
        if hit:
            fixes.append((r['id'], r['parcel_op_id'], r['entry_date'], hit[1], hit[0]))

    if not fixes:
        print(f'Checked {len(rows)} rows — nothing to fix.')
        conn.close()
        return

    print(f'Checked {len(rows)} rows — {len(fixes)} to fix:')
    print(f"{'id':>6}  {'parcel_op':>9}  {'stored':<12} -> {'corrected':<12} rule")
    for log_id, pop, old, new, rule in fixes:
        print(f'{log_id:>6}  {pop:>9}  {old:<12} -> {new:<12} {rule}')

    if apply_changes:
        for log_id, _, _, new, _ in fixes:
            cur.execute('UPDATE lueu_parcel_log SET entry_date=%s WHERE id=%s', [new, log_id])
        conn.commit()
        print(f'Applied {len(fixes)} updates.')
    else:
        print('Dry run — re-run with --apply to write these changes.')
    conn.close()


if __name__ == '__main__':
    selftest()
    main(apply_changes='--apply' in sys.argv)
