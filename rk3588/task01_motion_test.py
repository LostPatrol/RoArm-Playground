#!/usr/bin/env python3
"""Task01: measure one joint move and return; save commands, feedback and images.

Run explicitly after checking clearance. Never changes torque, PID, BOOT or Wi-Fi.
"""
import argparse
import json
import math
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

HTTP = build_opener(ProxyHandler({}))  # LAN must bypass the workstation proxy.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', default='http://192.168.112.156')
    parser.add_argument('--camera', default='http://192.168.112.122:8080')
    parser.add_argument('--delta-deg', type=float, default=10)
    parser.add_argument('--joint', type=int, choices=[1, 2, 3, 4], default=1)
    parser.add_argument('--mode', choices=['absolute', 'jog'], default='absolute')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= abs(args.delta_deg) <= 15:
        parser.error('This test supports only a 1–15 degree joint offset')
    args.output.mkdir(parents=True, exist_ok=True)
    key = ('b', 's', 'e', 't')[args.joint - 1]
    report = dict(mode=args.mode, joint=args.joint, requested_delta_deg=args.delta_deg, events=[])

    def record(event):
        report['events'].append(dict(time=time.time(), **event))
        (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')

    def command(payload):
        record(dict(command=payload))
        with HTTP.open(args.arm + '/js?' + urlencode({'json': json.dumps(payload)}), timeout=3) as response:
            return response.read()

    def feedback():
        state = json.loads(command({'T': 105}))
        if state.get('T') != 1051:
            raise RuntimeError('Invalid measured feedback')
        record(dict(feedback=state))
        return state

    def snapshot(name):
        with HTTP.open(args.camera + '/snapshot.jpg', timeout=3) as response:
            (args.output / (name + '.jpg')).write_bytes(response.read())

    def move(angle):
        command({'T': 101, 'joint': args.joint, 'rad': angle, 'spd': 100, 'acc': 5})

    initial = feedback()
    target = initial[key] + math.radians(args.delta_deg)
    # Interior joint limits leave margin from firmware's hard angle limits.
    low, high = ((-160, 160), (-80, 80), (-35, 170), (100, 300))[args.joint - 1]
    if not math.radians(low) < target < math.radians(high):
        raise RuntimeError('Too close to joint range limit')
    report['initial'] = initial
    snapshot('before')
    states = []
    try:
        if args.mode == 'absolute':
            move(target)
        else:
            command({'T': 123, 'm': 0, 'axis': args.joint, 'cmd': 1 if args.delta_deg > 0 else 2, 'spd': 3})
        # Jog is limited to 0.8s independently of goal, absolute move to 4s.
        deadline = time.monotonic() + (0.8 if args.mode == 'jog' else 4)
        while time.monotonic() < deadline:
            state = feedback()
            states.append(state)
            if abs(state[('torB', 'torS', 'torE', 'torH')[args.joint - 1]]) > 200:
                raise RuntimeError('Unexpected joint load; stop further testing')
            if abs(state[key] - initial[key]) > math.radians(15):
                raise RuntimeError('Unexpected joint travel; stop further testing')
            if abs(state[key] - target) < math.radians(.5):
                break
            time.sleep(.1)
        command({'T': 123, 'm': 0, 'axis': args.joint, 'cmd': 0, 'spd': 0})
        time.sleep(.4)
        report['offset'] = feedback()
        snapshot('offset')
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        # Stop the exact axis first; axis=0 does not stop this firmware's jog.
        command({'T': 123, 'm': 0, 'axis': args.joint, 'cmd': 0, 'spd': 0})
        move(initial[key])
        time.sleep(2)
        report['returned'] = feedback()
        snapshot('returned')
        report['max_measured_delta_deg'] = max((abs(math.degrees(s[key] - initial[key])) for s in states), default=0)
        report['actual_offset_deg'] = math.degrees(report.get('offset', initial)[key] - initial[key])
        report['return_error_deg'] = math.degrees(report['returned'][key] - initial[key])
        report['other_joint_max_delta_deg'] = max(abs(math.degrees(s[other] - initial[other]))
                                                  for s in states + [report['returned']] for other in ('b', 's', 'e', 't') if other != key)
        report['movement_verified'] = report['max_measured_delta_deg'] > .5
        report['goal_error_deg'] = report['actual_offset_deg'] - args.delta_deg
        report['passed'] = ('error' not in report and report['movement_verified']
                            and abs(report['return_error_deg']) < .5
                            and (args.mode == 'jog' or abs(report['goal_error_deg']) < .5))
        record(dict(finished=True))
    print(json.dumps({k: v for k, v in report.items() if k != 'events'}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
