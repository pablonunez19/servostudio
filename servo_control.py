#!/usr/bin/env python3
"""Control one Hitec MDB961 CAN servo through a DPC-20 on macOS.
Only runtime motion/speed commands are sent; no flash saves or limit changes.
"""
import argparse
import json
import math
import time
from dpc20_transport import DPCDriver

TICKS_PER_DEGREE = 4096 / 90
CAN_COMMAND_ID = 258560

class Servo:
    def __init__(self, port=None):
        self.bus = DPCDriver(port)
        self.actuator_id = 0
        self.node_id = None
        self.protocol = "dronecan"
        self.can_id = 0
        try:
            # Read-only discovery: Hitec's DroneCAN register access, then
            # standard/extended Hitec CAN. Never probe by writing registers.
            for protocol in ('dronecan', 'can2a', 'can2b'):
                self.protocol = protocol
                try:
                    self.actuator_id = self.read(0x32)
                    break
                except TimeoutError:
                    if protocol == 'can2b': raise
            if not 1 <= self.actuator_id <= (127 if self.protocol=='dronecan' else 255):
                raise RuntimeError('Invalid actuator ID')
        except BaseException:
            self.bus.close()
            raise

    def read(self, address):
        if self.protocol != 'dronecan':
            return self._read_can(address)
        # Drain old replies so an earlier value cannot satisfy this query.
        for _ in range(100):
            if self.bus.receive(0) is None:
                break
        self.bus.send(CAN_COMMAND_ID, bytes([128 | self.actuator_id, address, 0, 0, 192]), extended=True)
        deadline = time.monotonic() + 0.7
        replies = []
        while time.monotonic() < deadline:
            frame = self.bus.receive(min(.05, max(0, deadline-time.monotonic())))
            if not frame or not frame.extended:
                continue
            data = frame.data
            if ((frame.id >> 8) & 0xffff) != 1011 or len(data) != 4 or data[1] != address:
                continue
            if self.actuator_id and data[0] != self.actuator_id:
                continue
            if self.node_id is not None and (frame.id & 127) != self.node_id:
                continue
            replies.append((frame.id & 127, data[0], int.from_bytes(data[2:], 'little')))
            if self.node_id is not None:
                return replies[-1][2]
        if not replies:
            raise TimeoutError(f'No response for register 0x{address:02x}; check USB, power, and CAN wiring.')
        if len(set(replies)) != 1:
            raise RuntimeError('Multiple or inconsistent replies. Connect only one servo.')
        self.node_id = replies[0][0]
        return replies[0][2]

    def _read_can(self, address):
        for _ in range(100):
            if self.bus.receive(0) is None: break
        extended = self.protocol == 'can2b'
        self.bus.send(self.can_id, bytes([ord('r'), self.actuator_id, address]), extended=extended)
        deadline = time.monotonic() + .7
        replies = set()
        while time.monotonic() < deadline:
            frame = self.bus.receive(min(.05, max(0, deadline-time.monotonic())))
            if frame is None or frame.extended != extended: continue
            data = frame.data
            if len(data)!=5 or data[0]!=ord('v') or data[2]!=address: continue
            if self.actuator_id and data[1]!=self.actuator_id: continue
            if self.node_id is not None and frame.id!=self.can_id: continue
            replies.add((frame.id,data[1],int.from_bytes(data[3:5],'little')))
            if self.node_id is not None: return next(iter(replies))[2]
        if not replies: raise TimeoutError('No Hitec '+self.protocol+' reply; check protocol, power and CAN wiring')
        if len(replies)!=1: raise RuntimeError('Multiple or inconsistent CAN replies. Connect only one servo.')
        self.can_id, ident, value = next(iter(replies))
        self.node_id = self.can_id
        return value

    def _write(self, address, value):
        if self.protocol != 'dronecan':
            self.bus.send(self.can_id,bytes([ord('w'),self.actuator_id,address,value & 255,(value >> 8) & 255]),extended=self.protocol=='can2b')
            return
        self.bus.send(CAN_COMMAND_ID, bytes([self.actuator_id, address, value & 255, (value >> 8) & 255, 192]), extended=True)

    def status(self):
        regs = {'position': 12, 'voltage': 18, 'mode': 68, 'min': 178,
                'max': 176, 'target': 30, 'status': 72, 'speed': 84}
        result = {key: self.read(addr) for key, addr in regs.items()}
        result.update(actuator_id=self.actuator_id, node_id=self.node_id,
                      voltage_v=result['voltage']/100,
                      position_deg=round(result['position']/TICKS_PER_DEGREE, 3),
                      min_deg=round(result['min']/TICKS_PER_DEGREE, 3),
                      max_deg=round(result['max']/TICKS_PER_DEGREE, 3))
        return result

    def release(self):
        self._write(70, 512)
        time.sleep(.05)

    def jog(self, degrees, return_to_start=False):
        if not math.isfinite(degrees) or not 0 < abs(degrees) <= 5:
            raise ValueError('Use a nonzero jog of at most 5 degrees.')
        state = self.status()
        origin = state['position']
        target = origin + round(degrees*TICKS_PER_DEGREE)
        low, high = state['min'], state['max']
        if state['mode'] != 1:
            raise RuntimeError('Servo is not in position mode.')
        if not 0 <= low < high <= 16383 or not low+20 <= min(origin,target) <= max(origin,target) <= high-20:
            raise RuntimeError('Current position or target is outside the allowed range/margin. No motion sent.')
        if not 1050 <= state['voltage'] <= 1300 or state['status'] & 0x6fc0:
            raise RuntimeError('Voltage or servo fault prevents this 12 V bench test.')
        speed_changed = False
        try:
            self.release()
            speed_changed = True
            self._write(84, 23)  # ~5 degrees/second with this servo's verified PID period.
            if self.read(84) != 23:
                raise RuntimeError('Speed setting was not accepted.')
            self._write(30, origin)
            if self.read(30) != origin:
                raise RuntimeError('Initial target was not accepted.')
            self._write(70, 0)
            time.sleep(.1)
            if abs(self.read(12)-origin) > 91:
                raise RuntimeError('Unexpected movement on enable.')
            for goal in ([target, origin] if return_to_start else [target]):
                self._write(30, goal)
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    time.sleep(.15)
                    position, voltage, status = self.read(12), self.read(18), self.read(72)
                    print(json.dumps({'target_deg':round(goal/TICKS_PER_DEGREE,3),
                                      'position_deg':round(position/TICKS_PER_DEGREE,3),
                                      'voltage_v':voltage/100}), flush=True)
                    if voltage < 1050 or status & 0x6fc0:
                        raise RuntimeError('Voltage dropped or servo fault reported; motor released.')
                    if not min(origin,target)-91 <= position <= max(origin,target)+91:
                        raise RuntimeError('Unexpected travel; motor released.')
                    if abs(position-goal) <= 15:
                        break
                else:
                    raise TimeoutError('Target not reached; motor released.')
            print('PASS: encoder reached the requested position(s).')
        finally:
            try:
                self.release()
            finally:
                if speed_changed:
                    self._write(84,state['speed'])
                    if self.read(84) != state['speed']:
                        raise RuntimeError('Could not confirm original speed was restored.')
            print('Motor released; original speed restored.')

    def endpoint(self, which, hold=True, fast=False):
        state = self.status()
        low, high, origin = state['min'], state['max'], state['position']
        goal = low if which == 'min' else high
        if state['mode'] != 1 or not 0 <= low < high <= 16383:
            raise RuntimeError('Invalid limits or not in position mode.')
        # Allow the verified encoder deadband at a saved endpoint.
        if not low-20 <= origin <= high+20:
            raise RuntimeError('Current position is outside the saved range. No motion sent.')
        if not 1050 <= state['voltage'] <= 1300 or state['status'] & 0x6fc0:
            raise RuntimeError('Voltage or servo fault prevents movement.')
        initial_target = min(high, max(low, origin))
        success = False
        speed_changed = False
        requested_speed = 2000 if fast else 23
        try:
            self.release()
            speed_changed = True
            self._write(84, requested_speed)
            if self.read(84) != requested_speed:
                raise RuntimeError('Speed setting was not accepted.')
            self._write(30, initial_target)
            if self.read(30) != initial_target:
                raise RuntimeError('Initial target was not accepted.')
            self._write(70, 0)
            time.sleep(.1)
            if abs(self.read(12)-origin) > 91:
                raise RuntimeError('Unexpected movement on enable.')
            self._write(30, goal)
            if self.read(30) != goal:
                raise RuntimeError('Endpoint target was not accepted.')
            deadline = time.monotonic() + abs(goal-origin)/TICKS_PER_DEGREE/5 + 5
            progress_time, progress_position = time.monotonic(), origin
            while time.monotonic() < deadline:
                time.sleep(.25)
                position, voltage, status = self.read(12), self.read(18), self.read(72)
                print(json.dumps({'endpoint': which, 'target_deg':round(goal/TICKS_PER_DEGREE,3),
                                  'position_deg':round(position/TICKS_PER_DEGREE,3),
                                  'voltage_v':voltage/100}), flush=True)
                if not 1050 <= voltage <= 1300 or status & 0x6fc0:
                    raise RuntimeError('Voltage or servo fault; motor released.')
                if not min(origin,goal)-91 <= position <= max(origin,goal)+91:
                    raise RuntimeError('Unexpected travel; motor released.')
                if abs(position-goal) <= 15:
                    success = True
                    break
                if abs(position-progress_position) >= 10:
                    progress_time, progress_position = time.monotonic(), position
                if time.monotonic()-progress_time > 1.5:
                    raise RuntimeError('Motion stalled; motor released.')
            if not success:
                raise TimeoutError('Endpoint not reached; motor released.')
        finally:
            try:
                if not (success and hold):
                    self.release()
            finally:
                if speed_changed:
                    self._write(84, state['speed'])
                    if self.read(84) != state['speed']:
                        self.release()
                        raise RuntimeError('Could not confirm speed restoration; release command sent.')
        print(f'Reached saved {which}; ' + ('holding position. Use release to disable holding.' if hold else 'motor released.'))

    def close(self):
        self.bus.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Optional /dev/cu.usbmodem... port')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status'); sub.add_parser('release'); sub.add_parser('demo')
    jog=sub.add_parser('jog'); jog.add_argument('degrees',type=float)
    for name in ['min', 'max']:
        endpoint=sub.add_parser(name, help='Move to the saved endpoint and hold')
        endpoint.add_argument('--fast', action='store_true', help='Use the original servo speed setting (2000)')
        endpoint.add_argument('--release', action='store_true', help='Release motor after reaching the endpoint')
    args=parser.parse_args()
    servo=None
    try:
        servo=Servo(args.port)
        if args.command=='status': print(json.dumps(servo.status(),indent=2))
        elif args.command=='release': servo.release(); print('Motor release command sent.')
        elif args.command in ('min','max'): servo.endpoint(args.command,hold=not args.release,fast=args.fast)
        elif args.command=='demo': servo.jog(-3,return_to_start=True)
        else: servo.jog(args.degrees)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1,f'{error}\n')
    except KeyboardInterrupt:
        parser.exit(130,'Interrupted.\n')
    finally:
        if servo is not None: servo.close()
if __name__=='__main__': main()
