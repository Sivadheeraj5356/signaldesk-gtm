"""Outreach sequences: qualified accounts move initial -> follow-up -> meeting request.

This module never sends, emails, invites or books anything. Step drafts are prepared
for human review inside the app; any actual send happens outside the app and is
recorded back manually ('sent'). A dry-run plan shows what would happen without
mutating any state.
"""
import json, uuid, re

STEPS = [('initial', 'Initial outreach'), ('followup', 'Follow-up'), ('meeting', 'Meeting request')]
EVENTS = ['sent', 'replied', 'meeting_booked', 'stopped']
TERMINAL = ['replied', 'meeting_booked', 'stopped']

def list_campaigns(s):
    with s.connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT data FROM outreach ORDER BY rowid DESC')]

def store(s, camp):
    camp['updated'] = s.now()
    with s.connect() as c: c.execute('INSERT OR REPLACE INTO outreach VALUES(?,?)', (camp['id'], json.dumps(camp)))

def get(s, cid):
    camp = next((c for c in list_campaigns(s) if c['id'] == cid), None)
    if not camp: raise ValueError('Outreach campaign not found')
    return camp

def _valid_link(u):
    return bool(re.fullmatch(r'https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s]*)?', u or ''))

def create(s, d):
    name = s.text(d.get('name'), 200)
    if not name: raise ValueError('Campaign name is required')
    channel = d.get('channel') or s.config().get('channel', 'email')
    if channel not in ['email', 'linkedin', 'partner']: raise ValueError('Unknown distribution channel')
    link = s.text(d.get('booking_link'), 300)
    if link and not _valid_link(link): raise ValueError('Booking link must be a full https:// URL, for example your own scheduling page')
    camp = dict(id=str(uuid.uuid4()), name=name, channel=channel, booking_link=link,
                created=s.now(), updated=s.now(), members=[])
    store(s, camp)
    return camp

def enroll(s, d):
    camp = get(s, d.get('id'))
    ids = d.get('account_ids')
    if not isinstance(ids, list) or not ids or len(ids) > 25: raise ValueError('Choose 1-25 accounts to enroll')
    if len(set(ids)) != len(ids): raise ValueError('Duplicate accounts selected')
    cfg = s.config()
    accounts = {a['id']: a for a in s.records()}
    already = {m['account_id'] for m in camp['members']}
    added = []
    for aid in ids:
        a = accounts.get(aid)
        if not a: raise ValueError('Account not found: ' + str(aid))
        if aid in already: raise ValueError(a['company'] + ' is already enrolled')
        if a['suppressed']: raise ValueError(a['company'] + ' is suppressed and cannot be enrolled')
        if a.get('score') is None: raise ValueError(a['company'] + ' has not been qualified yet - run the workflow first')
        if a['score'] < cfg['threshold']: raise ValueError(a['company'] + ' scores below the qualification threshold')
        phase = 'awaiting_send' if (a.get('draft') and a.get('approved')) else ('awaiting_review' if a.get('draft') else 'awaiting_draft')
        camp['members'].append(dict(account_id=aid, company=a['company'], step=0, phase=phase,
                                    step_draft='', step_approved=False,
                                    history=[dict(at=s.now(), event='enrolled', detail='Enrolled at step 1: Initial outreach')]))
        added.append(aid)
    store(s, camp)
    return camp

def step_draft_text(s, a, cfg, kind, booking_link):
    contact = a.get('contact') or 'there'
    offer = cfg.get('offer') or 'our offer'
    if kind == 'followup':
        body = ('Hi ' + contact + ',\n\nFollowing up on my earlier note about ' + offer + '. '
                'If the timing is wrong, no problem - happy to reconnect later.\n\n' + (cfg.get('cta') or '')).strip()
    elif kind == 'meeting':
        ask = 'You can pick a time directly here: ' + booking_link if booking_link else 'Would any of these times work for a short call?'
        body = ('Hi ' + contact + ',\n\nWould a short call be useful to see whether ' + offer + ' fits your team?\n\n' + ask).strip()
    else:
        raise ValueError('Only follow-up and meeting steps generate sequence drafts; the initial draft comes from the workflow')
    return s.text(body, 2000)

