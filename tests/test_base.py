import sys,time,unittest,threading,json,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Control,SimServo,make_handler,ThreadingHTTPServer

def wait(c,p,timeout=6):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  s=c.snapshot()
  if p(s):return s
  time.sleep(.02)
 raise AssertionError(c.snapshot())

class Tests(unittest.TestCase):
 def setUp(self):
  self.c=Control(simulated=True);self.c.submit('connect');wait(self.c,lambda s:s['connected'] and not s['busy'])
 def tearDown(self):self.c.close()
 def test_invalid_angles(self):
  for value in [True,False,float('nan'),float('inf'),-100,300,'150',None]:
   with self.assertRaises(ValueError):self.c.submit('move',{'angle':value})
  self.assertFalse(self.c.snapshot()['busy'])
 def test_concurrent_and_stop(self):
  self.c.submit('min',{'speed':'slow'})
  with self.assertRaises(RuntimeError):self.c.submit('max')
  wait(self.c,lambda s:s['phase']=='moving')
  start=time.monotonic();self.c.release()
  s=wait(self.c,lambda s:not s['busy'] and s['phase']=='released')
  self.assertLess(time.monotonic()-start,1)
  self.assertFalse(s['holding']);self.assertGreater(s['position_deg'],170)
  self.assertEqual(self.c.servo.read(84),2000)
 def test_angle_and_hold(self):
  self.c.submit('move',{'angle':180,'speed':'normal','hold':True})
  s=wait(self.c,lambda s:not s['busy'] and s['phase']=='holding')
  self.assertLess(abs(s['position_deg']-180),.34)
  self.assertTrue(s['holding'])
  self.c.release();wait(self.c,lambda s:s['phase']=='released')
 def test_endpoints(self):
  for action in ['min','max']:
   self.c.submit(action,{'speed':'fast','hold':False})
   s=wait(self.c,lambda s:not s['busy'] and s['phase']=='released')
   self.assertLess(abs(s['position_deg']-s[action+'_deg']),.34)
 def test_recheck_limits_and_release_on_fault(self):
  self.c.servo.values[18]=900
  self.c.submit('move',{'angle':180})
  s=wait(self.c,lambda s:not s['busy'] and s['error'])
  self.assertIn('Voltage',s['error']);self.assertFalse(self.c.servo.enabled)
 def test_fault_while_moving(self):
  self.c.submit('min',{'speed':'slow'})
  wait(self.c,lambda s:s['phase']=='moving');self.c.servo.values[18]=900
  wait(self.c,lambda s:not s['busy'] and s['error'])
  self.assertFalse(self.c.servo.enabled);self.assertEqual(self.c.servo.read(84),2000)
 def test_shutdown_releases(self):
  self.c.submit('move',{'angle':180,'hold':True})
  wait(self.c,lambda s:s['phase']=='holding' and not s['busy']);servo=self.c.servo
  self.c.close();self.assertFalse(servo.enabled)
 def test_http_auth_and_validation(self):
  srv=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.c,'test-key'))
  t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
  url='http://127.0.0.1:'+str(srv.server_port)
  def req(path,body=None,token='test-key'):
   r=urllib.request.Request(url+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
   try:
    with urllib.request.urlopen(r,timeout=2) as f:return f.status,json.load(f)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  try:
   self.assertEqual(req('/api/status',token='wrong')[0],401)
   self.assertEqual(req('/api/status')[0],200)
   self.assertEqual(req('/api/move',{'angle':999})[0],400)
   self.assertEqual(req('/api/min',{'speed':'slow'})[0],202)
   self.assertEqual(req('/api/max',{})[0],409)
   self.assertEqual(req('/api/release',{})[0],202)
  finally:srv.shutdown();srv.server_close()
if __name__=='__main__':unittest.main(verbosity=2)
