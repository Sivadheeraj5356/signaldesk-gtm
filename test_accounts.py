import json, os, tempfile, types
import accounts, storage, security

def fake_server(path):
    os.environ.pop('DATABASE_URL', None)
    s = types.SimpleNamespace()
    s.now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat
    s.default_connect = lambda: storage.connect(path, None)
    s.connect_workspace = lambda w: storage.connect(path, w)
    s.access_granted = lambda e: False
    return s

def test_signup_login_roundtrip(tmp_path):
    s = fake_server(str(tmp_path / 't.sqlite3'))
    r = accounts.create(s, 'Founder@Example.com', 'tencharacters!')
    assert r['email'] == 'founder@example.com'
    assert r['ws'].startswith('u_')
    u = accounts.authenticate(s, 'founder@example.com', 'tencharacters!')
    assert u['ws'] == r['ws']
    # wrong password rejected
    try:
        accounts.authenticate(s, 'founder@example.com', 'wrong-password')
        assert False
    except ValueError as e:
        assert 'Incorrect' in str(e)

def test_signup_validation(tmp_path):
    s = fake_server(str(tmp_path / 't.sqlite3'))
    for email, pw in [('bad-email', 'tencharacters!'), ('a@b.co', 'short')]:
        try:
            accounts.create(s, email, pw); assert False
        except ValueError: pass

def test_duplicate_signup_rejected(tmp_path):
    s = fake_server(str(tmp_path / 't.sqlite3'))
    accounts.create(s, 'a@b.co', 'tencharacters!')
    try:
        accounts.create(s, 'a@b.co', 'tencharacters!'); assert False
    except ValueError as e:
        assert 'already exists' in str(e)

def test_workspace_provisioned_and_isolated(tmp_path):
    s = fake_server(str(tmp_path / 't.sqlite3'))
    r1 = accounts.create(s, 'a@b.co', 'tencharacters!')
    r2 = accounts.create(s, 'c@d.co', 'tencharacters!')
    assert r1['ws'] != r2['ws']
    # tenant workspaces accept writes independently (schema/file isolation)
    with s.connect_workspace(r1['ws']) as c:
        c.execute('INSERT INTO accounts VALUES(?,?)', ('x', json.dumps({'id': 'x'})))
    with s.connect_workspace(r2['ws']) as c:
        assert c.execute('SELECT data FROM accounts WHERE id=?', ('x',)).fetchone() is None

def test_tenant_session(tmp_path, monkeypatch):
    s = fake_server(str(tmp_path / 't.sqlite3'))
    monkeypatch.setenv('SIGNALDESK_PASSWORD', 'x' * 16)
    security.init(s)
    r = accounts.create(s, 'a@b.co', 'tencharacters!')
    raw, d = security.tenant_session(s, r['email'], r['ws'])
    assert d['ws'] == r['ws'] and d['email'] == r['email']
    got = security.session(s, 'signaldesk_session=' + raw)
    assert got and got['ws'] == r['ws']

def test_company_profile_config(tmp_path, monkeypatch):
    import server
    s = fake_server(str(tmp_path / 't.sqlite3'))
    monkeypatch.setenv('SIGNALDESK_DB', str(tmp_path / 't.sqlite3'))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', str(tmp_path / 't.sqlite3'))
    r = accounts.create(s, 'a@b.co', 'tencharacters!')
    server.CTX.ws = r['ws']
    cfg = server.action('/api/config', dict(company_name='Acme', company_website='https://www.acme.example/',
                                            company_details='B2B widgets', linkedin='https://www.linkedin.com/company/acme'))
    assert cfg['company_website'] == 'acme.example'
    assert cfg['linkedin'] == 'https://www.linkedin.com/company/acme'
    # bad linkedin rejected
    try:
        server.action('/api/config', dict(linkedin='https://example.com/not-linkedin')); assert False
    except ValueError as e:
        assert 'LinkedIn' in str(e)
    server.CTX.ws = None
