import sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import StudioControl
from test_hardware_workspace import FakeServo

class LiveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=StudioControl(True,data_dir=self.tmp.name)
  self.c.submit('connect');self.wait(lambda s:s['connected'] and not s['busy'])
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def wait(self,p,timeout=6):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   s=self.c.snapshot()
   if p(s):return s
   time.sleep(.015)
  self.fail(str(self.c.snapshot()))
 def live(self,angle,seq=1,stream='test-stream'):
  return self.c.submit('live',dict(angle=angle,stream=stream,seq=seq,speed='slow',hold=False))
 def test_retarget_without_waiting_for_old_position(self):
  job=self.live(100)
  self.wait(lambda s:s['phase']=='moving')
  for seq,angle in enumerate([130,150,175,180],2):self.assertEqual(self.live(angle,seq),job)
  s=self.wait(lambda s:not s['busy'])
  self.assertIsNone(s['error']);self.assertLess(abs(s['position_deg']-180),.34)
  self.assertGreater(s['position_deg'],170)
 def test_reject_stale_and_other_stream(self):
  self.live(100,5);self.wait(lambda s:s['phase']=='moving')
  with self.assertRaises(RuntimeError):self.live(110,4)
  with self.assertRaises(RuntimeError):self.live(110,6,'another-tab')
 def test_stop_invalidates_inflight_targets(self):
  self.live(100);self.wait(lambda s:s['phase']=='moving');self.c.release()
  self.wait(lambda s:not s['busy'] and s['phase']=='released')
  with self.assertRaises(RuntimeError):self.live(150,99)
  self.live(180,1,'fresh-stream');self.wait(lambda s:not s['busy'])
 def test_stop_before_request_arrives(self):
  self.c.cancel_live('delayed-stream');self.c.release()
  self.wait(lambda s:s['phase']=='released')
  with self.assertRaises(RuntimeError):self.live(100,1,'delayed-stream')
 def test_live_does_not_interrupt_sequence(self):
  self.c.submit('sequence',dict(angles=[100,180],speed='slow'))
  with self.assertRaises(RuntimeError):self.live(160)
 def test_invalid_angles_and_types(self):
  for angle in [float('nan'),True,0,400]:
   with self.assertRaises(ValueError):self.live(angle)
  with self.assertRaises(ValueError):self.live(150,True)
 def test_capture_encoder_not_command_and_no_flash(self):
  self.c.close();self.c=StudioControl(False,data_dir=self.tmp.name);self.c.factory=FakeServo
  self.c.submit('connect');self.wait(lambda s:s['connected'] and not s['busy'])
  self.c.servo.values[12]=7000;self.c.servo.values[30]=8500
  revision=self.c.config_revision
  self.c.submit('settings/capture',{'field':'center_deg','revision':revision})
  s=self.wait(lambda s:not s['busy']);self.assertIsNone(s['error'])
  self.assertEqual(self.c.servo.values[0xc2],7000)
  self.assertEqual(self.c.servo.values[0xb2],4300);self.assertEqual(self.c.servo.values[0xb0],8500)
  self.assertFalse(any(a==0x70 for a,v in self.c.servo.writes))
 def test_capture_rejects_inverted_range(self):
  self.c.servo.values[12]=self.c.servo.values[176]
  before=dict(self.c.snapshot()['config'])
  self.c.submit('settings/capture',{'field':'min_deg','revision':self.c.config_revision})
  s=self.wait(lambda s:not s['busy']);self.assertIsNotNone(s['error'])
  self.assertEqual(s['config'],before)
if __name__=='__main__':unittest.main()
