#!/usr/bin/env python3
"""Local servo panel and authenticated JSON API. Python 3.9+, pySerial for hardware."""
import argparse
import hmac
import json
import math
import os
import queue
import secrets
import threading
import time
import uuid
import sys
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from servo_control import Servo, TICKS_PER_DEGREE


class SimServo:
    def __init__(self, port=None):
        self.values = {12: 8288, 18: 1197, 68: 1, 178: 4300, 176: 8500,
                       30: 8288, 72: 1, 84: 2000, 50: 10}
        self.actuator_id = self.node_id = 10
        self.enabled = False
        self.last = time.monotonic()

    def read(self, addr):
        now = time.monotonic()
        if self.enabled:
            distance = self.values[30] - self.values[12]
            step = self.values[84]*10*(now-self.last)
            self.values[12] += max(-step, min(step, distance))
        self.last = now
        return round(self.values[addr])

    def _write(self, addr, value):
        self.read(12)
        if addr == 70:
            self.enabled = value == 0
        else:
            self.values[addr] = value

    def release(self):
        self._write(70, 512)

    def status(self):
        return {key: self.read(addr) for key, addr in {
            'position':12, 'voltage':18, 'mode':68, 'min':178,
            'max':176, 'target':30, 'status':72, 'speed':84}.items()}

    def close(self):
        pass


