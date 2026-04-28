"""initial_schema

Revision ID: 5cc47bd6c31d
Revises:
Create Date: 2026-02-02
"""
from typing import Sequence, Union
from alembic import op

revision: str = '5cc47bd6c31d'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Core tables from database.py ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS module_permissions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            module_code TEXT NOT NULL,
            can_read INTEGER DEFAULT 1,
            can_add INTEGER DEFAULT 0,
            can_edit INTEGER DEFAULT 0,
            can_delete INTEGER DEFAULT 0,
            UNIQUE(user_id, module_code),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS module_config (
            id SERIAL PRIMARY KEY,
            module_code TEXT UNIQUE NOT NULL,
            config_json TEXT DEFAULT '{}'
        )
    ''')

    # === Simple master tables ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_types (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_categories (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS gears (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_agents (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_operation_types (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_call_doc_series (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_type_of_discharge (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_run_types (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_delay_types (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_cargo (
            id SERIAL PRIMARY KEY,
            cargo_type TEXT,
            cargo_category TEXT,
            cargo_name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS quantity_uom (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_hatches (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_holds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS delay_account_types (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS equipment (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS contractors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS barges (
            id SERIAL PRIMARY KEY,
            barge_name TEXT NOT NULL UNIQUE,
            dwt REAL
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_master (
            id SERIAL PRIMARY KEY,
            mbc_name TEXT NOT NULL UNIQUE,
            dwt REAL
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS port_berth_master (
            id SERIAL PRIMARY KEY,
            berth_name TEXT NOT NULL UNIQUE,
            berth_location TEXT,
            remarks TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_doc_series (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vex_doc_series (
            id SERIAL PRIMARY KEY,
            name TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS conveyor_routes (
            id SERIAL PRIMARY KEY,
            route_name TEXT NOT NULL,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_date TEXT
        )
    ''')

    # === Vessel master (VC01) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS vessels (
            id SERIAL PRIMARY KEY,
            doc_num TEXT,
            doc_status TEXT,
            vessel_name TEXT,
            imo_num TEXT,
            vessel_type_name TEXT,
            vessel_category_name TEXT,
            gear TEXT,
            gt REAL,
            loa REAL,
            beam REAL,
            year_of_built INTEGER,
            created_by TEXT,
            created_date TEXT
        )
    ''')

    # === Importer/Exporter and Customer masters ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_importer_exporters (
            id SERIAL PRIMARY KEY,
            name TEXT,
            gl_code TEXT,
            gstin TEXT,
            gst_state_code TEXT,
            gst_state_name TEXT,
            pan TEXT,
            billing_address TEXT,
            city TEXT,
            pincode TEXT,
            contact_person TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            default_currency TEXT DEFAULT 'INR'
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vessel_customers (
            id SERIAL PRIMARY KEY,
            name TEXT,
            gl_code TEXT,
            gstin TEXT,
            gst_state_code TEXT,
            gst_state_name TEXT,
            pan TEXT,
            billing_address TEXT,
            city TEXT,
            pincode TEXT,
            contact_person TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            default_currency TEXT DEFAULT 'INR'
        )
    ''')

    # === Finance masters ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS gst_rates (
            id SERIAL PRIMARY KEY,
            rate_name TEXT NOT NULL,
            cgst_rate REAL,
            sgst_rate REAL,
            igst_rate REAL,
            effective_from TEXT,
            effective_to TEXT,
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_date TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS currency_master (
            id SERIAL PRIMARY KEY,
            currency_code TEXT UNIQUE NOT NULL,
            currency_name TEXT NOT NULL,
            currency_symbol TEXT,
            is_base_currency INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_date TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS currency_exchange_rates (
            id SERIAL PRIMARY KEY,
            from_currency TEXT NOT NULL,
            to_currency TEXT NOT NULL,
            exchange_rate REAL NOT NULL,
            effective_date TEXT NOT NULL,
            rate_type TEXT DEFAULT 'Mid',
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_date TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS finance_service_types (
            id SERIAL PRIMARY KEY,
            service_code TEXT UNIQUE NOT NULL,
            service_name TEXT NOT NULL,
            service_category TEXT,
            gl_code TEXT,
            sac_code TEXT,
            gst_rate_id INTEGER,
            uom TEXT,
            is_billable INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_date TEXT,
            FOREIGN KEY (gst_rate_id) REFERENCES gst_rates(id)
        )
    ''')

    # === Customer Agreements (FCAM01) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS customer_agreements (
            id SERIAL PRIMARY KEY,
            agreement_code TEXT UNIQUE NOT NULL,
            customer_type TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            customer_name TEXT,
            agreement_name TEXT,
            currency_code TEXT DEFAULT 'INR',
            valid_from TEXT,
            valid_to TEXT,
            is_active INTEGER DEFAULT 1,
            agreement_status TEXT DEFAULT 'Draft',
            created_by TEXT,
            created_date TEXT,
            approved_by TEXT,
            approved_date TEXT,
            remarks TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS customer_agreement_lines (
            id SERIAL PRIMARY KEY,
            agreement_id INTEGER NOT NULL,
            service_type_id INTEGER NOT NULL,
            service_name TEXT,
            rate REAL NOT NULL,
            uom TEXT,
            currency_code TEXT,
            min_charge REAL,
            max_charge REAL,
            remarks TEXT,
            FOREIGN KEY (agreement_id) REFERENCES customer_agreements(id) ON DELETE CASCADE,
            FOREIGN KEY (service_type_id) REFERENCES finance_service_types(id)
        )
    ''')

    # === VCN01 (Vessel Call Nomination) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_header (
            id SERIAL PRIMARY KEY,
            vcn_doc_num TEXT,
            vessel_master_doc TEXT,
            vessel_name TEXT,
            vessel_agent_name TEXT,
            importer_exporter_name TEXT,
            customer_name TEXT,
            operation_type TEXT,
            cargo_type TEXT,
            vcn_doc_series TEXT,
            type_of_discharge TEXT,
            doc_date TEXT,
            doc_status TEXT DEFAULT 'Pending',
            created_by TEXT,
            created_date TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_nominations (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            eta TEXT,
            etd TEXT,
            vessel_run_type TEXT,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_anchorage (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            latitude TEXT,
            longitude TEXT,
            anchored_time TEXT,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_delays (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            delay_name TEXT,
            delay_start TEXT,
            delay_end TEXT,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_cargo_declaration (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            cargo_name TEXT,
            bl_no TEXT,
            bl_date TEXT,
            bl_quantity REAL,
            quantity_uom TEXT,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_igm (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            igm_number TEXT,
            igm_manual_number TEXT,
            igm_date TEXT,
            dwt REAL,
            bl_quantity REAL,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vcn_stowage_plan (
            id SERIAL PRIMARY KEY,
            vcn_id INTEGER NOT NULL,
            cargo_name TEXT,
            hatch_name TEXT,
            hold_name TEXT,
            hatchwise_quantity REAL,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id) ON DELETE CASCADE
        )
    ''')

    # === LDUD01 (Loading/Unloading) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_header (
            id SERIAL PRIMARY KEY,
            doc_num TEXT,
            vcn_id INTEGER,
            vcn_doc_num TEXT,
            vessel_name TEXT,
            anchored_datetime TEXT,
            arrival_inner_anchorage TEXT,
            arrival_outer_anchorage TEXT,
            arrived_mbpt TEXT,
            arrived_mfl TEXT,
            free_pratique_granted TEXT,
            nor_tendered TEXT,
            nor_accepted TEXT,
            discharge_commenced TEXT,
            discharge_completed TEXT,
            initial_draft_survey_from TEXT,
            initial_draft_survey_to TEXT,
            initial_draft_survey_quantity REAL,
            final_draft_survey_from TEXT,
            final_draft_survey_to TEXT,
            doc_status TEXT DEFAULT 'Pending',
            created_by TEXT,
            created_date TEXT,
            FOREIGN KEY (vcn_id) REFERENCES vcn_header(id)
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_delays (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER NOT NULL,
            delay_name TEXT,
            delay_account_type TEXT,
            equipment_name TEXT,
            start_datetime TEXT,
            end_datetime TEXT,
            total_time_mins REAL,
            total_time_hrs REAL,
            delays_to_sof TEXT,
            invoiceable TEXT,
            minus_delay_hours TEXT,
            FOREIGN KEY (ldud_id) REFERENCES ldud_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS ldud_barge_lines (
            id SERIAL PRIMARY KEY,
            ldud_id INTEGER NOT NULL,
            trip_number INTEGER,
            hold_name TEXT,
            barge_name TEXT,
            contractor_name TEXT,
            cargo_name TEXT,
            bpt_bfl TEXT,
            along_side_vessel TEXT,
            commenced_loading TEXT,
            completed_loading TEXT,
            cast_off_mv TEXT,
            anchored_gull_island TEXT,
            aweigh_gull_island TEXT,
            along_side_berth TEXT,
            commence_discharge_berth TEXT,
            completed_discharge_berth TEXT,
            cast_off_berth TEXT,
            cast_off_berth_nt TEXT,
            discharge_quantity REAL,
            FOREIGN KEY (ldud_id) REFERENCES ldud_header(id) ON DELETE CASCADE
        )
    ''')

    # === MBC01 (MBC Operations) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_header (
            id SERIAL PRIMARY KEY,
            doc_num TEXT,
            doc_series TEXT,
            doc_date TEXT,
            mbc_name TEXT,
            operation_type TEXT,
            cargo_type TEXT,
            cargo_name TEXT,
            bl_quantity REAL,
            quantity_uom TEXT,
            doc_status TEXT DEFAULT 'Pending',
            created_by TEXT,
            created_date TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_delays (
            id SERIAL PRIMARY KEY,
            mbc_id INTEGER NOT NULL,
            delay_name TEXT,
            delay_account_type TEXT,
            equipment_name TEXT,
            start_datetime TEXT,
            end_datetime TEXT,
            total_time_mins REAL,
            total_time_hrs REAL,
            delays_to_sof TEXT,
            invoiceable TEXT,
            minus_delay_hours TEXT,
            FOREIGN KEY (mbc_id) REFERENCES mbc_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_load_port_lines (
            id SERIAL PRIMARY KEY,
            mbc_id INTEGER NOT NULL,
            arrived_load_port TEXT,
            alongside_berth TEXT,
            loading_commenced TEXT,
            loading_completed TEXT,
            cast_off_load_port TEXT,
            FOREIGN KEY (mbc_id) REFERENCES mbc_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS mbc_discharge_port_lines (
            id SERIAL PRIMARY KEY,
            mbc_id INTEGER NOT NULL,
            arrival_gull_island TEXT,
            departure_gull_island TEXT,
            vessel_arrival_port TEXT,
            vessel_all_made_fast TEXT,
            unloading_commenced TEXT,
            cleaning_commenced TEXT,
            unloading_completed TEXT,
            vessel_cast_off TEXT,
            vessel_unloaded_by TEXT,
            vessel_unloading_berth TEXT,
            discharge_stop_shifting TEXT,
            discharge_start_shifting TEXT,
            FOREIGN KEY (mbc_id) REFERENCES mbc_header(id) ON DELETE CASCADE
        )
    ''')

    # === LUEU01 (Load Unload Equipment Utilization) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS lueu_lines (
            id SERIAL PRIMARY KEY,
            source_type TEXT,
            source_id INTEGER,
            source_display TEXT,
            barge_name TEXT,
            equipment_name TEXT,
            operator_name TEXT,
            delay_name TEXT,
            cargo_name TEXT,
            operation_type TEXT,
            quantity REAL,
            quantity_uom TEXT,
            route_name TEXT,
            start_time TEXT,
            end_time TEXT,
            entry_date TEXT,
            created_by TEXT,
            created_date TEXT,
            is_billed INTEGER DEFAULT 0,
            bill_id INTEGER,
            service_type_id INTEGER
        )
    ''')

    # === VEX01 (Vessel Export) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS vex_header (
            id SERIAL PRIMARY KEY,
            vex_doc_num TEXT,
            doc_series TEXT,
            vessel_name TEXT,
            customer_name TEXT,
            cargo_name TEXT,
            bill_of_coastal_goods_date TEXT,
            bill_of_coastal_goods_qty REAL,
            quantity_uom TEXT,
            doc_status TEXT DEFAULT 'Pending',
            created_by TEXT,
            created_date TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vex_barge_lines (
            id SERIAL PRIMARY KEY,
            vex_id INTEGER NOT NULL,
            barge_name TEXT,
            FOREIGN KEY (vex_id) REFERENCES vex_header(id) ON DELETE CASCADE
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS vex_mbc_lines (
            id SERIAL PRIMARY KEY,
            vex_id INTEGER NOT NULL,
            mbc_name TEXT,
            FOREIGN KEY (vex_id) REFERENCES vex_header(id) ON DELETE CASCADE
        )
    ''')

    # === FIN01 (Billing & Invoicing) ===
    op.execute('''
        CREATE TABLE IF NOT EXISTS bill_header (
            id SERIAL PRIMARY KEY,
            bill_number TEXT UNIQUE NOT NULL,
            bill_date TEXT NOT NULL,
            bill_series TEXT,
            bill_type TEXT DEFAULT 'Standard',
            source_type TEXT,
            source_id INTEGER,
            source_display TEXT,
            customer_type TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            customer_name TEXT,
            customer_gstin TEXT,
            customer_gst_state_code TEXT,
            customer_gl_code TEXT,
            currency_code TEXT DEFAULT 'INR',
            exchange_rate REAL DEFAULT 1.0,
            subtotal REAL DEFAULT 0,
            cgst_amount REAL DEFAULT 0,
            sgst_amount REAL DEFAULT 0,
            igst_amount REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            bill_status TEXT DEFAULT 'Draft',
            created_by TEXT,
            created_date TEXT,
            approved_by TEXT,
            approved_date TEXT,
            rejection_reason TEXT,
            remarks TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS bill_lines (
            id SERIAL PRIMARY KEY,
            bill_id INTEGER NOT NULL,
            eu_line_id INTEGER,
            service_type_id INTEGER NOT NULL,
            service_name TEXT,
            service_description TEXT,
            quantity REAL,
            uom TEXT,
            rate REAL NOT NULL,
            line_amount REAL NOT NULL,
            gst_rate_id INTEGER,
            cgst_rate REAL DEFAULT 0,
            sgst_rate REAL DEFAULT 0,
            igst_rate REAL DEFAULT 0,
            cgst_amount REAL DEFAULT 0,
            sgst_amount REAL DEFAULT 0,
            igst_amount REAL DEFAULT 0,
            line_total REAL NOT NULL,
            gl_code TEXT,
            sac_code TEXT,
            remarks TEXT,
            FOREIGN KEY (bill_id) REFERENCES bill_header(id) ON DELETE CASCADE,
            FOREIGN KEY (eu_line_id) REFERENCES lueu_lines(id),
            FOREIGN KEY (service_type_id) REFERENCES finance_service_types(id),
            FOREIGN KEY (gst_rate_id) REFERENCES gst_rates(id)
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS invoice_header (
            id SERIAL PRIMARY KEY,
            invoice_number TEXT UNIQUE NOT NULL,
            invoice_date TEXT NOT NULL,
            financial_year TEXT NOT NULL,
            invoice_series TEXT,
            customer_type TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            customer_name TEXT,
            customer_gstin TEXT,
            customer_gst_state_code TEXT,
            customer_gl_code TEXT,
            customer_pan TEXT,
            billing_address TEXT,
            customer_city TEXT,
            customer_pincode TEXT,
            customer_phone TEXT,
            customer_email TEXT,
            currency_code TEXT DEFAULT 'INR',
            exchange_rate REAL DEFAULT 1.0,
            subtotal REAL DEFAULT 0,
            cgst_amount REAL DEFAULT 0,
            sgst_amount REAL DEFAULT 0,
            igst_amount REAL DEFAULT 0,
            tds_amount REAL DEFAULT 0,
            round_off REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            amount_in_words TEXT,
            invoice_status TEXT DEFAULT 'Generated',
            payment_terms TEXT,
            due_date TEXT,
            sap_document_number TEXT,
            sap_posting_date TEXT,
            sap_fiscal_year TEXT,
            sap_company_code TEXT,
            gst_irn TEXT,
            gst_ack_number TEXT,
            gst_ack_date TEXT,
            gst_qr_code TEXT,
            created_by TEXT,
            created_date TEXT,
            posted_by TEXT,
            posted_date TEXT,
            remarks TEXT
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS invoice_lines (
            id SERIAL PRIMARY KEY,
            invoice_id INTEGER NOT NULL,
            bill_id INTEGER,
            bill_number TEXT,
            line_number INTEGER NOT NULL,
            service_name TEXT,
            service_description TEXT,
            quantity REAL,
            uom TEXT,
            rate REAL NOT NULL,
            line_amount REAL NOT NULL,
            cgst_rate REAL DEFAULT 0,
            sgst_rate REAL DEFAULT 0,
            igst_rate REAL DEFAULT 0,
            cgst_amount REAL DEFAULT 0,
            sgst_amount REAL DEFAULT 0,
            igst_amount REAL DEFAULT 0,
            line_total REAL NOT NULL,
            gl_code TEXT,
            sac_code TEXT,
            profit_center TEXT,
            cost_center TEXT,
            FOREIGN KEY (invoice_id) REFERENCES invoice_header(id) ON DELETE CASCADE,
            FOREIGN KEY (bill_id) REFERENCES bill_header(id)
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS invoice_bill_mapping (
            id SERIAL PRIMARY KEY,
            invoice_id INTEGER NOT NULL,
            bill_id INTEGER NOT NULL,
            bill_number TEXT,
            bill_amount REAL,
            FOREIGN KEY (invoice_id) REFERENCES invoice_header(id) ON DELETE CASCADE,
            FOREIGN KEY (bill_id) REFERENCES bill_header(id)
        )
    ''')

    op.execute('''
        CREATE TABLE IF NOT EXISTS gst_api_config (
            id SERIAL PRIMARY KEY,
            api_base_url TEXT,
            api_username TEXT,
            api_password TEXT,
            gstin TEXT,
            client_id TEXT,
            client_secret TEXT,
            auth_token TEXT,
            sek TEXT,
            token_expiry TEXT,
            environment TEXT DEFAULT 'sandbox',
            is_active INTEGER DEFAULT 1,
            created_date TEXT
        )
    ''')


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute('DROP TABLE IF EXISTS gst_api_config CASCADE')
    op.execute('DROP TABLE IF EXISTS invoice_bill_mapping CASCADE')
    op.execute('DROP TABLE IF EXISTS invoice_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS invoice_header CASCADE')
    op.execute('DROP TABLE IF EXISTS bill_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS bill_header CASCADE')
    op.execute('DROP TABLE IF EXISTS vex_mbc_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS vex_barge_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS vex_header CASCADE')
    op.execute('DROP TABLE IF EXISTS lueu_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_discharge_port_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_load_port_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_delays CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_header CASCADE')
    op.execute('DROP TABLE IF EXISTS ldud_barge_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS ldud_delays CASCADE')
    op.execute('DROP TABLE IF EXISTS ldud_header CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_stowage_plan CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_igm CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_cargo_declaration CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_delays CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_anchorage CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_nominations CASCADE')
    op.execute('DROP TABLE IF EXISTS vcn_header CASCADE')
    op.execute('DROP TABLE IF EXISTS customer_agreement_lines CASCADE')
    op.execute('DROP TABLE IF EXISTS customer_agreements CASCADE')
    op.execute('DROP TABLE IF EXISTS finance_service_types CASCADE')
    op.execute('DROP TABLE IF EXISTS currency_exchange_rates CASCADE')
    op.execute('DROP TABLE IF EXISTS currency_master CASCADE')
    op.execute('DROP TABLE IF EXISTS gst_rates CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_customers CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_importer_exporters CASCADE')
    op.execute('DROP TABLE IF EXISTS vessels CASCADE')
    op.execute('DROP TABLE IF EXISTS conveyor_routes CASCADE')
    op.execute('DROP TABLE IF EXISTS vex_doc_series CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_doc_series CASCADE')
    op.execute('DROP TABLE IF EXISTS port_berth_master CASCADE')
    op.execute('DROP TABLE IF EXISTS mbc_master CASCADE')
    op.execute('DROP TABLE IF EXISTS barges CASCADE')
    op.execute('DROP TABLE IF EXISTS contractors CASCADE')
    op.execute('DROP TABLE IF EXISTS equipment CASCADE')
    op.execute('DROP TABLE IF EXISTS delay_account_types CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_holds CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_hatches CASCADE')
    op.execute('DROP TABLE IF EXISTS quantity_uom CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_cargo CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_delay_types CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_run_types CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_type_of_discharge CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_call_doc_series CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_operation_types CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_agents CASCADE')
    op.execute('DROP TABLE IF EXISTS gears CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_categories CASCADE')
    op.execute('DROP TABLE IF EXISTS vessel_types CASCADE')
    op.execute('DROP TABLE IF EXISTS module_config CASCADE')
    op.execute('DROP TABLE IF EXISTS module_permissions CASCADE')
    op.execute('DROP TABLE IF EXISTS users CASCADE')
