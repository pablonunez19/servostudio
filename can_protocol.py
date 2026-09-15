"""Hitec protocol capabilities and explicit, checked protocol changes.

Sources: Hitec protocol manual v2.5 and the firmware decoder in Hitec's
2024-04-03 configuration app (legacy /U firmware uses a 20000 offset).
"""
MODES = {'can2a': 'CAN 2.0A · 11-bit', 'can2b': 'CAN 2.0B · 29-bit',
         'dronecan': 'DroneCAN · 29-bit'}
REG_MODES = {'can2a': 0, 'can2b': 1, 'dronecan': 2}


def firmware(raw):
    if type(raw) is not int or not 0 < raw < 65535:
        return dict(raw=raw, type=None, version=None, label=f'Unknown ({raw})')
    value = raw & 0x7fff
    if value == 2012:
        kind, version = 'U', 1012
    elif 3000 <= value < 10000:
        kind, version = 'A', value - 2000
    elif 11000 <= value < 20000:
        kind, version = 'C', value - 10000
    elif 21000 <= value < 30000:
        kind, version = 'U', value - 20000
    elif 31000 <= value <= 32767:
        kind, version = 'U', value - 30000
    else:
        return dict(raw=raw, type=None, version=None, label=f'Unknown ({raw})')
    return dict(raw=raw, type=kind, version=version,
                label=f'{version//1000}.{version//10%100}({version%10}) /{kind}')


def inspect(servo):
    raw = servo.read(0xfc)
    if servo.read(0xfe) != (raw ^ 0xffff):
        raise RuntimeError('Firmware identity verification failed')
    fw = firmware(raw)
    register = servo.read(0x6a)
    supported = {'A': list(MODES), 'C': ['can2a','can2b'], 'U': ['dronecan']}.get(fw['type'], [])
    effective = 'dronecan' if fw['type']=='U' else next((k for k,v in REG_MODES.items() if v==register), None)
    # A mode register can describe a pending change; distinguish it from the
    # transport actually answering reads. /U firmware ignores this register.
    transport = getattr(servo, 'protocol', None)
    can_id = servo.read(0x3c)*65536 + servo.read(0x3e)
    switchable = fw['type'] in ('A','C') and 1040 <= fw['version'] <= 2039
    reason = ('This /U firmware supports DroneCAN only; the CAN mode register is ignored.' if fw['type']=='U'
              else 'Firmware type could not be verified. Protocol changes are disabled.' if not supported
              else 'Protocol switching is unavailable for this firmware version.' if not switchable
              else 'Changing protocol saves all current servo settings and requires a power cycle.')
    return dict(firmware=fw, supported=supported, configured=effective, transport=transport,
                mode_register=register, can_id=can_id, switchable=switchable,
                reason=reason, bitrate_code=servo.read(0x38))


def validate_change(info, target):
    if target not in MODES: raise ValueError('Unknown CAN protocol')
    if not info or not info['switchable'] or target not in info['supported']:
        raise ValueError((info or {}).get('reason','Read protocol information first'))
    if target==info['configured']: raise ValueError('That protocol is already configured')
    ident=info['can_id']
    if target=='can2a' and not 0 <= ident <= 0x7ff:
        raise ValueError('Current CAN ID exceeds 11 bits. Set a compatible CAN ID with Hitec before switching.')
    if target=='can2b' and not 0 <= ident <= 0x1fffffff:
        raise ValueError('Current CAN ID exceeds 29 bits')
    if target=='dronecan' and not 1 <= ident <= 127:
        raise ValueError('DroneCAN requires an assigned node ID from 1 to 127; configure it with Hitec first.')
