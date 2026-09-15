import sys,time,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import StudioControl
from server import SimServo
import hardware_settings as hw

class FakeServo(SimServo):
 def __init__(self,port=None):
  super().__init__(port)
  self.values.update({0x74:7961,0xfc:21062,0xc2:8500,0x4e:4,0x56:4095,0xdc:0,0x9a:3,0x9c:100})
  self.writes=[];self.reject=None
 def _write(self,a,v):
  self.writes.append((a,v))
  if (a,v)!=self.reject:super()._write(a,v)

class HardwareWorkspace(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=StudioControl(False,data_dir=self.tmp.name);self.c.factory=FakeServo;self.job('connect')
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def wait(self):
  end=time.monotonic()+6
  while time.monotonic()<end:
   s=self.c.snapshot()
   if not s['busy']:return s
   time.sleep(.01)
  self.fail(str(self.c.snapshot()))
 def job(self,a,p=None):
  self.c.submit(a,p);s=self.wait();self.assertIsNone(s['error']);return s
 def test_live_values_presets_edit_and_sequence(self):
  s=self.c.snapshot();self.assertAlmostEqual(s['config']['center_deg'],186.767578125)
  self.job('presets/add',{'name':'Open','angle':180})
  self.job('presets/update',{'name':'Open','new_name':'Closed','angle':175})
  self.assertEqual(self.c.snapshot()['presets'],[{'name':'Closed','angle':175}])
  self.job('presets/move',{'name':'Closed','hold':False})
  s=self.job('sequence',{'angles':[175,180],'cycles':1,'dwell_s':0,'hold':False})
  self.assertLess(abs(s['position_deg']-180),.34)
 def test_setting_readback_and_restore(self):
  revision=self.c.config_revision
  self.job('settings/apply',{'revision':revision,'settings':{'speed_native':1500}})
  self.assertEqual(self.c.servo.read(84),1500)
  self.assertTrue(self.c.snapshot()['settings_dirty'])
  self.job('settings/reload');self.assertEqual(self.c.servo.read(84),2000)
  self.assertFalse(any(a==0x70 for a,v in self.c.servo.writes))
 def test_rollback_on_rejected_write(self):
  current=hw.read(self.c.servo);self.c.servo.reject=(0x4e,6)
  with self.assertRaises(RuntimeError):hw.apply(self.c.servo,{'speed_native':1500,'deadband_ticks':6},current)
  self.assertEqual(hw.read(self.c.servo),current)
 def test_stale_hardware_and_invalid_limits(self):
  original=hw.read(self.c.servo);self.c.servo.values[84]=1200
  with self.assertRaises(RuntimeError):hw.apply(self.c.servo,{'speed_native':1500},original)
  self.assertFalse(any(a==84 for a,v in self.c.servo.writes))
  with self.assertRaises(ValueError):hw.apply(self.c.servo,{'max_deg':170,'center_deg':150},hw.read(self.c.servo))
 def test_sim_only_commands_rejected_connected(self):
  for a in ['sim/fault','sim/power-cycle','sim/signal-loss','settings/reset']:
   with self.assertRaises(RuntimeError):self.c.submit(a,{})
 def test_profile_mode_and_identity(self):
  profile=self.c.profile();self.job('profile/import',{'profile':profile})
  profile['simulation']=True
  with self.assertRaises(ValueError):self.c.submit('profile/import',{'profile':profile})
 def test_save_only_on_explicit_command(self):
  self.job('settings/save')
  self.assertIn((0x70,65535),self.c.servo.writes)
  self.assertIn('power-cycle',self.c.snapshot()['flash_state'])
if __name__=='__main__':unittest.main(verbosity=2)
