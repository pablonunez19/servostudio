import sys,unittest,os,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dpc20_transport import DPCDriver,choose_port
from app_paths import user_data_dir

class PortableTests(unittest.TestCase):
 def test_selection_prefers_identified_adapter(self):
  ports=[SimpleNamespace(device='COM1',vid=None,description='Bluetooth',manufacturer=''),
         SimpleNamespace(device='COM4',vid=1,description='AT32 Virtual COM',manufacturer='Artery'),
         SimpleNamespace(device='COM5',vid=2,description='Other USB',manufacturer='')]
  self.assertEqual(choose_port(ports),'COM4')
  with self.assertRaises(RuntimeError):choose_port([ports[0]])
  with self.assertRaises(RuntimeError):choose_port([ports[1],ports[1]])
 def test_fragmented_frame_and_checksum(self):
  d=DPCDriver.__new__(DPCDriver);d.buf=bytearray()
  message=(0x80000000|0x0803f30a).to_bytes(4,'little')+bytes([10,12,0x34,0x12])
  packet=bytes([4])+message+bytes([sum(message)&255,len(message),5])
  d.buf.extend(b'garbage'+packet[:-1]);self.assertIsNone(d._frame())
  d.buf.extend(packet[-1:]);f=d._frame()
  self.assertEqual(f.id,0x0803f30a);self.assertEqual(f.data,bytes([10,12,0x34,0x12]));self.assertTrue(f.extended)
 def test_user_data_override(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERVOSTUDIO_DATA_DIR':tmp}):
   self.assertEqual(user_data_dir(),Path(tmp))
 def test_packaged_smoke(self):
  from smoke_test import run
  run()
if __name__=='__main__':unittest.main()
