import unittest, tempfile, os, json, time, hashlib
import server as s
import security, jobs, storage

EXT='ext@example.com'
EXT_WS='u_'+hashlib.sha256(EXT.encode()).hexdigest()[:16]

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); s.DB=self.tmp.name+'/test.db'; s.connect().close()
        s.CTX.ws=None; s.CTX.email=None
        os.environ['SIGNALDESK_PASSWORD']='test-password-123456'
        security.FAILURES.clear()
    def tearDown(self):
        self.tmp.cleanup(); s.CTX.ws=None; s.CTX.email=None
    def row(self,**kw):
        d=dict(company='Demo',domain='demo.example',industry='SaaS',region='India',size=30,evidence='Supplied note',source='https://demo.example/news'); d.update(kw); return d

    def test_owner_workspace_is_default_and_unchanged(self):
        self.assertEqual(s.ws(),'owner')
        s.import_rows([self.row()])
        self.assertEqual(len(s.records()),1)
        self.assertTrue(os.path.exists(self.tmp.name+'/test.db'))

    def test_cross_workspace_read_write_isolation(self):
        s.import_rows([self.row()])  # owner data
        s.CTX.ws=EXT_WS
        self.assertEqual(s.records(),[])  # user sees nothing of owner
        s.import_rows([self.row(domain='other.example',company='Other')])
        self.assertEqual(len(s.records()),1)
        s.CTX.ws=None
        self.assertEqual(len(s.records()),1)  # owner unchanged
        self.assertEqual(s.records()[0]['domain'],'demo.example')

    def test_export_isolation(self):
        a=s.import_rows([self.row()]); r=s.records()[0]
        r.update(draft='Hi',approved=True); s.save(r)
        owner_csv=s.export()
        self.assertIn('Demo',owner_csv)
        s.CTX.ws=EXT_WS
        self.assertNotIn('Demo',s.export())
        self.assertEqual(s.export().strip(),'company,domain,contact,score,source,draft,engine')

    def test_job_writes_to_owning_workspace(self):
        s.CTX.ws=EXT_WS
        s.import_rows([self.row(domain='job.example')])
        j=jobs.start(s,dict(research=False))
        for _ in range(100):
            time.sleep(0.1)
            cur=jobs.list_jobs(s)[0]
            if cur['status'] in ['done','failed','cancelled','interrupted']: break
        s.CTX.ws=EXT_WS
        self.assertEqual(len(jobs.list_jobs(s)),1)
        s.CTX.ws=None
        self.assertEqual(jobs.list_jobs(s),[])  # owner sees no user jobs
        self.assertEqual(s.records(),[])  # owner accounts untouched

    def test_grants_owner_only_and_revoke_kills_sessions(self):
        security.init(s)
        # owner grants
        g=s.action('/api/access',{'email':EXT})
        self.assertEqual(g['email'],EXT)
        self.assertTrue(s.access_granted(EXT))
        # state exposes grants to owner
        self.assertEqual(s.state()['grants'][0]['email'],EXT)
        # external workspace cannot manage access
        s.CTX.ws=EXT_WS
        with self.assertRaises(ValueError): s.action('/api/access',{'email':'third@example.com'})
        self.assertNotIn('grants',s.state())
        s.CTX.ws=None
        # session for ext email exists; revoke removes grant and session
        import secrets as sc
        raw=sc.token_urlsafe(40)
        with s.default_connect() as c:
            c.execute('INSERT INTO sessions VALUES(?,?)',(security.token_hash(raw),json.dumps({'csrf':'x','expires':time.time()+1000,'version':security.token_hash(os.environ['SIGNALDESK_PASSWORD']),'email':EXT,'ws':EXT_WS})))
        self.assertIsNotNone(security.session(s,'signaldesk_session='+raw))
        s.action('/api/access',{'email':EXT,'remove':True})
        self.assertFalse(s.access_granted(EXT))
        self.assertIsNone(security.session(s,'signaldesk_session='+raw))

    def test_invalid_inputs_fail_closed(self):
        for bad in ['not-an-email','a b@c.com','','x@y','@x.com']:
            self.assertFalse(s.access_granted(bad))
            with self.assertRaises(ValueError): s.action('/api/access',{'email':bad})
        # hostile workspace strings are sanitized, never interpolated raw
        c=storage.connect(s.DB,'bad; DROP TABLE accounts;--')
        c.close()
        for f in os.listdir(self.tmp.name):
            self.assertNotIn(' ',f); self.assertNotIn(';',f); self.assertNotIn('DROP',f)

    def test_password_login_session_is_owner_scoped(self):
        security.init(s)
        raw,d=security.login(s,'test-password-123456','owner',email='owner@example.com')
        self.assertEqual(d['ws'],'owner'); self.assertEqual(d['email'],'owner@example.com')
        got=security.session(s,'signaldesk_session='+raw)
        self.assertEqual(got['ws'],'owner')

    def test_old_sessions_without_ws_stay_owner(self):
        security.init(s)
        import secrets as sc
        raw=sc.token_urlsafe(40)
        with s.default_connect() as c:
            c.execute('INSERT INTO sessions VALUES(?,?)',(security.token_hash(raw),json.dumps({'csrf':'x','expires':time.time()+1000,'version':security.token_hash(os.environ['SIGNALDESK_PASSWORD'])})))
        got=security.session(s,'signaldesk_session='+raw)
        self.assertIsNotNone(got)
        s.CTX.ws=got.get('ws')
        self.assertEqual(s.ws(),'owner')

if __name__=='__main__': unittest.main()
