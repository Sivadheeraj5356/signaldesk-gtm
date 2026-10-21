"""Negative checks for the self-serve tenant surface. These gate any public deployment."""
import json, os, types, datetime
import accounts, storage, security, server

def fake_server(path):
    os.environ.pop('DATABASE_URL', None)
    s = types.SimpleNamespace()
    s.now = datetime.datetime.now(datetime.timezone.utc).isoformat
    s.default_connect = lambda: storage.connect(path, None)
    s.connect_workspace = lambda w: storage.connect(path, w)
    s.access_granted = lambda e: False
    return s

def _mk(tmp_path, monkeypatch):
    db = str(tmp_path / 't.sqlite3')
    monkeypatch.setenv('SIGNALDESK_DB', db)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', db)
    monkeypatch.setenv('SIGNALDESK_PASSWORD', 'x' * 16)
    s = fake_server(db)
    security.init(s)
    return s

def teardown_function(_):
    server.CTX.ws = None
    server.CTX.email = None

def test_check_grant_tenant_binding(tmp_path, monkeypatch):
    s = _mk(tmp_path, monkeypatch)
    r = accounts.create(s, 'a@b.co', 'tencharacters!')
    # own workspace: allowed
    assert server.check_grant({'ws': r['ws'], 'email': 'a@b.co'}) is True
    # tampered workspace id in session data: rejected
    assert server.check_grant({'ws': 'u_deadbeef', 'email': 'a@b.co'}) is False
    # unknown tenant email: rejected
    assert server.check_grant({'ws': r['ws'], 'email': 'nobody@e.co'}) is False
    # owner workspace always allowed
    assert server.check_grant({'ws': 'owner'}) is True

def test_tenant_cannot_use_owner_endpoints(tmp_path, monkeypatch):
    s = _mk(tmp_path, monkeypatch)
    r = accounts.create(s, 'a@b.co', 'tencharacters!')
    server.CTX.ws = r['ws']; server.CTX.email = 'a@b.co'
    for path, payload in [('/api/access', {'email': 'x@y.co'}), ('/api/storage/probe', {})]:
        try:
            server.action(path, payload); assert False, path
        except ValueError as e:
            assert 'owner' in str(e).lower()

def test_cross_tenant_data_invisible(tmp_path, monkeypatch):
    s = _mk(tmp_path, monkeypatch)
    ra = accounts.create(s, 'a@b.co', 'tencharacters!')
    rb = accounts.create(s, 'c@d.co', 'tencharacters!')
    server.CTX.ws = ra['ws']
    server.action('/api/import', {'rows': [{'company': 'Acme', 'domain': 'acme.example'}]})
    server.CTX.ws = rb['ws']
    assert server.records() == []
    cfg = server.config()
    assert cfg['company_name'] == ''
    server.CTX.ws = ra['ws']
    assert len(server.records()) == 1

def test_tenant_session_rejects_foreign_workspace(tmp_path, monkeypatch):
    s = _mk(tmp_path, monkeypatch)
    ra = accounts.create(s, 'a@b.co', 'tencharacters!')
    raw, _ = security.tenant_session(s, 'a@b.co', ra['ws'])
    got = security.session(s, 'signaldesk_session=' + raw)
    assert got['ws'] == ra['ws']
    # session for another tenant does not leak into this one
    rb = accounts.create(s, 'c@d.co', 'tencharacters!')
    raw2, _ = security.tenant_session(s, 'c@d.co', rb['ws'])
    got2 = security.session(s, 'signaldesk_session=' + raw2)
    assert got2['ws'] == rb['ws'] != got['ws']

def test_owner_password_not_tenant_login(tmp_path, monkeypatch):
    s = _mk(tmp_path, monkeypatch)
    accounts.create(s, 'a@b.co', 'tencharacters!')
    # owner env password must NOT authenticate a tenant account
    try:
        accounts.authenticate(s, 'a@b.co', 'x' * 16); assert False
    except ValueError as e:
        assert 'Incorrect' in str(e)
