import unittest,tempfile,json,copy,sqlite3,time
from pathlib import Path
from unittest.mock import patch
import server as s,backup,research
class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DB;s.DB=self.tmp.name+'/restore.sqlite3';s.connect().close()
        s.import_rows([dict(company='Demo',domain='demo.example',industry='SaaS',size=30)])
        s.run();a=s.records()[0];s.action('/api/account',{'id':a['id'],'approved':True})
        s.campaign_save(dict(title='Manual campaign',stage='launched',manual_launch_confirmed=True,impressions=100,responses=10,conversions=1))
        self.data=dict(s.state(),format='signaldesk-backup-v1')
    def tearDown(self):s.DB=self.old;self.tmp.cleanup()
    def test_valid_restore_resets_derived_data(self):
        result=backup.restore(s,self.data,True);self.assertEqual(result['restored_accounts'],1)
        a=s.records()[0];self.assertFalse(a['approved']);self.assertIsNone(a['score']);self.assertTrue(a['draft']);self.assertEqual(a['engine'],'restored-unverified')
        self.assertEqual(s.campaigns()[0]['stage'],'idea');self.assertEqual(s.state()['runs'],[])
    def test_confirmation_required(self):
        with self.assertRaises(ValueError):backup.restore(s,self.data)
        self.assertTrue(s.records()[0]['approved'])
    def test_invalid_input_preserves_entire_database(self):
        old=s.state();bad=copy.deepcopy(self.data);bad['accounts'][0]['source']='javascript:alert(1)'
        with self.assertRaises(ValueError):backup.restore(s,bad,True)
        self.assertEqual(s.state(),old)
    def test_duplicate_domain_rejected(self):
        bad=copy.deepcopy(self.data);a=copy.deepcopy(bad['accounts'][0]);a['id']='70c0c6f5-7984-4570-8a80-ce486e31f779';bad['accounts'].append(a)
        with self.assertRaises(ValueError):backup.restore(s,bad,True)
    def test_database_failure_rolls_back_deletes_and_inserts(self):
        before=s.state()
        with s.connect() as c:c.execute("CREATE TRIGGER reject_restore BEFORE INSERT ON accounts BEGIN SELECT RAISE(ABORT, 'test simulated disk/write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):backup.restore(s,self.data,True)
        self.assertEqual(s.state(),before)
    def test_unknown_size_roundtrip(self):
        s.import_rows([dict(company='Unknown size',domain='unknown.example')]);data=dict(s.state(),format='signaldesk-backup-v1');backup.restore(s,data,True)
        self.assertEqual(len(s.records()),2)
    def test_untrusted_flags_numeric_types(self):
        for field,value in [('approved','true'),('suppressed',1),('size',True)]:
            bad=copy.deepcopy(self.data);bad['accounts'][0][field]=value
            with self.assertRaises(ValueError):backup.restore(s,bad,True)
    def test_bad_experiment_counts(self):
        bad=copy.deepcopy(self.data);bad['campaigns'][0]['responses']=1000
        with self.assertRaises(ValueError):backup.restore(s,bad,True)
    def test_hard_deadline_kills_real_slow_subprocess(self):
        f=Path(self.tmp.name,'slow.py');f.write_text('import time;time.sleep(10)')
        start=time.monotonic()
        with patch.object(research,'__file__',str(f)):
            with self.assertRaisesRegex(ValueError,'total deadline'):research.bounded_research('https://example.com',timeout=.15)
        self.assertLess(time.monotonic()-start,2)