def _member(camp, aid):
    m = next((m for m in camp['members'] if m['account_id'] == aid), None)
    if not m: raise ValueError('Account is not enrolled in this campaign')
    return m

def approve_step(s, d):
    camp = get(s, d.get('id'))
    m = _member(camp, d.get('account_id'))
    if m['step'] == 0: raise ValueError('The initial draft is approved from the Review drafts tab, not here')
    if not m['step_draft']: raise ValueError('No step draft to approve yet')
    if m['phase'] != 'awaiting_review': raise ValueError('This step is not awaiting review')
    m['step_approved'] = True; m['phase'] = 'awaiting_send'
    m['history'].append(dict(at=s.now(), event='reviewed', detail=STEPS[m['step']][1] + ' draft reviewed for export'))
    store(s, camp)
    return camp

def mark(s, d):
    camp = get(s, d.get('id'))
    m = _member(camp, d.get('account_id'))
    event = d.get('event')
    if event not in EVENTS: raise ValueError('Unknown event')
    if m['phase'] == 'done': raise ValueError('This sequence is already complete')
    accounts = {a['id']: a for a in s.records()}
    a = accounts.get(m['account_id'])
    note = s.text(d.get('note'), 500)
    if event == 'stopped':
        m['phase'] = 'done'; m['outcome'] = 'stopped'
        m['history'].append(dict(at=s.now(), event='stopped', detail=note or 'Sequence stopped manually'))
    elif event == 'sent':
        if m['phase'] != 'awaiting_send': raise ValueError('This step is not ready to be marked sent - it needs a reviewed draft first')
        label = STEPS[m['step']][1]
        m['history'].append(dict(at=s.now(), event='sent', detail=label + ' marked as sent outside the app' + (': ' + note if note else '')))
        if m['step'] < len(STEPS) - 1:
            m['step'] += 1
            m['step_draft'] = step_draft_text(s, a, s.config(), STEPS[m['step']][0], camp.get('booking_link'))
            m['step_approved'] = False; m['phase'] = 'awaiting_review'
            m['history'].append(dict(at=s.now(), event='drafted', detail=STEPS[m['step']][1] + ' draft prepared for review'))
        else:
            m['phase'] = 'awaiting_reply'
            m['history'].append(dict(at=s.now(), event='awaiting_reply', detail='Meeting request sent; waiting for a reply to be recorded'))
    elif event in TERMINAL[:2]:
        if m['phase'] not in ('awaiting_reply', 'awaiting_send') or not any(h['event'] == 'sent' for h in m['history']):
            raise ValueError('Record a send before recording a reply or booking')
        m['phase'] = 'done'; m['outcome'] = event
        detail = 'Reply recorded' if event == 'replied' else 'Meeting booked' + (' via ' + camp['booking_link'] if camp.get('booking_link') else '')
        m['history'].append(dict(at=s.now(), event=event, detail=detail + (': ' + note if note else '')))
    store(s, camp)
    return camp

def plan(s, d):
    """Dry-run: what would happen next for each member. Mutates nothing."""
    camp = get(s, d.get('id'))
    out = []
    for m in camp['members']:
        label = STEPS[m['step']][1]
        if m['phase'] == 'done':
            action = 'Sequence complete (' + m.get('outcome', 'done') + ')'
        elif m['phase'] == 'awaiting_draft':
            action = 'Run the workflow to prepare the initial draft'
        elif m['phase'] == 'awaiting_review':
            action = 'Review the ' + label.lower() + ' draft, then it can be marked sent'
        elif m['phase'] == 'awaiting_send':
            nxt = STEPS[m['step'] + 1][1].lower() + ' draft' if m['step'] < len(STEPS) - 1 else 'awaiting-reply state'
            action = 'Ready to export and send outside the app. Marking sent would prepare the ' + nxt
        else:
            action = 'Waiting for a reply or booking to be recorded'
        out.append(dict(company=m['company'], step=label, phase=m['phase'], next=action))
    return dict(campaign=camp['name'], dry_run=True, sent=0, members=out)
