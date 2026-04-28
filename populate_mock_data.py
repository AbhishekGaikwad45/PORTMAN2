"""
Mock Data Population Script for PORTMAN (PostgreSQL version)
Run this script after running migrations to populate sample data.
Usage: python populate_mock_data.py

Customers:
  - JSW Steel Limited (Dolvi Works)  — GSTIN: 27AAACJ4323M1ZI, PAN: AAACJ4323M
    (Maharashtra — JSW has multiple GSTINs per state; verify Dolvi-specific GSTIN at gst.gov.in)
  - Amba River Coke Limited          — GSTIN: 27AABCA5271R1ZF  (placeholder — verify at gst.gov.in)
    NOTE: Verify both GSTINs on https://www.gst.gov.in or https://www.knowyourgst.com before production use.

Scenarios covered:
  VCN-2526-001  JSW Steel   Import   Coking Coal    45 000 MT  Berth 1
  VCN-2526-002  JSW Steel   Export   HR Steel Coils 28 000 MT  Berth 2
  VCN-2526-003  Amba River  Import   Thermal Coal   38 000 MT  Berth 1
  VCN-2526-004  Amba River  Export   Coke           22 000 MT  Berth 3

  MBC-2526-001  Standalone (no VCN)  JSW Raigad barge  Coking Coal   3 200 MT
  MBC-2526-002  VCN-linked           JSW Manikgad barge  Thermal Coal  2 800 MT  → VCN-2526-003

Bills (all Approved, ready for FINV01 invoicing):
  BILL-JSW-001  JSW Steel   VCN+LDUD+LUEU chain   intra-state CGST+SGST
  BILL-JSW-002  JSW Steel   standalone service     intra-state CGST+SGST
  BILL-AMBA-001 Amba River  VCN+LDUD+LUEU chain   intra-state CGST+SGST
  BILL-AMBA-002 Amba River  MBC service (non-VCN)  intra-state CGST+SGST
"""

import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from config import DATABASE_URL

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def get_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def clear_mock_data():
    """Clear all mock/transactional data in correct FK order"""
    conn = get_db()
    cur = conn.cursor()

    tables_to_clear = [
        'credit_note_lines', 'credit_note_header',
        'invoice_lines', 'invoice_header',
        'bill_lines', 'bill_header',
        'service_record_values', 'service_records', 'service_field_definitions',
        'lueu_lines',
        'mbc_delays', 'mbc_discharge_port_lines', 'mbc_load_port_lines', 'mbc_header',
        'ldud_delays', 'ldud_barge_lines', 'ldud_header',
        'vcn_delays', 'vcn_stowage_plan', 'vcn_igm', 'vcn_cargo_declaration',
        'vcn_anchorage', 'vcn_nominations', 'vcn_header',
        'customer_agreement_lines', 'customer_agreements',
        'currency_exchange_rates',
        'vessels',
        'conveyor_routes', 'port_berth_master', 'port_delay_types', 'port_systems',
        'port_shift_incharge', 'port_shift_operators',
        'mbc_master', 'vessel_cargo', 'vessel_delay_types', 'vessel_run_types',
        'vessel_type_of_discharge', 'vessel_call_doc_series', 'vessel_operation_types',
        'vessel_customers', 'vessel_importer_exporters', 'vessel_agents',
        'gears', 'vessel_categories', 'vessel_types',
        'invoice_doc_series',
        'port_bank_accounts',
    ]

    cleared = 0
    for table in tables_to_clear:
        try:
            cur.execute(f'DELETE FROM {table}')
            count = cur.rowcount
            if count > 0:
                cleared += count
        except Exception as e:
            conn.rollback()
            print(f"  [WARN] Could not clear {table}: {e}")
            continue

    try:
        cur.execute("UPDATE finance_service_types SET has_custom_fields = 0")
    except Exception:
        pass

    conn.commit()
    conn.close()
    print(f"[OK] Cleared {cleared} rows across {len(tables_to_clear)} tables")


# ─────────────────────────────────────────────────────────────────────────────
# MASTER DATA
# ─────────────────────────────────────────────────────────────────────────────

def populate_vessel_agents():
    """VAM01 - Vessel Agent Master with GST details"""
    agents = [
        # (name, gstin, state_code, state_name, pan, billing_address, city, pincode, phone, email)
        ('Maersk Agency Services Pvt Ltd',     '27AABCM1234A1ZP', '27', 'Maharashtra', 'AABCM1234A',
         'Plot 45, JNPT Road, Nhava Sheva', 'Navi Mumbai', '400707', '022-27244100', 'ops@maersk-agency.in'),
        ('Mediterranean Shipping Agency India', '29BBBCM5678B2ZQ', '29', 'Karnataka',  'BBBCM5678B',
         '12 Port Trust Road, Panambur', 'Mangalore', '575010', '0824-2407100', 'india@msc-agency.in'),
        ('CMA CGM Agencies India Pvt Ltd',     '27CCCCC9012C3ZR', '27', 'Maharashtra', 'CCCCC9012C',
         '88 Dock Road', 'Raigad', '402201', '02192-266100', 'india@cmacgm.com'),
        ('Hapag-Lloyd India Pvt Ltd',           '27DDDDD3456D4ZS', '27', 'Maharashtra', 'DDDDD3456D',
         'Maker Chambers V, Nariman Point', 'Mumbai', '400021', '022-22875100', 'india@hapag-lloyd.com'),
        ('AMSOL Marine Services',               '27EEEEE7890E5ZT', '27', 'Maharashtra', 'EEEEE7890E',
         'Port Area, Dharamtar', 'Raigad', '402201', '02192-266200', 'ops@amsolmarine.in'),
    ]
    conn = get_db()
    cur = conn.cursor()
    for (name, gstin, sc, sn, pan, addr, city, pin, phone, email) in agents:
        cur.execute('''INSERT INTO vessel_agents
            (name, gstin, gst_state_code, gst_state_name, pan,
             billing_address, city, pincode, contact_phone, contact_email, gl_code, default_currency, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) ON CONFLICT DO NOTHING''',
            [name, gstin, sc, sn, pan, addr, city, pin, phone, email, f'1100{sc}', 'INR'])
    conn.commit()
    conn.close()
    print(f"[OK] Populated {len(agents)} vessel agents")


def populate_customers():
    """VCUM01 - Vessel Customer Master — JSW Steel Dolvi & Amba River Coke"""
    customers = [
        # JSW Steel Limited (Dolvi Works)
        # PAN AAACJ4323M / GSTIN 27AAACJ4323M1ZI widely cited for JSW Steel Maharashtra.
        # JSW has multiple GSTINs per state — verify the exact Dolvi Works GSTIN at gst.gov.in.
        ('JSW Steel Limited (Dolvi Works)',
         '27AAACJ4323M1ZI', '27', 'Maharashtra', 'AAACJ4323M',
         'JSW Steel Plant, Village Dolvi, Tal. Pen, Dist. Raigad',
         'Raigad', '402107',
         '02192-277777', 'finance.dolvi@jsw.in',
         'CUST100001', '5171', '110027001',
         '919876543200'),

        # Amba River Coke Limited
        # NOTE: GSTIN based on MCA/public records — verify before production use
        ('Amba River Coke Limited',
         '27AABCA5271R1ZF', '27', 'Maharashtra', 'AABCA5271R',
         'Amba River Coke Plant, Village Dolvi, Tal. Pen, Dist. Raigad',
         'Raigad', '402107',
         '02192-245000', 'accounts@ambarivercoke.in',
         'CUST100002', '5172', '110027002',
         '919876543201'),
    ]
    conn = get_db()
    cur = conn.cursor()
    for (name, gstin, sc, sn, pan, addr, city, pin, phone, email,
         sap_code, co_code, gl, va_num) in customers:
        cur.execute('''INSERT INTO vessel_customers
            (name, gstin, gst_state_code, gst_state_name, pan,
             billing_address, city, pincode, contact_phone, contact_email,
             sap_customer_code, company_code, gl_code, default_currency,
             virtual_account_number)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            [name, gstin, sc, sn, pan, addr, city, pin, phone, email,
             sap_code, co_code, gl, 'INR', va_num])
    conn.commit()
    conn.close()
    print(f"[OK] Populated {len(customers)} customers (JSW Steel Dolvi, Amba River Coke)")


def populate_importer_exporters():
    """VIEM01 - Same companies as customers (they are also importers/exporters)"""
    companies = [
        ('JSW Steel Limited (Dolvi Works)',
         '27AAACJ4323M1ZI', '27', 'Maharashtra', 'AAACJ4323M',
         'JSW Steel Plant, Village Dolvi, Tal. Pen, Dist. Raigad', 'Raigad', '402107',
         '02192-277777', 'finance.dolvi@jsw.in', '120027001'),
        ('Amba River Coke Limited',
         '27AABCA5271R1ZF', '27', 'Maharashtra', 'AABCA5271R',
         'Amba River Coke Plant, Village Dolvi, Tal. Pen, Dist. Raigad', 'Raigad', '402107',
         '02192-245000', 'accounts@ambarivercoke.in', '120027002'),
    ]
    conn = get_db()
    cur = conn.cursor()
    for (name, gstin, sc, sn, pan, addr, city, pin, phone, email, gl) in companies:
        cur.execute('''INSERT INTO vessel_importer_exporters
            (name, gstin, gst_state_code, gst_state_name, pan,
             billing_address, city, pincode, contact_phone, contact_email, gl_code, default_currency)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            [name, gstin, sc, sn, pan, addr, city, pin, phone, email, gl, 'INR'])
    conn.commit()
    conn.close()
    print(f"[OK] Populated {len(companies)} importer/exporters")


