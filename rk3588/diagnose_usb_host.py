#!/usr/bin/env python3
"""Read USB roles, enumerated devices, cameras and network state on RK3588."""
import json
from pathlib import Path
import subprocess


def read(path):
    try:
        return Path(path).read_text().strip('\x00\r\n')
    except (OSError, UnicodeError):
        return None


def command(args):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, timeout=12)
        return {'returncode': result.returncode, 'output': result.stdout.strip()}
    except Exception as exc:
        return {'error': str(exc)}


report = {'model': read('/proc/device-tree/model'), 'usb': [], 'usb_roles': {},
          'typec': {}, 'device_tree_usb_modes': {}, 'dwc3_debug_modes': {}, 'video': []}
for device in sorted(Path('/sys/bus/usb/devices').iterdir()):
    if not (device / 'idVendor').exists():
        continue
    report['usb'].append(dict(path=device.name,
                              **{key: read(device / key) for key in
                                 ('idVendor', 'idProduct', 'product', 'manufacturer', 'speed')}))
for path in Path('/sys/class/usb_role').glob('*/role'):
    report['usb_roles'][str(path)] = read(path)
for port in Path('/sys/class/typec').glob('port*'):
    report['typec'][port.name] = {key: read(port / key) for key in
                                ('data_role', 'power_role', 'port_type', 'preferred_role')}
for path in Path('/proc/device-tree').rglob('dr_mode'):
    report['device_tree_usb_modes'][str(path)] = read(path)
for path in Path('/sys/kernel/debug/usb').glob('*/mode'):
    report['dwc3_debug_modes'][str(path)] = read(path)
for node in sorted(Path('/sys/class/video4linux').glob('video*')):
    ancestry = (node / 'device').resolve()
    report['video'].append({'path': '/dev/' + node.name, 'name': read(node / 'name'),
                            'usb': any((parent / 'idVendor').exists() for parent in ancestry.parents)})
for key, args in [('network', ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status']),
                  ('addresses', ['ip', '-br', 'addr']),
                  ('camera_service', ['systemctl', 'status', 'roarm-camera', '--no-pager', '-l']),
                  ('kernel_recent', ['dmesg', '--ctime'])]:
    report[key] = command(args)
    if key == 'kernel_recent' and 'output' in report[key]:
        report[key]['output'] = '\n'.join(report[key]['output'].splitlines()[-65:])
print(json.dumps(report, ensure_ascii=False, indent=2))
