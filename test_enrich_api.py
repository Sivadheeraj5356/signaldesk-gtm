"""Server-level checks for /api/enrich: scoping, suppression, rate limit, storage."""
import datetime, types
import accounts, storage, security, server, enrich

def _mk(tmp_path, monkeypatch):
    db = str(tmp_path / 'e.sqlite3')
    monkeypatch.setenv('SIGNALDESK_DB', db)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', db)
    s = types.SimpleNamespace()
    s.now = datetime.datetime.now(datetime.timezone.utc).isoformat
    s.default_connect = lambda: storage.connect(db, None)
    s.connect_workspace = lambda w: storage.connect(db, w)
    return s

def teardown_function(_):
    server.CTX.ws = None; server.CTX.email = None
    server.RESEARCH_LAST.clear()

def _result(domain):
    return dict(domain=domain, pages_fetched=2, fetched_at='2026-10-21T00:00:00+00:00', errors=[],
                method='Company-published pages only; robots-respecting; no logged-in or third-party sources',
                contacts=[dict(type='email', value='hello@acme.example', label='generic', status='published',
                               source_url='https://acme.example/contact', source='company website',
                               fetched_at='2026-10-21T00:00:00+00:00')])

def test_enrich_happy_path_and_tenant_scoping(tmp_path, monkeypatch):
    s = _mk(tmp_path, monkeypatch)
    monkeypatch.setattr(enrich, 'contacts_for_domain', lambda d, max_pages=6: _result(d))
    ra = accounts.create(s, 'a@b.co', 'tencharacters!')
    rb = accounts.create(s, 'c@d.co', 'tencharacters!')
    server.CTX.ws = ra['ws']
    server.action('/api/import', {'rows': [{'company': 'Acme', 'domain': 'acme.example'}]})
    aid = server.records()[0]['id']
    out = server.action('/api/enrich', {'id': aid})
    assert out['contact_count'] == 1 and out['contacts'][0]['value'] == 'hello@acme.example'
    a = server.records()[0]
    assert a['contacts'][0]['status'] == 'published' and a['contacts'][0]['source_url'].startswith('https://')
    assert 'contacts_fetched_at' in a and 'no logged-in' in a['contacts_method']
    # other tenant sees neither the account nor the contacts
    server.CTX.ws = rb['ws']
    assert server.records() == []
    server.CTX.ws = ra['ws']

def test_enrich_unknown_and_suppressed(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setattr(enrich, 'contacts_for_domain', lambda d, max_pages=6: _result(d))
    server.CTX.ws = 'owner'
    try:
        server.action('/api/enrich', {'id': 'nope'}); assert False
    except ValueError as e: assert 'not found' in str(e).lower()
    server.action('/api/import', {'rows': [{'company': 'Acme', 'domain': 'acme.example'}]})
    a = server.records()[0]
    a['suppressed'] = True; server.save(a)
    try:
        server.action('/api/enrich', {'id': a['id']}); assert False
    except ValueError as e: assert 'suppressed' in str(e).lower()

def test_enrich_rate_limited_per_domain(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setattr(enrich, 'contacts_for_domain', lambda d, max_pages=6: _result(d))
    server.CTX.ws = 'owner'
    server.action('/api/import', {'rows': [{'company': 'Acme', 'domain': 'acme.example'}]})
    aid = server.records()[0]['id']
    server.action('/api/enrich', {'id': aid})
    try:
        server.action('/api/enrich', {'id': aid}); assert False
    except ValueError as e: assert 'one minute' in str(e).lower()

def test_enrich_network_failure_preserves_existing(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    server.CTX.ws = 'owner'
    server.action('/api/import', {'rows': [{'company': 'Acme', 'domain': 'acme.example'}]})
    a = server.records()[0]
    a['contacts'] = [dict(type='email', value='old@acme.example')]; server.save(a)
    monkeypatch.setattr(enrich, 'contacts_for_domain', lambda d, max_pages=6: (_ for _ in ()).throw(RuntimeError('boom')))
    try:
        server.action('/api/enrich', {'id': a['id']}); assert False
    except ValueError as e: assert 'preserved' in str(e).lower()
    assert server.records()[0]['contacts'][0]['value'] == 'old@acme.example'
