#!/usr/bin/env python3
"""After checking the workspace, move only the base 1 degree and restore it.

Protocol: https://www.waveshare.com/wiki/RoArm-M2-S_Robotic_Arm_Control
Run on RK3588 to test PC -> Wi-Fi -> RK3588 -> arm -> wrist camera.
"""
import json
import math
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler
import cv2
import numpy as np

ARM = 'http://192.168.112.156/js'  # Current arm's local HTTP command interface.
CAMERA = 'http://127.0.0.1:8080/snapshot.jpg'
DELTA = math.radians(1)  # Fixed small displacement; requires a clear, empty gripper.
SPEED = 30  # Servo encoder steps/second, about 2.64 degrees/second; still only 1 degree.
HTTP = build_opener(ProxyHandler({}))


def command(payload):
    """Use direct LAN HTTP without inheriting the PC's HTTP proxy."""
    with HTTP.open(ARM + '?' + urlencode({'json': json.dumps(payload, separators=(',', ':'))}), timeout=4) as response:
        return response.read()


def feedback():
    """Read the controller's measured joint angles, in radians."""
    result = json.loads(command({'T': 105}))
    if result.get('T') != 1051:
        raise RuntimeError('Unexpected arm feedback')
    return result


def move(base):
    command({'T': 101, 'joint': 1, 'rad': base, 'spd': SPEED, 'acc': 1})


def settle(base, trace):
    """Save measured positions and wait up to eight seconds for the requested angle."""
    started = time.monotonic()
    deadline = started + 8
    while time.monotonic() < deadline:
        state = feedback()
        trace.append({'elapsed_s': round(time.monotonic() - started, 3), **state})
        if abs(state['b'] - base) < .003:
            time.sleep(.3)  # Allow the next camera frames to capture the settled pose.
            return state
        time.sleep(.15)
    raise RuntimeError('Base did not reach the requested angle')


def snapshot(directory, name):
    with HTTP.open(CAMERA, timeout=4) as response:
        data = response.read()
    (directory / (name + '.jpg')).write_bytes(data)
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError('Camera JPEG did not decode')
    return image


def displacement(before, after):
    """Track fixed scene features to distinguish camera motion from JPEG noise."""
    points = cv2.goodFeaturesToTrack(before, 100, .03, 10)
    if points is None:
        return {'tracked_points': 0, 'median_shift_px': None}
    moved, status, errors = cv2.calcOpticalFlowPyrLK(before, after, points, None)
    good = (status.ravel() == 1) & (errors.ravel() < 20)
    delta = moved[good].reshape(-1, 2) - points[good].reshape(-1, 2)
    return {'tracked_points': len(delta),
            'median_shift_px': float(np.median(np.linalg.norm(delta, axis=1))) if len(delta) else None}


directory = Path(sys.argv[1])
directory.mkdir(parents=True, exist_ok=True)
initial = feedback()
if abs(initial['b'] + DELTA) > 3:
    raise SystemExit('Current base position is too close to the rotation limit')
before = snapshot(directory, 'before')
report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'initial': initial,
          'goal_delta_deg': 1, 'speed_steps_per_second': SPEED,
          'offset_trace': [], 'return_trace': []}
try:
    move(initial['b'] + DELTA)
    report['offset'] = settle(initial['b'] + DELTA, report['offset_trace'])
    offset = snapshot(directory, 'offset')
    report['camera_move'] = displacement(before, offset)
except Exception as exc:
    report['error'] = str(exc)
finally:
    # Restore the measured starting angle even if the image comparison fails.
    move(initial['b'])
    report['restored'] = settle(initial['b'], report['return_trace'])
    returned = snapshot(directory, 'returned')
    report['camera_return'] = displacement(before, returned)
    report['other_joints_max_delta_rad'] = max(abs(report['restored'][key] - initial[key])
                                                for key in ('s', 'e', 't'))
    report['actual_delta_deg'] = math.degrees(report.get('offset', initial)['b'] - initial['b'])
    shift = report.get('camera_move', {}).get('median_shift_px')
    report['passed'] = ('error' not in report and abs(report['actual_delta_deg'] - 1) < .3 and
                        abs(report['restored']['b'] - initial['b']) < .003 and
                        report['other_joints_max_delta_rad'] < .01 and
                        shift is not None and shift > 1)
    (directory / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
if not report['passed']:
    raise SystemExit(1)
