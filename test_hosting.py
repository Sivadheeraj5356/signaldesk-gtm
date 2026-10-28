import unittest,os,tempfile,time,json,threading,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import server as s,security
class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
class HostingTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.old=s.DB;s.DB=self.t.name+'/db';security.FAILURES.clear()
  self.env=patch.dict(os.environ,{'SIGNALDESK_MODE':'server','SIGNALDESK_PASSWORD':'a-long-test-password','SIGNALDESK_ORIGIN':'https://app.example','SIGNALDESK_PERSISTENT_DISK':'1'});self.env.start();security.init(s)
 def tearDown(self):s.DB=self.old;self.env.stop();self.t.cleanup()
 def test_config_fail_closed(self):
  security.validate()
  with patch.dict(os.environ,{'SIGNALDESK_PASSWORD':'short'}):
   with self.assertRaises(ValueError):security.validate()
  with patch.dict(os.environ,{'SIGNALDESK_ORIGIN':'http://app.example'}):
   with self.assertRaises(ValueError):security.validate()
 def test_session_hash_and_expiry(self):
  raw,d=security.login(s,'a-long-test-password','owner')
  self.assertTrue(security.session(s,'signaldesk_session='+raw))
  with s.connect() as c:
   rows=c.execute('SELECT id,data FROM sessions').fetchall();self.assertNotEqual(rows[0][0],raw)
   d['expires']=0;c.execute('UPDATE sessions SET data=?',(json.dumps(d),))
  self.assertIsNone(security.session(s,'signaldesk_session='+raw))
 def test_logout(self):
  raw,_=security.login(s,'a-long-test-password','owner');h='signaldesk_session='+raw;security.logout(s,h);self.assertIsNone(security.session(s,h))
 def test_throttle(self):
  for i in range(8):
   with self.assertRaisesRegex(ValueError,'Incorrect'):security.login(s,'bad','owner')
  with self.assertRaisesRegex(ValueError,'Too many'):security.login(s,'a-long-test-password','owner')
 def test_cookies(self):
  self.assertIn('HttpOnly',security.COOKIE);self.assertIn('Secure',security.COOKIE);self.assertIn('SameSite=Strict',security.COOKIE)
  self.assertIsNone(security.session(s,'signaldesk_session=invalid'))
 def test_password_rotation_revokes_sessions(self):
  raw,_=security.login(s,'a-long-test-password','owner')
  with patch.dict(os.environ,{'SIGNALDESK_PASSWORD':'a-different-long-password'}):self.assertIsNone(security.session(s,'signaldesk_session='+raw))
 def test_signin_route_authenticated_redirect_and_app(self):
  srv=ThreadingHTTPServer(('127.0.0.1',0),s.Handler);port=srv.server_address[1]
  threading.Thread(target=srv.serve_forever,daemon=True).start()
  base=f'http://127.0.0.1:{port}'
  try:
   with patch.dict(os.environ,{'SIGNALDESK_ORIGIN':f'https://127.0.0.1:{port}'}):
    r=urllib.request.urlopen(base+'/sign-in');self.assertEqual(r.status,200);self.assertIn('Sign in',r.read().decode())
    body=json.dumps({'email':'owner@example.com','password':'a-long-test-password'}).encode()
    req=urllib.request.Request(base+'/api/login',data=body,headers={'Content-Type':'application/json','Origin':f'https://127.0.0.1:{port}'})
    r=urllib.request.urlopen(req);self.assertEqual(r.status,200);cookie=r.headers['Set-Cookie'].split(';')[0]
    op=urllib.request.build_opener(_NoRedirect)
    try:op.open(urllib.request.Request(base+'/sign-in',headers={'Cookie':cookie}));self.fail('expected redirect')
    except urllib.error.HTTPError as e:self.assertEqual(e.status,302);self.assertEqual(e.headers['Location'],'/')
    r=urllib.request.urlopen(urllib.request.Request(base+'/app?connected=gmail&identity=x',headers={'Cookie':cookie}))
    self.assertEqual(r.status,200);self.assertIn('SignalDesk',r.read().decode())
  finally:srv.shutdown();srv.server_close()
 def test_render_origin_fallback(self):
  with patch.dict(os.environ,{'SIGNALDESK_ORIGIN':'','RENDER_EXTERNAL_URL':'https://actual-render.example'}):
   security.validate();self.assertEqual(security.origin(),'https://actual-render.example')
