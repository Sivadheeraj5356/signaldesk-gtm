"""SQLite locally or PostgreSQL on a server. Never fall back after database failure."""
import os,re,sqlite3,threading
READY=set()
LOCK=threading.Lock()
SCHEMA='signaldesk'
class Postgres:
    def __init__(self,url,ws=None):
        import psycopg
        schema='signaldesk' if not ws or ws=='owner' else 'sd_'+re.sub('[^a-z0-9_]','_',str(ws))[:40]
        self.c=psycopg.connect(url,connect_timeout=10,options='-c statement_timeout=15000 -c lock_timeout=5000',sslmode=os.environ.get('PGSSLMODE','verify-full'),sslrootcert=os.environ.get('PGSSLROOTCERT',os.path.join(os.path.dirname(__file__),'supabase-ca.crt')))
        self.c.execute('SET search_path TO '+schema)
        with LOCK:
            if (url,schema) not in READY:
                self.c.execute('CREATE SCHEMA IF NOT EXISTS '+schema)
                for table,cols in [('accounts','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('campaigns','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('outreach','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('connections','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('config','id INTEGER PRIMARY KEY, data TEXT NOT NULL'),('runs','id TEXT PRIMARY KEY, at TEXT, data TEXT NOT NULL'),('jobs','id TEXT PRIMARY KEY, data TEXT NOT NULL')]:
                    self.c.execute('CREATE TABLE IF NOT EXISTS '+table+' (rowid BIGSERIAL UNIQUE,'+cols+')')
                self.c.commit();READY.add((url,schema))
            else:self.c.commit()
    def execute(self,sql,args=()):
        if sql=='BEGIN IMMEDIATE':sql='BEGIN'
        if 'INSERT' in sql and ' VALUES' in sql:
            table=re.search(r'INTO (\w+)',sql).group(1)
            cols='id,at,data' if table=='runs' else 'id,data'
            replace='INSERT OR REPLACE' in sql
            sql=sql.replace('INSERT OR REPLACE','INSERT').replace(' VALUES',' ('+cols+') VALUES')
            if replace:sql+=' ON CONFLICT (id) DO UPDATE SET data=excluded.data'
        return self.c.execute(sql.replace('?','%s'),args)
    def __enter__(self):return self
    def __exit__(self,typ,val,tb):
        try:self.c.rollback() if typ else self.c.commit()
        finally:self.c.close()
    def close(self):self.c.close()
def connect(path,ws=None):
    url=os.environ.get('DATABASE_URL')
    if url:return Postgres(url,ws)
    if ws and ws!='owner':
        safe=re.sub('[^a-z0-9_-]','_',str(ws))[:40]
        path=re.sub(r'(\.sqlite3)?$','',str(path))+'-'+safe+'.sqlite3'
    c=sqlite3.connect(path,timeout=15);c.row_factory=sqlite3.Row
    for t,cols in [('jobs','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('campaigns','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('outreach','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('connections','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('accounts','id TEXT PRIMARY KEY, data TEXT NOT NULL'),('config','id INTEGER PRIMARY KEY, data TEXT NOT NULL'),('runs','id TEXT PRIMARY KEY, at TEXT, data TEXT NOT NULL')]:c.execute('CREATE TABLE IF NOT EXISTS '+t+'('+cols+')')
    c.commit();return c
def probe(path):
    token=os.urandom(6).hex()
    url=os.environ.get('DATABASE_URL')
    if url:
        schema='sd_probe_'+token
        c=None
        try:
            c=Postgres(url,'probe_'+token)
            c.execute('CREATE TABLE IF NOT EXISTS probe(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            c.execute('INSERT INTO probe VALUES(?,?)',('ok','ok'))
            r=c.execute('SELECT data FROM probe WHERE id=?',('ok',)).fetchone()
            if not r or r[0]!='ok': return {'ok':False,'detail':'Probe write did not read back. External workspaces are unavailable; the owner workspace is unaffected.'}
            c.execute('DROP SCHEMA IF EXISTS '+schema+' CASCADE')
            return {'ok':True,'detail':'External workspace storage verified: isolated schema create, write, read and cleanup all succeeded. No existing data was touched.'}
        except Exception as e:
            try:
                if c: c.execute('DROP SCHEMA IF EXISTS '+schema+' CASCADE')
            except Exception: pass
            return {'ok':False,'detail':'External workspace storage is unavailable: '+str(e)[:180]+' No privileges or existing data were changed.'}
        finally:
            try:
                if c: c.close()
            except Exception: pass
    p=re.sub(r'(\.sqlite3)?$','',str(path))+'-probe_'+token+'.sqlite3'
    try:
        c=sqlite3.connect(p); c.execute('CREATE TABLE probe(id TEXT PRIMARY KEY, data TEXT NOT NULL)'); c.execute('INSERT INTO probe VALUES(?,?)',('ok','ok')); c.commit()
        r=c.execute('SELECT data FROM probe WHERE id=?',('ok',)).fetchone(); c.close(); os.remove(p)
        if not r or r[0]!='ok': return {'ok':False,'detail':'Probe write did not read back.'}
        return {'ok':True,'detail':'External workspace storage verified: isolated database file created, written, read and removed.'}
    except Exception as e:
        try: os.remove(p)
        except Exception: pass
        return {'ok':False,'detail':'External workspace storage is unavailable: '+str(e)[:180]}
