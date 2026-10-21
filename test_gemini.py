"""Gemini provider: bounded output, terms gate, no key leakage, honest engine labels."""
import io, json, os, types, datetime
import pytest
import server, storage

def _mk(tmp_path, monkeypatch, key='test-key-not-real'):
    db = str(tmp_path / 'g.sqlite3')
    monkeypatch.setenv('SIGNALDESK_DB', db)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', db)
    if key: monkeypatch.setenv('SIGNALDESK_GEMINI_API_KEY', key)
    else: monkeypatch.delenv('SIGNALDESK_GEMINI_API_KEY', raising=False)

def teardown_function(_):
    server.CTX.ws = None; server.CTX.email = None

class _R:
    def __init__(self, body): self.body = body
    def read(self, n=-1): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False

def _resp(text):
    return _R(json.dumps({'candidates': [{'content': {'parts': [{'text': text}]}}]}).encode())

ACCOUNT = dict(company='Acme', domain='acme.example', contact='Priya', evidence='note', source='https://acme.example')

def test_gemini_draft_bounded(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setattr(server.urllib.request, 'urlopen', lambda req, timeout=None: _resp('Would faster payroll runs be useful for your team?'))
    cfg = dict(server.DEFAULT, ai=True, ai_provider='gemini', ai_terms=True, offer='payroll automation for small teams')
    out = server.gemini_ai(ACCOUNT, cfg)
    assert 'Would faster payroll runs be useful for your team?' in out
    assert 'Draft connection note' in out or 'Hi Priya' in out  # base template draft preserved

def test_gemini_rejects_unbounded_output(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setattr(server.urllib.request, 'urlopen', lambda req, timeout=None: _resp('Sure! Here is a paragraph about payroll...'))
    with pytest.raises(ValueError):
        server.gemini_ai(ACCOUNT, dict(server.DEFAULT, offer='x'))

def test_gemini_failure_is_bounded_and_key_free(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch, key='SECRET-KEY-12345')
    def boom(req, timeout=None): raise OSError('connection refused by https://generativelanguage.googleapis.com/?key=SECRET-KEY-12345')
    monkeypatch.setattr(server.urllib.request, 'urlopen', boom)
    with pytest.raises(ValueError) as e:
        server.gemini_ai(ACCOUNT, dict(server.DEFAULT, offer='x'))
    assert 'SECRET-KEY-12345' not in str(e.value)

def test_gemini_requires_server_key(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch, key=None)
    with pytest.raises(ValueError) as e:
        server.gemini_ai(ACCOUNT, dict(server.DEFAULT, offer='x'))
    assert 'not configured' in str(e.value)

def test_config_gate_terms_and_key(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch)
    base = dict(server.DEFAULT, industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email')
    # gemini without terms acknowledgment: rejected
    with pytest.raises(ValueError) as e:
        server.action('/api/config', dict(base, ai=True, ai_provider='gemini', ai_terms=False))
    assert 'terms acknowledgment' in str(e.value)
    # gemini with terms: accepted
    cfg = server.action('/api/config', dict(base, ai=True, ai_provider='gemini', ai_terms=True))
    assert cfg['ai_provider'] == 'gemini'
    # gemini without server key: rejected
    monkeypatch.delenv('SIGNALDESK_GEMINI_API_KEY')
    with pytest.raises(ValueError) as e:
        server.action('/api/config', dict(base, ai=True, ai_provider='gemini', ai_terms=True))
    assert 'not configured' in str(e.value)

def test_state_never_contains_key(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch, key='SECRET-KEY-12345')
    server.action('/api/config', dict(server.DEFAULT, ai=True, ai_provider='gemini', ai_terms=True,
                                      industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email'))
    assert 'SECRET-KEY-12345' not in json.dumps(server.state())

def test_prepare_labels_gemini_engine(monkeypatch, tmp_path):
    _mk(tmp_path, monkeypatch)
    monkeypatch.setattr(server.urllib.request, 'urlopen', lambda req, timeout=None: _resp('Would faster payroll runs be useful for your team?'))
    cfg = dict(server.DEFAULT, ai=True, ai_provider='gemini', ai_terms=True, threshold=50, offer='payroll automation')
    a = dict(server.ACCOUNT_TEMPLATE if hasattr(server, 'ACCOUNT_TEMPLATE') else {}, **ACCOUNT,
             id='t1', suppressed=False, approved=False, draft='', score=None, reasons=[], industry='SaaS',
             region='India', size=30, updated='')
    out = server.prepare(a, cfg)
    assert out['engine'] == 'gemini'
    assert 'Would faster payroll runs be useful' in out['draft']

def test_config_gate_string_false_does_not_bypass(monkeypatch, tmp_path):
    """Form-style string 'false' must not satisfy the terms gate (bool('false') is True in Python)."""
    _mk(tmp_path, monkeypatch)
    base = dict(server.DEFAULT, industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email')
    with pytest.raises(ValueError) as e:
        server.action('/api/config', dict(base, ai=True, ai_provider='gemini', ai_terms='false'))
    assert 'terms acknowledgment' in str(e.value)
    # string 'true' is the accepted affirmative form
    cfg = server.action('/api/config', dict(base, ai=True, ai_provider='gemini', ai_terms='true'))
    assert cfg['ai_terms'] is True
    # string 'false' for ai must also not enable AI
    cfg = server.action('/api/config', dict(base, ai='false', ai_provider='gemini', ai_terms='true'))
    assert cfg['ai'] is False
