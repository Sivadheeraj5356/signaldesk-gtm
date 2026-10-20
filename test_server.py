import unittest, tempfile, os, csv, io, threading, urllib.request, urllib.error, json
import server as s
class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); s.DB=self.tmp.name+'/test.db'; s.connect().close()
    def tearDown(self): self.tmp.cleanup()
    def row(self,**kw): return dict(company='Demo',domain='demo.example',industry='SaaS',region='India',size=30,evidence='Supplied note',source='https://demo.example/news',**kw)
    def test_normalization_and_dedupe(self):
        self.assertEqual(s.domain('https://WWW.Demo.example/path'),'demo.example')
        self.assertEqual(s.import_rows([self.row(),self.row()]),{'imported':1,'duplicates':1})
    def test_import_is_atomic(self):
        with self.assertRaises(ValueError): s.import_rows([self.row(),dict(company='Broken',domain='not a domain')])
        self.assertEqual(s.records(),[])
    def test_csv_quoted_newline(self):
        out=io.StringIO(); w=csv.DictWriter(out,fieldnames=self.row().keys());w.writeheader(); r=self.row();r['evidence']='a,b\nnext line';w.writerow(r)
        s.action('/api/import',{'csv':out.getvalue()});self.assertEqual(s.records()[0]['evidence'],'a,b\nnext line')
    def test_scores_trace(self):
        a=s.clean(self.row()); score,trace=s.evaluate(a,s.DEFAULT)
        self.assertEqual(score,85);self.assertEqual(sum(x['points'] for x in trace),85)
    def test_blank_data_no_invented_points(self):
        a=s.clean({'company':'Demo','domain':'demo.example'});self.assertEqual(s.evaluate(a,s.DEFAULT)[0],0)
    def test_suppressed_boolean_csv(self):
        self.assertFalse(s.clean(self.row(suppressed='false'))['suppressed'])
        self.assertTrue(s.clean(self.row(suppressed='true'))['suppressed'])
    def test_run_and_export_approval(self):
        s.import_rows([self.row()]);r=s.run();a=s.records()[0]
        self.assertEqual(r['drafts'],1);self.assertTrue(a['draft']);self.assertEqual(a['engine'],'template')
        self.assertEqual(len(list(csv.reader(io.StringIO(s.export())))),1)
        s.action('/api/account',{'id':a['id'],'approved':True})
        self.assertEqual(len(list(csv.reader(io.StringIO(s.export())))),2)
    def test_edit_invalidates_approval(self):
        s.import_rows([self.row()]);s.run();a=s.records()[0];s.action('/api/account',{'id':a['id'],'approved':True});s.action('/api/account',{'id':a['id'],'draft':'new draft'})
        self.assertFalse(s.records()[0]['approved'])
    def test_config_invalidates_approval(self):
        s.import_rows([self.row()]);s.run();a=s.records()[0];s.action('/api/account',{'id':a['id'],'approved':True});s.action('/api/config',s.DEFAULT)
        self.assertFalse(s.records()[0]['approved'])
    def test_suppression_blocks_export_and_run(self):
        s.import_rows([self.row()]);s.run();a=s.records()[0];s.action('/api/account',{'id':a['id'],'suppressed':True})
        self.assertEqual(len(list(csv.reader(io.StringIO(s.export())))),1);s.run();a=s.records()[0];self.assertEqual(a['score'],0);self.assertFalse(a['draft'])
    def test_rerun_resets_approvals(self):
        s.import_rows([self.row()]);s.run();a=s.records()[0];s.action('/api/account',{'id':a['id'],'approved':True});s.run();self.assertFalse(s.records()[0]['approved'])
    def test_bad_sources(self):
        r=self.row();r['source']='javascript:alert(1)'
        with self.assertRaises(ValueError): s.clean(r)
    def test_formula_injection(self):
        for value in ['=1+1','+SUM(A1)','-1+2','@abc','  =1']:
            self.assertTrue(s.safe_cell(value).startswith("'"))
    def test_ai_opt_in_failure_is_visible(self):
        old=os.environ.pop('SIGNALDESK_ENABLE_OLLAMA',None)
        try:
            s.import_rows([self.row()]);cfg=s.DEFAULT.copy();cfg['ai']=True;s.action('/api/config',cfg);s.run();a=s.records()[0];self.assertEqual(a['engine'],'error');self.assertFalse(a['draft']);self.assertIn('disabled',a['reasons'][-1]['detail'])
        finally:
            if old is not None:os.environ['SIGNALDESK_ENABLE_OLLAMA']=old
    def test_size_validation(self):
        r=self.row();r['size']='abc'
        with self.assertRaises(ValueError):s.clean(r)
    def test_limit(self):
        with self.assertRaises(ValueError):s.import_rows([self.row()]*501)
    def test_persistence(self):
        s.import_rows([self.row()]);s.connect().close();self.assertEqual(len(s.records()),1)
    def test_delete(self):
        s.import_rows([self.row()]);a=s.records()[0];s.action('/api/account',{'id':a['id'],'delete':True});self.assertEqual(s.records(),[])
    def test_invalid_ranges(self):
        cfg=s.DEFAULT.copy();cfg['min_size']=100;cfg['max_size']=10
        with self.assertRaises(ValueError):s.action('/api/config',cfg)
    def test_research_private_destination(self):
        import research
        for url in ['http://example.com','https://127.0.0.1/','https://localhost/','https://169.254.169.254/','https://name.local/','https://user:pass@example.com/','https://example.com:8080/']:
            with self.assertRaises(ValueError):research.public_target(url)
    def test_research_parser_omits_script(self):
        import research
        p=research.PublicHTML();p.feed('<html><title>Demo</title><script>evil()</script><p>Real text</p></html>')
        self.assertNotIn('evil()',p.parts);self.assertIn('Real text',p.parts)
    def test_channels(self):
        a=s.clean(self.row());cfg=s.DEFAULT.copy()
        for channel in ['email','linkedin','partner']:
            cfg['channel']=channel;self.assertIn('Demo',s.draft(a,cfg))
    def test_research_supplied_failure_preserves_data(self):
        s.import_rows([self.row()]);a=s.records()[0]
        with self.assertRaises(ValueError):s.action('/api/research',{'id':a['id']})
        self.assertEqual(s.records()[0]['evidence'],a['evidence'])
    def test_campaign_metrics(self):
        c=s.campaign_save({'title':'Test','impressions':100,'responses':10,'conversions':2})
        self.assertEqual(c['response_rate'],10);self.assertEqual(c['conversion_rate'],20)
        self.assertEqual(len(s.campaigns()),1)
    def test_campaign_no_fake_launch(self):
        with self.assertRaises(ValueError):s.campaign_save({'title':'Test','stage':'launched'})
        c=s.campaign_save({'title':'Test','stage':'launched','manual_launch_confirmed':True})
        self.assertEqual(c['stage'],'launched')
    def test_campaign_invalid_metrics(self):
        with self.assertRaises(ValueError):s.campaign_save({'title':'Test','impressions':1,'responses':10})
        c=s.campaign_save({'title':'Zero'});self.assertIsNone(c['response_rate'])
    def test_http_boundaries(self):
        server=s.ThreadingHTTPServer(('127.0.0.1',0),s.Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start();base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(base+'/api/state') as r:self.assertIn('accounts',json.load(r))
            req=urllib.request.Request(base+'/api/run',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            self.assertEqual(e.exception.code,403)
            req=urllib.request.Request(base+'/api/run',data=b'{}',headers={'Content-Type':'text/plain'})
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            self.assertEqual(e.exception.code,415)
        finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()
