"""SignalDesk: local-only GTM workspace. Python 3.10+, standard library only."""
import csv, io, json, os, re, sqlite3, uuid, datetime, hashlib, urllib.request, threading
import research as public_research
import jobs
import backup
import security
import sys
PIPELINE_LOCK=threading.RLock()
MODEL=None
RESEARCH_LAST={}
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
ROOT = Path(__file__).parent
DB = os.environ.get('SIGNALDESK_DB', str(ROOT / 'signaldesk.sqlite3'))
DEFAULT = dict(industry='SaaS', region='', min_size=10, max_size=500, threshold=55, offer='Turn account research into a repeatable GTM workflow', cta='Would a short walkthrough be useful?', ai=False, channel='email')
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def connect():
    import storage
    return storage.connect(DB)
def config():
    with connect() as c: r=c.execute('SELECT data FROM config WHERE id=1').fetchone()
    return json.loads(r[0]) if r else DEFAULT.copy()
def records():
    with connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT data FROM accounts ORDER BY rowid')]
def save(a):
    with connect() as c: c.execute('INSERT OR REPLACE INTO accounts VALUES(?,?)',(a['id'],json.dumps(a)))
def text(v, n=4000): return str(v or '').strip()[:n]
def domain(v):
    v=text(v,300).lower(); p=urlparse(v if '://' in v else 'https://'+v)
    if p.scheme not in ['http','https'] or p.username or p.password or p.port not in [None,80,443]:raise ValueError('Company domain must not contain credentials or a nonstandard port')
    h=p.hostname or ''
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}',h) or '..' in h or any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in h.split('.')): raise ValueError('Enter a valid company domain, for example company.example')
    return h.removeprefix('www.')
def clean(d):
    if not text(d.get('company')): raise ValueError('Company is required')
    size=d.get('size','')
    if size is not None and str(size).strip():
        try: size=int(size)
        except (ValueError,TypeError): raise ValueError('Company size must be a whole number')
        if size<0 or size>100000000: raise ValueError('Company size is out of range')
    else: size=None
    source=text(d.get('source'),1000)
    if source and (urlparse(source).scheme not in ['http','https'] or not urlparse(source).netloc): raise ValueError('Evidence source must be an http(s) URL')
    return dict(id=str(uuid.uuid4()),company=text(d.get('company'),200),domain=domain(d.get('domain','')),industry=text(d.get('industry'),100),region=text(d.get('region'),100),size=size,contact=text(d.get('contact'),200),evidence=text(d.get('evidence')),source=source,suppressed=str(d.get('suppressed',False)).strip().lower() in ['true','1','yes'],score=None,reasons=[],draft='',approved=False,engine='',updated=now())
def import_rows(rows):
    current={a['domain'] for a in records()}; pending=[]; duplicates=0
    if len(rows)>500: raise ValueError('Import at most 500 rows per batch')
    for i,r in enumerate(rows):
        try: a=clean(r)
        except ValueError as e: raise ValueError('Row '+str(i+1)+': '+str(e))
        if a['domain'] in current: duplicates+=1; continue
        current.add(a['domain']); pending.append(a)
    with connect() as c:
        for a in pending: c.execute('INSERT INTO accounts VALUES(?,?)',(a['id'],json.dumps(a)))
    return dict(imported=len(pending),duplicates=duplicates)
def evaluate(a,cfg):
    points=0; reasons=[]
    for label,ok,weight in [('Industry fit',bool(cfg['industry']) and cfg['industry'].lower() in a['industry'].lower(),30),('Team size',a['size'] is not None and cfg['min_size']<=a['size']<=cfg['max_size'],25),('Region fit',bool(cfg['region']) and cfg['region'].lower() in a['region'].lower(),15),('Source attached',bool(a['source'] and a['evidence']),30)]:
        if ok: points+=weight; reasons.append(dict(step=label,points=weight,detail='Matched supplied data; not independently verified'))
        else: reasons.append(dict(step=label,points=0,detail='Not matched or missing'))
    if a['suppressed']: points=0; reasons.append(dict(step='Suppression',points=0,detail='Excluded from draft generation and exports'))
    return points,reasons
def draft(a,cfg):
    if cfg.get('channel')=='linkedin':
        return 'Draft connection note for manual review: Hi '+(a['contact'] or 'there')+', I am exploring '+a['company']+' for '+cfg['offer']+'. '+cfg['cta']
    if cfg.get('channel')=='partner':
        return 'Partnership idea for '+a['company']+'\n\nPossible collaboration to review: '+cfg['offer']+'.\n\nSuggested conversation: '+cfg['cta']+'\n\nThis is a proposed idea, not an existing relationship or a verified opportunity.'
    greeting='Hi '+(a['contact'] or 'there')+','
    return greeting+'\n\nI am looking at '+a['company']+' as a potential fit for this offer: '+cfg['offer']+'.\n\n'+('Research note to verify before sending: '+a['evidence']+'\nSource: '+a['source']+'\n\n' if a['evidence'] and a['source'] else '')+cfg['cta']
