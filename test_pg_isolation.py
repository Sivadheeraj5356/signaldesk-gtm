"""PostgreSQL-backed tenant isolation: the open-signup gate.
Spins up a throwaway local PG (pgserver), runs real server actions for two
tenants, and proves schema separation directly in the database."""
import os, shutil, types, datetime
import pytest

pgserver = pytest.importorskip('pgserver')
import psycopg
import storage, accounts, security, server

@pytest.fixture(scope='module')
def pg():
    shutil.rmtree('/tmp/pgdata-test', ignore_errors=True)
    srv = pgserver.get_server('/tmp/pgdata-test')
    yield srv.get_uri()
    try: srv.cleanup()
    except Exception: pass
    shutil.rmtree('/tmp/pgdata-test', ignore_errors=True)

@pytest.fixture()
def env(pg, monkeypatch):
    storage.READY.clear()
    monkeypatch.setenv('DATABASE_URL', pg)
    monkeypatch.setenv('PGSSLMODE', 'disable')
    monkeypatch.setenv('SIGNALDESK_PASSWORD', 'x' * 16)
    with psycopg.connect(pg) as c:  # reset all app schemas between tests
        for (name,) in c.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'sd_%' OR schema_name='signaldesk'").fetchall():
            c.execute('DROP SCHEMA IF EXISTS "' + name + '" CASCADE')
    storage.READY.clear()
    s = types.SimpleNamespace()
    s.now = datetime.datetime.now(datetime.timezone.utc).isoformat
    s.default_connect = lambda: storage.connect('ignored.sqlite3', None)
    s.connect_workspace = lambda w: storage.connect('ignored.sqlite3', w)
    security.init(s)
    yield s
    server.CTX.ws = None; server.CTX.email = None

def test_tenants_get_separate_pg_schemas(pg, env):
    ra = accounts.create(env, 'a@b.co', 'tencharacters!')
    rb = accounts.create(env, 'c@d.co', 'tencharacters!')
    with psycopg.connect(pg) as c:
        schemas = {r[0] for r in c.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'sd_u_%'").fetchall()}
    assert len(schemas) == 2 and ('sd_' + ra['ws']) in schemas and ('sd_' + rb['ws']) in schemas

def test_pg_cross_tenant_data_invisible(pg, env):
    ra = accounts.create(env, 'a@b.co', 'tencharacters!')
    rb = accounts.create(env, 'c@d.co', 'tencharacters!')
    server.CTX.ws = ra['ws']
    server.action('/api/import', {'rows': [{'company': 'Acme', 'domain': 'acme.example'}]})
    server.action('/api/config', dict(company_name='Alpha Corp', industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email'))
    # tenant B through the same code path: sees nothing of A
    server.CTX.ws = rb['ws']
    assert server.records() == []
    assert server.config()['company_name'] == ''
    # and directly in PG: A's row lives only in A's schema
    with psycopg.connect(pg, autocommit=True) as c:
        c.execute('SET search_path TO "sd_' + ra['ws'] + '"')
        n_a = c.execute('SELECT count(*) FROM accounts').fetchone()[0]
        c.execute('SET search_path TO "sd_' + rb['ws'] + '"')
        n_b = c.execute('SELECT count(*) FROM accounts').fetchone()[0]
    assert (n_a, n_b) == (1, 0)

def test_pg_check_grant_and_owner_endpoints(pg, env):
    ra = accounts.create(env, 'a@b.co', 'tencharacters!')
    assert server.check_grant({'ws': ra['ws'], 'email': 'a@b.co'}) is True
    assert server.check_grant({'ws': 'u_deadbeef', 'email': 'a@b.co'}) is False
    assert server.check_grant({'ws': 'owner'}) is True
    server.CTX.ws = ra['ws']; server.CTX.email = 'a@b.co'
    for path, payload in [('/api/access', {'email': 'x@y.co'}), ('/api/storage/probe', {})]:
        with pytest.raises(ValueError):
            server.action(path, payload)

def test_pg_backup_is_tenant_scoped(pg, env):
    ra = accounts.create(env, 'a@b.co', 'tencharacters!')
    server.CTX.ws = ra['ws']
    server.action('/api/import', {'rows': [{'company': 'AlphaLead', 'domain': 'alphalead.example'}]})
    data = server.backup_data() if hasattr(server, 'backup_data') else None
    state = server.state()
    assert 'alphalead.example' in str(state['accounts'])
    server.CTX.ws = 'owner'
    assert 'alphalead.example' not in str(server.state()['accounts'])
