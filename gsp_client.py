"""
GST IRP (Invoice Registration Portal) API Client via GSP.

Handles:
- RSA-2048 public-key encryption of the app_key
- AES-256-ECB decryption of the SEK (Session Encryption Key)
- AES-256-ECB encryption of request payloads using SEK
- 6-hour auth token management
- Integration log writing for every API call
"""
import base64
import json
import os
import time
from datetime import datetime

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from database import get_db, get_cursor


# ---------------------------------------------------------------------------
# Session cache (module-level)
# ---------------------------------------------------------------------------
_session = {
    'auth_token': None,
    'sek': None,           # decrypted SEK bytes
    'expires_at': 0,
    'config': None,
}


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------
def _load_public_key(pem_path):
    """Load IRP's RSA-2048 public key from PEM file."""
    with open(pem_path, 'rb') as f:
        return serialization.load_pem_public_key(f.read())


def _rsa_encrypt(plaintext_bytes, public_key):
    """Encrypt bytes with RSA-2048 PKCS1v15 (IRP uses PKCS#1 v1.5)."""
    ciphertext = public_key.encrypt(
        plaintext_bytes,
        asym_padding.PKCS1v15()
    )
    return base64.b64encode(ciphertext).decode()


def _aes_decrypt(encrypted_b64, key_bytes):
    """AES-256-ECB decrypt (IRP uses ECB mode for SEK decryption)."""
    data = base64.b64decode(encrypted_b64)
    cipher = Cipher(algorithms.AES(key_bytes), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    # Remove PKCS7 padding
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _aes_encrypt(plaintext_bytes, key_bytes):
    """AES-256-ECB encrypt with PKCS7 padding."""
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext_bytes) + padder.finalize()
    cipher = Cipher(algorithms.AES(key_bytes), modes.ECB())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode()


def _aes_decrypt_response(encrypted_b64, sek_bytes):
    """Decrypt an IRP response payload encrypted with SEK."""
    return _aes_decrypt(encrypted_b64, sek_bytes)