class Control:
    def __init__(self, simulated=False, port=None, factory=None):
        self.simulated, self.port = simulated, port
        self.factory = factory or (SimServo if simulated else Servo)
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.stop = threading.Event()
        self.quit = threading.Event()
        self.servo = None
        self.reserved = False
        self.state = dict(connected=False, busy=False, phase='disconnected',
                          holding=None, error=None, position_deg=None,
                          min_deg=None, max_deg=None, target_deg=None,
                          voltage_v=None, updated_at=None, job_id=None,
                          simulation=simulated)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def submit(self, action, payload=None):
        payload = payload or {}
        if action not in ('connect', 'move', 'min', 'max'):
            raise ValueError('Unknown command')
        if action != 'connect':
            speed = payload.get('speed', 'fast')
            if speed not in ('slow', 'normal', 'fast'):
                raise ValueError('speed must be slow, normal, or fast')
            if not isinstance(payload.get('hold', True), bool):
                raise ValueError('hold must be true or false')
            if action == 'move':
                angle = payload.get('angle')
                if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle):
                    raise ValueError('angle must be a finite number in degrees')
        with self.lock:
            if self.reserved or self.stop.is_set():
                raise RuntimeError('Another operation is active. Stop it or wait for completion.')
            if action == 'connect' and self.state['connected']:
                raise RuntimeError('Already connected')
            if action != 'connect' and not self.state['connected']:
                raise RuntimeError('Connect the servo first')
            if action == 'move':
                ticks = round(payload['angle']*TICKS_PER_DEGREE)
                if not self.state['min_ticks'] <= ticks <= self.state['max_ticks']:
                    raise ValueError('Angle is outside the saved servo limits')
            self.reserved = True
            job_id = uuid.uuid4().hex
            self.state.update(busy=True, error=None, job_id=job_id, phase='queued')
            self.jobs.put((action, dict(payload), job_id))
        return job_id

    def release(self):
        self.stop.set()
        self.update(phase='stopping')

    def check_stop(self):
        if self.stop.is_set() or self.quit.is_set():
            raise InterruptedError('Stopped by operator')

    def telemetry(self):
        s = self.servo.status()
        if s['mode'] != 1 or not 0 <= s['min'] < s['max'] <= 16383:
            raise RuntimeError('Servo is not in supported position mode or limits are invalid')
        self.update(connected=True, position_deg=s['position']/TICKS_PER_DEGREE,
                    target_deg=s['target']/TICKS_PER_DEGREE,
                    min_deg=s['min']/TICKS_PER_DEGREE, max_deg=s['max']/TICKS_PER_DEGREE,
                    min_ticks=s['min'], max_ticks=s['max'], voltage_v=s['voltage']/100,
                    actuator_id=self.servo.actuator_id, node_id=self.servo.node_id,
                    updated_at=time.time())
        return s

    def move(self, action, payload):
        self.check_stop()
        s = self.telemetry()
        goal = s['min'] if action == 'min' else s['max'] if action == 'max' else round(payload['angle']*TICKS_PER_DEGREE)
        origin, low, high = s['position'], s['min'], s['max']
        if not low <= goal <= high or not low-20 <= origin <= high+20:
            raise ValueError('Current position or requested angle is outside saved limits')
        if (not hasattr(self.servo, 'config') and not 1050 <= s['voltage'] <= 1300) or s['status'] & 0x6fc0:
            raise RuntimeError('Voltage or servo fault prevents this 12 V bench operation')
        requested_speed = {'slow':min(23,s['speed']), 'normal':min(91,s['speed']), 'fast':s['speed']}[payload.get('speed','fast')]
        success = False
        changed = False
        hold = payload.get('hold', True)
        try:
            self.check_stop()
            self.servo.release()
            self.update(holding=False, phase='moving', target_deg=goal/TICKS_PER_DEGREE)
            changed = True
            self.servo._write(84, requested_speed)
            if self.servo.read(84) != requested_speed:
                raise RuntimeError('Speed setting rejected')
            self.check_stop()
            initial = max(low, min(high, origin))
            self.servo._write(30, initial)
            if self.servo.read(30) != initial:
                raise RuntimeError('Initial target rejected')
            self.check_stop()
            self.servo._write(70, 0)
            if self.stop.wait(.1):
                self.check_stop()
            if abs(self.servo.read(12)-origin) > 91:
                raise RuntimeError('Unexpected movement on enable')
            self.check_stop()
            self.servo._write(30, goal)
            if self.servo.read(30) != goal:
                raise RuntimeError('Target rejected')
            minimum_speed = min(5, self.servo.config['speed_dps'] * self.servo.config['torque_limit_pct']/100) if hasattr(self.servo, 'config') else 5
            deadline = time.monotonic() + abs(goal-origin)/TICKS_PER_DEGREE/minimum_speed + 5
            progress_at, progress_pos = time.monotonic(), origin
            while time.monotonic() < deadline:
                self.check_stop()
                pos = self.servo.read(12)
                self.check_stop()
                volt = self.servo.read(18)
                self.check_stop()
                flags = self.servo.read(72)
                self.update(position_deg=pos/TICKS_PER_DEGREE, voltage_v=volt/100, updated_at=time.time())
                self.motion_sample(pos)
                if (not hasattr(self.servo, 'config') and not 1050 <= volt <= 1300) or flags & 0x6fc0:
                    raise RuntimeError('Voltage or servo fault during movement')
                if not min(origin,goal)-91 <= pos <= max(origin,goal)+91:
                    raise RuntimeError('Unexpected travel')
                if abs(pos-goal) <= max(15, int(getattr(self, 'hardware_config', None).get('deadband_ticks',0))+1 if getattr(self, 'hardware_config', None) else 15):
                    success = True
                    break
                if abs(pos-progress_pos) >= 10:
                    progress_at, progress_pos = time.monotonic(), pos
                if time.monotonic()-progress_at > 1.5:
                    raise RuntimeError('Motion stalled')
                self.stop.wait(.1)
            if not success:
                raise TimeoutError('Target not reached')
        finally:
            keep_holding = success and hold and not self.stop.is_set() and not self.quit.is_set()
            try:
                if not keep_holding:
                    self.servo.release()
            finally:
                if changed:
                    try:
                        self.servo._write(84, s['speed'])
                        if self.servo.read(84) != s['speed']:
                            raise RuntimeError('Original speed could not be restored')
                    except BaseException:
                        self.servo.release()
                        raise
            self.update(holding=keep_holding, phase='holding' if keep_holding else 'released')

    def motion_sample(self, pos):
        pass

    def on_connect(self):
        pass

    def perform(self, action, payload):
        self.move(action, payload)

    def _fail(self, exc):
        release_ok = False
        if self.servo:
            try:
                self.servo.release()
                release_ok = True
            except Exception:
                pass
        self.update(error=str(exc), phase='error', holding=False if release_ok else None)
        if isinstance(exc, OSError):
            self.update(connected=False)
            if self.servo:
                try: self.servo.close()
                except Exception: pass
                self.servo = None

    def _run(self):
        last_poll = 0
        while not self.quit.is_set():
            if self.stop.is_set():
                try:
                    if self.servo: self.servo.release()
                    self.update(holding=False if self.servo else None, phase='released' if self.servo else 'disconnected', error=None)
                except Exception as exc:
                    self._fail(exc)
                # Cancel pending work before allowing another operator to submit.
                with self.lock:
                    while not self.jobs.empty(): self.jobs.get_nowait()
                    self.reserved = False
                    self.state['busy'] = False
                    self.stop.clear()
            try:
                action, payload, _ = self.jobs.get(timeout=.1)
            except queue.Empty:
                if self.servo and time.monotonic()-last_poll > .5:
                    try: self.telemetry()
                    except Exception as exc: self._fail(exc)
                    last_poll = time.monotonic()
                continue
            try:
                self.check_stop()
                if action == 'connect':
                    self.update(phase='connecting')
                    self.servo = self.factory(self.port)
                    self.check_stop()
                    self.on_connect()
                    self.telemetry()
                    self.update(phase='ready', holding=None)
                else:
                    self.perform(action, payload)
            except InterruptedError:
                self.update(phase='stopping')
            except Exception as exc:
                self._fail(exc)
                if action == 'connect' and self.servo:
                    try: self.servo.close()
                    except Exception: pass
                    self.servo = None
                    self.update(connected=False)
            finally:
                with self.lock:
                    self.reserved = False
                    self.state['busy'] = False
        if self.servo:
            try: self.servo.release()
            finally: self.servo.close()

    def close(self):
        self.quit.set()
        self.stop.set()
        self.thread.join(5)


