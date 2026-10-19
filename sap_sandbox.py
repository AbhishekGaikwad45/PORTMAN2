"""
SAP sandbox — Admin > SAP Sandbox sends a hand-edited DynaportInvoice payload
to a chosen SAP environment (DEV / QAS / production) and keeps what was sent
and what SAP returned in sap_sandbox_log.

Deliberately separate from sap_client: its own token fetch (no shared cache —
a cached production token must never reach QAS or the other way round) and
its own log table, so nothing here touches live invoice posting.
"""
import time
import requests
from psycopg2.extras import Json
from database import get_db, get_cursor


def environments():
    """Configured SAP environments (no secrets) for the sandbox picker."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT id, environment, base_url, is_active FROM sap_api_config
                   ORDER BY (environment = 'production'), id''')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _config(config_id):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('SELECT * FROM sap_api_config WHERE id = %s', [config_id])
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _log(config, url, payload, http_status, body, status, error, duration_ms, sent_by):
    conn = get_db()
    cur = get_cursor(conn)
    rec = (payload.get('Record_Header') or [{}])[0] if isinstance(payload, dict) else {}
    cur.execute('''INSERT INTO sap_sandbox_log
        (sent_by, environment, request_url, reference, request_body,
         http_status, response_body, status, error_message, duration_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
        [sent_by, config.get('environment'), url, rec.get('Reference'),
         Json(payload), http_status, Json(body) if body is not None else None,
         status, error, duration_ms])
    log_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return log_id


def send(config_id, payload, sent_by, confirm_production=False):
    """Post `payload` (dict) to the chosen environment. Raises ValueError for
    a bad request (unknown env, production without confirmation); SAP/network
    failures are logged and returned, not raised."""
    config = _config(config_id)
    if not config:
        raise ValueError('Unknown SAP environment')
    if config.get('environment') == 'production' and not confirm_production:
        raise ValueError('Production posts real documents in SAP — confirm to send')
    if not isinstance(payload, dict) or not payload.get('Record_Header'):
        raise ValueError('Payload must be a JSON object with Record_Header')

    base = (config.get('base_url') or '').rstrip('/')
    url = f'{base}/RESTAdapter/DynaportInvoice'
    started = time.time()
    http_status, body, error = None, None, None
    try:
        tok = requests.post(config.get('token_url') or f'{base}/RESTAdapter/OAuthServer', params={
            'client_id': config['client_id'], 'client_secret': config['client_secret'],
            'grant_type': 'client_credentials'}, timeout=30)
        tok.raise_for_status()
        resp = requests.post(url, json=payload, timeout=120, headers={
            'Authorization': f"Bearer {tok.json()['access_token']}",
            'Content-Type': 'application/json'})
        http_status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = {'raw': resp.text}
        if not resp.ok:
            error = f'HTTP {resp.status_code}'
    except (requests.RequestException, KeyError, ValueError) as e:
        error = f'{type(e).__name__}: {e}'
    duration_ms = int((time.time() - started) * 1000)
    status = 'Error' if error else 'Success'
    log_id = _log(config, url, payload, http_status, body, status, error, duration_ms, sent_by)
    return {'log_id': log_id, 'environment': config.get('environment'), 'request_url': url,
            'status': status, 'http_status': http_status, 'response_body': body,
            'error': error, 'duration_ms': duration_ms}


def history(limit=100):
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute('''SELECT id, to_char(sent_at, 'DD-MM-YYYY HH24:MI:SS') AS sent_at, sent_by,
                          environment, request_url, reference, request_body, http_status,
                          response_body, status, error_message, duration_ms
                   FROM sap_sandbox_log ORDER BY id DESC LIMIT %s''', [limit])
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
