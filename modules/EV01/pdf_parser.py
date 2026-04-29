import io
import re
from datetime import datetime

import pdfplumber


def _clean(v):
    if v is None:
        return None
    v = ' '.join(str(v).split())
    return v if v and v not in ('', '-', '---', 'NR', 'N/A') else None


def _parse_date(s):
    s = _clean(s)
    if not s:
        return None
    for fmt in ('%d-%b-%y', '%d-%b-%Y', '%d/%m/%y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def _parse_dt(s):
    s = _clean(s)
    if not s:
        return None
    # "06-Apr-26 03.48"  →  replace last period-in-time with colon
    s = re.sub(r'(\d{1,2})\.(\d{2})\s*$', r'\1:\2', s)
    for fmt in ('%d-%b-%y %H:%M', '%d-%b-%Y %H:%M', '%d-%b-%y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d %H:%M:00')
        except ValueError:
            pass
    return None


def _split_codes(raw):
    """Return comma-joined list of trimmed non-empty codes, or None."""
    if not raw:
        return None
    codes = [c.strip() for c in raw.split('+') if c.strip() and c.strip() not in ('---', '-', 'N/A')]
    return ','.join(codes) if codes else None


def _qty_list(s):
    """Keep '+'-separated quantities as a comma-joined list matching cargo order."""
    s = _clean(s)
    if not s:
        return None
    parts = [p.strip().replace(',', '') for p in s.split('+') if p.strip()]
    return ','.join(parts) if parts else None


def parse_pdf_ev_rows(file_bytes):
    """
    Extract rows from the B-II Expected/Waiting Vessels table in the JNPA
    Daily Performance Report PDF.

    Returns a list of dicts ready to upsert into expected_vessels.
    """
    results = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue

                # Locate the header row by checking for VIA + ETA (or TERMINAL)
                hdr_idx = None
                for i, row in enumerate(tbl):
                    text = ' '.join(str(c or '') for c in row).upper()
                    if 'VIA' in text and ('ETA' in text or 'TERMINAL' in text):
                        hdr_idx = i
                        break
                if hdr_idx is None:
                    continue

                hdr = [re.sub(r'\s+', ' ', str(c or '')).strip().upper() for c in tbl[hdr_idx]]

                def col(name):
                    for idx, h in enumerate(hdr):
                        if name in h:
                            return idx
                    return None

                ci = {
                    'terminal': col('TERMINAL'),
                    'vessel':   col('VESSEL'),
                    'via':      col('VIA'),
                    'loa':      col('LOA'),
                    'dft':      col('DFT'),
                    'agt':      col('AGT'),
                    'cargo':    col('CARGO'),
                    'mla':      col('MLA'),
                    'qty':      col('QTY'),
                    'ddp':      col('DDP'),
                    'dop':      col('DOP'),
                    'eta':      col('ETA'),
                    'ata':      col('ATA'),
                    'lpc':      col('LPC'),
                    'doc':      col('DOC'),
                    'nor':      col('NOR'),
                    'berth':    col('BERTH'),
                }

                for row in tbl[hdr_idx + 1:]:
                    if not row or not any(row):
                        continue

                    def g(key):
                        idx = ci.get(key)
                        if idx is None or idx >= len(row):
                            return None
                        return _clean(row[idx])

                    vessel_name = g('vessel')
                    if not vessel_name:
                        continue

                    # Parse AGT/TNK/CONS  →  split on "/"
                    agt_raw = g('agt') or ''
                    parts = agt_raw.split('/')
                    agents     = _split_codes(parts[0] if len(parts) > 0 else '')
                    tanks      = _split_codes(parts[1] if len(parts) > 1 else '')
                    consignees = _split_codes(parts[2] if len(parts) > 2 else '')

                    results.append({
                        'terminal_name': g('terminal'),
                        'vessel_name':   vessel_name,
                        'via_number':    g('via'),
                        'loa':           g('loa'),
                        'draft':         g('dft'),
                        'agents':        agents,
                        'tanks':         tanks,
                        'consignees':    consignees,
                        'cargo_name':    _split_codes(g('cargo')),
                        'mla':           g('mla'),
                        'quantity':      _qty_list(g('qty')),
                        'ddp':           _parse_date(g('ddp')),
                        'dop':           _parse_date(g('dop')),
                        'eta':           _parse_dt(g('eta')),
                        'ata':           _parse_dt(g('ata')),
                        'lpc':           _parse_dt(g('lpc')),
                        'doc':           _parse_dt(g('doc')),
                        'nor':           _parse_dt(g('nor')),
                        'berth_name':    g('berth'),
                    })

    return results
