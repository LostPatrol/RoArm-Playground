#!/usr/bin/env python3
"""Keep this adapter's virtual CD-ROM away from the storage driver."""
from pathlib import Path


quirks_path = Path('/sys/module/usb_storage/parameters/quirks')
if quirks_path.exists():
    original = [entry for entry in quirks_path.read_text().strip().split(',') if entry]
    entries = list(original)
    entries = [entry for entry in entries if not entry.lower().startswith('0bda:1a2b:')]
    # Preserve existing flags for this device, as well as all other devices.
    flags = ''.join(entry.split(':', 2)[2] for entry in original
                    if entry.lower().startswith('0bda:1a2b:'))
    entries.append('0bda:1a2b:' + ''.join(dict.fromkeys(flags + 'i')))
    quirks_path.write_text(','.join(entries) + '\n')

# Do not unbind a kernel driver in this early boot service. Unbinding can wait
# for storage I/O indefinitely and would hold up udev's coldplug processing.
# usb_modeswitch owns detaching storage interfaces after udev has started.