def local_ai(a,cfg):
    global MODEL
    model_path=os.environ.get('SIGNALDESK_GGUF')
    if model_path:
        try:
            from llama_cpp import Llama
            if MODEL is None: MODEL=Llama(model_path=model_path,n_ctx=2048,n_threads=2,verbose=False)
            message=MODEL.create_chat_completion(messages=[
                {'role':'system','content':'Rewrite the seller offer as one short question to a prospective customer. Start with Would and end with ?. Do not add facts or commentary. Do not mention any company name or research. Examples: Offer: help reduce manual spreadsheets. Question: Would reducing manual spreadsheet work be useful for your team? Offer: organize partner leads. Question: Would a clearer way to organize partner leads be useful for your team?'},
                {'role':'user','content':'Offer: '+cfg['offer'][:350]+'. Question:'}],max_tokens=65,temperature=0.1,seed=42)
            choice=message['choices'][0]
            result=text(choice['message']['content'],1000).strip('"')
            if choice.get('finish_reason')!='stop' or not result.startswith('Would ') or not result.endswith('?') or len(result)>500:
                raise ValueError('Model did not return a complete bounded question; review offer or retry')
            # Keep research and identity out of free-form model output. Only the value question is generated.
            base=draft(a,cfg)
            return base+'\n\nAI-suggested value question (review before use): '+result
        except Exception as e: raise ValueError('Local GGUF generation failed: '+str(e)[:200])
    if os.environ.get('SIGNALDESK_ENABLE_OLLAMA')!='1': raise ValueError('Local AI is disabled. Start with SIGNALDESK_ENABLE_OLLAMA=1 and a local Ollama model. No cloud provider is used.')
    payload=dict(model=os.environ.get('SIGNALDESK_MODEL','qwen2.5:1.5b'),stream=False,prompt='Rewrite the following seller offer as one short question to a prospective customer. Start with Would and end with ?. Do not add facts, company names, research or commentary. Offer: '+cfg['offer'][:350],options={'num_predict':65,'temperature':0.1})
    req=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=90) as r: data=json.loads(r.read(1000000))
    except Exception: raise ValueError('Local model unavailable. Start Ollama, install the configured model, and retry. Nothing was sent.')
    result=text(data.get('response'),8000)
    if not result.startswith('Would ') or not result.endswith('?') or len(result)>500: raise ValueError('Local model did not return a complete bounded question')
    return draft(a,cfg)+'\n\nAI-suggested value question (review before use): '+result

def prepare(a,cfg):
    score,reasons=evaluate(a,cfg);a.update(score=score,reasons=reasons,approved=False,draft='',engine='rules',updated=now())
    if not a['suppressed'] and score>=cfg['threshold']:
        try:a.update(draft=local_ai(a,cfg) if cfg['ai'] else draft(a,cfg),engine=('gguf' if os.environ.get('SIGNALDESK_GGUF') else 'ollama') if cfg['ai'] else 'template')
        except ValueError as e:a['engine']='error';reasons.append(dict(step='Draft failed',points=0,detail=str(e)))
    return a

def run():
    cfg=config();result=[]
    for a in records():
        a=prepare(a,cfg);save(a);result.append(dict(company=a['company'],score=a['score'],engine=a['engine'],reasons=a['reasons']))
    r=dict(id=str(uuid.uuid4()),at=now(),accounts=len(result),drafts=sum(x['engine'] in ['template','ollama','gguf'] for x in result),config=cfg,trace=result)
    with connect() as c:c.execute('INSERT INTO runs VALUES(?,?,?)',(r['id'],r['at'],json.dumps(r)))
    return r


def safe_cell(x):
    s=str(x if x is not None else '')
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s

def export():
    out=io.StringIO(); w=csv.writer(out); w.writerow(['company','domain','contact','score','source','draft','engine'])
    for a in records():
        if a['approved'] and a['draft'] and not a['suppressed']: w.writerow([safe_cell(a.get(k)) for k in ['company','domain','contact','score','source','draft','engine']])
    return out.getvalue()

def campaigns():
    with connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT data FROM campaigns ORDER BY rowid DESC')]

