"""Expanded simulator workspace. No additional hardware register writes."""
import copy
import json
import math
import os
import time
import uuid
import hardware_settings as hw
from app_paths import user_data_dir
from pathlib import Path
from server import Control, SimServo, TICKS_PER_DEGREE

DEFAULTS = dict(min_deg=4300/TICKS_PER_DEGREE, max_deg=8500/TICKS_PER_DEGREE,
                center_deg=140.625, direction='normal', speed_dps=180.0,
                deadband_deg=.1, soft_start_s=.25, failsafe_enabled=True,
                failsafe_deg=140.625, failsafe_timeout_s=1.0,
                torque_limit_pct=100.0, overload_time_s=1.0, overload_output_pct=20.0,
                voltage_min_v=10.5, voltage_max_v=13.0, temperature_max_c=75.0,
                actuator_id=10, node_id=10, can_bitrate=1000000)
# These are simulator UI ranges, not a promise of firmware-compatible register ranges.
SCHEMA = [
 ('min_deg','Minimum angle','Travel',0,359.97,.01,'°'),
 ('max_deg','Maximum angle','Travel',0,359.97,.01,'°'),
 ('center_deg','Center position','Travel',0,359.97,.01,'°'),
 ('direction','Direction','Travel',['normal','reversed'],None,None,''),
 ('speed_dps','Maximum speed','Response',1,400,1,'°/s'),
 ('deadband_deg','Position deadband','Response',0,.3,.01,'°'),
 ('soft_start_s','Soft start duration','Response',0,3,.05,'s'),
 ('torque_limit_pct','Output limit','Response',1,100,1,'%'),
 ('failsafe_enabled','Enable fail-safe','Fail-safe',True,None,None,''),
 ('failsafe_deg','Fail-safe position','Fail-safe',0,359.97,.01,'°'),
 ('failsafe_timeout_s','Signal loss delay','Fail-safe',.1,10,.1,'s'),
 ('overload_time_s','Overload delay','Protection',.1,10,.1,'s'),
 ('overload_output_pct','Output during overload','Protection',0,100,1,'%'),
 ('voltage_min_v','Low voltage threshold','Protection',0,32,.1,'V'),
 ('voltage_max_v','High voltage threshold','Protection',0,32,.1,'V'),
 ('temperature_max_c','High temperature threshold','Protection',20,100,1,'°C'),
 ('actuator_id','Actuator ID','Connection',1,127,1,''),
 ('node_id','DroneCAN node ID','Connection',1,127,1,''),
 ('can_bitrate','CAN bitrate','Connection',[125000,250000,500000,1000000],None,None,'bit/s'),
]


def number(v, low, high, name):
    if isinstance(v, bool) or not isinstance(v, (float,int)) or not math.isfinite(v) or not low <= v <= high:
        raise ValueError(f'{name} must be a number from {low} to {high}')
    return v


def validate_settings(patch, current):
    if not isinstance(patch,dict) or set(patch)-set(DEFAULTS):
        raise ValueError('Unknown settings field or invalid settings object')
    cfg = dict(current, **patch)
    for key,label,group,low,high,step,unit in SCHEMA:
        value = cfg[key]
        if isinstance(low,list):
            if isinstance(value,bool) or value not in low: raise ValueError(f'Invalid {label}')
        elif low is True:
            if type(value) is not bool: raise ValueError(f'{label} must be true or false')
        else:
            number(value,low,high,label)
            if key in ('actuator_id','node_id') and int(value)!=value: raise ValueError(f'{label} must be an integer')
    if cfg['max_deg']-cfg['min_deg'] < 1: raise ValueError('Travel must span at least 1°')
    for key in ('center_deg','failsafe_deg'):
        if not cfg['min_deg']<=cfg[key]<=cfg['max_deg']: raise ValueError(f'{key} must be inside the travel limits')
    if cfg['voltage_min_v']>=cfg['voltage_max_v']: raise ValueError('Low voltage must be below high voltage')
    if cfg['overload_output_pct']>cfg['torque_limit_pct']: raise ValueError('Overload output cannot exceed the output limit')
    return cfg


