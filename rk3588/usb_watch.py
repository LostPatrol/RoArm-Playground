#!/usr/bin/env python3
"""Persist a short USB/network trace across a cable swap or unexpected reboot."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def sample():
    return {'utc': datetime.now(timezone.utc).isoformat(), 'uptime': read('/proc/uptime'),
            'boot_id': read('/proc/sys/kernel/random/boot_id'),
            'typec': {key: read('/sys/class/typec/port0/' + key) for key in
                      ('data_role', 'power_role', 'preferred_role', 'port_type')},
            'controller': read('/sys/kernel/debug/usb/fc000000.usb/mode'),
            'usb': [{'port': p.name, 'vendor': read(p / 'idVendor'), 'product': read(p / 'idProduct'),
                     'name': read(p / 'product')} for p in Path('/sys/bus/usb/devices').iterdir()
                    if (p / 'idVendor').exists() and '-' in p.name],
            'network': {p.name: {'state': read(p / 'operstate'), 'carrier': read(p / 'carrier')}
                        for p in Path('/sys/class/net').iterdir()},
            'typec_vbus': read('/sys/class/regulator/regulator.5/state')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--output', type=Path, default=Path('/var/log/roarm-usb-watch.jsonl'))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Explicitly flush each record, so a cable-induced reset does not erase the evidence.
    with args.output.open('a') as stream:
        for _ in range(max(1, args.seconds)):
            stream.write(json.dumps(sample(), ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            time.sleep(1)


if __name__ == '__main__':
    main()
