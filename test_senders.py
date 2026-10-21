"""Send/booking provider contracts: mock always works, gmail/calcom env-gated,
approval gate for real execution, dry-run purity, no credential leakage."""
import json, os, types
import pytest
import server, senders, bookers, outreach

def _mk(tmp_path, monkeypatch, gmail_key=None, calcom_key=None):
    db = str(tmp_path / 's.sqlite3')
    monkeypatch.setenv('SIGNALDESK_DB', db)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', db)
    for k, v in [('SIGNALDESK_GMAIL_ACCESS_TOKEN', gmail_key), ('SIGNALDESK_CALCOM_API_KEY', calcom_key)]:
        monkeypatch.setenv(k, v) if v else monkeypatch.delenv(k, raising=False)

def teardown_function(_):
    server.CTX.ws = None; server.CTX.email = None

def _setup_campaign(tmp_path, monkeypatch, approved=True):
    _mk(tmp_path, monkeypatch)
    server.action('/api/config', dict(server.DEFAULT, industry='SaaS', min_size=1, max_size=500,
                                      threshold=50, channel='email', offer='payroll automation'))
    server.save(dict(id='a1', company='Acme', domain='acme.example', contact='Priya', evidence='n',
                     source='https://acme.example', industry='SaaS', region='India', size=30,
                     score=85, draft='Initial draft body', approved=True, suppressed=False,
                     reasons=[], engine='template', updated=''))
    c = server.action('/api/outreach/create', dict(name='Q4', channel='email', booking_link=''))
    server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['a1']))
    return c['id']

def test_mock_provider_records_intent_only():
    r = senders.send('mock', 'me@co.example', 'them@acme.example', 'Hi', 'Body', dry_run=False)
    assert r['delivered'] is False and 'nothing was delivered' in r['note'].lower()

def test_gmail_requires_env_key(monkeypatch):
    monkeypatch.delenv('SIGNALDESK_GMAIL_ACCESS_TOKEN', raising=False)
    with pytest.raises(ValueError) as e:
        senders.send('gmail', 'me@co.example', 't@x.example', 'Hi', 'Body')
    assert 'not configured' in str(e.value)

def test_gmail_dry_run_builds_exact_request_without_network(monkeypatch):
    monkeypatch.setenv('SIGNALDESK_GMAIL_ACCESS_TOKEN', 'TOKEN-SECRET-987')
    def boom(req, timeout=None): raise AssertionError('network must not be touched in dry-run')
    monkeypatch.setattr(senders.urllib.request, 'urlopen', boom)
    r = senders.send('gmail', 'me@co.example', 'them@acme.example', 'Intro', 'Hello body', dry_run=True)
    assert r['dry_run'] is True and r['delivered'] is False
    assert r['request']['url'] == 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
    assert r['request']['to'] == 'them@acme.example'

def test_gmail_failure_strips_token(monkeypatch):
    monkeypatch.setenv('SIGNALDESK_GMAIL_ACCESS_TOKEN', 'TOKEN-SECRET-987')
    def boom(req, timeout=None): raise OSError('401 invalid TOKEN-SECRET-987')
    monkeypatch.setattr(senders.urllib.request, 'urlopen', boom)
    with pytest.raises(ValueError) as e:
        senders.send('gmail', 'me@co.example', 't@x.example', 'Hi', 'Body', dry_run=False)
    assert 'TOKEN-SECRET-987' not in str(e.value)

def test_approval_requires_exact_sender_and_confirmation(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    with pytest.raises(ValueError): server.action('/api/outreach/approve-send', dict(id=cid, sender='notanemail', confirmed=True))
    with pytest.raises(ValueError): server.action('/api/outreach/approve-send', dict(id=cid, sender='me@co.example', confirmed=False))
    with pytest.raises(ValueError): server.action('/api/outreach/approve-send', dict(id=cid, sender='me@co.example', confirmed=True, recipient_scope='everyone'))
    c = server.action('/api/outreach/approve-send', dict(id=cid, sender='me@co.example', confirmed=True))
    assert c['send_approval']['sender'] == 'me@co.example'
    c = server.action('/api/outreach/revoke-send', dict(id=cid))
    assert 'send_approval' not in c

def test_send_step_gates(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    # real send without approval: rejected
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', to='t@x.example', sender='me@co.example', dry_run=False))
    assert 'approval' in str(e.value).lower()
    # dry-run without approval: allowed, records intent in history
    r = server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', to='t@x.example', sender='me@co.example'))
    assert r['delivered'] is False
    camp = server.action('/api/outreach/plan', dict(id=cid))
    # real send with approval + mock provider: records, still delivers nothing
    server.action('/api/outreach/approve-send', dict(id=cid, sender='me@co.example', confirmed=True))
    r = server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', to='t@x.example', dry_run=False))
    assert r['provider'] == 'mock' and r['delivered'] is False
    # real send with approval but unconfigured gmail: rejected with config message
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='gmail', to='t@x.example', dry_run=False))
    assert 'not configured' in str(e.value)

def test_send_step_requires_recipient_and_ready_draft(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', sender='me@co.example'))
    assert 'recipient' in str(e.value).lower()

def test_calcom_gates_and_dry_run(monkeypatch):
    monkeypatch.delenv('SIGNALDESK_CALCOM_API_KEY', raising=False)
    with pytest.raises(ValueError): bookers.availability(1, '2026-10-24')
    monkeypatch.setenv('SIGNALDESK_CALCOM_API_KEY', 'CAL-SECRET-555')
    def boom(req, timeout=None): raise AssertionError('network must not be touched in dry-run')
    monkeypatch.setattr(bookers.urllib.request, 'urlopen', boom)
    r = bookers.book(42, '2026-10-24T10:00:00+05:30', 'Priya', 'priya@acme.example', dry_run=True)
    assert r['dry_run'] is True and r['request']['event_type_id'] == 42

def test_state_exposes_provider_config_without_secrets(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, gmail_key='TOKEN-SECRET-987', calcom_key='CAL-SECRET-555')
    st = server.state()
    assert st['send_providers']['gmail']['configured'] is True
    assert st['book_providers']['calcom']['configured'] is True
    blob = json.dumps(st)
    assert 'TOKEN-SECRET-987' not in blob and 'CAL-SECRET-555' not in blob
