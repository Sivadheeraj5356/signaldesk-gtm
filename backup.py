"""Strict validated replacement restore. No network or model invocation."""
import json,re,uuid

def validate(s,data):
    if not isinstance(data,dict) or data.get('format')!='signaldesk-backup-v1':raise ValueError('Unsupported backup format')
    accounts=data.get('accounts');campaigns=data.get('campaigns');cfg=data.get('config')
    if not isinstance(accounts,list) or len(accounts)>5000:raise ValueError('Backup must contain at most 5000 accounts')
    if not isinstance(campaigns,list) or len(campaigns)>1000:raise ValueError('Backup must contain at most 1000 experiments')
    if not isinstance(cfg,dict) or set(cfg)!=set(s.DEFAULT):raise ValueError('Invalid playbook fields')
    for k in ['industry','region','offer','cta']:
        if not isinstance(cfg[k],str) or len(cfg[k])>500:raise ValueError('Invalid playbook text')
    for k in ['min_size','max_size','threshold']:
        if type(cfg[k]) is not int:raise ValueError('Playbook numeric values must be integers')
    if not 0<=cfg['threshold']<=100 or not 0<=cfg['min_size']<=cfg['max_size']:raise ValueError('Invalid playbook ranges')
    if type(cfg['ai']) is not bool or cfg['channel'] not in ['email','linkedin','partner']:raise ValueError('Invalid draft settings')
    restored=[];ids=set();domains=set()
    for a in accounts:
        if not isinstance(a,dict):raise ValueError('Invalid account record')
        try:aid=str(uuid.UUID(a['id']))
        except Exception:raise ValueError('Invalid account ID')
        if aid in ids:raise ValueError('Duplicate account ID')
        ids.add(aid)
        for k in ['company','domain','industry','region','contact','evidence','source','draft']:
            if not isinstance(a.get(k),str):raise ValueError('Invalid account text')
        for k in ['suppressed','approved']:
            if type(a.get(k)) is not bool:raise ValueError('Invalid account flag')
        if a.get('size') is not None and type(a.get('size')) is not int:raise ValueError('Invalid account size')
        clean=s.clean(a)
        if clean['domain'] in domains:raise ValueError('Duplicate company domain')
        domains.add(clean['domain'])
        # Derived scores, model output provenance and approvals are never trusted on restore.
        clean.update(id=aid,draft=s.text(a['draft'],8000),approved=False,score=None,reasons=[],engine='restored-unverified')
        restored.append(clean)
    exp=[];eids=set()
    for c in campaigns:
        if not isinstance(c,dict):raise ValueError('Invalid experiment record')
        try:cid=str(uuid.UUID(c['id']))
        except Exception:raise ValueError('Invalid experiment ID')
        if cid in eids:raise ValueError('Duplicate experiment ID')
        eids.add(cid)
        if c.get('channel') not in ['content','community','partner','email','linkedin'] or c.get('stage') not in ['idea','ready','launched','learning']:raise ValueError('Invalid experiment stage/channel')
        for k in ['title','hypothesis','copy','learning']:
            if not isinstance(c.get(k),str):raise ValueError('Invalid experiment text')
        n={k:c.get(k) for k in ['impressions','responses','conversions']}
        if any(type(v) is not int for v in n.values()) or not 0<=n['conversions']<=n['responses']<=n['impressions']:raise ValueError('Invalid experiment counts')
        if not c['title'].strip():raise ValueError('Experiment title required')
        exp.append(dict(id=cid,title=s.text(c['title'],200),hypothesis=s.text(c['hypothesis'],1000),copy=s.text(c['copy'],5000),learning=s.text(c['learning'],1000),channel=c['channel'],stage='idea',updated=s.now(),**n,response_rate=round(n['responses']/n['impressions']*100,2) if n['impressions'] else None,conversion_rate=round(n['conversions']/n['responses']*100,2) if n['responses'] else None))
    return restored,exp,cfg.copy()

def restore(s,data,confirmed=False):
    if confirmed is not True:raise ValueError('Explicit replacement confirmation is required')
    accounts,campaigns,cfg=validate(s,data)
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for t in ['accounts','campaigns','config','runs','jobs']:c.execute('DELETE FROM '+t)
        for a in accounts:c.execute('INSERT INTO accounts VALUES(?,?)',(a['id'],json.dumps(a)))
        for x in campaigns:c.execute('INSERT INTO campaigns VALUES(?,?)',(x['id'],json.dumps(x)))
        c.execute('INSERT INTO config VALUES(1,?)',(json.dumps(cfg),))
    return dict(restored_accounts=len(accounts),restored_experiments=len(campaigns),approvals_reset=True,history_restored=False)
