"""Per-workspace provider connections (Gmail first). Replaces static env tokens with
durable OAuth connections: verified identity, refresh-token rotation, fail-closed
status. Token storage: workspace DB (tenant-isolated schema on PG). Limitation:
tokens are plaintext in the workspace DB behind TLS + tenant isolation - see
docs-tenant-connections.md; an external secret store is the hardening path.
"""
import os, json, time, uuid, urllib.request, urllib.parse

GOOGLE_TOKEN = 'https://oauth2.googleapis.com/token'
GMAIL_PROFILE = 'https://gmail.googleapis.com/gmail/v1/users/me/profile'

def list_connections(s):
    with s.connect() as c:
        try: return [json.loads(r[0]) for r in c.execute('SELECT data FROM connections ORDER BY rowid DESC')]
        except Exception: return []

def _store(s, conn):
    conn['updated'] = s.now()
    with s.connect() as c: c.execute('INSERT OR REPLACE INTO connections VALUES(?,?)', (conn['id'], json.dumps(conn)))

def get(s, provider):
    return next((c for c in list_connections(s) if c['provider'] == provider and c.get('status') == 'active'), None)

def public_state(s):
    """Safe for /api/state: identity + status only, never tokens."""
    return [dict(provider=c['provider'], identity=c.get('identity'), status=c.get('status'),
                 connected_at=c.get('connected_at')) for c in list_connections(s)]

def save_gmail(s, identity, refresh_token, access_token=None, expires_in=None):
    conn = dict(id=str(uuid.uuid4()), provider='gmail', identity=identity.lower(),
                refresh_token=refresh_token, access_token=access_token or '',
                access_expires=time.time() + (expires_in or 0) if access_token else 0,
                scopes=['gmail.send'], status='active', connected_at=s.now(), updated_at=s.now())
    _store(s, conn)
    return conn

def _post(url, params, timeout=15):
    body = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=timeout) as r:
        return json.loads(r.read(200000))

def gmail_access_token(s, conn, timeout=15):
    """Valid access token, refreshing when expired. Marks the connection expired
    (fail-closed) when the refresh token is rejected."""
    if conn.get('access_token') and time.time() < conn.get('access_expires', 0) - 60:
        return conn['access_token']
    if not conn.get('refresh_token'):
        raise ValueError('Gmail connection has no refresh token; reconnect required')
    cid, csec = os.environ.get('GOOGLE_CLIENT_ID'), os.environ.get('GOOGLE_CLIENT_SECRET')
    if not (cid and csec): raise ValueError('Google OAuth client is not configured on this server')
    try:
        t = _post(GOOGLE_TOKEN, dict(client_id=cid, client_secret=csec,
                                     refresh_token=conn['refresh_token'], grant_type='refresh_token'), timeout)
    except Exception:
        conn['status'] = 'expired'; _store(s, conn)
        raise ValueError('Gmail connection expired and could not refresh; reconnect the account')
    conn['access_token'] = t['access_token']
    conn['access_expires'] = time.time() + t.get('expires_in', 3600)
    _store(s, conn)
    return conn['access_token']

def verify_identity(access_token, timeout=15):
    req = urllib.request.Request(GMAIL_PROFILE, headers={'Authorization': 'Bearer ' + access_token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(100000)).get('emailAddress', '').lower()

def disconnect(s, provider, timeout=15):
    conn = get(s, provider)
    if not conn: raise ValueError('No active ' + provider + ' connection')
    try:  # best-effort revocation at Google; local removal happens regardless
        token = conn.get('refresh_token') or conn.get('access_token')
        if token:
            urllib.request.urlopen(urllib.request.Request(
                'https://oauth2.googleapis.com/revoke?token=' + urllib.parse.quote(token, safe=''),
                data=b''), timeout=timeout)
    except Exception: pass
    conn['status'] = 'revoked'; _store(s, conn)
    return {'disconnected': provider, 'identity': conn.get('identity')}
