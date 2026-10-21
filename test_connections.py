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
    conn['access_expires'] = time.time() - 5  # force refresh
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
        if 'profile' in req.full_url: return _R(json.dumps({'emailAddress': 'connected@real.example'}).encode())
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