def campaign_save(d):
    title=text(d.get('title'),200)
    if not title: raise ValueError('Campaign title is required')
    channel=d.get('channel','content')
    if channel not in ['content','community','partner','email','linkedin']:raise ValueError('Invalid channel')
    stage=d.get('stage','idea')
    if stage not in ['idea','ready','launched','learning']:raise ValueError('Invalid stage')
    counts={k:int(d.get(k,0)) for k in ['impressions','responses','conversions']}
    if any(x<0 for x in counts.values()) or counts['conversions']>counts['responses'] or counts['responses']>counts['impressions']:raise ValueError('Metrics must satisfy 0 <= conversions <= responses <= impressions')
    cid=d.get('id') or str(uuid.uuid4())
    old=next((c for c in campaigns() if c['id']==cid),None)
    if d.get('id') and not old: raise ValueError('Campaign not found')
    if stage=='launched' and not d.get('manual_launch_confirmed'):raise ValueError('Confirm that you launched it yourself outside this app')
    c=dict(id=cid,title=title,channel=channel,stage=stage,hypothesis=text(d.get('hypothesis'),1000),copy=text(d.get('copy'),5000),learning=text(d.get('learning'),1000),updated=now(),**counts)
    c['response_rate']=round(c['responses']/c['impressions']*100,2) if c['impressions'] else None
    c['conversion_rate']=round(c['conversions']/c['responses']*100,2) if c['responses'] else None
    with connect() as db:db.execute('INSERT OR REPLACE INTO campaigns VALUES(?,?)',(cid,json.dumps(c)))
    return c

def state():
    with connect() as c: runs=[json.loads(r[0]) for r in c.execute('SELECT data FROM runs ORDER BY at DESC LIMIT 20')]
    return dict(accounts=records(),config=config(),runs=runs,campaigns=campaigns(),jobs=jobs.list_jobs(sys.modules[__name__]),ai_enabled=bool(os.environ.get('SIGNALDESK_GGUF')) or os.environ.get('SIGNALDESK_ENABLE_OLLAMA')=='1')

