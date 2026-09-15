import sys,time,unittest,tempfile,json,threading,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import StudioControl,DEFAULTS,validate_settings
from server import make_handler,ThreadingHTTPServer

def wait(c,p,timeout=8):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  s=c.snapshot()
  if p(s):return s
  time.sleep(.015)
 raise AssertionError(c.snapshot())

class StudioTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=StudioControl(True,data_dir=self.tmp.name)
  self.runjob('connect')
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def runjob(self,action,body=None,timeout=8):
  job=self.c.submit(action,body);s=wait(self.c,lambda s:s['job_id']==job and not s['busy'],timeout)
  self.assertIsNone(s['error']);return s
 def apply(self,patch):return self.runjob('settings/apply',{'revision':self.c.snapshot()['config_revision'],'settings':patch})
 def test_settings_validation_atomic_and_revision(self):
  old=self.c.snapshot()['config']
  for patch in [{'max_deg':80},{'speed_dps':float('nan')},{'min_deg':True},{'node_id':1.5},{'failsafe_deg':50},{'oops':3}]:
   with self.assertRaises(ValueError):self.c.submit('settings/apply',{'revision':self.c.config_revision,'settings':patch})
   self.assertEqual(self.c.snapshot()['config'],old)
  revision=self.c.config_revision;self.apply({'speed_dps':120})
  with self.assertRaises(RuntimeError):self.c.submit('settings/apply',{'revision':revision,'settings':{'speed_dps':150}})
 def test_save_reboot_and_restart(self):
  self.apply({'speed_dps':123});self.runjob('settings/save')
  self.apply({'speed_dps':321});s=self.runjob('sim/power-cycle')
  self.assertEqual(s['config']['speed_dps'],123);self.assertFalse(s['settings_dirty'])
  self.c.close();self.c=StudioControl(True,data_dir=self.tmp.name);s=self.runjob('connect')
  self.assertEqual(s['config']['speed_dps'],123)
 def test_presets_profile_roundtrip(self):
  self.runjob('presets/add',{'name':'Open','angle':170})
  with self.assertRaises(ValueError):self.c.submit('presets/add',{'name':'open','angle':150})
  self.apply({'speed_dps':140});profile=self.c.profile()
  self.runjob('settings/reset');self.runjob('presets/remove',{'name':'Open'})
  s=self.runjob('profile/import',{'profile':profile});self.assertEqual(s['config']['speed_dps'],140)
  self.assertEqual(s['presets'],[{'name':'Open','angle':170}])
  s=self.runjob('presets/move',{'name':'Open','hold':False})
  self.assertLess(abs(s['position_deg']-170),.34)
 def test_reversed_output_and_center(self):
  self.apply({'direction':'reversed'})
  s=self.runjob('center',{'hold':False})
  self.assertLess(abs(s['position_deg']-DEFAULTS['center_deg']),.34)
  self.assertAlmostEqual(s['output_angle_deg'],s['min_deg']+s['max_deg']-s['position_deg'],places=2)
 def test_sequence_completion_and_cancel_dwell(self):
  s=self.runjob('sequence',{'angles':[175,180],'cycles':2,'dwell_s':.05,'hold':False})
  self.assertFalse(s['holding']);self.assertLess(abs(s['position_deg']-180),.34)
  self.c.submit('sequence',{'angles':[180,100],'dwell_s':5})
  wait(self.c,lambda s:s['phase']=='holding' and s['busy'])
  self.c.release();s=wait(self.c,lambda s:s['phase']=='released' and not s['busy'])
  self.assertIsNone(s['sequence_step']);self.assertFalse(self.c.servo.enabled)
 def test_voltage_and_stall(self):
  self.runjob('sim/fault',{'kind':'undervoltage'})
  self.c.submit('min');s=wait(self.c,lambda s:not s['busy'] and s['error'])
  self.assertFalse(self.c.servo.enabled)
  self.runjob('sim/fault',{'kind':'none'})
  self.runjob('sim/fault',{'kind':'stall'});self.c.submit('min')
  s=wait(self.c,lambda s:not s['busy'] and s['error'])
  self.assertIn('stalled',s['error']);self.assertFalse(self.c.servo.enabled)
 def test_signal_loss_and_cancel(self):
  self.apply({'failsafe_timeout_s':.1,'failsafe_deg':160})
  s=self.runjob('sim/signal-loss',{'hold':False});self.assertLess(abs(s['position_deg']-160),.34)
  self.apply({'failsafe_timeout_s':5})
  self.c.submit('sim/signal-loss');wait(self.c,lambda s:s['phase']=='signal loss')
  self.c.release();wait(self.c,lambda s:s['phase']=='released' and not s['busy'])
  self.assertFalse(self.c.servo.enabled)
 def test_hardware_rejects_advanced_without_opening_usb(self):
  h=StudioControl(False,data_dir=self.tmp.name)
  try:
   for action in h.extra_actions:
    with self.assertRaises(RuntimeError):h.submit(action,{})
   self.assertIsNone(h.servo)
  finally:h.close()
 def test_http_extended_routes(self):
  srv=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.c,'key'))
  threading.Thread(target=srv.serve_forever,daemon=True).start()
  def req(path,body=None,token='key'):
   r=urllib.request.Request('http://127.0.0.1:'+str(srv.server_port)+'/api/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+token})
   try:
    with urllib.request.urlopen(r,timeout=3) as f:return f.status,json.load(f)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  try:
   self.assertEqual(req('capabilities',token='bad')[0],401)
   self.assertEqual(req('capabilities')[0],200)
   self.assertEqual(req('profile')[1]['format'],'servo-studio-profile')
   self.assertEqual(req('settings/apply',{'revision':self.c.config_revision,'settings':{'node_id':999}})[0],400)
   self.assertEqual(req('sequence',{'angles':[175,180],'dwell_s':2})[0],202)
   self.assertEqual(req('settings/reset',{})[0],409)
   self.assertEqual(req('release',{})[0],202)
  finally:srv.shutdown();srv.server_close()
if __name__=='__main__':unittest.main(verbosity=2)
