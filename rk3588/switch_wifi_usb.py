#!/usr/bin/env python3
"""Switch the verified Realtek adapter, including multi-level hub USB paths."""
from pathlib import Path
import re
import subprocess
import sys
import time


port = sys.argv[1]
if not re.fullmatch(r'\d+-\d+(?:\.\d+)*', port):
    raise SystemExit('Invalid USB device path')
device = Path('/sys/bus/usb/devices') / port


def identity():
    try:
        return ((device / 'idVendor').read_text().strip(),
                (device / 'idProduct').read_text().strip())
    except FileNotFoundError:
        return None


if identity() == ('0bda', 'c812'):
    raise SystemExit(0)
if identity() != ('0bda', '1a2b'):
    raise SystemExit('Expected adapter is absent')
bus = (device / 'busnum').read_text().strip()
number = (device / 'devnum').read_text().strip()
subprocess.run(['usb_modeswitch', '-K', '-v', '0bda', '-p', '1a2b',
                '-b', bus, '-g', number], timeout=15)
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    if identity() == ('0bda', 'c812'):
        subprocess.run(['modprobe', 'rtw_8822cu'], check=True, timeout=3)
        print('RTL8822CU wireless mode ready on', port)
        raise SystemExit(0)
    time.sleep(.2)
raise SystemExit('Adapter did not enter wireless mode; see USB logs')
