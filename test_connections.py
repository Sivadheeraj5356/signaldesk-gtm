"""Per-workspace Gmail connections: storage, refresh rotation, fail-closed expiry,
identity binding at approval, token secrecy in state."""
import json, time
import pytest
import server, connections, senders

def _mk(tmp_path, monkeypatch):
    db = str(tmp_path / 'c.sqlite3')
    monkeypatch.setenv('SIGNALDESK_DB', db)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', db)

def teardown_function(_):
    server.CTX.ws = None; server.CTX.email = None

class _R:
    def __init__(self, body): self.body = body
    def read(self, n=-1): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_connection_storage_and_public_state(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    connections.save_gmail(server, 'Siva@Kernely.example', 'REFRESH-SECRET-1', 'ACCESS-SECRET-1', 3600)
    pub = connections.public_state(server)
    assert pub[0]['identity'] == 'siva@kernely.example' and pub[0]['status'] == 'active'
    blob = json.dumps(pub) + json.dumps(server.state())
    assert 'REFRESH-SECRET-1' not in blob and 'ACCESS-SECRET-1' not in blob

def test_access_token_cached_then_refreshed(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cid'); monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'csec')
    conn = connections.save_gmail(server, 'a@b.example', 'REFRESH-1', 'ACCESS-OLD', 3600)
    assert connections.gmail_access_token(server, conn) == 'ACCESS-OLD'  # cached, no network
    conn = connections.save_gmail(server, 'a@b.example', 'REFRESH-1', 'ACCESS-OLD', -10)  # expired, forces refresh
    calls = []
    def fake_post(url, params, timeout=15):
        calls.append(params)
        return {'access_token': 'ACCESS-NEW', 'expires_in': 3600}
    monkeypatch.setattr(connections, '_post', fake_post)
    assert connections.gmail_access_token(server, conn) == 'ACCESS-NEW'
    assert calls[0]['refresh_token'] == 'REFRESH-1' and calls[0]['grant_type'] == 'refresh_token'
    # refreshed token persisted
    assert connections.get(server, 'gmail')['access_token'] == 'ACCESS-NEW'

def test_refresh_failure_marks_expired_fail_closed(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cid'); monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'csec')
    conn = connections.save_gmail(server, 'a@b.example', 'REFRESH-BAD', '', 0)
    def boom(url, params, timeout=15): raise OSError('invalid_grant')
    monkeypatch.setattr(connections, '_post', boom)
    with pytest.raises(ValueError) as e:
        connections.gmail_access_token(server, conn)
    assert 'reconnect' in str(e.value)
    assert connections.list_connections(server)[0]['status'] == 'expired'
    # expired connection is no longer returned as active
    assert connections.get(server, 'gmail') is None

def test_send_uses_connection_identity_over_env(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setenv('SIGNALDESK_GMAIL_ACCESS_TOKEN', 'ENV-TOKEN')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cid'); monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'csec')
    connections.save_gmail(server, 'connected@real.example', 'REFRESH-1', 'ACCESS-1', 3600)
    # approval for a different sender must be rejected against the connection identity
    server.action('/api/config', dict(server.DEFAULT, industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email'))
    server.save(dict(id='a1', company='Acme', domain='acme.example', contact='Priya', contact_email='p@acme.example',
                     subject='Hi', evidence='', source='', industry='SaaS', region='', size=30, score=85,
                     draft='Body', approved=True, suppressed=False, reasons=[], engine='template', updated=''))
    c = server.action('/api/outreach/create', dict(name='Q', channel='email', booking_link=''))
    server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['a1']))
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/approve-send', dict(id=c['id'], sender='other@else.example', confirmed=True))
    assert 'connected Gmail account' in str(e.value)
    ok = server.action('/api/outreach/approve-send', dict(id=c['id'], sender='connected@real.example', confirmed=True))
    assert ok['send_approval']['sender'] == 'connected@real.example'
    # real send path: connection token used, identity matches, gmail deliver attempted via mocked transport
    import base64
    def fake_urlopen(req, timeout=None):
        if 'userinfo' in req.full_url: return _R(json.dumps({'email': 'connected@real.example', 'email_verified': True}).encode())
        return _R(json.dumps({'id': 'msg-1', 'threadId': 'th-1'}).encode())
    monkeypatch.setattr(senders.urllib.request, 'urlopen', fake_urlopen)
    r = server.action('/api/outreach/send', dict(id=c['id'], account_id='a1', provider='gmail', dry_run=False))
    assert r['delivered'] is True and r['sender'] == 'connected@real.example'

def test_disconnect_revokes_and_removes_active(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    connections.save_gmail(server, 'a@b.example', 'REFRESH-1', 'ACCESS-1', 3600)
    monkeypatch.setattr(connections.urllib.request, 'urlopen', lambda req, timeout=None: _R(b'{}'))
    r = connections.disconnect(server, 'gmail')
    assert r['disconnected'] == 'gmail'
    assert connections.get(server, 'gmail') is None


def test_tokens_encrypted_at_rest(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    connections.save_gmail(server, 'a@b.example', 'REFRESH-PLAINTEXT-MARKER', 'ACCESS-PLAINTEXT-MARKER', 3600)
    with server.connect() as c:
        blob = c.execute('SELECT data FROM connections').fetchone()[0]
    assert 'REFRESH-PLAINTEXT-MARKER' not in blob and 'ACCESS-PLAINTEXT-MARKER' not in blob
    # working copy still decrypts
    assert connections.get(server, 'gmail')['refresh_token'] == 'REFRESH-PLAINTEXT-MARKER'

def test_disconnect_revoke_failure_still_removes(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    connections.save_gmail(server, 'a@b.example', 'REFRESH-1', 'ACCESS-1', 3600)
    def boom(req, timeout=None): raise OSError('network down')
    monkeypatch.setattr(connections.urllib.request, 'urlopen', boom)
    r = connections.disconnect(server, 'gmail')
    assert r['revoked_at_google'] is False
    assert connections.get(server, 'gmail') is None  # fail-closed locally
    # tokens wiped from the stored blob
    with server.connect() as c:
        blob = json.loads(c.execute('SELECT data FROM connections').fetchone()[0])
    assert blob['refresh_token'] == '' and blob['access_token'] == ''

def test_revoke_uses_post_body_not_url(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    connections.save_gmail(server, 'a@b.example', 'REFRESH-MARKER-9', 'ACCESS-1', 3600)
    seen = {}
    def fake(req, timeout=None):
        seen['url'] = req.full_url; seen['body'] = req.data.decode()
        return _R(b'{}')
    monkeypatch.setattr(connections.urllib.request, 'urlopen', fake)
    connections.disconnect(server, 'gmail')
    assert 'REFRESH-MARKER-9' not in seen['url'] and 'REFRESH-MARKER-9' in seen['body']

def test_single_refresh_under_concurrency(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cid'); monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'csec')
    conn = connections.save_gmail(server, 'a@b.example', 'REFRESH-1', '', 0)
    calls = []
    def fake_post(url, params, timeout=15):
        import time as _t; _t.sleep(0.05); calls.append(1)
        return {'access_token': 'ACCESS-FRESH', 'expires_in': 3600}
    monkeypatch.setattr(connections, '_post', fake_post)
    import threading
    results = []
    def worker(): results.append(connections.gmail_access_token(server, dict(conn)))
    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(calls) == 1 and all(r == 'ACCESS-FRESH' for r in results)

def test_pkce_and_minimal_scope_in_connect_url(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    with server.default_connect() as c: c.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cid'); monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'csec')
    import security
    url = security.gmail_connect_start(server, 'owner', 'owner@x.example')
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(url).query)
    assert q['scope'][0] == 'openid email https://www.googleapis.com/auth/gmail.send'
    assert q['code_challenge_method'][0] == 'S256' and len(q['code_challenge'][0]) >= 43
    assert q['access_type'][0] == 'offline' and q['prompt'][0] == 'consent'
    # finish sends the verifier with the exchange
    state = q['state'][0]
    exchanged = {}
    def fake_urlopen(req, timeout=None):
        if 'token' in req.full_url:
            exchanged.update(__import__('urllib.parse', fromlist=['parse_qs']).parse_qs(req.data.decode()))
            return _R(json.dumps({'access_token': 'ACC', 'refresh_token': 'REF', 'expires_in': 3600}).encode())
        return _R(json.dumps({'email': 'person@real.example', 'email_verified': True}).encode())
    monkeypatch.setattr(connections.urllib.request, 'urlopen', fake_urlopen)  # patches the shared urllib.request module
    r = security.gmail_connect_finish(server, 'CODE', state)
    assert r['connected'] == 'person@real.example'
    assert exchanged['code_verifier'][0] and exchanged['grant_type'] == ['authorization_code']
    assert connections.get(server, 'gmail')['identity'] == 'person@real.example'
    # state nonce is one-time
    import pytest as _pt
    with _pt.raises(ValueError): security.gmail_connect_finish(server, 'CODE', state)
