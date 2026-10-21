"""Send provider contracts for outreach campaigns.

Two independent gates before anything real leaves the app:
1. Provider configuration: operator-supplied credentials (env / OAuth). Absent
   credentials -> the provider reports not_configured and only dry-run is possible.
2. Operational approval: a recorded approval on the campaign naming the sender
   identity, the recipient scope and an explicit confirmation. Absent approval,
   even a configured provider only dry-runs.

The mock provider always works and records send intents; it never touches a network.
The gmail provider drafts a Gmail API request; with dry_run=True it returns the exact
request it would make without performing it.
"""
import os, json, base64, urllib.request

PROVIDERS = ['mock', 'gmail']

def provider_state():
    return {
        'mock': dict(configured=True, note='Records send intents only. Never delivers anything.'),
        'gmail': dict(configured=bool(os.environ.get('SIGNALDESK_GMAIL_ACCESS_TOKEN')),
                      note='Gmail API. Operator sets up OAuth and provides SIGNALDESK_GMAIL_ACCESS_TOKEN after the user completes consent.'),
    }

def _gmail_request(sender, to, subject, body):
    raw = ('From: ' + sender + '\r\nTo: ' + to + '\r\nSubject: ' + subject + '\r\n\r\n' + body).encode()
    payload = json.dumps({'raw': base64.urlsafe_b64encode(raw).decode()}).encode()
    return urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                                  data=payload, headers={'Content-Type': 'application/json'})

def send(provider, sender, to, subject, body, dry_run=True, timeout=30):
    if provider not in PROVIDERS: raise ValueError('Unknown send provider')
    if provider == 'mock':
        return dict(provider='mock', dry_run=dry_run, delivered=False,
                    intent=dict(sender=sender, to=to, subject=subject, body=body[:2000]),
                    note='Recorded intent only; nothing was delivered')
    if not os.environ.get('SIGNALDESK_GMAIL_ACCESS_TOKEN'):
        raise ValueError('gmail provider is not configured: missing SIGNALDESK_GMAIL_ACCESS_TOKEN (OAuth consent not completed)')
    req = _gmail_request(sender, to, subject, body)
    if dry_run:
        return dict(provider='gmail', dry_run=True, delivered=False,
                    request=dict(url=req.full_url, method='POST', to=to, sender=sender, subject=subject,
                                 body_bytes=len(req.data)),
                    note='Dry run: this is the exact Gmail API request a real send would make')
    token = os.environ['SIGNALDESK_GMAIL_ACCESS_TOKEN']
    req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read(100000))
        return dict(provider='gmail', dry_run=False, delivered=True, message_id=resp.get('id'), thread_id=resp.get('threadId'))
    except Exception as e:
        raise ValueError('Gmail send failed: ' + str(e)[:200].replace(token, ''))
