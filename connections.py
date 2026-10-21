"""Per-workspace provider connections (Gmail first). Replaces static env tokens with
durable OAuth connections: verified OIDC identity, refresh-token rotation, fail-closed
status. Identity comes from the OIDC userinfo endpoint (openid+email scopes), NOT the
Gmail profile endpoint: users.getProfile is not authorized by gmail.send alone.

Token storage: AES-256-GCM encrypted at rest in the workspace DB (tenant-isolated schema
on PG). Key: SIGNALDESK_TOKEN_KEY env (base64url 32 bytes) in deployed environments; in
local dev a key is generated once and persisted next to the DB with mode 0600. Losing the
key invalidates stored connections (they must be reconnected) - it never exposes tokens.
DB backups therefore carry ciphertext only.
"""
import os, json, time, uuid, base64, threading, urllib.request, urllib.parse
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

GOOGLE_TOKEN = 'https://oauth2.googleapis.com/token'
GOOGLE_REVOKE = 'https://oauth2.googleapis.com/revoke'
USERINFO = 'https://openidconnect.googleapis.com/v1/userinfo'

_locks = {}
_locks_guard = threading.Lock()

def _lock_for(conn_id):
    with _locks_guard: return _locks.setdefault(conn_id, threading.Lock())

def _key():
    raw = os.environ.get('SIGNALDESK_TOKEN_KEY', '')
    if raw:
        k = base64.urlsafe_b64decode(raw.encode())
        if len(k) != 32: raise ValueError('SIGNALDESK_TOKEN_KEY must be a base64url-encoded 32-byte key')
        return k
    import server
    path = server.DB + '.tokenkey' if server.DB != ':memory:' else None
    if path and os.path.exists(path):
        with open(path, 'rb') as f: return base64.urlsafe_b64decode(f.read())
    k = AESGCM.generate_key(bit_length=256)
    if path:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'wb') as f: f.write(base64.urlsafe_b64encode(k))
    return k

def _enc(plaintext):
    if not plaintext: return ''
    nonce = os.urandom(12)
    return 'v1.' + base64.urlsafe_b64encode(nonce + AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)).decode()

def _dec(stored):
    if not stored: return ''
    raw = base64.urlsafe_b64decode(stored[3:].encode())
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()

def list_connections(s):
    with s.connect() as c:
        try: return [json.loads(r[0]) for r in c.execute('SELECT data FROM connections ORDER BY rowid DESC')]
        except Exception: return []

def _materialize(conn):
    """Decrypted working copy; never persisted."""
    c = dict(conn)
    c['refresh_token'] = _dec(conn.get('refresh_token', ''))
    c['access_token'] = _dec(conn.get('access_token', ''))
    return c

def _store(s, conn):
    conn['updated'] = s.now()
    blob = dict(conn, refresh_token=_enc(conn.get('refresh_token', '')),
                access_token=_enc(conn.get('access_token', '')))
    with s.connect() as c: c.execute('INSERT OR REPLACE INTO connections VALUES(?,?)', (conn['id'], json.dumps(blob)))

def get(s, provider):
    conn = next((c for c in list_connections(s) if c['provider'] == provider and c.get('status') == 'active'), None)
    return _materialize(conn) if conn else None

def public_state(s):
    """Safe for /api/state: identity + status only, never tokens (encrypted or not)."""
    return [dict(provider=c['provider'], identity=c.get('identity'), status=c.get('status'),
                 connected_at=c.get('connected_at')) for c in list_connections(s)]

def save_gmail(s, identity, refresh_token, access_token=None, expires_in=None, scopes=None):
    # one active connection per provider per workspace: a new connect supersedes the old
    for old in list_connections(s):
        if old['provider'] == 'gmail' and old.get('status') == 'active':
            old = _materialize(old); old['status'] = 'replaced'
            old['refresh_token'] = ''; old['access_token'] = ''; old['access_expires'] = 0
            _store(s, old)
    conn = dict(id=str(uuid.uuid4()), provider='gmail', identity=identity.lower(),
                refresh_token=refresh_token, access_token=access_token or '',
                access_expires=time.time() + (expires_in or 0) if access_token else 0,
                scopes=scopes or ['openid', 'email', 'gmail.send'], status='active',
                connected_at=s.now(), updated_at=s.now())
    _store(s, conn)
    return conn

def _post(url, params, timeout=15):
    body = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=timeout) as r:
        return json.loads(r.read(200000))

def gmail_access_token(s, conn, timeout=15):
    """Valid access token, refreshing when expired - one refresh per connection at a time
    (a second caller waits and reuses the result). Marks the connection expired
    (fail-closed) when Google rejects the refresh token. Rotation-safe: a new refresh
    token in Google's response replaces the old one."""
    if conn.get('access_token') and time.time() < conn.get('access_expires', 0) - 60:
        return conn['access_token']
    with _lock_for(conn['id']):
        fresh = get(s, conn['provider'])
        if fresh and fresh['id'] == conn['id'] and fresh.get('access_token') \
           and time.time() < fresh.get('access_expires', 0) - 60:
            return fresh['access_token']
        if fresh and fresh['id'] == conn['id']: conn = fresh
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
        if t.get('refresh_token'): conn['refresh_token'] = t['refresh_token']
        _store(s, conn)
        return conn['access_token']

def verify_identity(access_token, timeout=15):
    """Verified OIDC identity: userinfo with openid+email scopes, email_verified required.
    Deliberately not the Gmail profile endpoint (needs gmail.readonly/metadata/modify)."""
    req = urllib.request.Request(USERINFO, headers={'Authorization': 'Bearer ' + access_token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        u = json.loads(r.read(100000))
    if not u.get('email_verified'): raise ValueError('Google did not verify this email address')
    return str(u.get('email', '')).lower()

def disconnect(s, provider, timeout=15):
    """Revoke at Google (token in POST body, never in URLs), then remove the active
    connection regardless of revoke outcome - fail-closed locally either way. Reports
    whether the remote revocation succeeded."""
    conn = get(s, provider)
    if not conn: raise ValueError('No active ' + provider + ' connection')
    revoked = False
    token = conn.get('refresh_token') or conn.get('access_token')
    if token:
        try:
            body = urllib.parse.urlencode({'token': token}).encode()
            urllib.request.urlopen(urllib.request.Request(GOOGLE_REVOKE, data=body), timeout=timeout).read()
            revoked = True
        except Exception: revoked = False
    conn['status'] = 'revoked'
    conn['refresh_token'] = ''; conn['access_token'] = ''; conn['access_expires'] = 0
    _store(s, conn)
    return {'disconnected': provider, 'identity': conn.get('identity'), 'revoked_at_google': revoked}
