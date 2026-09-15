"""Documented settings for the verified MDB961 hardware. All writes read back."""
import math
from server import TICKS_PER_DEGREE as T

# name, label, group, min, max, step, unit (same schema as simulator)
SCHEMA=[
 ('min_deg','Minimum angle','Travel',0,359.97,.01,'°'),
 ('max_deg','Maximum angle','Travel',0,359.97,.01,'°'),
 ('center_deg','Center position','Travel',0,359.97,.01,'°'),
 ('speed_native','Speed limit','Response',1,4095,1,'native units'),
 ('deadband_ticks','Position deadband','Response',0,4095,1,'encoder ticks'),
 ('output_limit_pct','Motor output limit','Response',1,100,.1,'%'),
 ('acceleration_ms','Acceleration time','Response',0,65535,1,'ms'),
 ('overload_time_s','Overload delay','Protection',0,5000,1,'s'),
 ('overload_output_pct','Output during overload','Protection',0,100,1,'%')]
MAP={'min_deg':(0xb2,T),'max_deg':(0xb0,T),'center_deg':(0xc2,T),
     'speed_native':(0x54,1),'deadband_ticks':(0x4e,1),'output_limit_pct':(0x56,4095/100),
     'acceleration_ms':(0xdc,1),'overload_time_s':(0x9a,1),'overload_output_pct':(0x9c,1)}
IDENTITY=(7961,21062)

def read(servo):
    return {key:servo.read(addr)/scale for key,(addr,scale) in MAP.items()}

def validate(patch,current):
    if not isinstance(patch,dict) or set(patch)-set(MAP):raise ValueError('Unknown hardware settings field')
    cfg=dict(current,**patch)
    for key,label,_,low,high,step,unit in SCHEMA:
        value=cfg.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'{label} must be between {low} and {high} {unit}')
        if step==1 and value!=int(value):raise ValueError(f'{label} must be an integer')
    if round(cfg['max_deg']*T)-round(cfg['min_deg']*T)<46:raise ValueError('Travel must span at least 1°')
    if not cfg['min_deg']<=cfg['center_deg']<=cfg['max_deg']:raise ValueError('Center must be within travel limits')
    return cfg

def apply(servo,patch,expected):
    current=read(servo)
    if current!=expected:raise RuntimeError('Servo settings changed. Reload settings before applying.')
    cfg=validate(patch,current)
    pos=servo.read(12)
    if not round(cfg['min_deg']*T)-15<=pos<=round(cfg['max_deg']*T)+15:
        raise ValueError('Move the shaft inside the proposed limits before changing them')
    before={key:round(current[key]*scale) for key,(_,scale) in MAP.items()}
    after={key:round(cfg[key]*scale) for key,(_,scale) in MAP.items()}
    changed=[key for key in MAP if before[key]!=after[key]]
    if not changed:return current
    servo.release()
    # Widen before narrowing so intermediate limits are never inverted.
    changed.sort(key=lambda k:0 if k=='min_deg' and after[k]<before[k] or k=='max_deg' and after[k]>before[k] else 1)
    attempted=[]
    try:
        for key in changed:
            addr,_=MAP[key];attempted.append(key)
            servo._write(addr,after[key])
            if servo.read(addr)!=after[key]:raise RuntimeError(f'{key} write was not accepted')
        return read(servo)
    except Exception as exc:
        failures=[]
        for key in reversed(attempted):
            addr,_=MAP[key]
            try:
                servo._write(addr,before[key])
                if servo.read(addr)!=before[key]:failures.append(key)
            except Exception:failures.append(key)
        servo.release()
        raise RuntimeError(f'Settings update failed: {exc}. '+('Rollback could not be verified: '+', '.join(failures) if failures else 'Previous values restored.')) from exc
