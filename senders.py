"""Send provider contracts for outreach campaigns.

Binding rules (main's review, 2026-10-22):
- The sender is the VERIFIED IDENTITY of a connected account, never a typed-in
  address. For Gmail that identity comes from the Gmail profile endpoint at
  connect/send time; the campaign approval's sender must match it exactly.
- The recipient is the enrolled member's bound contact email (supplied
  evidence on the account), never an arbitrary per-send address.
- The body is the exact approved draft; no edits at send time.
- The operator env token is an owner-workspace development path ONLY. Tenant
  workspaces can never use it; they need their own OAuth connection
  (not yet implemented - reported as a gap, not worked around).

Gates before real delivery: configured provider for THIS workspace + recorded
campaign approval + bound recipient + approved draft. dry_run always available.
"""
import os, json, base64, urllib.request

PROVIDERS = ['mock', 'gmail']

def provider_state(ws='owner'):
    gmail_env = bool(os.environ.get('SIGNALDESK_GMAIL_ACCESS_TOKEN'))
    return {
        'mock': dict(configured=True, note='Records send intents only. Never delivers anything.'),
        'gmail': dict(configured=(ws == 'owner') and gmail_env,
                      note='Gmail API. Owner workspace: operator env token (development path). Tenant workspaces need their own OAuth connection, which is not built yet.' if gmail_env else 'Gmail API. Not connected; OAuth consent flow is not built yet.'),
    }

def gmail_identity(token, timeout=15):
    """Verified sender identity from the Gmail profile. Real path only."""
    req = urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/profile',
                                 headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(100000)).get('emailAddress', '').lower()
    except Exception as e:
        raise ValueError('Could not verify the connected Gmail identity: ' + str(e)[:200].replace(token, ''))

def _gmail_request(sender, to, subject, body):
    raw = ('From: ' + sender + '\r\nTo: ' + to + '\r\nSubject: ' + subject + '\r\n\r\n' + body).encode()
    payload = json.dumps({'raw': base64.urlsafe_b64encode(raw).decode()}).encode()
    return urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                                  data=payload, headers={'Content-Type': 'application/json'})

def send(provider, sender, to, subject, body, ws='owner', dry_run=True, timeout=30):
    if provider not in PROVIDERS: raise ValueError('Unknown send provider')
    if provider == 'mock':
        return dict(provider='mock', dry_run=dry_run, delivered=False,
                    intent=dict(sender=sender, to=to, subject=subject, body=body[:2000]),
                    note='Recorded intent only; nothing was delivered')
    token = os.environ.get('SIGNALDESK_GMAIL_ACCESS_TOKEN')
    if not token or ws != 'owner':
        raise ValueError('gmail provider is not configured for this workspace (tenant OAuth connections are not built yet)')
    if dry_run:
        req = _gmail_request(sender, to, subject, body)
        return dict(provider='gmail', dry_run=True, delivered=False,
                    request=dict(url=req.full_url, method='POST', to=to, sender=sender, subject=subject, body_bytes=len(req.data)),
                    note='Dry run: this is the exact Gmail API request a real send would make')
    identity = gmail_identity(token)
    if identity != sender.lower():
        raise ValueError('Connected Gmail identity (' + identity + ') does not match the approved sender (' + sender + '). Approval and connection must be the same account.')
    req = _gmail_request(identity, to, subject, body)
    req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read(100000))
        return dict(provider='gmail', dry_run=False, delivered=True, message_id=resp.get('id'), thread_id=resp.get('threadId'), sender=identity)
    except Exception as e:
        raise ValueError('Gmail send failed: ' + str(e)[:200].replace(token, ''))
