"""Self-serve tenant accounts: signup, password login, workspace provisioning.

Owner access (env password / owner Google emails) is unchanged. Tenant passwords
are PBKDF2-HMAC-SHA256 hashes with per-user salt; only hashes persist.
Each account gets an isolated workspace u_<hash> (storage.py schema isolation).
"""
import hashlib, hmac, os, re, secrets, time, json

ITERATIONS = 210_000
EMAIL_RE = r'[^@\s]+@[^@\s]+\.[^@\s]+'

def _hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS).hex()

def workspace_for(email):
    return 'u_' + hashlib.sha256(email.encode()).hexdigest()[:16]

def _table(c):
    c.execute('CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, data TEXT NOT NULL)')

def create(s, email, password, company=None):
    email = str(email or '').strip().lower()
    if not re.fullmatch(EMAIL_RE, email):
        raise ValueError('Enter a valid email address')
    if len(str(password)) < 10:
        raise ValueError('Password must contain at least 10 characters')
    import security
    if email in security.owner_emails():
        raise ValueError('This email already has owner access; sign in instead')
    with s.default_connect() as c:
        _table(c)
        if c.execute('SELECT data FROM users WHERE id=?', (email,)).fetchone():
            raise ValueError('An account with this email already exists; sign in instead')
        salt = secrets.token_bytes(16)
        ws = workspace_for(email)
        u = dict(email=email, salt=salt.hex(), hash=_hash(str(password), salt),
                 ws=ws, created=s.now(), company=None)
        c.execute('INSERT INTO users VALUES(?,?)', (email, json.dumps(u)))
    # Provision the tenant workspace eagerly so first login never depends on it.
    with s.connect_workspace(ws) as c:
        pass
    return {'email': email, 'ws': ws}

def authenticate(s, email, password):
    email = str(email or '').strip().lower()
    with s.default_connect() as c:
        _table(c)
        r = c.execute('SELECT data FROM users WHERE id=?', (email,)).fetchone()
    if not r:
        raise ValueError('Incorrect email or password')
    u = json.loads(r[0])
    if not hmac.compare_digest(_hash(str(password), bytes.fromhex(u['salt'])), u['hash']):
        raise ValueError('Incorrect email or password')
    return u

def get(s, email):
    with s.default_connect() as c:
        _table(c)
        r = c.execute('SELECT data FROM users WHERE id=?', (str(email or '').strip().lower(),)).fetchone()
    return json.loads(r[0]) if r else None