class StudioServo(SimServo):
    """Kinematic demo: intentionally not a motor/electrical or firmware model."""
    def __init__(self, port=None):
        super().__init__(port)
        self.config = dict(DEFAULTS)
        self.velocity_dps = 0.0
        self.temperature_c = 26.0
        self.fault = 'none'
        self.output_pct = 0.0
        self.overload_at = None
        self.started = time.monotonic()

    def read(self, addr):
        now = time.monotonic()
        dt = min(now-self.last,.25)
        c = self.config
        dist = self.values[30]-self.values[12]
        desired = min(c['speed_dps'], self.values[84]*10/TICKS_PER_DEGREE) * c['torque_limit_pct']/100
        if abs(dist)/TICKS_PER_DEGREE <= c['deadband_deg'] or not self.enabled:
            desired = 0
        ramp = desired if not c['soft_start_s'] else c['speed_dps']*dt/c['soft_start_s']
        speed = min(desired,abs(self.velocity_dps)+ramp)
        if self.fault=='stall':
            if self.overload_at is None: self.overload_at=now
            self.output_pct = c['torque_limit_pct'] if now-self.overload_at<c['overload_time_s'] else c['overload_output_pct']
            speed=0
        else:
            self.overload_at=None
            self.output_pct = c['torque_limit_pct'] if desired else (5 if self.enabled else 0)
        flags = self.values[72] & ~0x6800
        volt = self.values[18]/100
        if volt<c['voltage_min_v']:flags|=0x2000
        if volt>c['voltage_max_v']:flags|=0x4000
        if self.temperature_c>c['temperature_max_c']:flags|=0x0800
        self.values[72]=flags
        if flags & 0x6fc0: speed=0; self.enabled=False; self.output_pct=0
        step = min(abs(dist),speed*dt*TICKS_PER_DEGREE)
        self.values[12] += math.copysign(step,dist)
        self.velocity_dps = math.copysign(step/TICKS_PER_DEGREE/dt,dist) if dt>0 else 0
        self.last=now
        return round(self.values[addr])

    def apply(self, cfg):
        self.release()
        self.config=dict(cfg)
        self.values[178]=round(cfg['min_deg']*TICKS_PER_DEGREE)
        self.values[176]=round(cfg['max_deg']*TICKS_PER_DEGREE)
        self.actuator_id=int(cfg['actuator_id']);self.node_id=int(cfg['node_id'])
        self.values[50]=self.actuator_id
        # Applying configuration never teleports or moves the simulated shaft.
        self.values[30]=self.values[12]

    def inject(self, kind):
        self.fault=kind
        self.values[18]=900 if kind=='undervoltage' else 1500 if kind=='overvoltage' else 1197
        self.temperature_c=95 if kind=='overheat' else 26
        self.values[72]=1
        self.overload_at=None
        self.read(12)


