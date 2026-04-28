"""seed_data

Revision ID: 745e51f340e0
Revises: 5cc47bd6c31d
Create Date: 2026-02-02
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text
import json

revision: str = '745e51f340e0'
down_revision: Union[str, None] = '5cc47bd6c31d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # === Users ===
    conn.execute(text(
        "INSERT INTO users (username, password, is_admin) VALUES ('admin', 'admin', 1) ON CONFLICT (username) DO NOTHING"
    ))
    conn.execute(text(
        "INSERT INTO users (username, password, is_admin) VALUES ('approver', 'approver', 0) ON CONFLICT (username) DO NOTHING"
    ))
    conn.execute(text(
        "INSERT INTO users (username, password, is_admin) VALUES ('user', 'user', 0) ON CONFLICT (username) DO NOTHING"
    ))

    # Get user IDs
    result = conn.execute(text("SELECT id FROM users WHERE username = 'approver'"))
    approver_id = result.fetchone()[0]
    result = conn.execute(text("SELECT id FROM users WHERE username = 'user'"))
    regular_user_id = result.fetchone()[0]

    # === Module permissions ===
    # VC01 for regular user
    conn.execute(text(
        f"INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete) "
        f"VALUES ({regular_user_id}, 'VC01', 1, 1, 1, 0) ON CONFLICT (user_id, module_code) DO NOTHING"
    ))
    # VC01 for approver
    conn.execute(text(
        f"INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete) "
        f"VALUES ({approver_id}, 'VC01', 1, 1, 1, 1) ON CONFLICT (user_id, module_code) DO NOTHING"
    ))

    # Master modules - approver full access, user read-only
    master_modules = [
        'VTM01', 'VCM01', 'GM01', 'VAM01', 'VIEM01', 'VCUM01', 'VOT01', 'VCDS01',
        'VTOD01', 'VRT01', 'VDM01', 'VCG01', 'VQM01', 'VHM01', 'VHO01', 'VDAT01',
        'VEM01', 'VBM01', 'VCTM01', 'MBCM01', 'PBM01', 'MBCDS01', 'VEXDS01',
        'CRM01', 'FCRM01', 'FGRM01', 'FSTM01', 'FCAM01'
    ]
    for module in master_modules:
        conn.execute(text(
            f"INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete) "
            f"VALUES ({approver_id}, '{module}', 1, 1, 1, 1) ON CONFLICT (user_id, module_code) DO NOTHING"
        ))
        conn.execute(text(
            f"INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete) "
            f"VALUES ({regular_user_id}, '{module}', 1, 0, 0, 0) ON CONFLICT (user_id, module_code) DO NOTHING"
        ))

    # Transaction modules - approver full, user add/edit but no delete
    transaction_modules = ['VCN01', 'LDUD01', 'MBC01', 'EU01', 'FIN01', 'VEX01']
    for module in transaction_modules:
        conn.execute(text(
            f"INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete) "
            f"VALUES ({approver_id}, '{module}', 1, 1, 1, 1) ON CONFLICT (user_id, module_code) DO NOTHING"
        ))
        conn.execute(text(
            f"INSERT INTO module_permissions (user_id, module_code, can_read, can_add, can_edit, can_delete) "
            f"VALUES ({regular_user_id}, '{module}', 1, 1, 1, 0) ON CONFLICT (user_id, module_code) DO NOTHING"
        ))

    # === Module configs with approval ===
    approval_modules = ['VC01', 'VCN01', 'LDUD01', 'MBC01', 'VEX01', 'FIN01', 'FCAM01']
    for module in approval_modules:
        config = json.dumps({'approval_add': True, 'approval_edit': True, 'approver_id': str(approver_id)})
        conn.execute(text(
            f"INSERT INTO module_config (module_code, config_json) VALUES ('{module}', '{config}') "
            f"ON CONFLICT (module_code) DO NOTHING"
        ))

    # === Seed data for lookup tables ===

    # Quantity UOM
    for name in ['MT', 'TEU', 'LITRE', 'KG', 'CBM']:
        conn.execute(text(
            f"INSERT INTO quantity_uom (name) VALUES ('{name}') ON CONFLICT (name) DO NOTHING"
        ))

    # Vessel Hatches
    for i in range(1, 11):
        conn.execute(text(
            f"INSERT INTO vessel_hatches (name) VALUES ('Hatch {i}') ON CONFLICT (name) DO NOTHING"
        ))

    # Vessel Holds
    for i in range(1, 11):
        conn.execute(text(
            f"INSERT INTO vessel_holds (name) VALUES ('Hold {i}') ON CONFLICT (name) DO NOTHING"
        ))

    # Delay Account Types
    for name in ['Vessel Account', 'Port Account', 'Shipper Account', 'Receiver Account', 'Weather Account', 'Third Party Account']:
        conn.execute(text(
            f"INSERT INTO delay_account_types (name) VALUES ('{name}') ON CONFLICT (name) DO NOTHING"
        ))

    # Equipment
    for name in ['Grab Crane', 'Conveyor Belt', 'Ship Unloader', 'Hopper', 'Mobile Crane', 'Forklift', 'Payloader', 'Truck', 'Barge Crane']:
        conn.execute(text(
            f"INSERT INTO equipment (name) VALUES ('{name}') ON CONFLICT (name) DO NOTHING"
        ))

    # Contractors
    for name in ['Marine Services Ltd', 'Port Logistics Co', 'Coastal Transport Inc', 'Harbor Operations', 'Seaboard Contractors', 'Maritime Solutions']:
        conn.execute(text(
            f"INSERT INTO contractors (name) VALUES ('{name}') ON CONFLICT (name) DO NOTHING"
        ))

    # Barges
    barges = [
        ('Radha Krishna 1', 2800), ('Radha Krishna 2', 3000), ('Radha Krishna 3', 2900),
        ('Radha Krishna 4', 3200), ('Radha Krishna 5', 2700),
        ('Aisha 1', 3100), ('Aisha 2', 2850), ('Aisha 3', 3050)
    ]
    for name, dwt in barges:
        conn.execute(text(
            f"INSERT INTO barges (barge_name, dwt) VALUES ('{name}', {dwt}) ON CONFLICT (barge_name) DO NOTHING"
        ))

    # MBC Doc Series
    for name in ['MBC25-26', 'MBC26-27', 'MBC27-28']:
        conn.execute(text(
            f"INSERT INTO mbc_doc_series (name) VALUES ('{name}')"
        ))

    # Currency Master
    currencies = [
        ('INR', 'Indian Rupee', '₹', 1), ('USD', 'US Dollar', '$', 0),
        ('EUR', 'Euro', '€', 0), ('GBP', 'British Pound', '£', 0),
        ('AED', 'UAE Dirham', 'د.إ', 0)
    ]
    for code, cname, symbol, is_base in currencies:
        conn.execute(text(
            f"INSERT INTO currency_master (currency_code, currency_name, currency_symbol, is_base_currency, is_active) "
            f"VALUES ('{code}', '{cname}', '{symbol}', {is_base}, 1) ON CONFLICT (currency_code) DO NOTHING"
        ))

    # GST Rates
    gst_rates = [
        ('GST 0%', 0, 0, 0), ('GST 5%', 2.5, 2.5, 5), ('GST 12%', 6, 6, 12),
        ('GST 18%', 9, 9, 18), ('GST 28%', 14, 14, 28)
    ]
    for name, cgst, sgst, igst in gst_rates:
        conn.execute(text(
            f"INSERT INTO gst_rates (rate_name, cgst_rate, sgst_rate, igst_rate, effective_from, effective_to, is_active) "
            f"VALUES ('{name}', {cgst}, {sgst}, {igst}, '2017-07-01', NULL, 1)"
        ))

    # Finance Service Types
    service_types = [
        ('CHGL01', 'Cargo Handling Loading', 'Cargo', 'REV001', '996511', 'MT'),
        ('CHGU01', 'Cargo Handling Unloading', 'Cargo', 'REV001', '996511', 'MT'),
        ('EQP001', 'Equipment Rental', 'Equipment', 'REV002', '997212', 'Hours'),
        ('DEL001', 'Delay Charges', 'Delay', 'REV003', '999794', 'Hours'),
        ('STO001', 'Storage Charges', 'Storage', 'REV004', '996792', 'Days'),
        ('CON001', 'Conveyor Charges', 'Cargo', 'REV005', '996511', 'MT'),
    ]
    for code, sname, cat, gl, sac, uom in service_types:
        is_billable = 0 if code == 'DEL001' else 1
        conn.execute(text(
            f"INSERT INTO finance_service_types (service_code, service_name, service_category, gl_code, sac_code, gst_rate_id, uom, is_billable, is_active) "
            f"VALUES ('{code}', '{sname}', '{cat}', '{gl}', '{sac}', NULL, '{uom}', {is_billable}, 1) "
            f"ON CONFLICT (service_code) DO NOTHING"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DELETE FROM module_config"))
    conn.execute(text("DELETE FROM module_permissions"))
    conn.execute(text("DELETE FROM finance_service_types"))
    conn.execute(text("DELETE FROM gst_rates"))
    conn.execute(text("DELETE FROM currency_master"))
    conn.execute(text("DELETE FROM mbc_doc_series"))
    conn.execute(text("DELETE FROM barges"))
    conn.execute(text("DELETE FROM contractors"))
    conn.execute(text("DELETE FROM equipment"))
    conn.execute(text("DELETE FROM delay_account_types"))
    conn.execute(text("DELETE FROM vessel_holds"))
    conn.execute(text("DELETE FROM vessel_hatches"))
    conn.execute(text("DELETE FROM quantity_uom"))
    conn.execute(text("DELETE FROM users"))
