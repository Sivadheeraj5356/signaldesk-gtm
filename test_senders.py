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
    server.save(dict(id='a1', company='Acme', domain='acme.example', contact='Priya', contact_email='',
                     subject='Intro: Acme payroll', evidence='n',
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

def test_gmail_env_token_not_usable_by_tenant(monkeypatch):
    monkeypatch.setenv('SIGNALDESK_GMAIL_ACCESS_TOKEN', 'TOKEN-SECRET-987')
    with pytest.raises(ValueError) as e:
        senders.send('gmail', 'me@co.example', 't@x.example', 'Hi', 'Body', ws='t-abc123')
    assert 'not configured for this workspace' in str(e.value)
    assert senders.provider_state('t-abc123')['gmail']['configured'] is False
    assert senders.provider_state('owner')['gmail']['configured'] is True

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
    # no contact email evidence on the account: send rejected (bound recipient required)
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', dry_run=True))
    assert 'contact email evidence' in str(e.value)
    server.action('/api/account', dict(id='a1', contact_email='priya@acme.example'))
    server.action('/api/account', dict(id='a1', approved=True))
    # enrolled before binding: member has no bound recipient -> refused
    # (enrollment happened in _setup_campaign before contact_email existed)
    # rebind by re-creating the campaign with evidence present
    cid2 = server.action('/api/outreach/create', dict(name='Q4b', channel='email', booking_link=''))['id']
    server.action('/api/outreach/enroll', dict(id=cid2, account_ids=['a1']))
    cid = cid2
    # arbitrary recipient substitution rejected even when it matches nothing bound
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', to='someone-else@other.example', dry_run=True))
    assert 'arbitrary recipients are out of scope' in str(e.value)
    # real send without approval: rejected
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', dry_run=False))
    assert 'approval' in str(e.value).lower()
    # dry-run without approval: allowed, recipient is the BOUND evidence email
    r = server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock'))
    assert r['delivered'] is False and r['intent']['to'] == 'priya@acme.example'
    # matching bound recipient accepted
    server.action('/api/outreach/approve-send', dict(id=cid, sender='me@co.example', confirmed=True))
    r = server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock', to='priya@acme.example', dry_run=False))
    assert r['provider'] == 'mock' and r['delivered'] is False and r['intent']['sender'] == 'me@co.example'
    # real send with approval but unconfigured gmail: rejected with workspace-config message
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='gmail', dry_run=False))
    assert 'not configured' in str(e.value)

