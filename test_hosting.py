import unittest,os,tempfile,time,json
from unittest.mock import patch
import server as s,security
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
