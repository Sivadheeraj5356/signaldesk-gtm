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
                                    recipient_email=a.get('contact_email') or '', recipient_name=a.get('contact') or '',
                                    recipient_bound_at=s.now(),
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
            m['step_subject'] = STEPS[m['step']][1] + ': ' + m['company']
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


# --- Provider-gated execution: sends and bookings ---------------------------
import senders, bookers

def set_approval(s, d):
    """Record an operational approval on the campaign: the exact sender identity,
    recipient scope and an explicit confirmation. Without this, providers dry-run only."""
    camp = get(s, d.get('id'))
    sender = s.text(d.get('sender'), 200).lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', sender or ''): raise ValueError('Approval needs the exact sender email address')
    if d.get('confirmed') is not True: raise ValueError('Approval needs an explicit confirmation')
    scope = d.get('recipient_scope', 'enrolled')
    if scope != 'enrolled': raise ValueError('Recipient scope must be the enrolled members of this campaign')
    if not camp['members']: raise ValueError('Enroll accounts before approving sends')
    camp['send_approval'] = dict(sender=sender, recipient_scope=scope, confirmed_at=s.now())
    camp.setdefault('history', []).append(dict(at=s.now(), event='approval', detail='Send approval recorded for sender ' + sender))
    store(s, camp)
    return camp

def revoke_approval(s, d):
    camp = get(s, d.get('id'))
    camp.pop('send_approval', None)
    camp.setdefault('history', []).append(dict(at=s.now(), event='approval_revoked', detail='Send approval revoked; providers dry-run only'))
    store(s, camp)
    return camp

def send_step(s, d):
    """Send the current approved step draft for one member. Real sends require both a
    configured provider and a recorded campaign approval; otherwise dry_run is forced."""
    camp = get(s, d.get('id'))
    m = _member(camp, d.get('account_id'))
    provider = d.get('provider', 'mock')
    dry = d.get('dry_run') is not False
    approval = camp.get('send_approval')
    if not dry:
        if not approval: raise ValueError('No operational approval on this campaign. Record sender, recipient scope and confirmation first.')
        state = senders.provider_state().get(provider, {})
        if not state.get('configured'): raise ValueError(provider + ' provider is not configured. Dry-run is still available.')
    if m['phase'] != 'awaiting_send': raise ValueError('This step has no reviewed draft ready to send')
    a = next((a for a in s.records() if a['id'] == m['account_id']), None)
    if m['step'] == 0:
        if not (a and a.get('approved')): raise ValueError('The initial draft must be reviewed before sending')
        body = (a or {}).get('draft', '')
        subject = ((a or {}).get('subject') or '').strip()
        if not subject: raise ValueError('The initial draft has no subject. Review the draft and set the exact subject line first - it is recipient-visible content.')
    else:
        if not m['step_approved']: raise ValueError('The step draft must be reviewed before sending')
        body = m['step_draft']
        subject = (m.get('step_subject') or '').strip()
        if not subject: raise ValueError('This step has no reviewed subject line')
    if not body: raise ValueError('No draft body for this step')
    # Recipient binds immutably to the address reviewed at enrollment. If the account's
    # contact evidence changed since, this member's binding is stale: re-enroll instead
    # of silently substituting a different mailbox.
    to = (m.get('recipient_email') or '').lower()
    if not to: raise ValueError('This member has no bound contact email. Bind one at enrollment after adding contact email evidence to the account.')
    current = ((a or {}).get('contact_email') or '').lower()
    if current and current != to:
        raise ValueError('Account contact evidence changed after enrollment (' + to + ' was bound). Review and re-enroll to rebind - no silent substitution.')
    supplied = s.text(d.get('to'), 200).lower()
    if supplied and supplied != to: raise ValueError('Recipient must be the enrolled contact ' + to + ' - arbitrary recipients are out of scope')
    if not dry and not approval: raise ValueError('No operational approval on this campaign. Record sender, recipient scope and confirmation first.')
    sender = approval['sender'] if approval else '(dry-run: approval not recorded)'
    result = senders.send(provider, sender, to, subject, body, ws=s.ws(), dry_run=dry)
    m['history'].append(dict(at=s.now(), event='send_' + ('dry_run' if dry else 'attempt'),
                             detail=result.get('note') or ('Delivered via ' + provider)))
    store(s, camp)
    return result

def book_meeting(s, d):
    """Create a booking through a provider. Real bookings require a configured provider
    and the campaign approval; dry_run returns the exact request."""
    camp = get(s, d.get('id'))
    m = _member(camp, d.get('account_id'))
    dry = d.get('dry_run') is not False
    if not dry and not camp.get('send_approval'): raise ValueError('No operational approval on this campaign.')
    a = next((a for a in s.records() if a['id'] == m['account_id']), None)
    invitee_email = (m.get('recipient_email') or '').lower()
    if not invitee_email: raise ValueError('This member has no bound contact email to invite')
    current = ((a or {}).get('contact_email') or '').lower()
    if current and current != invitee_email:
        raise ValueError('Account contact evidence changed after enrollment. Review and re-enroll to rebind - no silent substitution.')
    invitee_name = (m.get('recipient_name') or (a or {}).get('contact') or m['company'])[:200]
    start = s.text(d.get('start'), 40)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})', start or ''):
        raise ValueError('Booking needs an explicit ISO start time with offset, e.g. 2026-10-24T10:00:00+05:30')
    tz = s.text(d.get('timezone'), 60) or 'Asia/Calcutta'
    if not re.fullmatch(r'[A-Za-z_]+/[A-Za-z_]+', tz): raise ValueError('Booking needs an IANA timezone like Asia/Calcutta')
    result = bookers.book(d.get('event_type_id'), start, tz, invitee_name, invitee_email, ws=s.ws(), dry_run=dry)
    m['history'].append(dict(at=s.now(), event='booking_' + ('dry_run' if dry else 'attempt'), detail=result.get('note', 'Booking created')))
    store(s, camp)
    return result