def test_send_step_uses_exact_approved_draft(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    server.action('/api/account', dict(id='a1', contact_email='priya@acme.example'))
    server.action('/api/account', dict(id='a1', approved=True))
    cid = server.action('/api/outreach/create', dict(name='Q4b', channel='email', booking_link=''))['id']
    server.action('/api/outreach/enroll', dict(id=cid, account_ids=['a1']))
    r = server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock'))
    assert r['intent']['body'] == 'Initial draft body'
    assert r['intent']['subject'] == 'Intro: Acme payroll'  # reviewed subject, not derived

def test_send_requires_reviewed_subject(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    server.action('/api/account', dict(id='a1', contact_email='priya@acme.example', subject=''))
    server.action('/api/account', dict(id='a1', approved=True))
    cid = server.action('/api/outreach/create', dict(name='Q4b', channel='email', booking_link=''))['id']
    server.action('/api/outreach/enroll', dict(id=cid, account_ids=['a1']))
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock'))
    assert 'subject' in str(e.value).lower()

def test_stale_contact_evidence_blocks_send(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    server.action('/api/account', dict(id='a1', contact_email='priya@acme.example'))
    server.action('/api/account', dict(id='a1', approved=True))
    cid = server.action('/api/outreach/create', dict(name='Q4b', channel='email', booking_link=''))['id']
    server.action('/api/outreach/enroll', dict(id=cid, account_ids=['a1']))
    # contact evidence changes after enrollment: silent substitution must be blocked
    server.action('/api/account', dict(id='a1', contact_email='rahul@acme.example'))
    server.action('/api/account', dict(id='a1', approved=True))
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/send', dict(id=cid, account_id='a1', provider='mock'))
    assert 'no silent substitution' in str(e.value)

def test_contact_email_validated(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch)
    server.action('/api/config', dict(server.DEFAULT, industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email'))
    server.save(dict(id='a1', company='Acme', domain='acme.example', contact='', contact_email='', evidence='',
                     source='', industry='', region='', size=1, score=None, draft='', approved=False,
                     suppressed=False, reasons=[], engine='', updated=''))
    with pytest.raises(ValueError): server.action('/api/account', dict(id='a1', contact_email='not-an-email'))
    a = server.action('/api/account', dict(id='a1', contact_email='  Priya@Acme.Example '))
    assert a['contact_email'] == 'priya@acme.example' and a['approved'] is False  # evidence change resets review

def test_calcom_gates_and_dry_run(monkeypatch):
    monkeypatch.delenv('SIGNALDESK_CALCOM_API_KEY', raising=False)
    with pytest.raises(ValueError): bookers.availability(1, '2026-10-24', '2026-10-25')
    monkeypatch.setenv('SIGNALDESK_CALCOM_API_KEY', 'CAL-SECRET-555')
    r = bookers.availability(42, '2026-10-24', '2026-10-25', timezone='Asia/Calcutta', dry_run=True)
    assert r['request']['url'].startswith('https://api.cal.com/v2/slots?eventTypeId=42&start=2026-10-24&end=2026-10-25')
    assert 'Asia%2FCalcutta' in r['request']['url']
    def boom(req, timeout=None): raise AssertionError('network must not be touched in dry-run')
    monkeypatch.setattr(bookers.urllib.request, 'urlopen', boom)
    r = bookers.book(42, '2026-10-24T10:00:00+05:30', 'Asia/Calcutta', 'Priya', 'priya@acme.example', dry_run=True)
    assert r['dry_run'] is True and r['request']['event_type_id'] == 42 and r['request']['timezone'] == 'Asia/Calcutta'
    assert r['request']['url'] == 'https://api.cal.com/v2/bookings'
    # tenant workspace cannot use the operator env key
    with pytest.raises(ValueError) as e:
        bookers.book(42, '2026-10-24T10:00:00+05:30', 'Asia/Calcutta', 'Priya', 'priya@acme.example', ws='t-abc', dry_run=True)
    assert 'not configured for this workspace' in str(e.value)

def test_booking_binds_invitee_and_slot(tmp_path, monkeypatch):
    cid = _setup_campaign(tmp_path, monkeypatch)
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/book', dict(id=cid, account_id='a1', event_type_id=42, start='2026-10-24T10:00:00+05:30', dry_run=True))
    assert 'bound contact email' in str(e.value)
    server.action('/api/account', dict(id='a1', contact_email='priya@acme.example'))
    server.action('/api/account', dict(id='a1', approved=True))
    cid = server.action('/api/outreach/create', dict(name='Q4b', channel='email', booking_link=''))['id']
    server.action('/api/outreach/enroll', dict(id=cid, account_ids=['a1']))
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/book', dict(id=cid, account_id='a1', event_type_id=42, start='tomorrow morning', dry_run=True))
    assert 'ISO start time' in str(e.value)
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/book', dict(id=cid, account_id='a1', event_type_id=42, start='2026-10-24T10:00:00+05:30', timezone='IST', dry_run=True))
    assert 'IANA timezone' in str(e.value)
    with pytest.raises(ValueError):  # trailing comma fails ISO validation
        server.action('/api/outreach/book', dict(id=cid, account_id='a1', event_type_id=42, start='2026-10-24T10:00:00+05:30,', timezone='Asia/Calcutta', dry_run=True))
    monkeypatch.setenv('SIGNALDESK_CALCOM_API_KEY', 'CAL-SECRET-555')
    r = server.action('/api/outreach/book', dict(id=cid, account_id='a1', event_type_id=42, start='2026-10-24T10:00:00+05:30', timezone='Asia/Calcutta', dry_run=True))
    assert r['dry_run'] is True and r['request']['invitee'] == 'priya@acme.example' and r['request']['timezone'] == 'Asia/Calcutta'


def test_state_exposes_provider_config_without_secrets(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, gmail_key='TOKEN-SECRET-987', calcom_key='CAL-SECRET-555')
    st = server.state()
    assert st['send_providers']['gmail']['configured'] is True
    assert st['book_providers']['calcom']['configured'] is True
    blob = json.dumps(st)
    assert 'TOKEN-SECRET-987' not in blob and 'CAL-SECRET-555' not in blob
