"""DPC-20 serial/CAN transport for Windows, macOS and Linux (pySerial)."""
import struct
import sys
import time
from dataclasses import dataclass

@dataclass
class CANFrame:
    id: int
    data: bytes
    extended: bool


def serial_ports():
    from serial.tools import list_ports
    return list(list_ports.comports())


def choose_port(ports):
    # Prefer the programmer's advertised product/manufacturer. Otherwise only
    # auto-select when there is one USB serial candidate; never choose Bluetooth.
    preferred = [p.device for p in ports if any(word in ((p.description or '')+' '+(p.manufacturer or '')).lower()
                 for word in ('dpc-20','dpc20','artery','at32'))]
    candidates = preferred or [p.device for p in ports if p.vid is not None]
    if not candidates:
        raise RuntimeError('DPC-20 not detected. Connect its USB cable, check the serial driver and device permissions, then retry.')
    if len(candidates)!=1:
        raise RuntimeError('Multiple USB serial devices found. Select the DPC-20 using --serial-port. Candidates: '+', '.join(candidates))
    return candidates[0]


class DPCDriver:
    def __init__(self, port=None):
        import serial
        self.buf=bytearray()
        self.serial=serial.Serial(port=None,baudrate=115200,timeout=0,write_timeout=1,
                                  exclusive=True if sys.platform!='win32' else None)
        try:
            # Set line states before opening; AT32 requires DTR on and RTS off.
            self.serial.dtr=True
            self.serial.rts=False
            self.serial.port=port or choose_port(serial_ports())
            self.serial.open()
            time.sleep(.2)
            self.serial.write(b':A:A:A')
            time.sleep(.5)
            self.serial.write(b'\x02XX\x03')
            time.sleep(.1)
            self.serial.reset_input_buffer()
            self.write_packet(b'S\x00\x01')
        except BaseException:
            self.serial.close()
            raise

    def write_packet(self, message):
        packet=bytes([2])+message+bytes([sum(message)&255,len(message),3])
        if self.serial.write(packet)!=len(packet):raise OSError('Incomplete USB write')

    def send(self,message_id,message,extended=False,canfd=False):
        if canfd:raise ValueError('Classic CAN only')
        self.write_packet((b'B'+struct.pack('<I',message_id) if extended else b'A'+struct.pack('<H',message_id))+bytes(message))

    def _frame(self):
        for start,b in enumerate(self.buf):
            if b not in (4,6):continue
            for stop in range(start+4,len(self.buf)):
                if self.buf[stop]!=b+1 or stop-start!=self.buf[stop-1]+3:continue
                m=bytes(self.buf[start+1:stop-2])
                if sum(m)&255!=self.buf[stop-2]:continue
                del self.buf[:stop+1]
                if b==4 and len(m)>=4:
                    ident=int.from_bytes(m[:4],'little')
                    return CANFrame(ident&0x1fffffff,m[4:],bool(ident&0x80000000))
                raise OSError('DPC-20 reported a CAN adapter error')
        return None

    def receive(self,timeout=None):
        deadline=time.monotonic()+max(0,timeout or 0)
        while True:
            frame=self._frame()
            if frame:return frame
            waiting=self.serial.in_waiting
            if waiting:
                self.buf.extend(self.serial.read(waiting))
                if len(self.buf)>4096:del self.buf[:-256]
                continue
            remaining=deadline-time.monotonic()
            if remaining<=0:return None
            time.sleep(min(.002,remaining))

    def close(self):
        self.serial.close()
