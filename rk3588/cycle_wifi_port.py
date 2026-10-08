#!/usr/bin/env python3
"""Cycle only the verified Realtek adapter's dedicated USB root-hub port."""
import fcntl
import os
from pathlib import Path
import struct
import time


device = Path('/sys/bus/usb/devices/2-1')
if ((device / 'idVendor').read_text().strip(),
        (device / 'idProduct').read_text().strip()) != ('0bda', '1a2b'):
    raise SystemExit('Expected the driver-storage adapter on port 2-1')
others = [p.name for p in Path('/sys/bus/usb/devices').glob('2-*')
          if p.name != '2-1' and (p / 'idVendor').exists()]
if others:
    raise SystemExit('Other USB devices share this bus: ' + repr(others))
hub = Path('/sys/bus/usb/devices/usb2')
node = '/dev/bus/usb/{:03d}/{:03d}'.format(int((hub / 'busnum').read_text()),
                                        int((hub / 'devnum').read_text()))
# USBDEVFS_CONTROL is _IOWR('U', 0, struct usbdevfs_ctrltransfer), size 24 on ARM64.
fd = os.open(node, os.O_RDWR)


def power(enabled):
    # Class/other OUT; CLEAR_FEATURE=1, SET_FEATURE=3; PORT_POWER=8; port=1.
    request = struct.pack('<BBHHHI4xQ', 0x23, 3 if enabled else 1, 8, 1, 0, 2000, 0)
    fcntl.ioctl(fd, 0xC0185500, request)


try:
    power(False)
    print('Wi-Fi root-hub port power off', flush=True)
    time.sleep(3)
finally:
    try:
        power(True)
        print('Wi-Fi root-hub port power on', flush=True)
    finally:
        os.close(fd)
time.sleep(5)
