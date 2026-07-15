"""Self-check for the RP01 CSV parsers: python -m modules.RP01.RP01.test_mis_parse"""
from modules.RP01.RP01.views import parse_mis_csv, parse_vm_csv, MIS_COLUMNS, VM_COLUMNS

MIS_HDR = ','.join(f'"{h}"' for h, *_ in MIS_COLUMNS)

# vessel first row + continuation row (blank vessel cells) + subtotal row (no customer)
MIS_GOOD = MIS_HDR + '''
1,2024-25,Nov-24,Nov-24,Q5928,MT WISDOM STAR,Cargill India,NARENDRA FWD,Edible Oil,Edible Oil,Veg Oil,Crude,,EDIBLE OIL,GBL,"12,000.000",Overseas,Import,252,3024000,100,1200000,24.2,290400,Interocean,10000,,,,Cargill India Pvt. Ltd.
,,,,,,Reliance Consumer,NARENDRA FWD,Edible Oil,Edible Oil,,,,EDIBLE OIL,Suraj,10000.000,Overseas,Import,252,2520000,100,1000000,24.2,242000,,,,,#N/A,Reliance Consumer Products Ltd.
,,,,,,,,,,,,,,,48469.946,,,,12214426,,4846995,,1172973,,30000,,,,
'''

MIS_BAD = MIS_HDR + '''
1,2024-25,Nov-24,Nov-24,Q5928,MT SHIP,Cargill,NF,EO,EO,EO,EO,EO,EO,GBL,12x00,Overseas,Import,,,,,,,,,,,,
'''

VM_HDR = ','.join(f'"{h}"' for h, *_ in VM_COLUMNS)

# real row (dash in anchorage time, #DIV/0! junk in a KPI col) + totals row (no vessel name)
VM_GOOD = VM_HDR + '''
1,2024-25,Dec-24,LB-03,Q6133,MT TINY GOLD,Overseas,F,9251559,Liberia,,UAILK,"CHORNOMORSK, UKRAINE",25063,6.5,176,Import,Interocean,"12"" DIA",Suraj,Suraj,Edible Oil,Other,Edible Oil,EDIBLE OIL,25-12-2024 07:48,-,25-12-2024 05:48,25-12-2024 07:48,25-12-2024 08:06,25-12-2024 09:00,27-12-2024 07:42,27-12-2024 11:55,27-12-2024 11:55,,27-12-2024 13:55,"2,431.625",52,Vessel Pumping issue,0.01,0.01,#DIV/0!,2.16,0.04,1.95,0.21,0.21,0,0.1,0.08
,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,110310.15,,,,,,,,,,,,,
'''

VM_BAD = VM_HDR + '''
1,2024-25,Dec-24,LB-03,,MT SHIP,Overseas,F,1,X,,,,not-num,,,Import,A,,,,,,,,junk-date,,,,,,,,,,,100,,,,,,,,,,,,,
'''


def demo():
    rows, errors = parse_mis_csv(MIS_GOOD)
    assert errors == [], errors
    assert len(rows) == 2, f'subtotal row not skipped: {len(rows)}'
    r1, r2 = rows
    assert r1['sr_no'] == 1 and r2['sr_no'] is None, 'sr_no parsed, not forward-filled'
    assert r1['quantity'] == 12000.0, 'comma number'
    assert r2['vcn_no'] == 'Q5928' and r2['vessel_name'] == 'MT WISDOM STAR', 'forward-fill'
    assert r2['gangway_amount'] is None, 'gangway must not forward-fill'
    assert r2['remarks'] is None, '#N/A treated as blank'
    assert r1['cargo_category_2'] == 'Veg Oil' and r1['cargo_sub_category'] == 'Crude', 'vcg01-aligned cols'
    assert r2['cargo_category_2'] is None and r2['cargo_name'] == 'EDIBLE OIL', 'vcg01-aligned cols'

    rows, errors = parse_mis_csv(MIS_BAD)
    assert any('quantity' in e for e in errors), errors

    rows, errors = parse_mis_csv('"Wrong Header"\nx')
    assert errors and 'Missing columns' in errors[0]

    rows, errors = parse_vm_csv(VM_GOOD)
    assert errors == [], errors
    assert len(rows) == 1, f'totals row not skipped: {len(rows)}'
    r = rows[0]
    assert r['nor'] == '2024-12-25T07:48'
    assert r['anchorage_time'] is None, 'dash treated as blank'
    assert r['pilot_board_departure'] is None, 'blank timing'
    assert r['waiting_non_port'] is None, '#DIV/0! treated as blank'
    assert r['quantity'] == 2431.625

    rows, errors = parse_vm_csv(VM_BAD)
    assert any('grt' in e for e in errors), errors
    assert any('nor' in e for e in errors), errors
    assert any('missing vcn_no' in e for e in errors), errors

    # the template's format-hint row (blank anchor cell) must be ignored
    mis_hint = ','.join(f'"{h}"' for *_, h in MIS_COLUMNS)
    rows, errors = parse_mis_csv(MIS_HDR + '\n' + mis_hint + '\n')
    assert rows == [] and errors == [], (rows, errors)
    vm_hint = ','.join(f'"{h}"' for *_, h in VM_COLUMNS)
    rows, errors = parse_vm_csv(VM_HDR + '\n' + vm_hint + '\n')
    assert rows == [] and errors == [], (rows, errors)
    print('mis + vessel-master parse self-check OK')


if __name__ == '__main__':
    demo()
