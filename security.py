"""Single-owner server gate. Secrets stay in environment; only hashes are persisted."""
import os,secrets,hashlib,hmac,time,threading,json
from http.cookies import SimpleCookie
LOCK=threading.Lock()
FAILURES={}
def enabled():return os.environ.get('SIGNALDESK_MODE','local')=='server'
def validate():
    if not enabled():return
    from urllib.parse import urlparse
    u=urlparse(os.environ.get('SIGNALDESK_ORIGIN',''))
    if u.scheme!='https' or not u.netloc or u.path not in ['', '/']:raise ValueError('Server mode requires SIGNALDESK_ORIGIN=https://your-host')
    if len(os.environ.get('SIGNALDESK_PASSWORD',''))<16:raise ValueError('Server password must contain at least 16 characters')
    if not os.environ.get('DATABASE_URL') and not os.environ.get('SIGNALDESK_PERSISTENT_DISK')=='1':raise ValueError('Server mode needs DATABASE_URL or a confirmed persistent volume')
def origin():return os.environ.get('SIGNALDESK_ORIGIN','').rstrip('/')
def token_hash(v):return hashlib.sha256(v.encode()).hexdigest()
def init(s):
    with s.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
def cookie(h):
    try:
        c=SimpleCookie(h or '');return c['signaldesk_session'].value if 'signaldesk_session' in c else ''
    except Exception:return ''
def session(s,h):
    raw=cookie(h)
    if not raw:return None
    with s.connect() as c:r=c.execute('SELECT data FROM sessions WHERE id=?',(token_hash(raw),)).fetchone()
    if not r:return None
    d=json.loads(r[0]);return d if d['expires']>time.time() and hmac.compare_digest(d.get('version',''),token_hash(os.environ.get('SIGNALDESK_PASSWORD',''))) else None
def login(s,password,key):
    # Global cap is intentional behind a reverse proxy. Do not trust forwarded client IPs.
    with LOCK:
        attempts=FAILURES.get(key,[]);attempts=[x for x in attempts if time.time()-x<900]
        if len(attempts)>=8:raise ValueError('Too many attempts. Wait 15 minutes.')
        if not hmac.compare_digest(str(password).encode(),os.environ.get('SIGNALDESK_PASSWORD','').encode()):
            FAILURES[key]=attempts+[time.time()];raise ValueError('Incorrect password')
        FAILURES.pop(key,None)
    raw=secrets.token_urlsafe(40);d={'csrf':secrets.token_urlsafe(32),'expires':time.time()+43200,'version':token_hash(os.environ.get('SIGNALDESK_PASSWORD',''))}
    with s.connect() as c:
        for row in c.execute('SELECT id,data FROM sessions').fetchall():
            if json.loads(row[1])['expires']<time.time():c.execute('DELETE FROM sessions WHERE id=?',(row[0],))
        c.execute('INSERT INTO sessions VALUES(?,?)',(token_hash(raw),json.dumps(d)))
    return raw,d
COOKIE='signaldesk_session={}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200'
def logout(s,h):
    with s.connect() as c:c.execute('DELETE FROM sessions WHERE id=?',(token_hash(cookie(h)),))
