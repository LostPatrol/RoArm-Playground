#!/usr/bin/env python3
"""Read-only integration checks from the PC or RK3588; never move the arm."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler


HTTP = build_opener(ProxyHandler({}))


def fetch(url, timeout=4):
    start = time.monotonic()
    with HTTP.open(url, timeout=timeout) as response:
        return response.read(), (time.monotonic() - start) * 1000


def robot_check(url, samples):
    output = {'url': url, 'passed': False, 'samples': samples}
    try:
        page, elapsed = fetch(url + '/')
        output['page'] = {'roarm_title': b'RoArm-M2' in page, 'latency_ms': round(elapsed, 1)}
        timings, failures, feedback = [], [], None
        endpoint = url + '/js?' + urlencode({'json': json.dumps({'T': 105})})
        for index in range(samples):
            try:
                data, elapsed = fetch(endpoint)
                feedback = json.loads(data)
                if feedback.get('T') != 1051 or not all(key in feedback for key in ('x', 'y', 'z', 'b', 's', 'e', 't')):
                    raise ValueError('Unexpected robot feedback format')
                timings.append(elapsed)
            except Exception as exc:
                failures.append({'sample': index + 1, 'error': str(exc)})
            if index + 1 < samples:
                time.sleep(.5)
        output.update(successful_reads=len(timings), failures=failures, feedback=feedback)
        if timings:
            output['latency_ms'] = {'median': round(statistics.median(timings), 1),
                                    'maximum': round(max(timings), 1)}
        output['passed'] = output['page']['roarm_title'] and len(timings) == samples
    except Exception as exc:
        output['error'] = str(exc)
    return output


def camera_check(url, duration, directory):
    output = {'url': url, 'passed': False}
    try:
        _, page_ms = fetch(url + '/')
        status_data, status_ms = fetch(url + '/status')
        status = json.loads(status_data)
        output.update(status=status, page_latency_ms=round(page_ms, 1), status_latency_ms=round(status_ms, 1))
        if not status.get('ready'):
            raise RuntimeError(status.get('error', 'Camera not ready'))
        jpeg, snapshot_ms = fetch(url + '/snapshot.jpg')
        if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise ValueError('Snapshot is not a complete JPEG')
        snapshot = directory / 'camera-snapshot.jpg'
        snapshot.write_bytes(jpeg)
        output['snapshot'] = {'path': str(snapshot.resolve()), 'bytes': len(jpeg), 'latency_ms': round(snapshot_ms, 1)}
        # Verify decoding if OpenCV is available; endpoints can still be checked without it.
        try:
            import cv2
            import numpy as np
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError('JPEG could not be decoded')
            output['snapshot']['decoded_size'] = [int(frame.shape[1]), int(frame.shape[0])]
        except ImportError:
            output['snapshot']['decode_check'] = 'OpenCV unavailable on test machine'
        started, total_bytes, frames = time.monotonic(), 0, 0
        arrivals, hashes, buffer = [], set(), b''
        with HTTP.open(url + '/stream.mjpg', timeout=6) as response:
            if 'multipart/x-mixed-replace' not in response.headers.get('Content-Type', ''):
                raise ValueError('Unexpected MJPEG content type')
            while time.monotonic() - started < duration:
                chunk = response.read1(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                buffer += chunk
                while True:
                    start = buffer.find(b'\xff\xd8')
                    end = buffer.find(b'\xff\xd9', start + 2) if start >= 0 else -1
                    if end < 0:
                        break
                    frame = buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                    frames += 1
                    arrivals.append(time.monotonic())
                    hashes.add(hashlib.sha256(frame).digest())
                if len(buffer) > 8 * 1024 * 1024:
                    raise ValueError('No complete frame within 8 MiB')
        elapsed = time.monotonic() - started
        gaps = [right - left for left, right in zip(arrivals, arrivals[1:])]
        output['stream'] = {'seconds': round(elapsed, 2), 'frames': frames,
                            'fps_received': round(frames / max(elapsed, .01), 2),
                            'unique_frames': len(hashes), 'bytes': total_bytes,
                            'mbps': round(total_bytes * 8 / max(elapsed, .01) / 1e6, 2),
                            'max_frame_gap_ms': round(max(gaps, default=0) * 1000, 1)}
        output['passed'] = elapsed >= duration and frames >= 2 and max(gaps, default=0) < 5
    except Exception as exc:
        output['error'] = str(exc)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--robot', default='http://192.168.112.156')
    parser.add_argument('--camera', default='http://192.168.112.122:8080')
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--output', type=Path, default=Path('system-test'))
    args = parser.parse_args()
    if args.samples < 1 or args.seconds < 1:
        parser.error('samples and seconds must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        robot = pool.submit(robot_check, args.robot.rstrip('/'), args.samples)
        camera = pool.submit(camera_check, args.camera.rstrip('/'), args.seconds, args.output)
        report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'motion_commands_sent': False,
                  'robot': robot.result(), 'camera': camera.result()}
    report['passed'] = report['robot']['passed'] and report['camera']['passed']
    (args.output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
