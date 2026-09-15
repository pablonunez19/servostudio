import tempfile,time,unittest
from unittest.mock import patch
from collections import deque
import can_protocol as cp
from dpc20_transport import CANFrame
from servo_control import Servo
from studio import StudioControl
from test_hardware_workspace import FakeServo

class Bus:
 def __init__(self,port=None,mode='can2a'):
  self.mode=mode;self.frames=deque();self.sent=[]
 def send(self,ident,data,extended=False):
  self.sent.append((ident,data,extended))
  if extended==(self.mode=='can2b') and data[:1]==b'r':
   self.frames.append(CANFrame(10,bytes([ord('v'),10,data[2],10,0]),extended))
 def receive(self,timeout=None):return self.frames.popleft() if self.frames else None
 def close(self):pass

class CapServo(FakeServo):
 def __init__(self,port=None):
  super().__init__(port);self.protocol='can2a'
  self.values.update({0xfc:3062,0xfe:3062^65535,0x6a:0,0x3c:0,0x3e:10,0x38:0})

class ProtocolTests(unittest.TestCase):
 def test_firmware_variants(self):
  for raw,kind,label in [(21062,'U','1.6(2) /U'),(31052,'U','1.5(2) /U'),(11052,'C','1.5(2) /C'),(3052,'A','1.5(2) /A'),(2012,'U','1.1(2) /U')]:
   self.assertEqual(cp.firmware(raw)['type'],kind);self.assertEqual(cp.firmware(raw)['label'],label)
  self.assertIsNone(cp.firmware(65535)['type'])
 def test_u_ignores_register_zero(self):
  servo=CapServo();servo.values.update({0xfc:21062,0xfe:21062^65535})
  info=cp.inspect(servo)
  self.assertEqual(info['configured'],'dronecan');self.assertEqual(info['supported'],['dronecan'])
  with self.assertRaises(ValueError):cp.validate_change(info,'can2b')
  self.assertEqual(servo.writes,[])
 def test_integrity_and_limits(self):
  servo=CapServo();servo.values[0xfe]=0
  with self.assertRaises(RuntimeError):cp.inspect(servo)
  servo.values[0xfe]=3062^65535;info=cp.inspect(servo)
  info.update(configured='can2b',can_id=2048)
  with self.assertRaises(ValueError):cp.validate_change(info,'can2a')
  with self.assertRaises(ValueError):cp.validate_change(info,'dronecan')
 def test_standard_and_extended_packets(self):
  for mode in ('can2a','can2b'):
   bus=Bus(mode=mode)
   with patch('servo_control.DPCDriver',return_value=bus):servo=Servo()
   self.assertEqual(servo.protocol,mode);self.assertEqual(servo.actuator_id,10)
   servo._write(30,5000)
   self.assertEqual(bus.sent[-1],(10,b'w\x0a\x1e\x88\x13',mode=='can2b'))
   self.assertEqual(servo.read(12),10)
 def test_wrong_frame_rejected(self):
  servo=Servo.__new__(Servo);servo.bus=Bus();servo.protocol='can2a';servo.actuator_id=10;servo.can_id=10;servo.node_id=10
  servo.bus.mode='can2b'
  with self.assertRaises(TimeoutError):servo.read(12)
 def wait(self,c):
  deadline=time.monotonic()+5
  while c.snapshot()['busy'] and time.monotonic()<deadline:time.sleep(.01)
  self.assertFalse(c.snapshot()['busy']);return c.snapshot()
 def test_change_requires_ack_then_disconnects(self):
  with tempfile.TemporaryDirectory() as d:
   c=StudioControl(False,data_dir=d);c.factory=CapServo
   try:
    c.submit('connect');self.wait(c);servo=c.servo
    payload=dict(protocol='can2b',revision=c.config_revision)
    with self.assertRaises(ValueError):c.submit('protocol/change',payload)
    self.assertFalse(servo.writes)
    payload['acknowledge_save']=True;c.submit('protocol/change',payload);s=self.wait(c)
    self.assertIsNone(s['error']);self.assertFalse(s['connected']);self.assertIsNone(c.servo)
    self.assertEqual(s['protocol_pending'],'can2b')
    self.assertEqual([p for p in servo.writes if p[0] in (0x6a,0x70)],[(0x6a,1),(0x70,65535)])
   finally:c.close()
 def test_rejected_change_rolls_back_without_save(self):
  with tempfile.TemporaryDirectory() as d:
   c=StudioControl(False,data_dir=d);c.factory=CapServo
   try:
    c.submit('connect');self.wait(c);servo=c.servo;servo.reject=(0x6a,1)
    c.submit('protocol/change',dict(protocol='can2b',revision=c.config_revision,acknowledge_save=True));s=self.wait(c)
    self.assertIn('rejected',s['error']);self.assertEqual(servo.read(0x6a),0)
    self.assertFalse(any(a==0x70 for a,v in servo.writes))
   finally:c.close()
 def test_simulation_switch(self):
  with tempfile.TemporaryDirectory() as d:
   c=StudioControl(True,data_dir=d)
   try:
    c.submit('connect');self.wait(c)
    c.submit('protocol/change',dict(protocol='can2a',revision=c.config_revision,acknowledge_save=True));s=self.wait(c)
    self.assertIsNone(s['error']);self.assertEqual(s['protocol_info']['configured'],'can2a');self.assertTrue(s['connected'])
   finally:c.close()