def action(path,d):
    if path=='/api/restore':return backup.restore(sys.modules[__name__],d.get('backup'),d.get('confirmed'))
    if path=='/api/campaign': return campaign_save(d)
    if path=='/api/research':
        a=next((a for a in records() if a['id']==d.get('id')),None)
        if not a: raise ValueError('Account not found')
        if a['suppressed']: raise ValueError('Suppressed accounts are not researched')
        import time
        last=RESEARCH_LAST.get(a['domain'],0)
        if time.monotonic()-last<60: raise ValueError('Wait one minute between research requests for this domain')
        RESEARCH_LAST[a['domain']]=time.monotonic()
        url='https://'+a['domain']+'/'
        try: result=public_research.bounded_research(url)
        except ValueError: raise
        except Exception: raise ValueError('Public research failed or timed out. Existing evidence was preserved; use manual evidence instead.')
        a.update(source=result['url'],evidence=result['excerpt'],research=result,approved=False,draft='',score=None,reasons=[],updated=now())
        save(a); return result
    if path=='/api/import':
        if 'csv' in d:
            reader=csv.DictReader(io.StringIO(d['csv']))
            if not reader.fieldnames or not {'company','domain'}.issubset(reader.fieldnames): raise ValueError('CSV needs company and domain headers')
            return import_rows(list(reader))
        return import_rows(d['rows'])
    if path=='/api/config':
        cfg={k:d.get(k,v) for k,v in DEFAULT.items()}
        for k in ['min_size','max_size','threshold']: cfg[k]=int(cfg[k])
        if not 0<=cfg['threshold']<=100 or not 0<=cfg['min_size']<=cfg['max_size']: raise ValueError('Check score and size ranges')
        for k in ['industry','region','offer','cta']: cfg[k]=text(cfg[k],500)
        cfg['ai']=bool(cfg['ai'])
        if cfg.get('channel') not in ['email','linkedin','partner']: raise ValueError('Unknown distribution channel')
        with connect() as c:
            c.execute('INSERT OR REPLACE INTO config VALUES(1,?)',(json.dumps(cfg),))
            for a in records(): a.update(approved=False); c.execute('UPDATE accounts SET data=? WHERE id=?',(json.dumps(a),a['id']))
        return cfg
    if path=='/api/run': return run()
    if path=='/api/account':
        old=next((a for a in records() if a['id']==d.get('id')),None)
        if not old: raise ValueError('Account not found')
        if 'delete' in d:
            with connect() as c: c.execute('DELETE FROM accounts WHERE id=?',(old['id'],))
            return {'deleted':True}
        if 'draft' in d: old.update(draft=text(d['draft'],8000),approved=False)
        if 'suppressed' in d: old.update(suppressed=bool(d['suppressed']),approved=False)
        if 'approved' in d:
            if d['approved'] and (not old['draft'] or old['suppressed']): raise ValueError('A non-suppressed draft is required')
            old['approved']=bool(d['approved'])
        old['updated']=now(); save(old); return old
    raise ValueError('Unknown action')

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(30)
    def log_message(self,*args): pass
    def trusted(self):
        if security.enabled():
            u=urlparse(security.origin())
            return self.headers.get('Host')==u.netloc and (not self.headers.get('Origin') or self.headers.get('Origin')==security.origin())
        return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'] and (not self.headers.get('Origin') or self.headers['Origin'] in [f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'])
    def send(self,status,data,typ='application/json',cookie=None):
        b=data.encode() if isinstance(data,str) else json.dumps(data).encode(); self.send_response(status)
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Referrer-Policy','no-referrer')
        if security.enabled():self.send_header('Strict-Transport-Security','max-age=31536000')
        self.send_header('Content-Type',typ+'; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path=='/healthz': return self.send(200,{'ok':True})
        if not self.trusted(): return self.send(403,{'error':'Local access only'})
        if security.enabled():
            auth=security.session(sys.modules[__name__],self.headers.get('Cookie'))
            if self.path=='/api/auth':return self.send(200,{'authenticated':bool(auth),'csrf':auth['csrf'] if auth else None})
            if self.path=='/api/auth/google/start':
                if not security.google_configured():return self.send(400,{'error':'Google sign-in is not configured'})
                self.send_response(302);self.send_header('Location',security.google_start(sys.modules[__name__]));self.send_header('Content-Length','0');self.end_headers();return
            if self.path.startswith('/api/auth/google/callback'):
                if not security.google_configured():return self.send(400,{'error':'Google sign-in is not configured'})
                from urllib.parse import parse_qs
                q=parse_qs(urlparse(self.path).query)
                try:raw,_=security.google_finish(sys.modules[__name__],q.get('code',[''])[0],q.get('state',[''])[0])
                except ValueError as e:return self.send(400,{'error':str(e)})
                self.send_response(302);self.send_header('Location','/');self.send_header('Set-Cookie',security.COOKIE.format(raw));self.send_header('Content-Length','0');self.end_headers();return
            if not auth:
                if self.path in ['/','/index.html']:
                    page=(ROOT/'login.html').read_text().replace('__GOOGLE_ENABLED__','true' if security.google_configured() else 'false')
                    return self.send(200,page,'text/html')
                return self.send(401,{'error':'Sign in required'})
        if self.path=='/api/state': return self.send(200,state())
        if self.path=='/api/backup':
            data=state();data.update(format='signaldesk-backup-v1',created=now());return self.send(200,data)
        if self.path=='/api/export': return self.send(200,export(),'text/csv')
        if self.path in ['/','/index.html']: return self.send(200,(ROOT/'index.html').read_text(),'text/html')
        return self.send(404,{'error':'Not found'})
    def do_POST(self):
        if not self.trusted(): return self.send(403,{'error':'Local access only'})
        if self.headers.get_content_type()!='application/json': return self.send(415,{'error':'Use application/json'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=10000000: raise ValueError('Payload must be between 1 byte and 10 MB')
            d=json.loads(self.rfile.read(n))
            if not isinstance(d,dict):raise ValueError('JSON body must be an object')
            if security.enabled():
                if self.headers.get('Origin')!=security.origin():return self.send(403,{'error':'Same-origin request required'})
                if self.path=='/api/login':
                    if not security.email_allowed(d.get('email','')):return self.send(403,{'error':'This email is not authorized for this workspace'})
                    raw,auth=security.login(sys.modules[__name__],d.get('password',''),'owner')
                    return self.send(200,{'ok':True},cookie=security.COOKIE.format(raw))
                auth=security.session(sys.modules[__name__],self.headers.get('Cookie'))
                if not auth:return self.send(401,{'error':'Sign in required'})
                if not __import__('hmac').compare_digest(self.headers.get('X-CSRF-Token',''),auth['csrf']):return self.send(403,{'error':'Refresh your session and retry'})
                if self.path=='/api/logout':
                    security.logout(sys.modules[__name__],self.headers.get('Cookie'));return self.send(200,{'ok':True},cookie=security.COOKIE.format('')+'; Max-Age=0')
            if self.path=='/api/jobs/start':
                with PIPELINE_LOCK:result=jobs.start(sys.modules[__name__],d)
            elif self.path=='/api/jobs/cancel':result=jobs.cancel(sys.modules[__name__],d.get('id'))
            else:
                with PIPELINE_LOCK:
                    if jobs.active(sys.modules[__name__]):raise ValueError('A batch is active. Wait or cancel before changing workspace data.')
                    result=action(self.path,d)
            return self.send(200,result)
        except (ValueError,KeyError,TypeError) as e: return self.send(400,{'error':str(e)})
        except Exception: return self.send(500,{'error':'Internal error; check local data and retry'})
def main():
    security.validate()
    port=int(os.environ.get('PORT','8787')); connect().close()
    if security.enabled():security.init(sys.modules[__name__])
    jobs.recover(sys.modules[__name__])
    host='0.0.0.0' if security.enabled() else '127.0.0.1'
    print('SignalDesk listening on '+host+':'+str(port),flush=True)
    ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=='__main__':main()
