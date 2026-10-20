"""Durable single-worker batch preparation. Never sends messages or publishes content."""
import json,uuid,threading,time
LOCK=threading.RLock()
WORKER=None
CANCEL=threading.Event()
def list_jobs(s):
    with s.connect() as c:return [json.loads(r[0]) for r in c.execute('SELECT data FROM jobs ORDER BY rowid DESC LIMIT 30')]
def store(s,j):
    j['updated']=s.now()
    with s.connect() as c:c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(j['id'],json.dumps(j)))
def active(s):return any(j['status'] in ['queued','running','cancelling'] for j in list_jobs(s))
def recover(s):
    for j in list_jobs(s):
        if j['status'] in ['queued','running','cancelling']:
            j.update(status='interrupted',message='Server restarted. Completed accounts are preserved. Retry creates a new job; no external delivery occurred.');store(s,j)
def cancel(s,jid):
    with LOCK:
        j=next((j for j in list_jobs(s) if j['id']==jid),None)
        if not j:raise ValueError('Job not found')
        if j['status'] not in ['queued','running','cancelling']:return j
        CANCEL.set();j.update(status='cancelling',message='Stop requested. The current network/model step may finish before cancellation.');store(s,j);return j

def start(s,d):
    global WORKER
    with LOCK:
        if active(s):raise ValueError('A batch is already active. Wait or cancel it first.')
        ids=d.get('ids')
        available={a['id']:a for a in s.records()}
        if ids is None:ids=list(available)
        if not isinstance(ids,list) or not ids or len(ids)>25:raise ValueError('Choose 1-25 accounts per batch')
        if len(set(ids))!=len(ids) or any(i not in available for i in ids):raise ValueError('Invalid or duplicate account IDs')
        if d.get('research') not in [True,False,None]:raise ValueError('Research must be a boolean')
        j=dict(id=str(uuid.uuid4()),status='queued',created=s.now(),updated=s.now(),ids=ids,research=bool(d.get('research')),config=s.config(),total=len(ids),completed=0,trace=[],message='Preparing account batch. Nothing will be sent.')
        CANCEL.clear();store(s,j);WORKER=threading.Thread(target=process,args=(s,j),daemon=True);WORKER.start();return j

def process(s,j):
    j['status']='running';store(s,j)
    try:
        for aid in j['ids']:
            if CANCEL.is_set():break
            item=dict(id=aid,steps=[],status='complete')
            with s.PIPELINE_LOCK:
                a=next((a for a in s.records() if a['id']==aid),None)
                if not a:item.update(status='skipped',steps=['Account missing'])
                elif a['suppressed']:item.update(company=a['company'],status='skipped',steps=['Suppressed: no research, score or draft change'])
                else:
                    item['company']=a['company']
                    if j['research']:
                        try:
                            s.action('/api/research',{'id':aid});item['steps'].append('Public homepage captured with provenance')
                            a=next(a for a in s.records() if a['id']==aid)
                        except Exception as e:
                            # No silent use of stale research after a requested refresh failed.
                            item.update(status='error');item['steps'].append('Research failed; account left unchanged: '+str(e)[:300])
                    if item['status']!='error' and CANCEL.is_set():
                        item.update(status='cancelled');item['steps'].append('Cancelled before scoring/draft; any completed research is preserved')
                    if item['status']!='error' and not CANCEL.is_set():
                        a=s.prepare(a,j['config']);s.save(a);item['score']=a['score'];item['engine']=a['engine'];item['steps'].append('Scored using job config snapshot')
                        item['steps'].append('Draft prepared for human review' if a['draft'] else 'No draft: below threshold or generation error')
                        if a['engine']=='error':item['status']='error';item['steps'].append(a['reasons'][-1]['detail'])
                        if not a['draft'] and a['engine']!='error':item['status']='skipped'
            j['trace'].append(item);j['completed']+=1
            with LOCK:
                if CANCEL.is_set():j['status']='cancelling'
                store(s,j)
        j['status']='cancelled' if CANCEL.is_set() else 'complete'
        j['message']='Stopped. Completed work preserved; nothing sent.' if CANCEL.is_set() else 'Batch finished. Inspect per-account results and review drafts. Nothing sent.'
    except Exception as e:j.update(status='failed',message='Batch stopped: '+str(e)[:200])
    finally:store(s,j)