class StudioControl(Control):
    extra_actions = ('settings/apply','settings/save','settings/reload','settings/reset',
                     'sim/power-cycle','sim/fault','sim/signal-loss','presets/add',
                     'presets/remove','presets/update','presets/move','sequence','center','profile/import','settings/read','settings/capture')

    def __init__(self, simulated=False, port=None, data_dir=None):
        self.saved = dict(DEFAULTS)
        self.presets = []
        self.events = []
        self.config_revision = 0
        self.hardware_config = None
        self.hardware_baseline = None
        self.hardware_identity = None
        self.hardware_config_error = None
        self.flash_state = 'unknown'
        self.data_dir = Path(data_dir) if data_dir else user_data_dir()/('simulation' if simulated else 'hardware')
        self.storage_error = None
        try:
            raw=json.loads((self.data_dir/'workspace.json').read_text())
            self.saved=validate_settings(raw['saved'],DEFAULTS)
            self.presets=self.validate_presets(raw.get('presets',[]))
        except FileNotFoundError: pass
        except (ValueError,KeyError,OSError,TypeError) as exc:
            self.storage_error=f'Workspace could not be loaded: {exc}'
        super().__init__(simulated,port,factory=StudioServo if simulated else None)
        self.update(config=None,config_revision=0,settings_dirty=False, sequence_step=None,
                    event_log=[],presets=copy.deepcopy(self.presets), storage_error=self.storage_error)

    @staticmethod
    def validate_presets(items):
        if not isinstance(items,list) or len(items)>30: raise ValueError('Use at most 30 presets')
        result=[]
        for item in items:
            if not isinstance(item,dict):raise ValueError('Invalid preset')
            name=item.get('name')
            if not isinstance(name,str) or not 1<=len(name.strip())<=40:raise ValueError('Preset name must contain 1–40 characters')
            angle=number(item.get('angle'),0,359.97,'Preset angle')
            result.append(dict(name=name.strip(),angle=angle))
        if len({p['name'].casefold() for p in result})!=len(result):raise ValueError('Preset names must be unique')
        return result

    def persist(self, saved=None, presets=None):
        saved=self.saved if saved is None else saved
        presets=self.presets if presets is None else presets
        self.data_dir.mkdir(parents=True,exist_ok=True)
        temp=self.data_dir/'workspace.tmp'
        temp.write_text(json.dumps(dict(saved=saved,presets=presets),indent=2,allow_nan=False))
        os.replace(temp,self.data_dir/'workspace.json')

    def event(self, text):
        self.events=(self.events+[dict(at=time.time(),message=text)])[-40:]
        self.update(event_log=copy.deepcopy(self.events))

    def capabilities(self):
        mode='simulation' if self.simulated else 'hardware'
        return dict(mode=mode, schema=SCHEMA if self.simulated else hw.SCHEMA, features=[
            dict(name='Angle control, Min / Max, speed and release',status='available'),
            dict(name='Named presets and repeatable motion tests',status='available'),
            dict(name='Travel, center, speed, deadband, output and overload settings',status='available on verified MDB961 firmware'),
            dict(name='Direction, fail-safe and CAN identity writes',status='simulation only'),
            dict(name='Fail-safe, protection and connection settings',status='simulation only'),
            dict(name='Profiles, simulated save / reboot / reset',status='simulation only'),
            dict(name='Telemetry, events and fault injection',status='simulation only'),
            dict(name='Firmware flashing and recovery',status='not implemented'),
            dict(name='Multi-servo discovery and control',status='not implemented'),
            dict(name='Multi-turn, continuous rotation and speed modes',status='not implemented'),
            dict(name='Model-specific tuning and raw register editor',status='not implemented')])

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.state)

    def profile(self):
        s=self.snapshot()
        if s.get('config') is None:raise RuntimeError('Connect and read settings first')
        return dict(format='servo-studio-profile',version=1,simulation=self.simulated,identity=list(self.hardware_identity) if self.hardware_identity else None,settings=s['config'],presets=s['presets'])

    def submit(self, action, payload=None):
        if action not in self.extra_actions:return super().submit(action,payload)
        payload=payload or {}
        if not self.simulated and (action.startswith('sim/') or action=='settings/reset'):
            raise RuntimeError('Fault injection, virtual reboot and demo reset are simulation-only')
        with self.lock:
            if self.reserved or self.stop.is_set():raise RuntimeError('Another operation is active. Stop it or wait for completion.')
            if not self.state['connected']:raise RuntimeError('Connect the servo first')
            cfg=self.state['config']
            if not self.simulated and action in ('settings/apply','settings/save','settings/reload','settings/capture','profile/import','center') and self.hardware_config is None:
                raise RuntimeError(self.hardware_config_error or 'Hardware configuration unavailable')
            if action=='settings/capture':
                if payload.get('field') not in ('min_deg','max_deg','center_deg'):raise ValueError('Capture field must be min_deg, max_deg or center_deg')
                if payload.get('revision')!=self.config_revision:raise RuntimeError('Settings changed. Reload the form before capturing.')
            if action=='settings/apply':
                (validate_settings if self.simulated else hw.validate)(payload.get('settings'),cfg)
                if payload.get('revision')!=self.config_revision:raise RuntimeError('Settings changed. Reload the form before applying.')
            elif action=='sim/fault':
                if payload.get('kind') not in ('none','stall','undervoltage','overvoltage','overheat'):raise ValueError('Unknown simulated fault')
            elif action=='presets/add':self.validate_presets(self.presets+[payload])
            elif action in ('presets/remove','presets/move','presets/update'):
                if not any(p['name']==payload.get('name') for p in self.presets):raise ValueError('Preset not found')
                if action=='presets/update':self.validate_presets([dict(name=payload.get('new_name'),angle=payload.get('angle')) if p['name']==payload['name'] else p for p in self.presets])
            elif action=='sequence':
                number(payload.get('cycles',1),1,20,'Cycles')
                if int(payload.get('cycles',1))!=payload.get('cycles',1):raise ValueError('Cycles must be an integer')
                number(payload.get('dwell_s',.5),0,10,'Dwell')
                angles=payload.get('angles')
                if not isinstance(angles,list) or not 2<=len(angles)<=20:raise ValueError('Provide 2–20 angles')
                for angle in angles:number(angle,self.state['min_deg'],self.state['max_deg'],'Sequence angle')
            elif action=='profile/import':
                self.validate_profile(payload.get('profile'))
            if action in ('sequence','center','presets/move','sim/signal-loss'):
                if payload.get('speed','fast') not in ('slow','normal','fast'):raise ValueError('Invalid speed')
                if type(payload.get('hold',True)) is not bool:raise ValueError('hold must be true or false')
            job=uuid.uuid4().hex
            self.reserved=True
            self.state.update(busy=True,error=None,job_id=job,phase='queued',operation=action,live_stream=None)
            self.jobs.put((action,copy.deepcopy(payload),job))
            return job

    def validate_profile(self, profile):
        if not isinstance(profile,dict) or profile.get('format')!='servo-studio-profile' or profile.get('version')!=1 or profile.get('simulation') is not self.simulated:
            raise ValueError('Profile must match this workspace mode and format version 1')
        if not self.simulated:
            if profile.get('identity')!=list(self.hardware_identity or []):raise ValueError('Hardware profile identity does not match this servo')
            return hw.validate(profile.get('settings'),self.hardware_config),self.validate_presets(profile.get('presets',[]))
        if not isinstance(profile.get('settings'),dict) or set(profile['settings'])!=set(DEFAULTS):raise ValueError('Profile must contain every settings field')
        cfg=validate_settings(profile['settings'],DEFAULTS)
        presets=self.validate_presets(profile.get('presets',[]))
        return cfg,presets

    def telemetry(self):
        s=super().telemetry()
        if self.simulated:
            servo=self.servo;c=servo.config
            if not servo.enabled:self.update(holding=False)
            self.update(config=dict(c),config_revision=self.config_revision,
                        settings_dirty=c!=self.saved,presets=copy.deepcopy(self.presets),
                        velocity_dps=servo.velocity_dps,temperature_c=servo.temperature_c,
                        output_pct=servo.output_pct,sim_fault=servo.fault,
                        output_angle_deg=(c['min_deg']+c['max_deg']-s['position']/TICKS_PER_DEGREE) if c['direction']=='reversed' else s['position']/TICKS_PER_DEGREE,
                        status_flags=s['status'],uptime_s=round(time.monotonic()-servo.started,1))
        else:
            self.update(config=copy.deepcopy(self.hardware_config),config_revision=self.config_revision,
                        settings_dirty=self.hardware_config!=self.hardware_baseline,presets=copy.deepcopy(self.presets),
                        config_error=self.hardware_config_error,flash_state=self.flash_state,status_flags=s['status'])
        return s

    def release(self):
        super().release()
        # Event history is owned by the worker; status already reports stopping.

    def motion_sample(self, pos):
        if self.simulated:
            servo=self.servo;c=servo.config
            self.update(velocity_dps=servo.velocity_dps,temperature_c=servo.temperature_c,
                        output_pct=servo.output_pct,status_flags=servo.values[72],
                        output_angle_deg=(c['min_deg']+c['max_deg']-pos/TICKS_PER_DEGREE) if c['direction']=='reversed' else pos/TICKS_PER_DEGREE,
                        uptime_s=round(time.monotonic()-servo.started,1))

    def on_connect(self):
        if self.simulated:
            self.servo.apply(self.saved)
            # Initial virtual position lies within the saved profile.
            self.servo.values[12]=max(self.servo.values[178],min(self.servo.values[176],self.servo.values[12]))
            self.servo.values[30]=self.servo.values[12]
            self.config_revision+=1
        else:
            self.hardware_identity=(self.servo.read(0x74),self.servo.read(0xfc))
            if self.hardware_identity==hw.IDENTITY:
                self.hardware_config=hw.read(self.servo);self.hardware_baseline=dict(self.hardware_config);self.config_revision+=1
                self.hardware_config_error=None
            else:self.hardware_config_error='Configuration is supported only for the verified MDB961 firmware; movement and presets remain available.'
        self.event('Simulator connected' if self.simulated else 'Servo connected')

    def perform(self, action, payload):
        if action not in self.extra_actions:
            self.event(f'Move requested: {payload.get("angle",action)}')
            super().perform(action,payload)
            self.telemetry()
            self.event('Position reached')
            return
        servo=self.servo
        if not self.simulated and action.startswith('settings/'):
            self.hardware_settings_action(action,payload)
            self.telemetry()
            return
        if action=='settings/capture':
            cfg=validate_settings({payload['field']:servo.read(12)/TICKS_PER_DEGREE},servo.config)
            self.apply_config(cfg)
            self.event('Current encoder position applied to '+payload['field']+'; not saved to flash')
        elif action=='settings/read':
            self.config_revision+=1
        elif action=='settings/apply':
            cfg=validate_settings(payload['settings'],servo.config)
            self.apply_config(cfg)
            self.event('Settings applied to virtual servo; not yet saved')
        elif action=='settings/save':
            self.persist(saved=servo.config)
            self.saved=dict(servo.config)
            self.event('Virtual nonvolatile settings saved')
        elif action in ('settings/reload','sim/power-cycle'):
            self.apply_config(self.saved)
            servo.inject('none')
            if action=='sim/power-cycle':servo.started=time.monotonic()
            self.event('Saved virtual settings loaded; motor released')
        elif action=='settings/reset':
            self.apply_config(DEFAULTS)
            self.event('Demo defaults restored; not manufacturer factory values')
        elif action=='sim/fault':
            servo.inject(payload['kind']);self.update(error=None)
            self.event('Simulated fault: '+payload['kind'])
        elif action=='presets/add':
            items=self.validate_presets(self.presets+[payload]);self.persist(presets=items);self.presets=items
            self.event('Preset saved: '+payload['name'])
        elif action=='presets/update':
            items=self.validate_presets([dict(name=payload['new_name'],angle=payload['angle']) if p['name']==payload['name'] else p for p in self.presets])
            self.persist(presets=items);self.presets=items;self.event('Preset updated: '+payload['new_name'])
        elif action=='presets/remove':
            items=[p for p in self.presets if p['name']!=payload['name']];self.persist(presets=items);self.presets=items
            self.event('Preset removed: '+payload['name'])
        elif action=='profile/import':
            cfg,items=self.validate_profile(payload['profile'])
            if self.simulated:self.apply_config(cfg)
            else:self.hardware_settings_action('settings/apply',{'settings':cfg})
            self.persist(presets=items);self.presets=items
            self.event('Profile imported; settings applied, not saved to flash')
        elif action=='sequence':
            angles=payload['angles'];cycles=int(payload.get('cycles',1))
            try:
                for cycle in range(cycles):
                    for i,angle in enumerate(angles):
                        self.check_stop()
                        self.update(sequence_step=f'Cycle {cycle+1}/{cycles} · position {i+1}/{len(angles)}')
                        self.move('move',dict(payload,angle=angle,hold=True))
                        if self.stop.wait(payload.get('dwell_s',.5)):self.check_stop()
                if not payload.get('hold',True):servo.release();self.update(holding=False,phase='released')
                self.event('Sequence completed')
            except BaseException:
                servo.release();self.update(holding=False)
                raise
            finally:self.update(sequence_step=None)
        elif action=='sim/signal-loss':
            servo.release();self.update(holding=False,phase='signal loss')
            if self.stop.wait(servo.config['failsafe_timeout_s']):self.check_stop()
            if servo.config['failsafe_enabled']:
                self.move('move',dict(payload,angle=servo.config['failsafe_deg']))
                self.event('Signal-loss test: fail-safe position reached')
            else:self.event('Signal-loss test: fail-safe disabled, motor released');self.update(phase='released')
        else:
            angle=(servo.config if self.simulated else self.hardware_config)['center_deg'] if action=='center' else next(p['angle'] for p in self.presets if p['name']==payload['name'])
            self.move('move',dict(payload,angle=angle))
            self.event('Position reached')
        if self.snapshot()['phase']=='queued':
            holding=servo.enabled if self.simulated else self.snapshot()['holding']
            self.update(phase='holding' if holding else 'released',holding=holding)
        self.telemetry()

    def hardware_settings_action(self, action, payload):
        servo=self.servo
        if action=='settings/capture':
            self.hardware_config=hw.apply(servo,{payload['field']:servo.read(12)/TICKS_PER_DEGREE},self.hardware_config)
            self.update(holding=False)
            self.event('Current encoder position applied to '+payload['field']+'; not saved to flash')
        elif action=='settings/read':
            if self.hardware_identity!=hw.IDENTITY:raise RuntimeError('Unsupported hardware identity')
            self.hardware_config=hw.read(servo)
            self.hardware_config_error=None
        elif action=='settings/apply':
            try:self.hardware_config=hw.apply(servo,payload['settings'],self.hardware_config)
            except Exception:
                self.hardware_config=hw.read(servo)
                self.config_revision+=1
                raise
            self.update(holding=False)
            self.event('Hardware settings applied and read back; not saved to flash')
        elif action=='settings/reload':
            # Restore this connection's baseline; do not invoke a whole-device reset.
            self.hardware_config=hw.apply(servo,self.hardware_baseline,self.hardware_config)
            self.update(holding=False)
            self.event('Connection baseline restored')
        elif action=='settings/save':
            fresh=hw.read(servo)
            if fresh!=self.hardware_config:raise RuntimeError('Settings changed. Read them again before saving.')
            servo.release();self.update(holding=False)
            servo._write(0x70,65535)
            time.sleep(.3)
            if hw.read(servo)!=fresh:raise RuntimeError('Read-back changed after save command')
            self.hardware_baseline=dict(fresh)
            self.flash_state='save command sent; persistence requires a power-cycle check'
            self.event('Flash save command sent; runtime values verified')
        else:raise ValueError('Unsupported hardware settings action')
        self.config_revision+=1
        self.update(phase='released' if self.snapshot()['holding'] is False else 'ready')

    def apply_config(self,cfg):
        self.servo.apply(cfg);self.config_revision+=1
        self.update(holding=False,phase='released')

    def _fail(self,exc):
        super()._fail(exc)
        self.event(str(exc))
