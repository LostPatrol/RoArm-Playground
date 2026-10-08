#!/usr/bin/env python3
"""Try kernel CD-ROM eject with automatic modeswitch paused temporarily."""
import fcntl
import glob
import os
from pathlib import Path
import subprocess
import sys
import time


def run(*args):
    subprocess.run(args, check=True)


port = Path('/sys/bus/usb/devices/2-1')
if (port / 'idVendor').read_text().strip() != '0bda' or (port / 'idProduct').read_text().strip() != '1a2b':
    raise SystemExit('Expected Realtek driver-storage device is not on USB port 2-1')
other_devices = [p for p in Path('/sys/bus/usb/devices').glob('2-*')
                 if p.name != '2-1' and (p / 'idVendor').exists()]
if other_devices:
    raise SystemExit('Other devices share this USB bus; leaving the bus unchanged')

unit = 'usb_modeswitch@2-1.service'
quirks_path = Path('/sys/module/usb_storage/parameters/quirks')
old_quirks = quirks_path.read_text().strip()
ignore_storage = '--ignore-storage' in sys.argv
run('systemctl', 'mask', '--runtime', unit)
try:
    if ignore_storage:
        quirks_path.write_text(','.join(filter(None, [old_quirks, '0bda:1a2b:i'])))
    # This bus contains only the external adapter, not the ADB gadget.
    Path('/sys/bus/usb/drivers/usb/unbind').write_text('usb2')
    time.sleep(1)
    Path('/sys/bus/usb/drivers/usb/bind').write_text('usb2')
    if ignore_storage:
        time.sleep(2)
        subprocess.run(['usb_modeswitch', '-K', '-v', '0bda', '-p', '1a2b'], timeout=20)
        time.sleep(2)
        subprocess.run(['lsusb'])
        subprocess.run(['ip', '-br', 'addr'])
        raise SystemExit(0)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        nodes = glob.glob('/dev/sr*')
        if nodes:
            for node in nodes:
                device = (Path('/sys/class/block') / Path(node).name / 'device').resolve()
                if not any(p.name == '2-1' for p in device.parents):
                    continue
                print('Kernel eject:', node, flush=True)
                fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    # CDROMEJECT, scoped to this adapter's virtual driver CD-ROM.
                    fcntl.ioctl(fd, 0x5309)
                    print('Eject request accepted', flush=True)
                finally:
                    os.close(fd)
                break
            else:
                time.sleep(.5)
                continue
            break
        time.sleep(.5)
    else:
        print('No driver CD-ROM appeared within 12 seconds', flush=True)
    time.sleep(2)
finally:
    if ignore_storage:
        quirks_path.write_text(old_quirks + '\n')
    run('systemctl', 'unmask', '--runtime', unit)
subprocess.run(['lsusb'])
subprocess.run(['ip', '-br', 'addr'])
