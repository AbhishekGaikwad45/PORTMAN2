"""sap_inbound token lifecycle + verification.

_verify_token touches request.headers/remote_addr on the success path (to
record last_used_ip), so it must run inside a Flask request context - a
bare Flask app is enough, the full app.py is not needed.
"""
from flask import Flask
import sap_inbound
from database import get_db, get_cursor

_app = Flask(__name__)


def test_token_generate_verify_revoke():
    sap_inbound.ensure_token_table()
    tok = sap_inbound.generate_token('pytest-token', created_by='t')
    raw = tok['token'] if isinstance(tok, dict) else tok
    try:
        with _app.test_request_context('/api/sap/callback'):
            assert sap_inbound._verify_token('Bearer ' + raw) is not None
            assert sap_inbound._verify_token('Bearer wrong-' + raw) is None
    finally:
        conn = get_db(); cur = get_cursor(conn)
        cur.execute("DELETE FROM sap_inbound_tokens WHERE token=%s", [raw])
        conn.commit(); conn.close()