def populate_operation_types():
    ops = ['Import', 'Export', 'Transshipment', 'Coastal', 'Bunker Only', 'Repair']
    conn = get_db()
    cur = conn.cursor()
    for op in ops:
        cur.execute('INSERT INTO vessel_operation_types (name) VALUES (%s) ON CONFLICT DO NOTHING', [op])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(ops)} operation types")


def populate_doc_series():
    series = ['VCN/25-26', 'VCN/26-27', 'IMP/25-26', 'EXP/25-26', 'CST/25-26']
    conn = get_db()
    cur = conn.cursor()
    for s in series:
        cur.execute('INSERT INTO vessel_call_doc_series (name) VALUES (%s) ON CONFLICT DO NOTHING', [s])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(series)} VCN doc series")


def populate_invoice_doc_series():
    """INVDS01 - Invoice Doc Series"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('''CREATE TABLE IF NOT EXISTS invoice_doc_series (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL,
            prefix TEXT NOT NULL, is_default BOOLEAN DEFAULT FALSE)''')
        series = [
            ('DPPL 25-26', 'DPPL', True),
            ('DPPL 26-27', 'DPPL2627', False),
        ]
        for name, prefix, is_def in series:
            cur.execute(
                'INSERT INTO invoice_doc_series (name, prefix, is_default) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                [name, prefix, is_def])
        conn.commit()
        print(f"[OK] Populated {len(series)} invoice doc series (default: DPPL)")
    except Exception as e:
        print(f"  [WARN] invoice_doc_series: {e}")
        conn.rollback()
    conn.close()


def populate_discharge_types():
    types = ['Full Discharge', 'Part Discharge', 'Direct Delivery', 'Warehouse Storage', 'Transhipment', 'Lighterage']
    conn = get_db()
    cur = conn.cursor()
    for t in types:
        cur.execute('INSERT INTO vessel_type_of_discharge (name) VALUES (%s) ON CONFLICT DO NOTHING', [t])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(types)} discharge types")


def populate_run_types():
    types = ['Coastal', 'Foreign Going', 'Overseas', 'Domestic', 'International']
    conn = get_db()
    cur = conn.cursor()
    for t in types:
        cur.execute('INSERT INTO vessel_run_types (name) VALUES (%s) ON CONFLICT DO NOTHING', [t])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(types)} run types")


def populate_delay_types():
    delays = [
        'Weather Delay', 'Port Congestion', 'Berth Unavailability', 'Tidal Restrictions',
        'Cargo Not Ready', 'Documentation Delay', 'Customs Clearance', 'Equipment Breakdown',
        'Labor Strike', 'Pilotage Delay', 'Tug Unavailability',
    ]
    conn = get_db()
    cur = conn.cursor()
    for d in delays:
        cur.execute('INSERT INTO vessel_delay_types (name) VALUES (%s) ON CONFLICT DO NOTHING', [d])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(delays)} vessel delay types")


def populate_cargo_master():
    cargo_data = [
        ('Bulk', 'Coal', 'Thermal Coal'), ('Bulk', 'Coal', 'Coking Coal'), ('Bulk', 'Coal', 'Anthracite'),
        ('Bulk', 'Iron Ore', 'Iron Ore Fines'), ('Bulk', 'Iron Ore', 'Iron Ore Pellets'),
        ('Bulk', 'Iron Ore', 'Lump Ore'),
        ('Bulk', 'Coke', 'Petroleum Coke'), ('Bulk', 'Coke', 'Metallurgical Coke'),
        ('Bulk', 'Steel', 'HR Steel Coils'), ('Bulk', 'Steel', 'CR Steel Coils'),
        ('Bulk', 'Steel', 'Steel Billets'), ('Bulk', 'Steel', 'Steel Plates'),
        ('Bulk', 'Grain', 'Wheat'), ('Bulk', 'Grain', 'Corn'), ('Bulk', 'Grain', 'Soybean'),
        ('Bulk', 'Fertilizer', 'Urea'), ('Bulk', 'Fertilizer', 'DAP'), ('Bulk', 'Fertilizer', 'MOP'),
        ('Bulk', 'Minerals', 'Bauxite'), ('Bulk', 'Minerals', 'Limestone'), ('Bulk', 'Minerals', 'Manganese Ore'),
        ('Liquid', 'Crude Oil', 'Brent Crude'), ('Liquid', 'Petroleum Products', 'Diesel'),
        ('Container', 'General', 'Mixed Cargo'), ('Break Bulk', 'Steel', 'Heavy Equipment'),
    ]
    conn = get_db()
    cur = conn.cursor()
    for cargo_type, cargo_category, cargo_name in cargo_data:
        cur.execute('INSERT INTO vessel_cargo (cargo_type, cargo_category, cargo_name) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                    [cargo_type, cargo_category, cargo_name])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(cargo_data)} cargo entries")


def populate_vessel_types():
    types = ['Bulk Carrier', 'Container Ship', 'Tanker', 'General Cargo', 'Ro-Ro',
             'LNG Carrier', 'LPG Carrier', 'Chemical Tanker', 'Car Carrier', 'Reefer Vessel']
    conn = get_db()
    cur = conn.cursor()
    for t in types:
        cur.execute('INSERT INTO vessel_types (name) VALUES (%s) ON CONFLICT DO NOTHING', [t])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(types)} vessel types")


def populate_vessel_categories():
    cats = ['Handysize', 'Handymax', 'Supramax', 'Panamax', 'Capesize',
            'VLCC', 'ULCC', 'Aframax', 'Suezmax', 'Post-Panamax']
    conn = get_db()
    cur = conn.cursor()
    for c in cats:
        cur.execute('INSERT INTO vessel_categories (name) VALUES (%s) ON CONFLICT DO NOTHING', [c])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(cats)} vessel categories")


def populate_gears():
    gears = ['Geared', 'Gearless', 'Self-Unloader', 'Crane Equipped']
    conn = get_db()
    cur = conn.cursor()
    for g in gears:
        cur.execute('INSERT INTO gears (name) VALUES (%s) ON CONFLICT DO NOTHING', [g])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(gears)} gear types")


def populate_vessels():
    """VC01 - Vessels used in the test scenarios"""
    vessels = [
        # (name, imo, type, category, gear, gt, loa, beam, year_built, doc_num)
        ('MV Shiv Ganga',      '9441362', 'Bulk Carrier', 'Supramax',  'Gearless', 58200, 200, 32, 2017, 'VM001'),
        ('MV Pacific Pride',   '9523871', 'Bulk Carrier', 'Panamax',   'Gearless', 74500, 225, 32, 2019, 'VM002'),
        ('MV Ocean Breeze',    '9612384', 'Bulk Carrier', 'Handymax',  'Geared',   43800, 185, 30, 2018, 'VM003'),
        ('MV Coastal Carrier', '9387156', 'Bulk Carrier', 'Handysize', 'Geared',   28500, 170, 27, 2016, 'VM004'),
        ('MV Iron Falcon',     '9456723', 'Bulk Carrier', 'Capesize',  'Gearless', 178000, 290, 45, 2021, 'VM005'),
        ('MV Steel Express',   '9534126', 'Bulk Carrier', 'Supramax',  'Gearless', 57000, 198, 32, 2020, 'VM006'),
    ]
    conn = get_db()
    cur = get_cursor(conn)
    for (name, imo, vtype, vcat, gear, gt, loa, beam, year, doc_num) in vessels:
        cur.execute('''INSERT INTO vessels
            (doc_num, vessel_name, imo_num, vessel_type_name, vessel_category_name,
             gear, gt, loa, beam, year_of_built, created_by, created_date, doc_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'admin',%s,'Approved') ON CONFLICT DO NOTHING''',
            [doc_num, name, imo, vtype, vcat, gear, gt, loa, beam, year,
             datetime.now().strftime('%Y-%m-%d')])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(vessels)} vessels")


def populate_mbc_master():
    """MBCM01 - MBC Master (JSW barges at Dharamtar)"""
    mbcs = [
        ('JSW Raigad',   8200),
        ('JSW Manikgad', 7800),
        ('JSW Devgad',   8500),
        ('Amba Prayag',  6500),
    ]
    conn = get_db()
    cur = conn.cursor()
    for mbc_name, dwt in mbcs:
        cur.execute('INSERT INTO mbc_master (mbc_name, dwt) VALUES (%s,%s) ON CONFLICT DO NOTHING', [mbc_name, dwt])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(mbcs)} MBC entries")


def populate_port_berths():
    berths = [
        ('Berth 1', 'North Terminal', 'Deep water bulk berth — Import'),
        ('Berth 2', 'North Terminal', 'Export bulk cargo berth'),
        ('Berth 3', 'South Terminal', 'General / Export cargo'),
        ('Berth 4', 'South Terminal', 'General cargo'),
        ('Berth 5', 'East Terminal',  'Tanker operations'),
    ]
    conn = get_db()
    cur = conn.cursor()
    for bname, bloc, rem in berths:
        cur.execute('INSERT INTO port_berth_master (berth_name, berth_location, remarks) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                    [bname, bloc, rem])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(berths)} port berths")


def populate_conveyor_routes():
    routes = [
        ('Route A - Berth 1 to Stockyard 1', 'Main import coal conveyor'),
        ('Route B - Berth 2 to Export Shed',  'Export loading route'),
        ('Route C - Stockyard 1 to Plant',    'Plant feed conveyor'),
        ('Route D - Berth 3 to Stockyard 2',  'Secondary import route'),
    ]
    conn = get_db()
    cur = conn.cursor()
    for rname, rdesc in routes:
        cur.execute('''INSERT INTO conveyor_routes (route_name, description, is_active, created_by, created_date)
            VALUES (%s,%s,1,'admin',%s) ON CONFLICT DO NOTHING''',
            [rname, rdesc, datetime.now().strftime('%Y-%m-%d')])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(routes)} conveyor routes")


def populate_finance_currencies():
    conn = get_db()
    cur = conn.cursor()
    base_date = datetime.now()
    rates = [
        ('USD', 'INR', 83.25, (base_date - timedelta(days=1)).strftime('%Y-%m-%d')),
        ('EUR', 'INR', 90.50, (base_date - timedelta(days=1)).strftime('%Y-%m-%d')),
        ('GBP', 'INR', 105.75,(base_date - timedelta(days=1)).strftime('%Y-%m-%d')),
        ('AED', 'INR', 22.65, (base_date - timedelta(days=1)).strftime('%Y-%m-%d')),
    ]
    for fc, tc, rate, eff_date in rates:
        cur.execute('''INSERT INTO currency_exchange_rates
            (from_currency, to_currency, exchange_rate, effective_date, is_active)
            VALUES (%s,%s,%s,%s,1) ON CONFLICT DO NOTHING''', [fc, tc, rate, eff_date])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(rates)} currency exchange rates")


def populate_port_delay_types():
    delays = ['Equipment Breakdown', 'Weather Delay', 'Power Failure', 'Conveyor Stoppage',
              'Labour Dispute', 'Maintenance', 'Port Congestion', 'Tidal Restrictions',
              'Rain Delay', 'Night Restriction', 'Berth Unavailability', 'Customs Hold']
    conn = get_db()
    cur = conn.cursor()
    for d in delays:
        cur.execute('INSERT INTO port_delay_types (name) VALUES (%s) ON CONFLICT DO NOTHING', [d])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(delays)} port delay types")


def populate_port_systems():
    systems = ['Conveyor System 1', 'Conveyor System 2', 'Ship Unloader 1', 'Ship Unloader 2',
               'Stacker Reclaimer 1', 'Stacker Reclaimer 2', 'Grab Crane 1', 'Grab Crane 2',
               'Belt Conveyor A', 'Belt Conveyor B']
    conn = get_db()
    cur = conn.cursor()
    for s in systems:
        cur.execute('INSERT INTO port_systems (name) VALUES (%s) ON CONFLICT DO NOTHING', [s])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(systems)} port systems")


def populate_port_shift_incharge():
    names = ['Rajesh Kumar', 'Suresh Patil', 'Anil Sharma', 'Mahesh Desai', 'Vinod Yadav', 'Prakash Nair']
    conn = get_db()
    cur = conn.cursor()
    for n in names:
        cur.execute('INSERT INTO port_shift_incharge (name) VALUES (%s) ON CONFLICT DO NOTHING', [n])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(names)} shift incharge names")


def populate_port_shift_operators():
    names = ['Ramesh - Crane Op', 'Sunil - Conveyor Op', 'Vijay - Grab Op',
             'Ganesh - Unloader Op', 'Santosh - Barge Op', 'Deepak - Grab Op']
    conn = get_db()
    cur = conn.cursor()
    for n in names:
        cur.execute('INSERT INTO port_shift_operators (name) VALUES (%s) ON CONFLICT DO NOTHING', [n])
    conn.commit(); conn.close()
    print(f"[OK] Populated {len(names)} shift operators")


def populate_customer_agreements():
    """FCAM01 - Service rate agreements for both customers"""
    conn = get_db()
    cur = get_cursor(conn)

    cur.execute("SELECT id, name FROM vessel_customers ORDER BY id")
    customers = cur.fetchall()
    if not customers:
        print("[SKIP] No customers — run populate_customers() first")
        conn.close(); return

    cur.execute("SELECT id, service_code, service_name, uom FROM finance_service_types WHERE is_active = 1")
    service_types = {r['service_code']: r for r in cur.fetchall()}
    if not service_types:
        print("[SKIP] No service types — seed data not loaded")
        conn.close(); return

    # Rates per service code
    service_rates = {
        'CHGL01': 52.00,   # Cargo Handling Loading (MT)
        'CHGU01': 48.00,   # Cargo Handling Unloading (MT)
        'EQP001': 950.00,  # Equipment Rental (HRS)
        'STO001': 18000.00,# Storage Charges (DAY)
        'CON001': 42.00,   # Conveyor Charges (MT)
        'DEL001': 1200.00, # Delay Charges (HRS)
    }

    agreement_count = 0
    valid_from = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    valid_to   = (datetime.now() + timedelta(days=305)).strftime('%Y-%m-%d')

    for idx, customer in enumerate(customers, 1):
        cur.execute("""
            INSERT INTO customer_agreements
            (agreement_code, customer_type, customer_id, customer_name,
             agreement_name, currency_code, valid_from, valid_to,
             is_active, agreement_status, created_by, created_date, approved_by, approved_date)
            VALUES (%s,'Customer',%s,%s,%s,'INR',%s,%s,1,'Approved','admin',%s,'admin',%s) RETURNING id
        """, [f'AGR2526{idx:03d}', customer['id'], customer['name'],
              f"{customer['name']} — FY 2025-26 Tariff Agreement",
              valid_from, valid_to,
              datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d')])
        agr_id = cur.fetchone()['id']

        for svc_code, rate in service_rates.items():
            if svc_code not in service_types:
                continue
            svc = service_types[svc_code]
            cur.execute("""
                INSERT INTO customer_agreement_lines
                (agreement_id, service_type_id, service_name, rate, uom, currency_code, min_charge, max_charge)
                VALUES (%s,%s,%s,%s,%s,'INR',%s,%s)
            """, [agr_id, svc['id'], svc['service_name'], rate, svc['uom'],
                  rate * 50, rate * 100000])
        agreement_count += 1

    conn.commit(); conn.close()
    print(f"[OK] Populated {agreement_count} customer agreements with 6 service lines each")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION DATA
# ─────────────────────────────────────────────────────────────────────────────

def populate_vcn_records():
    """VCN01 - 4 scenarios: JSW Import/Export, Amba Import/Export"""
    conn = get_db()
    cur = get_cursor(conn)

    # Vessels
    cur.execute("SELECT id, doc_num, vessel_name, gt FROM vessels ORDER BY id")
    vessels = {v['doc_num']: v for v in cur.fetchall()}

    # Customers/importers
    cur.execute("SELECT id, name FROM vessel_customers ORDER BY id")
    customers = {c['name']: c for c in cur.fetchall()}
    jsw_id  = customers.get('JSW Steel Limited (Dolvi Works)', {}).get('id')
    amba_id = customers.get('Amba River Coke Limited', {}).get('id')

    # Agent
    cur.execute("SELECT id, name FROM vessel_agents WHERE name LIKE 'AMSOL%' LIMIT 1")
    agent_row = cur.fetchone()
    agent_name = agent_row['name'] if agent_row else 'AMSOL Marine Services'

    today = datetime.now()

    scenarios = [
        # (doc_num, vessel_doc, operation_type, cargo_name, bl_qty, igm, customer_name, customer_id,
        #  eta_offset_days, loa, grt)
        ('VCN-2526-001', 'VM001', 'Import', 'Coking Coal',   45000, 'IGM/2526/001',
         'JSW Steel Limited (Dolvi Works)',  jsw_id,  -45, 200, 58200),
        ('VCN-2526-002', 'VM002', 'Export', 'HR Steel Coils', 28000, None,
         'JSW Steel Limited (Dolvi Works)',  jsw_id,  -30, 225, 74500),
        ('VCN-2526-003', 'VM003', 'Import', 'Thermal Coal',  38000, 'IGM/2526/003',
         'Amba River Coke Limited',          amba_id, -20, 185, 43800),
        ('VCN-2526-004', 'VM004', 'Export', 'Metallurgical Coke', 22000, None,
         'Amba River Coke Limited',          amba_id, -10, 170, 28500),
    ]

    vcn_ids = {}
    for (vcn_num, vdoc, op_type, cargo, bl_qty, igm_num,
         cust_name, cust_id, eta_offset, loa, grt) in scenarios:

        vessel = vessels.get(vdoc, {})
        vessel_name = vessel.get('vessel_name', 'MV Unknown')

        eta = today + timedelta(days=eta_offset)
        etd = eta + timedelta(days=5 if op_type == 'Import' else 3)
        doc_date = (eta - timedelta(days=7)).strftime('%Y-%m-%d')

        cur.execute("""
            INSERT INTO vcn_header
            (vcn_doc_num, vessel_master_doc, vessel_name, vessel_agent_name,
             importer_exporter_name, customer_name,
             operation_type, cargo_type, doc_date, doc_status, created_by, created_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'Bulk',%s,'Approved','admin',%s) RETURNING id
        """, [vcn_num, f"{vdoc}/{vessel_name}", vessel_name, agent_name,
              cust_name, cust_name,
              op_type, doc_date, doc_date])
        vcn_id = cur.fetchone()['id']
        vcn_ids[vcn_num] = vcn_id

        # Nomination
        cur.execute("INSERT INTO vcn_nominations (vcn_id, eta, etd, vessel_run_type) VALUES (%s,%s,%s,'Foreign Going')",
                    [vcn_id, eta.strftime('%Y-%m-%dT10:00'), etd.strftime('%Y-%m-%dT18:00')])

        # Anchorage
        anc_arr = eta - timedelta(hours=10)
        cur.execute("""INSERT INTO vcn_anchorage (vcn_id, anchorage_name, anchorage_arrival, anchorage_departure)
            VALUES (%s,'Outer Anchorage - Dharamtar',%s,%s)""",
            [vcn_id, anc_arr.strftime('%Y-%m-%dT%H:%M'), eta.strftime('%Y-%m-%dT10:00')])

        # Cargo declaration
        bl_date = (eta - timedelta(days=3)).strftime('%Y-%m-%d')
        bl_num  = f"BL/{vcn_num[-3:]}/2526"
        cur.execute("""INSERT INTO vcn_cargo_declaration
            (vcn_id, cargo_name, bl_no, bl_date, bl_quantity, quantity_uom)
            VALUES (%s,%s,%s,%s,%s,'MT')""",
            [vcn_id, cargo, bl_num, bl_date, bl_qty])

        # IGM (import only)
        if igm_num:
            cur.execute("""INSERT INTO vcn_igm
                (vcn_id, igm_number, igm_manual_number, igm_date, dwt, bl_quantity)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                [vcn_id, igm_num.replace('/', ''), igm_num,
                 (eta + timedelta(days=1)).strftime('%Y-%m-%d'), grt + 5000, bl_qty])

        # Stowage plan (3 holds)
        for h in range(1, 4):
            cur.execute("""INSERT INTO vcn_stowage_plan
                (vcn_id, cargo_name, hatch_name, hold_name, hatchwise_quantity)
                VALUES (%s,%s,%s,%s,%s)""",
                [vcn_id, cargo, f'Hatch {h}', f'Hold {h}', bl_qty // 3])

        # Delay (1 weather delay per VCN)
        delay_start = eta + timedelta(hours=18)
        cur.execute("""INSERT INTO vcn_delays (vcn_id, delay_name, delay_start, delay_end)
            VALUES (%s,'Weather Delay',%s,%s)""",
            [vcn_id, delay_start.strftime('%Y-%m-%dT%H:%M'),
             (delay_start + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M')])

    conn.commit(); conn.close()
    print(f"[OK] Populated {len(scenarios)} VCN records (JSW Import/Export, Amba Import/Export)")
    return vcn_ids


def populate_ldud_records():
    """LDUD01 - Lighter/Discharge/Unload — for the two import VCNs with full timestamps"""
    conn = get_db()
    cur = get_cursor(conn)

    cur.execute("""SELECT id, vcn_doc_num, vessel_name
                   FROM vcn_header WHERE operation_type='Import' AND doc_status='Approved'
                   ORDER BY id""")
    vcns = cur.fetchall()
    if not vcns:
        print("[SKIP] No import VCNs found"); conn.close(); return

    today = datetime.now()
    ldud_specs = [
        # (doc_num, nor_offset_days, discharge_days, grt, cargo)
        ('LDUD-2526-001', -43, 5, 58200, 'Coking Coal',   45000, 'Berth 1'),
        ('LDUD-2526-002', -18, 4, 43800, 'Thermal Coal',  38000, 'Berth 1'),
    ]

    ldud_ids = {}
    for idx, (vcn, (doc_num, nor_offset, dis_days, grt, cargo, qty, berth)) in \
            enumerate(zip(vcns, ldud_specs), 1):

        nor = today + timedelta(days=nor_offset)
        dis_completed = nor + timedelta(days=dis_days)

        cur.execute("""
            INSERT INTO ldud_header
            (doc_num, vcn_id, vcn_doc_num, vessel_name,
             nor_tendered, discharge_completed,
             operation_type,
             doc_status, created_by, created_date)
            VALUES (%s,%s,%s,%s,%s,%s,'Import','Approved','admin',%s) RETURNING id
        """, [doc_num, vcn['id'], vcn['vcn_doc_num'], vcn['vessel_name'],
              nor.strftime('%Y-%m-%dT10:00'),
              dis_completed.strftime('%Y-%m-%dT18:00'),
              today.strftime('%Y-%m-%d')])
        ldud_id = cur.fetchone()['id']
        ldud_ids[doc_num] = ldud_id

        # Barge lines (3 trips)
        barges = ['JSW Raigad', 'JSW Manikgad', 'JSW Devgad']
        qty_per_barge = qty // 3
        for trip_num, barge in enumerate(barges, 1):
            ls = nor + timedelta(hours=trip_num * 20)
            cur.execute("""
                INSERT INTO ldud_barge_lines
                (ldud_id, trip_number, hold_name, barge_name, contractor_name, cargo_name,
                 along_side_vessel, commenced_loading, completed_loading, cast_off_mv,
                 along_side_berth, commence_discharge_berth, completed_discharge_berth,
                 cast_off_berth, discharge_quantity)
                VALUES (%s,%s,%s,%s,'Marine Services Ltd',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, [ldud_id, trip_num, f'Hold {trip_num}', barge, cargo,
                  ls.strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=8)).strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M'),
                  (ls + timedelta(hours=12, minutes=30)).strftime('%Y-%m-%dT%H:%M'),
                  qty_per_barge])

        # Delay
        delay_start = nor + timedelta(hours=30)
        cur.execute("""INSERT INTO ldud_delays
            (ldud_id, delay_name, delay_account_type, equipment_name,
             start_datetime, end_datetime, total_time_mins, total_time_hrs,
             delays_to_sof, invoiceable, minus_delay_hours)
            VALUES (%s,'Port Congestion','Port Account','Grab Crane 1',%s,%s,120,2.0,1,0,0)""",
            [ldud_id, delay_start.strftime('%Y-%m-%dT%H:%M'),
             (delay_start + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')])

    conn.commit(); conn.close()
    print(f"[OK] Populated {len(ldud_specs)} LDUD records with NOR/discharge timestamps and barge lines")
    return ldud_ids


def populate_mbc_records():
    """MBC01 - Two scenarios: standalone (no VCN) + VCN-linked"""
    conn = get_db()
    cur = get_cursor(conn)

    today = datetime.now()

    # 1. Standalone MBC — JSW Raigad, no VCN, Coking Coal transhipment
    standalone_date = today - timedelta(days=25)
    cur.execute("""
        INSERT INTO mbc_header
        (doc_num, doc_series, doc_date, mbc_name, operation_type, cargo_type,
         cargo_name, bl_quantity, quantity_uom,
         doc_status, created_by, created_date)
        VALUES (%s,'MBC25-26',%s,'JSW Raigad','Import','Bulk',
                'Coking Coal',3200,'MT','Approved','admin',%s) RETURNING id
    """, ['MBC-2526-001', standalone_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
    mbc1_id = cur.fetchone()['id']

    ls1 = standalone_date + timedelta(hours=6)
    cur.execute("""INSERT INTO mbc_load_port_lines
        (mbc_id, arrived_load_port, alongside_berth, loading_commenced, loading_completed, cast_off_load_port)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        [mbc1_id, ls1.strftime('%Y-%m-%dT%H:%M'),
         (ls1+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
         (ls1+timedelta(hours=1,minutes=30)).strftime('%Y-%m-%dT%H:%M'),
         (ls1+timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M'),
         (ls1+timedelta(hours=6,minutes=30)).strftime('%Y-%m-%dT%H:%M')])

    ds1 = ls1 + timedelta(hours=8)
    cur.execute("""INSERT INTO mbc_discharge_port_lines
        (mbc_id, arrival_gull_island, departure_gull_island, vessel_arrival_port,
         vessel_all_made_fast, unloading_commenced, unloading_completed,
         vessel_cast_off, vessel_unloaded_by, vessel_unloading_berth)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Conveyor','Berth 1')""",
        [mbc1_id, ds1.strftime('%Y-%m-%dT%H:%M'),
         (ds1+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
         (ds1+timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
         (ds1+timedelta(hours=2,minutes=30)).strftime('%Y-%m-%dT%H:%M'),
         (ds1+timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'),
         (ds1+timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M'),
         (ds1+timedelta(hours=7,minutes=30)).strftime('%Y-%m-%dT%H:%M')])

    # 2. VCN-linked MBC — JSW Manikgad, linked to Amba's import VCN (VCN-2526-003)
    cur.execute("SELECT id FROM vcn_header WHERE vcn_doc_num='VCN-2526-003' LIMIT 1")
    amba_vcn = cur.fetchone()
    vcn_link_id = amba_vcn['id'] if amba_vcn else None

    mbc2_date = today - timedelta(days=18)
    cur.execute("""
        INSERT INTO mbc_header
        (doc_num, doc_series, doc_date, mbc_name, operation_type, cargo_type,
         cargo_name, bl_quantity, quantity_uom,
         doc_status, created_by, created_date)
        VALUES (%s,'MBC25-26',%s,'JSW Manikgad','Import','Bulk',
                'Thermal Coal',2800,'MT','Approved','admin',%s) RETURNING id
    """, ['MBC-2526-002', mbc2_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
    mbc2_id = cur.fetchone()['id']

    ls2 = mbc2_date + timedelta(hours=8)
    cur.execute("""INSERT INTO mbc_load_port_lines
        (mbc_id, arrived_load_port, alongside_berth, loading_commenced, loading_completed, cast_off_load_port)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        [mbc2_id, ls2.strftime('%Y-%m-%dT%H:%M'),
         (ls2+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
         (ls2+timedelta(hours=1,minutes=30)).strftime('%Y-%m-%dT%H:%M'),
         (ls2+timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
         (ls2+timedelta(hours=5,minutes=30)).strftime('%Y-%m-%dT%H:%M')])

    ds2 = ls2 + timedelta(hours=7)
    cur.execute("""INSERT INTO mbc_discharge_port_lines
        (mbc_id, arrival_gull_island, departure_gull_island, vessel_arrival_port,
         vessel_all_made_fast, unloading_commenced, unloading_completed,
         vessel_cast_off, vessel_unloaded_by, vessel_unloading_berth)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Conveyor','Berth 1')""",
        [mbc2_id, ds2.strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=2,minutes=30)).strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=6,minutes=30)).strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M')])

    cur.execute("""INSERT INTO mbc_delays
        (mbc_id, delay_name, delay_account_type, equipment_name,
         start_datetime, end_datetime, total_time_mins, total_time_hrs,
         delays_to_sof, invoiceable, minus_delay_hours)
        VALUES (%s,'Equipment Breakdown','Port Account','Conveyor Belt',%s,%s,45,0.75,1,0,0)""",
        [mbc2_id, (ds2+timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
         (ds2+timedelta(hours=4,minutes=45)).strftime('%Y-%m-%dT%H:%M')])

    conn.commit(); conn.close()
    print("[OK] Populated 2 MBC records: MBC-2526-001 (standalone) + MBC-2526-002 (VCN-linked)")
    return mbc1_id, mbc2_id


def populate_eu_records():
    """LUEU01 - Equipment Utilization linked to LDUD (primary) and MBC"""
    conn = get_db()
    cur = get_cursor(conn)

    today = datetime.now()
    eu_ids = {}  # key: scenario tag → list of lueu_line ids

    # ── LDUD-2526-001 (JSW Coking Coal Import) ─────────────────────────────
    cur.execute("SELECT id, vessel_name, vcn_doc_num FROM ldud_header WHERE doc_num='LDUD-2526-001'")
    ldud1 = cur.fetchone()
    if ldud1:
        base = today - timedelta(days=42)
        for shift in range(3):   # 3 x 8hr shifts
            start = base + timedelta(hours=shift*8)
            end   = start + timedelta(hours=8)
            qty   = 5000 + shift*500
            cur.execute("""
                INSERT INTO lueu_lines
                (source_type, source_id, source_display, equipment_name, operator_name,
                 cargo_name, operation_type, quantity, quantity_uom, route_name,
                 start_time, end_time, entry_date, created_by, created_date, is_billed)
                VALUES ('LDUD',%s,%s,%s,%s,'Coking Coal','Unloading',%s,'MT',
                        'Route A - Berth 1 to Stockyard 1',%s,%s,%s,'admin',%s,0) RETURNING id
            """, [ldud1['id'],
                  f"LDUD-2526-001 - {ldud1['vessel_name']}",
                  'Ship Unloader 1', f'Ramesh - Crane Op',
                  qty,
                  start.strftime('%Y-%m-%dT%H:%M'), end.strftime('%Y-%m-%dT%H:%M'),
                  base.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
            eu_ids.setdefault('LDUD1', []).append(cur.fetchone()['id'])

    # ── LDUD-2526-002 (Amba Thermal Coal Import) ───────────────────────────
    cur.execute("SELECT id, vessel_name, vcn_doc_num FROM ldud_header WHERE doc_num='LDUD-2526-002'")
    ldud2 = cur.fetchone()
    if ldud2:
        base = today - timedelta(days=17)
        for shift in range(2):
            start = base + timedelta(hours=shift*10)
            end   = start + timedelta(hours=10)
            qty   = 7000 + shift*1000
            cur.execute("""
                INSERT INTO lueu_lines
                (source_type, source_id, source_display, equipment_name, operator_name,
                 cargo_name, operation_type, quantity, quantity_uom, route_name,
                 start_time, end_time, entry_date, created_by, created_date, is_billed)
                VALUES ('LDUD',%s,%s,%s,%s,'Thermal Coal','Unloading',%s,'MT',
                        'Route A - Berth 1 to Stockyard 1',%s,%s,%s,'admin',%s,0) RETURNING id
            """, [ldud2['id'],
                  f"LDUD-2526-002 - {ldud2['vessel_name']}",
                  'Grab Crane 2', 'Sunil - Conveyor Op',
                  qty,
                  start.strftime('%Y-%m-%dT%H:%M'), end.strftime('%Y-%m-%dT%H:%M'),
                  base.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
            eu_ids.setdefault('LDUD2', []).append(cur.fetchone()['id'])

    # ── MBC-2526-001 (Standalone, JSW Coking Coal) ─────────────────────────
    cur.execute("SELECT id, mbc_name FROM mbc_header WHERE doc_num='MBC-2526-001'")
    mbc1 = cur.fetchone()
    if mbc1:
        base = today - timedelta(days=24)
        start = base + timedelta(hours=6)
        end   = start + timedelta(hours=5)
        cur.execute("""
            INSERT INTO lueu_lines
            (source_type, source_id, source_display, barge_name, equipment_name, operator_name,
             cargo_name, operation_type, quantity, quantity_uom,
             start_time, end_time, entry_date, created_by, created_date, is_billed)
            VALUES ('MBC',%s,%s,'JSW Raigad','Ship Unloader 2','Ganesh - Unloader Op',
                    'Coking Coal','Loading',3200,'MT',%s,%s,%s,'admin',%s,0) RETURNING id
        """, [mbc1['id'], f"MBC-2526-001 - {mbc1['mbc_name']}",
              start.strftime('%Y-%m-%dT%H:%M'), end.strftime('%Y-%m-%dT%H:%M'),
              base.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
        eu_ids.setdefault('MBC1', []).append(cur.fetchone()['id'])

    # ── MBC-2526-002 (VCN-linked, Amba Thermal Coal) ───────────────────────
    cur.execute("SELECT id, mbc_name FROM mbc_header WHERE doc_num='MBC-2526-002'")
    mbc2 = cur.fetchone()
    if mbc2:
        base = today - timedelta(days=17)
        start = base + timedelta(hours=8)
        end   = start + timedelta(hours=4)
        cur.execute("""
            INSERT INTO lueu_lines
            (source_type, source_id, source_display, barge_name, equipment_name, operator_name,
             cargo_name, operation_type, quantity, quantity_uom,
             start_time, end_time, entry_date, created_by, created_date, is_billed)
            VALUES ('MBC',%s,%s,'JSW Manikgad','Conveyor System 1','Vijay - Grab Op',
                    'Thermal Coal','Loading',2800,'MT',%s,%s,%s,'admin',%s,0) RETURNING id
        """, [mbc2['id'], f"MBC-2526-002 - {mbc2['mbc_name']}",
              start.strftime('%Y-%m-%dT%H:%M'), end.strftime('%Y-%m-%dT%H:%M'),
              base.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
        eu_ids.setdefault('MBC2', []).append(cur.fetchone()['id'])

    conn.commit(); conn.close()
    total = sum(len(v) for v in eu_ids.values())
    print(f"[OK] Populated {total} LUEU01 records: LDUD1×{len(eu_ids.get('LDUD1',[]))}, "
          f"LDUD2×{len(eu_ids.get('LDUD2',[]))}, MBC1×{len(eu_ids.get('MBC1',[]))}, "
          f"MBC2×{len(eu_ids.get('MBC2',[]))}")
    return eu_ids


def link_service_types_to_gst():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT id FROM gst_rates WHERE igst_rate = 18 AND is_active = 1 LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("[SKIP] No GST 18% rate found"); conn.close(); return
    cur.execute("UPDATE finance_service_types SET gst_rate_id=%s WHERE is_active=1 AND gst_rate_id IS NULL", [row['id']])
    updated = cur.rowcount
    conn.commit(); conn.close()
    print(f"[OK] Linked {updated} service types to GST 18%")


def populate_fin01_config():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT id, config_json FROM module_config WHERE module_code='FIN01'")
    existing = cur.fetchone()
    seller_config = {
        'approval_add': True,
        'approval_edit': True,
        'port_gst_state_code': '27',
        'seller_gstin': '27AACCJ9361Q1ZS',
        'seller_legal_name': 'JSW DHARAMTAR PORT PVT. LTD.',
        'seller_address': 'At:Dharamtar, Post:Dolvi, Tal: Pen, Dist:Raigad, Maharashtra 402107',
        'seller_location': 'Raigad',
        'seller_pincode': '402107',
        'seller_phone': '02192-266000',
        'seller_email': 'billing@dharamtarport.in',
    }
    if existing:
        try:
            ecfg = json.loads(existing['config_json']) if existing['config_json'] else {}
        except Exception:
            ecfg = {}
        ecfg.update(seller_config)
        cur.execute("UPDATE module_config SET config_json=%s WHERE module_code='FIN01'", [json.dumps(ecfg)])
    else:
        cur.execute("INSERT INTO module_config (module_code, config_json) VALUES ('FIN01',%s)",
                    [json.dumps(seller_config)])
    conn.commit(); conn.close()
    print("[OK] Populated FIN01 config (JSW Dharamtar Port seller details)")


def populate_port_bank_accounts():
    """Admin - Port bank account for FINV01 invoice payment section"""
    conn = get_db()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT id FROM port_bank_accounts LIMIT 1")
        if cur.fetchone():
            print("[SKIP] Port bank accounts already exist"); conn.close(); return
        cur.execute("""INSERT INTO port_bank_accounts
            (bank_name, branch_name, account_number, ifsc_code,
             account_holder_name, pan, cin, corporate_office_address)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            ['AXIS BANK', 'PEDDER ROAD BRANCH',
             '912020054050222', 'UTIB0001152',
             'JSW DHARAMTAR PORT PRIVATE LIMITED',
             'AACCJ9361Q',
             'U93030MH2012PTC236083',
             'JSW Centre,Bandra Kurla Complex,Bandra(East),MUMBAI,Maharashtra,India,400051,Tel:02242861000,Fax:02242863000'])
        conn.commit()
        print("[OK] Populated port bank account (SBI Pen Branch)")
    except Exception as e:
        print(f"  [WARN] port_bank_accounts: {e}")
        conn.rollback()
    conn.close()


def populate_service_field_definitions():
    """FSTM01 - Custom field definitions"""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("SELECT id, service_code FROM finance_service_types WHERE is_active=1")
    svc_map = {r['service_code']: r['id'] for r in cur.fetchall()}
    now = datetime.now().strftime('%Y-%m-%d')
    field_count = 0

    if 'EQP001' in svc_map:
        st_id = svc_map['EQP001']
        cur.execute("UPDATE finance_service_types SET has_custom_fields=1 WHERE id=%s", [st_id])
        for fname, flabel, ftype, fopts, formula, rtype, is_req, is_billable, order in [
            ('grab_make',       'Grab Make',          'dropdown', '["Nemag","Mitsui","Orts","Peiner"]', None, None, 0, 0, 1),
            ('grab_capacity',   'Grab Capacity (CBM)','number',   None, None, None, 1, 0, 2),
            ('deployment_start','Deployment Start',   'datetime', None, None, None, 1, 0, 3),
            ('deployment_end',  'Deployment End',     'datetime', None, None, None, 1, 0, 4),
            ('total_hours',     'Total Hours',        'calculated',None,'deployment_end - deployment_start','hours',0,1,5),
            ('operator_name',   'Operator Name',      'text',     None, None, None, 0, 0, 6),
        ]:
            cur.execute("""INSERT INTO service_field_definitions
                (service_type_id, field_name, field_label, field_type, field_options,
                 calculation_formula, calculation_result_type, is_required, is_billable_qty,
                 display_order, is_active, created_by, created_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,'admin',%s)""",
                [st_id, fname, flabel, ftype, fopts, formula, rtype, is_req, is_billable, order, now])
            field_count += 1

    conn.commit(); conn.close()
    print(f"[OK] Populated {field_count} service field definitions")


def populate_srv01_permissions():
    conn = get_db()
    cur = get_cursor(conn)
    for uname, rd, ad, ed, dl in [('approver',1,1,1,1),('user',1,1,1,0)]:
        cur.execute("SELECT id FROM users WHERE username=%s", [uname])
        row = cur.fetchone()
        if row:
            cur.execute("""INSERT INTO module_permissions
                (user_id, module_code, can_read, can_add, can_edit, can_delete)
                VALUES (%s,'SRV01',%s,%s,%s,%s) ON CONFLICT (user_id, module_code) DO NOTHING""",
                [row['id'], rd, ad, ed, dl])
    conn.commit(); conn.close()
    print("[OK] SRV01 permissions set")


def populate_accounts_data():
    """
    Bills ready for FINV01 invoicing — all linked through LUEU01 → LDUD/MBC chain

    BILL-JSW-001  : JSW Steel, 3 lines (Cargo Handling, Conveyor, Equipment Rental) — LDUD chain
    BILL-JSW-002  : JSW Steel, standalone Storage service (no EU link)
    BILL-AMBA-001 : Amba River Coke, 2 lines (Cargo Handling, Conveyor) — LDUD chain
    BILL-AMBA-002 : Amba River Coke, MBC barge service (non-VCN MBC chain)
    """
    conn = get_db()
    cur  = get_cursor(conn)
    today = datetime.now().strftime('%Y-%m-%d')

    print("\n--- Accounts & Finance Mock Data ---")

    # GST rates
    cur.execute("SELECT id, rate_name, cgst_rate, sgst_rate, igst_rate FROM gst_rates WHERE is_active=1")
    gst_map = {r['rate_name']: r for r in cur.fetchall()}
    gst18 = gst_map.get('GST 18%', {})
    gst5  = gst_map.get('GST 5%',  {})

    # Service types
    cur.execute("SELECT id, service_code, service_name FROM finance_service_types WHERE is_active=1")
    svc = {r['service_code']: r for r in cur.fetchall()}

    # Customers
    cur.execute("SELECT id, name, gstin, gst_state_code, gl_code FROM vessel_customers ORDER BY id")
    custs = {r['name']: r for r in cur.fetchall()}
    jsw   = custs.get('JSW Steel Limited (Dolvi Works)', {})
    amba  = custs.get('Amba River Coke Limited', {})

    # LUEU01 ids linked to LDUD
    cur.execute("""
        SELECT ll.id, ll.source_type, ll.source_id, ll.cargo_name, ll.quantity
        FROM lueu_lines ll
        WHERE ll.source_type IN ('LDUD','MBC') AND ll.is_billed=0
        ORDER BY ll.id
    """)
    eu_lines = cur.fetchall()

    def eu_for(source_type, source_doc):
        """Get first LUEU01 id matching source_type and source doc_num"""
        cur.execute(f"""SELECT ll.id FROM lueu_lines ll
            JOIN {"ldud_header" if source_type=="LDUD" else "mbc_header"} h ON h.id=ll.source_id
            WHERE ll.source_type=%s AND h.doc_num=%s LIMIT 1""",
            [source_type, source_doc])
        row = cur.fetchone()
        return row['id'] if row else None

    # Update SAP fields on agents
    print("[ACCT 1/5] Updating agents...")
    for name, sap_code in [('Maersk Agency Services Pvt Ltd','CUST001234'),
                            ('Mediterranean Shipping Agency India','CUST005678'),
                            ('AMSOL Marine Services','CUST009012')]:
        cur.execute("UPDATE vessel_agents SET sap_customer_code=%s WHERE name=%s", [sap_code, name])
    conn.commit()

    # SAP GL codes on service types
    print("[ACCT 2/5] Setting SAP GL codes on services...")
    for code, (gl, tc, pc, cc) in {
        'CHGL01': ('4101076030','50','PC5171001','CC5171001'),
        'CHGU01': ('4101076031','50','PC5171001','CC5171002'),
        'EQP001': ('4101076032','50','PC5171002','CC5171003'),
        'STO001': ('4101076033','51','PC5171002','CC5171004'),
        'CON001': ('4101076034','50','PC5171003','CC5171005'),
        'DEL001': ('4101076035','50','PC5171003','CC5171006'),
    }.items():
        cur.execute("UPDATE finance_service_types SET sap_gl_account=%s,sap_tax_code=%s,"
                    "sap_profit_center=%s,sap_cost_center=%s WHERE service_code=%s",
                    [gl, tc, pc, cc, code])
    conn.commit()

    # SAP/GST config
    cur.execute("UPDATE sap_api_config SET is_active=0")
    cur.execute("UPDATE sap_api_config SET is_active=1 WHERE environment='development'")
    cur.execute("SELECT id FROM gst_api_config WHERE environment='sandbox'")
    if not cur.fetchone():
        cur.execute("""INSERT INTO gst_api_config
            (environment,api_base_url,api_username,api_password,gstin,client_id,client_secret,is_active,created_date)
            VALUES ('sandbox','https://einv-apisandbox.nic.in','','','','','',1,%s)""",
            [datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    else:
        cur.execute("UPDATE gst_api_config SET is_active=0")
        cur.execute("UPDATE gst_api_config SET is_active=1 WHERE environment='sandbox'")
    conn.commit()

    # ── Bills ─────────────────────────────────────────────────────────────
    print("[ACCT 3/5] Creating bills...")

    cur.execute("SELECT id FROM bill_header WHERE bill_number='BILL-JSW-001'")
    if cur.fetchone():
        print("  [SKIP] Bills already exist"); conn.close(); return

    eu_ldud1 = eu_for('LDUD', 'LDUD-2526-001')   # JSW Coking Coal
    eu_ldud2 = eu_for('LDUD', 'LDUD-2526-002')   # Amba Thermal Coal
    eu_mbc1  = eu_for('MBC',  'MBC-2526-001')    # JSW standalone MBC
    eu_mbc2  = eu_for('MBC',  'MBC-2526-002')    # Amba VCN-linked MBC

    # ─ BILL-JSW-001: JSW Steel, VCN+LDUD+LUEU, intra-state CGST+SGST ─────
    # Lines: Cargo Handling Unloading (45000 MT @ 48) + Conveyor (45000 MT @ 42) + Equipment Rental (24 hrs @ 950)
    jsw_sub  = 45000*48 + 45000*42 + 24*950
    jsw_cgst = round(jsw_sub * 0.09, 2)
    jsw_sgst = jsw_cgst
    jsw_tot  = jsw_sub + jsw_cgst + jsw_sgst

    cur.execute("""INSERT INTO bill_header
        (bill_number, bill_date, source_type, source_id,
         customer_type, customer_id, customer_name, customer_gstin,
         customer_gst_state_code, customer_gl_code, currency_code, exchange_rate,
         subtotal, cgst_amount, sgst_amount, igst_amount, total_amount,
         bill_status, created_by, created_date, approved_by, approved_date)
        VALUES (%s,'2026-01-28','VCN',(SELECT id FROM vcn_header WHERE vcn_doc_num='VCN-2526-001' LIMIT 1),
                'Customer',%s,%s,%s,%s,%s,'INR',1.0,
                %s,%s,%s,0,%s,'Approved','admin',%s,'admin',%s) RETURNING id""",
        ['BILL-JSW-001', jsw['id'], jsw.get('name',''), jsw.get('gstin',''),
         jsw.get('gst_state_code','27'), jsw.get('gl_code',''),
         jsw_sub, jsw_cgst, jsw_sgst, jsw_tot, today, today])
    b1 = cur.fetchone()['id']

    for (eu_id, svc_code, desc, qty, uom, rate) in [
        (eu_ldud1, 'CHGU01', f'Unloading Coking Coal at Berth 1, MV Shiv Ganga, 45000 MT', 45000, 'MT', 48),
        (eu_ldud1, 'CON001', f'Conveyor charges Coking Coal via Route A, 45000 MT',        45000, 'MT', 42),
        (None,     'EQP001', f'Ship Unloader 1 hire, 24 hrs — LDUD-2526-001',              24,    'HRS', 950),
    ]:
        lamt = qty * rate
        cgst = round(lamt * 0.09, 2)
        cur.execute("""INSERT INTO bill_lines
            (bill_id, eu_line_id, service_type_id, service_name, service_description,
             quantity, uom, rate, line_amount,
             gst_rate_id, cgst_rate, sgst_rate, igst_rate,
             cgst_amount, sgst_amount, igst_amount, line_total,
             gl_code, sac_code, sap_tax_code)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,9,9,0,%s,%s,0,%s,%s,'996719','50')""",
            [b1, eu_id, svc.get(svc_code, {}).get('id'),
             svc.get(svc_code, {}).get('service_name', svc_code), desc,
             qty, uom, rate, lamt,
             gst18.get('id'), cgst, cgst, lamt + cgst + cgst,
             svc.get(svc_code, {}).get('sap_gl_account', '4101076030') if False else
             {'CHGU01':'4101076031','CON001':'4101076034','EQP001':'4101076032'}.get(svc_code,'4101076030')])

    # ─ BILL-JSW-002: JSW Steel, standalone Storage service (no LUEU link) ─
    cur.execute("""INSERT INTO bill_header
        (bill_number, bill_date,
         customer_type, customer_id, customer_name, customer_gstin,
         customer_gst_state_code, customer_gl_code, currency_code, exchange_rate,
         subtotal, cgst_amount, sgst_amount, igst_amount, total_amount,
         bill_status, created_by, created_date, approved_by, approved_date)
        VALUES (%s,'2026-02-05',
                'Customer',%s,%s,%s,%s,%s,'INR',1.0,
                108000,9720,9720,0,127440,
                'Approved','admin',%s,'admin',%s) RETURNING id""",
        ['BILL-JSW-002', jsw['id'], jsw.get('name',''), jsw.get('gstin',''),
         jsw.get('gst_state_code','27'), jsw.get('gl_code',''), today, today])
    b2 = cur.fetchone()['id']
    cur.execute("""INSERT INTO bill_lines
        (bill_id, service_type_id, service_name, service_description,
         quantity, uom, rate, line_amount,
         gst_rate_id, cgst_rate, sgst_rate, igst_rate,
         cgst_amount, sgst_amount, igst_amount, line_total,
         gl_code, sac_code, sap_tax_code)
        VALUES (%s,%s,'Storage Charges','Coking Coal stockyard storage — Yard A, 6 days',
                6,'DAYS',18000,108000,%s,9,9,0,9720,9720,0,127440,'4101076033','996719','51')""",
        [b2, svc.get('STO001', {}).get('id'), gst18.get('id')])

    # ─ BILL-AMBA-001: Amba River Coke, VCN+LDUD+LUEU, intra-state ─────────
    amba_sub  = 38000*48 + 38000*42 + 20*950
    amba_cgst = round(amba_sub * 0.09, 2)
    amba_sgst = amba_cgst
    amba_tot  = amba_sub + amba_cgst + amba_sgst

    cur.execute("""INSERT INTO bill_header
        (bill_number, bill_date, source_type, source_id,
         customer_type, customer_id, customer_name, customer_gstin,
         customer_gst_state_code, customer_gl_code, currency_code, exchange_rate,
         subtotal, cgst_amount, sgst_amount, igst_amount, total_amount,
         bill_status, created_by, created_date, approved_by, approved_date)
        VALUES (%s,'2026-02-10','VCN',(SELECT id FROM vcn_header WHERE vcn_doc_num='VCN-2526-003' LIMIT 1),
                'Customer',%s,%s,%s,%s,%s,'INR',1.0,
                %s,%s,%s,0,%s,'Approved','admin',%s,'admin',%s) RETURNING id""",
        ['BILL-AMBA-001', amba['id'], amba.get('name',''), amba.get('gstin',''),
         amba.get('gst_state_code','27'), amba.get('gl_code',''),
         amba_sub, amba_cgst, amba_sgst, amba_tot, today, today])
    b3 = cur.fetchone()['id']

    for (eu_id, svc_code, desc, qty, uom, rate) in [
        (eu_ldud2, 'CHGU01', 'Unloading Thermal Coal at Berth 1, MV Ocean Breeze, 38000 MT', 38000, 'MT', 48),
        (eu_ldud2, 'CON001', 'Conveyor charges Thermal Coal via Route A, 38000 MT',           38000, 'MT', 42),
        (None,     'EQP001', 'Grab Crane 2 hire, 20 hrs — LDUD-2526-002',                    20,    'HRS', 950),
    ]:
        lamt = qty * rate
        cgst = round(lamt * 0.09, 2)
        cur.execute("""INSERT INTO bill_lines
            (bill_id, eu_line_id, service_type_id, service_name, service_description,
             quantity, uom, rate, line_amount,
             gst_rate_id, cgst_rate, sgst_rate, igst_rate,
             cgst_amount, sgst_amount, igst_amount, line_total,
             gl_code, sac_code, sap_tax_code)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,9,9,0,%s,%s,0,%s,%s,'996719','50')""",
            [b3, eu_id, svc.get(svc_code, {}).get('id'),
             svc.get(svc_code, {}).get('service_name', svc_code), desc,
             qty, uom, rate, lamt,
             gst18.get('id'), cgst, cgst, lamt + cgst + cgst,
             {'CHGU01':'4101076031','CON001':'4101076034','EQP001':'4101076032'}.get(svc_code,'4101076030')])

    # ─ BILL-AMBA-002: Amba River Coke, MBC standalone barge service ────────
    mbc_sub  = 3200 * 42    # Conveyor charges for MBC-2526-001
    mbc_cgst = round(mbc_sub * 0.09, 2)
    mbc_sgst = mbc_cgst
    mbc_tot  = mbc_sub + mbc_cgst + mbc_sgst

    cur.execute("""INSERT INTO bill_header
        (bill_number, bill_date, source_type, source_id,
         customer_type, customer_id, customer_name, customer_gstin,
         customer_gst_state_code, customer_gl_code, currency_code, exchange_rate,
         subtotal, cgst_amount, sgst_amount, igst_amount, total_amount,
         bill_status, created_by, created_date, approved_by, approved_date)
        VALUES (%s,'2026-02-12','MBC',(SELECT id FROM mbc_header WHERE doc_num='MBC-2526-001' LIMIT 1),
                'Customer',%s,%s,%s,%s,%s,'INR',1.0,
                %s,%s,%s,0,%s,'Approved','admin',%s,'admin',%s) RETURNING id""",
        ['BILL-AMBA-002', amba['id'], amba.get('name',''), amba.get('gstin',''),
         amba.get('gst_state_code','27'), amba.get('gl_code',''),
         mbc_sub, mbc_cgst, mbc_sgst, mbc_tot, today, today])
    b4 = cur.fetchone()['id']

    cur.execute("""INSERT INTO bill_lines
        (bill_id, eu_line_id, service_type_id, service_name, service_description,
         quantity, uom, rate, line_amount,
         gst_rate_id, cgst_rate, sgst_rate, igst_rate,
         cgst_amount, sgst_amount, igst_amount, line_total,
         gl_code, sac_code, sap_tax_code)
        VALUES (%s,%s,%s,'Conveyor Charges',
                'Conveyor charges — Coking Coal, MBC-2526-001 (JSW Raigad), 3200 MT',
                3200,'MT',42,%s,%s,9,9,0,%s,%s,0,%s,'4101076034','996719','50')""",
        [b4, eu_mbc1, svc.get('CON001', {}).get('id'),
         mbc_sub, gst18.get('id'), mbc_cgst, mbc_cgst, mbc_tot])

    conn.commit()
    print(f"  Created 4 bills:")
    print(f"    BILL-JSW-001  (JSW Steel, LDUD chain, INR {jsw_tot:,.2f}) -> Approved, ready to invoice")
    print(f"    BILL-JSW-002  (JSW Steel, Storage,    INR 127440.00)  -> Approved, ready to invoice")
    print(f"    BILL-AMBA-001 (Amba River, LDUD chain, INR {amba_tot:,.2f}) -> Approved, ready to invoice")
    print(f"    BILL-AMBA-002 (Amba River, MBC service, INR {mbc_tot:,.2f}) -> Approved, ready to invoice")

    # ── Summary counts ──────────────────────────────────────────────────────
    print("\n[ACCT 4/5] Summary:")
    for tbl in ['bill_header', 'bill_lines', 'lueu_lines', 'ldud_header', 'mbc_header', 'vcn_header']:
        cur.execute(f"SELECT COUNT(*) as cnt FROM {tbl}")
        print(f"  {tbl}: {cur.fetchone()['cnt']} rows")

    print("\n[ACCT 5/5] LUEU01 -> LDUD chain check:")
    cur.execute("""
        SELECT bl.bill_id, bl.service_name, ll.source_type, ll.source_id,
               lh.doc_num AS ldud_doc, vh.vcn_doc_num, vh.vessel_name
        FROM bill_lines bl
        JOIN lueu_lines ll ON ll.id = bl.eu_line_id
        JOIN ldud_header lh ON lh.id = ll.source_id AND ll.source_type='LDUD'
        JOIN vcn_header vh ON vh.id = lh.vcn_id
    """)
    for r in cur.fetchall():
        print(f"  bill_line -> eu_line[LDUD:{r['ldud_doc']}] -> VCN:{r['vcn_doc_num']} ({r['vessel_name']})")

    conn.close()


def main():
    print("\n" + "="*65)
    print("PORTMAN Mock Data — JSW Steel Dolvi & Amba River Coke Limited")
    print("="*65 + "\n")

    print("Step 1: Clearing existing data...")
    clear_mock_data()

    print("\nStep 2: Master tables...")
    populate_vessel_types()
    populate_vessel_categories()
    populate_gears()
    populate_vessel_agents()
    populate_customers()
    populate_importer_exporters()
    populate_operation_types()
    populate_run_types()
    populate_delay_types()
    populate_cargo_master()
    populate_mbc_master()
    populate_port_berths()
    populate_conveyor_routes()
    populate_port_delay_types()
    populate_port_systems()
    populate_port_shift_incharge()
    populate_port_shift_operators()
    populate_doc_series()
    populate_invoice_doc_series()

    print("\nStep 3: Vessels...")
    populate_vessels()

    print("\nStep 4: Agreements & Currencies...")
    populate_finance_currencies()
    populate_customer_agreements()

    print("\nStep 5: Transactions (VCN -> LDUD -> LUEU01)...")
    populate_vcn_records()
    populate_ldud_records()
    populate_mbc_records()
    populate_eu_records()

    print("\nStep 6: Finance config & services...")
    link_service_types_to_gst()
    populate_fin01_config()
    populate_port_bank_accounts()
    populate_service_field_definitions()
    populate_srv01_permissions()

    print("\nStep 7: Bills (Approved, ready for FINV01 invoicing)...")
    populate_accounts_data()

    print("\n" + "="*65)
    print("Done!")
    print("  Customers : JSW Steel Limited (Dolvi Works), Amba River Coke Limited")
    print("  VCNs      : VCN-2526-001..004  (Import+Export for each customer)")
    print("  LDUD      : LDUD-2526-001..002 (Import discharge records with NOR/dates/GRT)")
    print("  MBC       : MBC-2526-001 (standalone), MBC-2526-002 (VCN-linked)")
    print("  LUEU01    : 7 EU lines (LDUD chain + MBC chain)")
    print("  Bills     : BILL-JSW-001/002, BILL-AMBA-001/002  -> all Approved")
    print("  INVDS01   : DPPL (default) doc series ready")
    print("="*65)
    print("\n** GST rates, UOMs, equipment, holds seeded by Alembic migrations **\n")


if __name__ == '__main__':
    main()
