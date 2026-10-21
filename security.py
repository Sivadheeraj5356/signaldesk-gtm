"""Single-owner server gate. Secrets stay in environment; only hashes are persisted."""
import os,secrets,hashlib,hmac,time,threading,json
from http.cookies import SimpleCookie
LOCK=threading.Lock()
FAILURES={}
def enabled():return os.environ.get('SIGNALDESK_MODE','local')=='server'
def validate():
    if not enabled():return
    from urllib.parse import urlparse
    u=urlparse(origin())
    if u.scheme!='https' or not u.netloc or u.path not in ['', '/']:raise ValueError('Server mode requires SIGNALDESK_ORIGIN=https://your-host')
    if len(os.environ.get('SIGNALDESK_PASSWORD',''))<16:raise ValueError('Server password must contain at least 16 characters')
    if not os.environ.get('DATABASE_URL') and not os.environ.get('SIGNALDESK_PERSISTENT_DISK')=='1':raise ValueError('Server mode needs DATABASE_URL or a confirmed persistent volume')
def origin():return (os.environ.get('SIGNALDESK_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/')
def token_hash(v):return hashlib.sha256(v.encode()).hexdigest()
def init(s):
    with s.default_connect() as c:c.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
def cookie(h):
    try:
        c=SimpleCookie(h or '');return c['signaldesk_session'].value if 'signaldesk_session' in c else ''
    except Exception:return ''
def session(s,h):
    raw=cookie(h)
    if not raw:return None
    with s.default_connect() as c:r=c.execute('SELECT data FROM sessions WHERE id=?',(token_hash(raw),)).fetchone()
    if not r:return None
    d=json.loads(r[0])
    if not (d['expires']>time.time() and hmac.compare_digest(d.get('version',''),token_hash(os.environ.get('SIGNALDESK_PASSWORD','')))):return None
    if 'ws' not in d:
        if 'email' in d:
            if d.get('email') in owner_emails(): d['ws']='owner'
            else: return None
        else: d['ws']='owner'
    return d
def login(s,password,key,email=''):
    # Global cap is intentional behind a reverse proxy. Do not trust forwarded client IPs.
    with LOCK:
        attempts=FAILURES.get(key,[]);attempts=[x for x in attempts if time.time()-x<900]
        if len(attempts)>=8:raise ValueError('Too many attempts. Wait 15 minutes.')
        if not hmac.compare_digest(str(password).encode(),os.environ.get('SIGNALDESK_PASSWORD','').encode()):
            FAILURES[key]=attempts+[time.time()];raise ValueError('Incorrect password')
        FAILURES.pop(key,None)
    raw=secrets.token_urlsafe(40);d={'csrf':secrets.token_urlsafe(32),'expires':time.time()+43200,'version':token_hash(os.environ.get('SIGNALDESK_PASSWORD','')),'email':str(email).strip().lower(),'ws':'owner'}
    with s.default_connect() as c:
        for row in c.execute('SELECT id,data FROM sessions').fetchall():
            if json.loads(row[1])['expires']<time.time():c.execute('DELETE FROM sessions WHERE id=?',(row[0],))
        c.execute('INSERT INTO sessions VALUES(?,?)',(token_hash(raw),json.dumps(d)))
    return raw,d
COOKIE='signaldesk_session={}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200'
def tenant_session(s,email,ws):
    raw=secrets.token_urlsafe(40)
    d={'csrf':secrets.token_urlsafe(32),'expires':time.time()+43200,'version':token_hash(os.environ.get('SIGNALDESK_PASSWORD','')),'email':str(email).strip().lower(),'ws':ws}
    with s.default_connect() as c:c.execute('INSERT INTO sessions VALUES(?,?)',(token_hash(raw),json.dumps(d)))
    return raw,d
def logout(s,h):
    with s.default_connect() as c:c.execute('DELETE FROM sessions WHERE id=?',(token_hash(cookie(h)),))

def google_configured():return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))
def owner_emails():return [e.strip().lower() for e in os.environ.get('SIGNALDESK_OWNER_EMAILS','').split(',') if e.strip()]
def email_allowed(v):return not owner_emails() or str(v).strip().lower() in owner_emails()
def google_start(s):
    raw=secrets.token_urlsafe(24)
    with s.default_connect() as c:c.execute('INSERT INTO sessions VALUES(?,?)',(token_hash('oauth-state-'+raw),json.dumps({'oauth':True,'expires':time.time()+600})))
    from urllib.parse import urlencode
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':os.environ['GOOGLE_CLIENT_ID'],'redirect_uri':origin()+'/api/auth/google/callback','response_type':'code','scope':'openid email profile','state':raw,'access_type':'online'})
def gmail_connect_start(s,ws,email):
    """OAuth consent for gmail.send on the SAME Google OAuth client as sign-in.
    State nonce binds this workspace+user; offline access asks for a refresh token."""
    if not google_configured():raise ValueError('Google OAuth client is not configured on this server')
    raw=secrets.token_urlsafe(24)
    with s.default_connect() as c:c.execute('INSERT INTO sessions VALUES(?,?)',(token_hash('gmail-connect-'+raw),json.dumps({'ws':ws,'email':email,'expires':time.time()+600})))
    from urllib.parse import urlencode
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':os.environ['GOOGLE_CLIENT_ID'],'redirect_uri':origin()+'/api/connect/gmail/callback','response_type':'code','scope':'https://www.googleapis.com/auth/gmail.send','state':raw,'access_type':'offline','prompt':'consent'})
def gmail_connect_finish(s,code,state):
    import connections
    if not code or not state:raise ValueError('Google consent was cancelled or failed. Try again.')
    with s.default_connect() as c:
        r=c.execute('SELECT data FROM sessions WHERE id=?',(token_hash('gmail-connect-'+state),)).fetchone()
        c.execute('DELETE FROM sessions WHERE id=?',(token_hash('gmail-connect-'+state),))
    if not r:raise ValueError('Connection attempt expired or unknown. Start again.')
    st=json.loads(r[0])
    if st['expires']<time.time():raise ValueError('Connection attempt expired. Start again.')
    import urllib.request,urllib.parse
    body=urllib.parse.urlencode({'code':code,'client_id':os.environ['GOOGLE_CLIENT_ID'],'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'redirect_uri':origin()+'/api/connect/gmail/callback','grant_type':'authorization_code'}).encode()
    try:
        t=json.loads(urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token',data=body),timeout=15).read())
    except Exception:raise ValueError('Google token exchange failed. Try again.')
    if not t.get('refresh_token'):raise ValueError('Google did not return a refresh token. Revoke SignalDesk access in your Google account and connect again.')
    s.CTX.ws=st['ws'];s.CTX.email=st['email']
    identity=connections.verify_identity(t['access_token'])
    if not identity:raise ValueError('Could not verify the connected Gmail address.')
    conn=connections.save_gmail(s,identity,t['refresh_token'],t.get('access_token'),t.get('expires_in'))
    return {'connected':identity,'ws':st['ws']}
def google_finish(s,code,state):
    if not code or not state:raise ValueError('Google sign-in was cancelled or failed. Try again.')
    with s.default_connect() as c:
        r=c.execute('SELECT data FROM sessions WHERE id=?',(token_hash('oauth-state-'+state),)).fetchone()
        c.execute('DELETE FROM sessions WHERE id=?',(token_hash('oauth-state-'+state),))
    if not r or json.loads(r[0])['expires']<time.time():raise ValueError('Sign-in link expired. Start again.')
    import urllib.request,urllib.parse
    body=urllib.parse.urlencode({'code':code,'client_id':os.environ['GOOGLE_CLIENT_ID'],'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'redirect_uri':origin()+'/api/auth/google/callback','grant_type':'authorization_code'}).encode()
    try:
        t=json.loads(urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token',data=body),timeout=15).read())
        req=urllib.request.Request('https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+t['access_token']})
        u=json.loads(urllib.request.urlopen(req,timeout=15).read())
    except Exception:raise ValueError('Google sign-in failed. Try again.')
    email=str(u.get('email','')).lower()
    if not email or not u.get('email_verified'):raise ValueError('This Google account is not authorized for this workspace.')
    if email in owner_emails(): ws='owner'
    elif s.access_granted(email): ws='u_'+hashlib.sha256(email.encode()).hexdigest()[:16]
    else:
        import accounts
        existing=accounts.get(s,email)
        if existing: ws=existing['ws']
        else: ws=accounts.create(s,email,secrets.token_urlsafe(24))['ws']
    raw=secrets.token_urlsafe(40);d={'csrf':secrets.token_urlsafe(32),'expires':time.time()+43200,'version':token_hash(os.environ.get('SIGNALDESK_PASSWORD','')),'email':email,'ws':ws}
    with s.default_connect() as c:c.execute('INSERT INTO sessions VALUES(?,?)',(token_hash(raw),json.dumps(d)))
    return raw,d
