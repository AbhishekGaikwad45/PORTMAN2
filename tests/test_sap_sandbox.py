"""Admin SAP sandbox: sends to the chosen environment, refuses production
without confirmation, and logs request + response as JSONB in sap_sandbox_log.
No network: requests.post is faked. Uses the dev DB; created rows are removed."""
import pytest
import sap_sandbox
from app import app
from database import get_db, get_cursor

PAYLOAD = {'Record_Header': [{'Reference': 'JJLTPL-2627-/1', 'ITEM': []}]}


class _Resp:
    def __init__(self, status, body=None, text=''):
        self.status_code, self._body, self.text = status, body, text
        self.ok = status < 400
    def json(self):
        if self._body is None:
            raise ValueError('not json')
        return self._body
    def raise_for_status(self):
        if not self.ok:
            raise sap_sandbox.requests.HTTPError(str(self.status_code))


def _env(name):
    return next(e for e in sap_sandbox.environments() if e['environment'] == name)


@pytest.fixture
def client(monkeypatch):
    calls = []
    def fake_post(url, **kw):
        calls.append(url)
        if url.endswith('OAuthServer'):
            return _Resp(200, {'access_token': 'tok', 'expires_in': 3600})
        return _Resp(200, {'Document_Number': '5100000001', 'Message': 'Posted'})
    monkeypatch.setattr(sap_sandbox.requests, 'post', fake_post)
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'], s['is_admin'], s['username'] = 1, True, 'tester'
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('SELECT COALESCE(MAX(id), 0) AS m FROM sap_sandbox_log'); start = cur.fetchone()['m']
    conn.close()
    yield c, calls
    conn = get_db(); cur = get_cursor(conn)
    cur.execute('DELETE FROM sap_sandbox_log WHERE id > %s', [start]); conn.commit(); conn.close()


def test_send_to_qas_logs_request_and_response(client):
    c, calls = client
    qas = _env('quality')
    import json
    r = c.post('/admin/api/sap-sandbox/send', json={'config_id': qas['id'], 'payload': json.dumps(PAYLOAD)})
    out = r.get_json()
    assert r.status_code == 200 and out['status'] == 'Success'
    assert all(u.startswith(qas['base_url']) for u in calls)        # never production
    row = next(x for x in c.get('/admin/api/sap-sandbox/log').get_json() if x['id'] == out['log_id'])
    assert row['request_body'] == PAYLOAD                             # JSONB round-trip
    assert row['response_body']['Document_Number'] == '5100000001'
    assert (row['environment'], row['reference'], row['sent_by']) == ('quality', 'JJLTPL-2627-/1', 'tester')


def test_production_needs_confirmation_and_bad_json_is_refused(client):
    c, calls = client
    prod = _env('production')
    r = c.post('/admin/api/sap-sandbox/send', json={'config_id': prod['id'], 'payload': '{"Record_Header": [{}]}'})
    assert r.status_code == 400 and 'confirm' in r.get_json()['error']
    r = c.post('/admin/api/sap-sandbox/send', json={'config_id': prod['id'], 'payload': '{oops'})
    assert r.status_code == 400 and 'JSON' in r.get_json()['error']
    assert calls == []                                                # nothing reached SAP


def test_sap_error_is_logged_not_raised(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(sap_sandbox.requests, 'post',
                        lambda url, **kw: _Resp(200, {'access_token': 't'}) if url.endswith('OAuthServer')
                        else _Resp(500, None, '<html>boom</html>'))
    out = sap_sandbox.send(_env('quality')['id'], PAYLOAD, 'tester')
    assert out['status'] == 'Error' and out['http_status'] == 500
    assert out['response_body'] == {'raw': '<html>boom</html>'}
