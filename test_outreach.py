"""Outreach sequence: enrollment gates, step drafts, review/send gates, dry-run purity, audit."""
import json
import pytest
import server, outreach

def _mk(tmp_path, monkeypatch):
    db = str(tmp_path / 'o.sqlite3')
    monkeypatch.setenv('SIGNALDESK_DB', db)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(server, 'DB', db)

def teardown_function(_):
    server.CTX.ws = None; server.CTX.email = None

def _account(aid='a1', company='Acme', score=80, draft='Draft body', approved=True, suppressed=False):
    return dict(id=aid, company=company, domain='acme.example', contact='Priya', evidence='note',
                source='https://acme.example', industry='SaaS', region='India', size=30,
                score=score, draft=draft, approved=approved, suppressed=suppressed,
                reasons=[], engine='template', updated='')

def _save(a):
    server.save(a)

def _cfg(**kw):
    base = dict(server.DEFAULT, industry='SaaS', min_size=1, max_size=500, threshold=50, channel='email')
    base.update(kw)
    return server.action('/api/config', base)

def _create(name='Q4 push', link=''):
    return server.action('/api/outreach/create', dict(name=name, channel='email', booking_link=link))

def test_create_validates(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch); _cfg()
    with pytest.raises(ValueError): server.action('/api/outreach/create', dict(name='', channel='email'))
    with pytest.raises(ValueError): server.action('/api/outreach/create', dict(name='x', channel='sms'))
    with pytest.raises(ValueError): server.action('/api/outreach/create', dict(name='x', channel='email', booking_link='http://insecure.example'))
    with pytest.raises(ValueError): server.action('/api/outreach/create', dict(name='x', channel='email', booking_link='not-a-url'))
    c = _create(link='https://cal.example/siva')
    assert c['booking_link'] == 'https://cal.example/siva'

def test_enroll_gates(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch); _cfg()
    c = _create()
    _save(_account('q', score=80))           # qualified
    _save(_account('low', company='Low', score=20))   # below threshold
    _save(_account('noscore', company='NoScore', score=None, draft=''))
    _save(_account('sup', company='Sup', score=90, suppressed=True))
    for ids, frag in [([], '1-25'), (['missing'], 'not found'), (['low'], 'threshold'),
                      (['noscore'], 'not been qualified'), (['sup'], 'suppressed'), (['q','q'], 'Duplicate')]:
        with pytest.raises(ValueError) as e:
            server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=ids))
        assert frag in str(e.value)
    c = server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['q']))
    assert c['members'][0]['phase'] == 'awaiting_send'  # approved initial draft already exists
    with pytest.raises(ValueError) as e:
        server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['q']))
    assert 'already enrolled' in str(e.value)

def test_full_sequence_to_booking(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch); _cfg(offer='payroll automation', cta='Would a walkthrough help?')
    _save(_account('a1'))
    c = _create(link='https://cal.example/siva')
    c = server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['a1']))
    m = c['members'][0]
    assert m['phase'] == 'awaiting_send' and m['step'] == 0
    # reply/booking before any send: rejected
    with pytest.raises(ValueError): server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='replied'))
    # mark initial sent -> follow-up draft generated, awaiting review
    c = server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='sent', note='sent from my inbox'))
    m = c['members'][0]
    assert m['step'] == 1 and m['phase'] == 'awaiting_review'
    assert 'payroll automation' in m['step_draft'] and 'Priya' in m['step_draft']
    # cannot mark sent before review
    with pytest.raises(ValueError) as e: server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='sent'))
    assert 'reviewed draft' in str(e.value)
    # approve step draft -> awaiting send
    c = server.action('/api/outreach/approve', dict(id=c['id'], account_id='a1'))
    assert c['members'][0]['phase'] == 'awaiting_send'
    # mark sent -> meeting request draft with booking link
    c = server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='sent'))
    m = c['members'][0]
    assert m['step'] == 2 and 'https://cal.example/siva' in m['step_draft']
    c = server.action('/api/outreach/approve', dict(id=c['id'], account_id='a1'))
    c = server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='sent'))
    assert c['members'][0]['phase'] == 'awaiting_reply'
    # book the meeting -> terminal
    c = server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='meeting_booked'))
    m = c['members'][0]
    assert m['phase'] == 'done' and m['outcome'] == 'meeting_booked'
    assert any('cal.example' in h['detail'] for h in m['history'])
    # terminal: no further events
    with pytest.raises(ValueError): server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='sent'))

def test_stop_and_unknown_event(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch); _cfg()
    _save(_account('a1', draft='x', approved=False))
    c = _create()
    c = server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['a1']))
    assert c['members'][0]['phase'] == 'awaiting_review'
    with pytest.raises(ValueError): server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='deleted'))
    c = server.action('/api/outreach/mark', dict(id=c['id'], account_id='a1', event='stopped', note='asked to opt out'))
    assert c['members'][0]['outcome'] == 'stopped'

def test_dry_run_mutates_nothing(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch); _cfg()
    _save(_account('a1')); _save(_account('a2', company='Beta', approved=False))
    c = _create()
    server.action('/api/outreach/enroll', dict(id=c['id'], account_ids=['a1', 'a2']))
    before = json.dumps(server.state(), sort_keys=True)
    p = server.action('/api/outreach/plan', dict(id=c['id']))
    after = json.dumps(server.state(), sort_keys=True)
    assert before == after
    assert p['dry_run'] is True and p['sent'] == 0 and len(p['members']) == 2
    assert any('export and send outside the app' in m['next'] for m in p['members'])
    assert any('Review the' in m['next'] for m in p['members'])

def test_state_exposes_outreach(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch); _cfg()
    _create()
    st = server.state()
    assert 'outreach' in st and len(st['outreach']) == 1
