#!/usr/bin/env python3
"""Drain boot-time storage replies, then eject the identified Realtek virtual CD."""
import ctypes as ct
from pathlib import Path
import re
import subprocess
import sys
import time


# Standard 31-byte BOT CBW: zero transfer length, six-byte START STOP UNIT, EJECT.
# usb_modeswitch 2.5.2 -K aborts before EJECT when its preliminary CSW overflows.
EJECT_MESSAGE = '5553424397654321000000000000061b000000020000000000000000000000'


def identity(device):
    try:
        return ((device / 'idVendor').read_text().strip(),
                (device / 'idProduct').read_text().strip())
    except FileNotFoundError:
        return None


def drain_storage_replies(device):
    """Detach this adapter's storage driver and consume at most eight stale packets."""
    bus, number = (int((device / field).read_text()) for field in ('busnum', 'devnum'))
    usb = ct.CDLL('libusb-1.0.so.0')  # Already provided by usb-modeswitch's dependency.
    pointer = ct.c_void_p
    signatures = {
        'init': ([ct.POINTER(pointer)], ct.c_int),
        'get_device_list': ([pointer, ct.POINTER(ct.POINTER(pointer))], ct.c_ssize_t),
        'get_bus_number': ([pointer], ct.c_uint8),
        'get_device_address': ([pointer], ct.c_uint8),
        'open': ([pointer, ct.POINTER(pointer)], ct.c_int),
        'kernel_driver_active': ([pointer, ct.c_int], ct.c_int),
        'detach_kernel_driver': ([pointer, ct.c_int], ct.c_int),
        'claim_interface': ([pointer, ct.c_int], ct.c_int),
        'bulk_transfer': ([pointer, ct.c_uint8, pointer, ct.c_int, ct.POINTER(ct.c_int), ct.c_uint], ct.c_int),
        'release_interface': ([pointer, ct.c_int], ct.c_int),
        'close': ([pointer], None),
        'free_device_list': ([ct.POINTER(pointer), ct.c_int], None),
        'exit': ([pointer], None),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(usb, 'libusb_' + name)
        function.argtypes, function.restype = arguments, result
    context, handle = pointer(), pointer()
    devices = ct.POINTER(pointer)()
    claimed = False

    def check(code, operation):
        if code < 0:
            raise RuntimeError('%s failed: libusb %s' % (operation, code))

    check(usb.libusb_init(ct.byref(context)), 'init')
    try:
        count = usb.libusb_get_device_list(context, ct.byref(devices))
        check(count, 'enumerate')
        matches = [devices[i] for i in range(count)
                   if usb.libusb_get_bus_number(devices[i]) == bus
                   and usb.libusb_get_device_address(devices[i]) == number]
        if len(matches) != 1 or identity(device) != ('0bda', '1a2b'):
            raise RuntimeError('Target adapter changed before USB drain')
        check(usb.libusb_open(matches[0], ct.byref(handle)), 'open')
        active = usb.libusb_kernel_driver_active(handle, 0)
        check(active, 'driver state')
        if active:
            check(usb.libusb_detach_kernel_driver(handle, 0), 'detach storage')
        check(usb.libusb_claim_interface(handle, 0), 'claim storage')
        claimed = True
        for _ in range(8):
            buffer, length = ct.create_string_buffer(512), ct.c_int()
            status = usb.libusb_bulk_transfer(handle, 0x8a, buffer, 512, ct.byref(length), 1000)
            if status == -7:  # Timeout with no packet: queue is empty, not device failure.
                if length.value:
                    raise RuntimeError('Partial packet while draining USB replies')
                return
            check(status, 'drain storage response')
            print('Drained stale storage reply:', length.value, 'bytes', flush=True)
        raise RuntimeError('USB reply queue exceeded eight packets')
    finally:
        if claimed:
            usb.libusb_release_interface(handle, 0)
        if handle:
            usb.libusb_close(handle)
        if devices:
            usb.libusb_free_device_list(devices, 1)
        usb.libusb_exit(context)


def switch_wifi(port, sysfs_root=Path('/sys/bus/usb/devices')):
    """Only the udev-selected storage-mode adapter may receive an EJECT packet."""
    if not re.fullmatch(r'\d+-\d+(?:\.\d+)*', port):
        raise ValueError('Invalid USB device path')
    device = sysfs_root / port
    if identity(device) == ('0bda', 'c812'):
        return
    if identity(device) != ('0bda', '1a2b'):
        raise RuntimeError('Expected adapter is absent')
    drain_storage_replies(device)
    bus = (device / 'busnum').read_text().strip()
    number = (device / 'devnum').read_text().strip()
    subprocess.run(['usb_modeswitch', '-M', EJECT_MESSAGE, '-v', '0bda', '-p', '1a2b',
                    '-b', bus, '-g', number], timeout=15)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if identity(device) == ('0bda', 'c812'):
            subprocess.run(['modprobe', 'rtw_8822cu'], check=True, timeout=3)
            print('RTL8822CU wireless mode ready on', port)
            return
        time.sleep(.2)
    raise RuntimeError('Adapter did not enter wireless mode; see USB logs')


if __name__ == '__main__':
    switch_wifi(sys.argv[1])
