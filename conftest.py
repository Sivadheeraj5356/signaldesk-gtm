"""When SIGNALDESK_TEST_PG_URI is set, run every test against a fresh PG schema set."""
import os
import pytest

URI = os.environ.get('SIGNALDESK_TEST_PG_URI')

@pytest.fixture(autouse=True)
def _pg_reset(monkeypatch):
    if not URI:
        yield; return
    import psycopg, storage
    storage.READY.clear()
    monkeypatch.setenv('DATABASE_URL', URI)
    monkeypatch.setenv('PGSSLMODE', 'disable')
    with psycopg.connect(URI, autocommit=True) as c:
        for (name,) in c.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'sd_%' OR schema_name='signaldesk'").fetchall():
            c.execute('DROP SCHEMA IF EXISTS "' + name + '" CASCADE')
    storage.READY.clear()
    yield