def make_handler(control, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, fmt, *args):
            pass

        def send_json(self, code, data):
            encoded = json.dumps(data, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(encoded)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(encoded)

        def authorized(self):
            value = self.headers.get('Authorization','')
            return hmac.compare_digest(value, 'Bearer '+token)

        def do_GET(self):
            if self.path == '/':
                body = Path(__file__).with_name('index.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Frame-Options','DENY')
                self.send_header('Referrer-Policy','no-referrer')
                self.end_headers()
                self.wfile.write(body)
                return
            if not self.authorized(): return self.send_json(401,{'error':'Access key required'})
            if self.path == '/api/status': return self.send_json(200,control.snapshot())
            if self.path == '/api/capabilities' and hasattr(control,'capabilities'): return self.send_json(200,control.capabilities())
            if self.path == '/api/profile' and hasattr(control,'profile'):
                try: return self.send_json(200,control.profile())
                except RuntimeError as exc: return self.send_json(409,{'error':str(exc)})
            self.send_json(404,{'error':'Not found'})

        def do_POST(self):
            if not self.authorized(): return self.send_json(401,{'error':'Access key required'})
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 <= size <= 16384: raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(payload,dict): raise ValueError('Expected a JSON object')
                if self.path == '/api/shutdown':
                    control.release()
                    self.send_json(202,{'accepted':True})
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                    return
                if self.path == '/api/release':
                    control.release()
                    return self.send_json(202,{'accepted':True})
                action = self.path.removeprefix('/api/')
                if self.path != '/api/'+action or action not in ('connect','move','min','max')+getattr(control,'extra_actions',()):
                    return self.send_json(404,{'error':'Not found'})
                job = control.submit(action,payload)
                self.send_json(202,{'accepted':True,'job_id':job})
            except (ValueError, TypeError) as exc: self.send_json(400,{'error':str(exc)})
            except RuntimeError as exc: self.send_json(409,{'error':str(exc)})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1'],help='Local access only')
    p.add_argument('--port',type=int,default=8108)
    p.add_argument('--serial-port')
    p.add_argument('--simulate',action='store_true')
    p.add_argument('--open',action='store_true',help='Open the browser (already the default)')
    p.add_argument('--no-browser',action='store_true',help='Run without opening the browser')
    p.add_argument('--data-dir',help='Override the persistent workspace directory')
    args = p.parse_args()
    token = os.environ.get('SERVO_API_TOKEN') or secrets.token_urlsafe(24)
    from studio import StudioControl
    control = StudioControl(args.simulate,args.serial_port,data_dir=args.data_dir)
    try:
        server = ThreadingHTTPServer((args.host,args.port),make_handler(control,token))
    except OSError:
        # An unrelated service may own the preferred port. Never send it our key.
        try: server = ThreadingHTTPServer((args.host,0),make_handler(control,token))
        except BaseException:
            control.close()
            raise
    args.port=server.server_port
    server.daemon_threads = True
    print('SIMULATION — no hardware' if args.simulate else 'HARDWARE MODE — waiting for Connect',flush=True)
    print(f'Open http://127.0.0.1:{args.port}/#key={token}',flush=True)
    print(f'API access key: {token}',flush=True)
    if not args.no_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{args.port}/#key={token}')
    def stop_signal(signum,frame):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop_signal)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        control.close()

if __name__ == '__main__': main()