# ---------------------------------------------------------------------------
# Integration log helper
# ---------------------------------------------------------------------------
def _write_log(integration_type, source_type, source_id, source_reference,
               request_body, response_body, status, error_message=None, created_by=None):
    conn = get_db()
    cur = get_cursor(conn)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute('''INSERT INTO integration_logs
        (integration_type, source_type, source_id, source_reference,
         request_body, response_body, status, error_message,
         created_by, created_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id''',
        [integration_type, source_type, source_id, source_reference,
         json.dumps(request_body) if request_body else None,
         json.dumps(response_body) if response_body else None,
         status, error_message, created_by, now])
    log_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return log_id


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def _get_active_gst_config():
    """Fetch the active gst_api_config row."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM gst_api_config WHERE is_active=1 LIMIT 1')
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _authenticate(config, force=False):
    """
    Authenticate with IRP to obtain AuthToken + SEK.

    Flow:
    1. Generate a random 32-byte app_key
    2. RSA-encrypt app_key with IRP public key
    3. POST /eivital/v1.04/auth with asp_id, asp_secret, encrypted app_key
    4. Decrypt the returned SEK using app_key (AES-256-ECB)
    5. Cache auth_token + decrypted SEK for 6 hours
    """
    global _session
    now = time.time()

    if not force and _session['auth_token'] and now < _session['expires_at']:
        return

    # Generate random 32-byte AES key as app_key
    app_key = os.urandom(32)

    # Load IRP public key and encrypt app_key
    pub_key_path = os.path.join(os.path.dirname(__file__), 'keys', 'irp_public_key.pem')
    public_key = _load_public_key(pub_key_path)
    encrypted_app_key = _rsa_encrypt(app_key, public_key)

    url = f"{config['api_base_url'].rstrip('/')}/eivital/v1.04/auth"
    payload = {
        'Data': encrypted_app_key,
        'ForceRefreshAccessToken': force,
    }
    headers = {
        'Content-Type': 'application/json',
        'client_id': config.get('client_id', ''),
        'client_secret': config.get('client_secret', ''),
        'user_name': config.get('api_username', ''),
        'Gstin': config.get('gstin', ''),
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json()

    if body.get('Status') != 1:
        raise Exception(f"IRP auth failed: {body.get('ErrorDetails', body)}")

    data = body['Data']
    auth_token = data['AuthToken']
    encrypted_sek = data['Sek']

    # Decrypt SEK using our app_key
    sek = _aes_decrypt(encrypted_sek, app_key)

    _session['auth_token'] = auth_token
    _session['sek'] = sek
    _session['config'] = config
    # Token valid for ~6 hours; subtract 5-min buffer
    _session['expires_at'] = now + (6 * 3600) - 300


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_irn(einvoice_json, reference_type, reference_id, reference_number, created_by=None):
    """
    Generate an IRN by posting e-invoice JSON to IRP.

    Parameters
    ----------
    einvoice_json : dict
        The complete e-invoice payload (built by einvoice_builder).
    reference_type : str
        'Invoice' or 'CreditNote'.
    reference_id : int
    reference_number : str
    created_by : str, optional

    Returns
    -------
    dict  {"ok": bool, "irn": str|None, "ack_number": str|None,
           "signed_invoice": str|None, "message": str, "log_id": int}
    """
    config = _get_active_gst_config()
    if not config:
        log_id = _write_log('GST_IRN', reference_type, reference_id, reference_number,
                            einvoice_json, None, 'Error',
                            'No active GST configuration found', created_by)
        return {'ok': False, 'irn': None, 'ack_number': None,
                'signed_invoice': None, 'message': 'No active GST configuration found',
                'log_id': log_id}

    try:
        _authenticate(config)
    except Exception as e:
        log_id = _write_log('GST_IRN', reference_type, reference_id, reference_number,
                            einvoice_json, None, 'Error',
                            f'Auth error: {str(e)}', created_by)
        return {'ok': False, 'irn': None, 'ack_number': None,
                'signed_invoice': None, 'message': f'IRP auth error: {str(e)}',
                'log_id': log_id}

    # Encrypt the e-invoice JSON with SEK
    json_str = json.dumps(einvoice_json)
    encrypted_payload = _aes_encrypt(json_str.encode('utf-8'), _session['sek'])

    url = f"{config['api_base_url'].rstrip('/')}/eicore/v1.03/Invoice"
    headers = {
        'Content-Type': 'application/json',
        'auth-token': _session['auth_token'],
        'client_id': config.get('client_id', ''),
        'Gstin': config['gstin'],
    }
    request_body = {'Data': encrypted_payload}

    try:
        resp = requests.post(url, json=request_body, headers=headers, timeout=60)
        resp_body = resp.json()

        if resp_body.get('Status') == 1:
            # Decrypt the response data with SEK
            encrypted_data = resp_body.get('Data', '')
            if encrypted_data:
                decrypted = _aes_decrypt_response(encrypted_data, _session['sek'])
                result_data = json.loads(decrypted.decode('utf-8'))
            else:
                result_data = {}

            irn = result_data.get('Irn')
            ack_no = result_data.get('AckNo')
            signed_inv = result_data.get('SignedInvoice')

            log_id = _write_log('GST_IRN', reference_type, reference_id, reference_number,
                                einvoice_json, result_data, 'Success', None, created_by)
            return {'ok': True, 'irn': irn, 'ack_number': str(ack_no) if ack_no else None,
                    'signed_invoice': signed_inv, 'message': 'IRN generated successfully',
                    'log_id': log_id}
        else:
            error_details = resp_body.get('ErrorDetails', [])
            error_msg = '; '.join([e.get('ErrorMessage', '') for e in error_details]) if error_details else str(resp_body)
            log_id = _write_log('GST_IRN', reference_type, reference_id, reference_number,
                                einvoice_json, resp_body, 'Error', error_msg, created_by)
            return {'ok': False, 'irn': None, 'ack_number': None,
                    'signed_invoice': None, 'message': f'IRP error: {error_msg}',
                    'log_id': log_id}

    except requests.RequestException as e:
        log_id = _write_log('GST_IRN', reference_type, reference_id, reference_number,
                            einvoice_json, None, 'Error',
                            f'Request failed: {str(e)}', created_by)
        return {'ok': False, 'irn': None, 'ack_number': None,
                'signed_invoice': None, 'message': f'IRP request failed: {str(e)}',
                'log_id': log_id}


def cancel_irn(irn, reason_code, remark, reference_type, reference_id,
               reference_number, created_by=None):
    """
    Cancel a previously generated IRN.

    reason_code: 1=Duplicate, 2=Data Entry Mistake, 3=Order Cancelled, 4=Others
    """
    config = _get_active_gst_config()
    if not config:
        log_id = _write_log('GST_IRN_CANCEL', reference_type, reference_id, reference_number,
                            None, None, 'Error',
                            'No active GST configuration found', created_by)
        return {'ok': False, 'message': 'No active GST configuration found', 'log_id': log_id}

    try:
        _authenticate(config)
    except Exception as e:
        log_id = _write_log('GST_IRN_CANCEL', reference_type, reference_id, reference_number,
                            None, None, 'Error', f'Auth error: {str(e)}', created_by)
        return {'ok': False, 'message': f'IRP auth error: {str(e)}', 'log_id': log_id}

    cancel_data = {
        'Irn': irn,
        'CnlRsn': str(reason_code),
        'CnlRem': remark[:100],
    }
    encrypted_payload = _aes_encrypt(json.dumps(cancel_data).encode('utf-8'), _session['sek'])

    url = f"{config['api_base_url'].rstrip('/')}/eicore/v1.03/Invoice/Cancel"
    headers = {
        'Content-Type': 'application/json',
        'auth-token': _session['auth_token'],
        'client_id': config.get('client_id', ''),
        'Gstin': config['gstin'],
    }

    try:
        resp = requests.post(url, json={'Data': encrypted_payload}, headers=headers, timeout=60)
        resp_body = resp.json()

        if resp_body.get('Status') == 1:
            log_id = _write_log('GST_IRN_CANCEL', reference_type, reference_id, reference_number,
                                cancel_data, resp_body, 'Success', None, created_by)
            return {'ok': True, 'message': 'IRN cancelled successfully', 'log_id': log_id}
        else:
            error_details = resp_body.get('ErrorDetails', [])
            error_msg = '; '.join([e.get('ErrorMessage', '') for e in error_details]) if error_details else str(resp_body)
            log_id = _write_log('GST_IRN_CANCEL', reference_type, reference_id, reference_number,
                                cancel_data, resp_body, 'Error', error_msg, created_by)
            return {'ok': False, 'message': f'Cancel error: {error_msg}', 'log_id': log_id}

    except requests.RequestException as e:
        log_id = _write_log('GST_IRN_CANCEL', reference_type, reference_id, reference_number,
                            cancel_data, None, 'Error',
                            f'Request failed: {str(e)}', created_by)
        return {'ok': False, 'message': f'Cancel request failed: {str(e)}', 'log_id': log_id}
