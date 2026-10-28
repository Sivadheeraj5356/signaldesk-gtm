import unittest,tempfile,time,threading
from unittest.mock import patch
import server as s
import jobs
class BatchTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.old=s.DB;s.DB=self.tmp.name+'/batch.sqlite3';s.connect().close();jobs.CANCEL.clear()
    def tearDown(self):
        if jobs.WORKER:jobs.WORKER.join(3)
        s.DB=self.old;self.tmp.cleanup()
    def add(self,n=2):
        s.import_rows([dict(company='Demo '+str(i),domain='demo'+str(i)+'.example',industry='SaaS',size=30) for i in range(n)])
        return [a['id'] for a in s.records()]
    def wait(self):
        jobs.WORKER.join(4);self.assertFalse(jobs.WORKER.is_alive());return jobs.list_jobs(s)[0]
    def test_batch_real_rules(self):
        ids=self.add();j=jobs.start(s,{'ids':ids,'research':False});j=self.wait()
        self.assertEqual(j['status'],'complete');self.assertEqual(j['completed'],2);self.assertTrue(all(a['draft'] for a in s.records()));self.assertTrue(all(not a['approved'] for a in s.records()))
    def test_config_snapshot(self):
        ids=self.add();j=jobs.start(s,{'ids':ids});self.wait();self.assertEqual(j['config']['industry'],'SaaS')

    def test_stale_batch_expires(self):
        import json as _json, datetime as _dt
        stale=(_dt.datetime.now(_dt.timezone.utc)-_dt.timedelta(minutes=11)).isoformat()
        with s.connect() as c:
            c.execute('INSERT INTO jobs VALUES(?,?)',('stale1',_json.dumps(dict(id='stale1',status='running',updated=stale,ws='owner'))))
        self.assertTrue(jobs.active(s) is False)
        row=next(j for j in jobs.list_jobs(s) if j['id']=='stale1')
        self.assertEqual(row['status'],'interrupted')
    def test_limits(self):
        self.add()
        for ids in [[],['unknown'],['x']*26]:
            with self.assertRaises(ValueError):jobs.start(s,{'ids':ids})
    def test_suppressed_skipped(self):
        ids=self.add(1);s.action('/api/account',{'id':ids[0],'suppressed':True});jobs.start(s,{'ids':ids});j=self.wait();self.assertEqual(j['trace'][0]['status'],'skipped');self.assertIsNone(s.records()[0]['score'])
    def test_cancel_between_accounts(self):
        ids=self.add(3);gate=threading.Event();original=s.prepare
        def slow(a,c):gate.set();time.sleep(.15);return original(a,c)
        with patch.object(s,'prepare',slow):
            j=jobs.start(s,{'ids':ids});self.assertTrue(gate.wait(2));jobs.cancel(s,j['id']);j=self.wait()
        self.assertEqual(j['status'],'cancelled');self.assertLess(j['completed'],3)
    def test_no_second_active_job(self):
        ids=self.add();gate=threading.Event();original=s.prepare
        def slow(a,c):gate.set();time.sleep(.15);return original(a,c)
        with patch.object(s,'prepare',slow):
            jobs.start(s,{'ids':ids});gate.wait(2)
            with self.assertRaises(ValueError):jobs.start(s,{'ids':ids})
            self.wait()
    def test_research_failure_preserves_account(self):
        ids=self.add(1);before=s.records()[0].copy();jobs.start(s,{'ids':ids,'research':True});j=self.wait();self.assertEqual(j['trace'][0]['status'],'error');self.assertEqual(s.records()[0],before)
    def test_restart_recovery(self):
        jobs.store(s,dict(id='test',status='running',total=3,completed=1,trace=[],config={}))
        jobs.recover(s);self.assertEqual(jobs.list_jobs(s)[0]['status'],'interrupted')
    def test_bad_domain_identity(self):
        for d in ['https://user:pass@example.com','https://example.com:1234','ftp://example.com']:
            with self.assertRaises(ValueError):s.domain(d)
