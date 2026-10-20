"""Optional real-model integration smoke test. No mock inference or cloud API."""
import os,tempfile,unittest
import server as s
@unittest.skipUnless(os.environ.get('SIGNALDESK_GGUF'),'Set SIGNALDESK_GGUF to a local GGUF model for actual inference')
class RealModelTest(unittest.TestCase):
    def test_real_generation_and_export_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            old=s.DB;s.DB=folder+'/ai.sqlite3'
            try:
                s.import_rows([{'company':'Fictional Northstar','domain':'northstar.example','industry':'SaaS','size':48}])
                cfg=s.DEFAULT.copy();cfg['ai']=True;s.action('/api/config',cfg);r=s.run();a=s.records()[0]
                self.assertEqual(a['engine'],'gguf',a['reasons']);self.assertEqual(r['drafts'],1)
                self.assertIn('AI-suggested value question',a['draft']);self.assertFalse(a['approved'])
                self.assertNotIn('Fictional Northstar',s.export())
            finally:s.DB=old
if __name__=='__main__':unittest.main()
