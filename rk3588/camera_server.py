#!/usr/bin/env python3
"""USB video and same-origin playground API; demo control uses the USB serial link."""

import argparse
import json
import logging
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener

import cv2


ASSETS = Path(__file__).resolve().parent
# A source checkout stores laptop modules beside rk3588; deployment keeps them here.
sys.path.insert(0, str(ASSETS.parent))
# Native firmware serves these pages and endpoints, with no external resources.
ARM_PATHS = {'/', '/horiDrag', '/vertDrag', '/js', '/getDevInfo'}
# Never expose reboot, flash/NVS reset or boot mission reset through this UI.
BLOCKED_COMMANDS = {600, 601, 603, 604}
ARM_TIMEOUT = 3  # Seconds; the browser timeout is longer than this proxy deadline.


class ArmProxy:
    """Forward only known native routes to one configured arm, without LAN proxies."""

    def __init__(self, url):
        self.url = url.rstrip('/')
        self.opener = build_opener(ProxyHandler({}))
        self.command_lock = threading.Lock()
        self.motion_sequences = {}

    def get(self, path, query):
        if path not in ARM_PATHS:
            return 404, 'text/plain; charset=utf-8', '机械臂接口不存在'.encode()
        if path == '/getDevInfo':
            # Reserved legacy BOOT entry: do not forward an unverified action.
            return 403, 'text/plain; charset=utf-8', 'BOOT 入口已禁用；请使用反馈读取设备状态'.encode()
        if path == '/js':
            # Re-encode JSON as one argument: &, # and + inside user text must survive.
            params = parse_qs(query, keep_blank_values=True)
            try:
                if set(params) != {'json'} or len(params['json']) != 1:
                    raise ValueError('需要一个 json 参数')
                command = json.loads(params['json'][0])
                if not isinstance(command, dict) or type(command.get('T')) is not int:
                    raise ValueError('JSON 指令需要整数 T')
                if command['T'] in BLOCKED_COMMANDS:
                    return 403, 'text/plain; charset=utf-8', '已禁用 BOOT、重启及重置指令'.encode()
                client = command.pop('_ui_client', None)
                sequence = command.pop('_ui_sequence', None)
                if client is not None and (not isinstance(client, str) or len(client) > 80 or
                                           type(sequence) is not int or sequence < 0):
                    raise ValueError('运动请求序号错误')
                if client is not None and command['T'] == 123 and type(command.get('axis')) is not int:
                    raise ValueError('持续运动指令需要整数 axis')
            except (ValueError, KeyError) as exc:
                return 400, 'text/plain; charset=utf-8', str(exc).encode()
            query = urlencode({'json': json.dumps(command, ensure_ascii=False, separators=(',', ':'))})
        elif query:
            return 400, 'text/plain; charset=utf-8', '此接口不接受参数'.encode()
        url = self.url + path + ('?' + query if query else '')
        try:
            # One complete command/feedback transaction at a time; the UI also queues
            # requests so a released key cannot overtake its preceding start command.
            if path == '/js':
                with self.command_lock:
                    if command['T'] == 123 and client is not None:
                        # Exit keepalive can arrive before its pending start. Per-axis
                        # sequence numbers ensure that late starts cannot resume motion.
                        key = (client, command.get('axis'))
                        previous = self.motion_sequences.get(key, (-1, 0))
                        if sequence <= previous[0]:
                            return 409, 'text/plain; charset=utf-8', '忽略已过期的持续运动请求'.encode()
                        self.motion_sequences[key] = (sequence, time.monotonic())
                        if len(self.motion_sequences) > 128:
                            cutoff = time.monotonic() - 3600
                            self.motion_sequences = {key: value for key, value in self.motion_sequences.items()
                                                     if value[1] >= cutoff}
                    return self.fetch(url)
            return self.fetch(url)
        except (URLError, TimeoutError, OSError) as exc:
            logging.warning('Arm unavailable: %s', exc)
            return 502, 'text/plain; charset=utf-8', '机械臂连接失败或超时，请检查机械臂网络'.encode()

    def fetch(self, url):
        try:
            with self.opener.open(url, timeout=ARM_TIMEOUT) as response:
                body = response.read()
                content_type = response.headers.get('Content-Type', 'text/plain')
                if 'text/html' in content_type:
                    body = self.adapt_page(body.decode('utf-8')).encode('utf-8')
                    content_type = 'text/html; charset=utf-8'
                return response.status, content_type, body
        except HTTPError as exc:
            return exc.code, 'text/plain; charset=utf-8', f'机械臂返回 HTTP {exc.code}'.encode()

    @staticmethod
    def adapt_page(page):
        """Keep the live native page, correcting its root links and adding release handling."""
        page = re.sub(r'([\"\'])/(horiDrag|vertDrag)([\"\'])', r'\1/arm/\2\3', page)
        page = re.sub(r'([\"\'])/([\"\'])', r'\1/arm/\2', page)
        page = page.replace('<head>', '<head><base href="/arm/">', 1)
        adapter = '<script src="/arm-adapter.js"></script>'
        return page.replace('</body>', adapter + '</body>') if '</body>' in page else page + adapter


def usb_cameras():
    """Ignore the RK3588's many built-in ISP/codec video nodes."""
    nodes = []
    for node in Path('/sys/class/video4linux').glob('video*'):
        device = (node / 'device').resolve()
        if any((parent / 'idVendor').exists() for parent in device.parents):
            nodes.append('/dev/' + node.name)
    return sorted(nodes, key=lambda name: int(name[len('/dev/video'):]))


class Camera:
    def __init__(self, args):
        self.args = args
        self.condition = threading.Condition()
        self.frame = None
        self.sequence = 0
        self.updated = 0
        self.details = dict(device=None, width=0, height=0, fps=0,
                            error='未识别到 USB 摄像头，请接到小主机的 USB 主机口')
        threading.Thread(target=self.capture, daemon=True).start()

    def status(self):
        with self.condition:
            return dict(self.details, ready=self.frame is not None and
                        time.monotonic() - self.updated < 5)

    def unavailable(self, message):
        with self.condition:
            self.frame = None
            self.details['error'] = message
            self.condition.notify_all()

    def capture(self):
        while True:
            devices = [self.args.device] if self.args.device else usb_cameras()
            if not devices:
                self.unavailable('未识别到 USB 摄像头，请接到小主机的 USB 主机口')
                time.sleep(2)
                continue
            for device in devices:
                cap = None
                try:
                    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
                    if not cap.isOpened():
                        continue
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.height)
                    cap.set(cv2.CAP_PROP_FPS, self.args.fps)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    logging.info('Opened %s', device)
                    started, count = time.monotonic(), 0
                    while True:
                        tick = time.monotonic()
                        ok, image = cap.read()
                        if not ok:
                            raise RuntimeError('摄像头读取失败或已拔出')
                        ok, jpeg = cv2.imencode('.jpg', image,
                                               [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if not ok:
                            raise RuntimeError('图像编码失败')
                        count += 1
                        with self.condition:
                            self.frame = jpeg.tobytes()
                            self.sequence += 1
                            self.updated = time.monotonic()
                            self.details = dict(device=device, width=image.shape[1],
                                                height=image.shape[0], error='',
                                                fps=round(count / max(.01, self.updated - started), 1))
                            self.condition.notify_all()
                        time.sleep(max(0, 1 / self.args.fps - (time.monotonic() - tick)))
                except Exception as exc:
                    logging.warning('%s: %s', device, exc)
                    self.unavailable(str(exc))
                finally:
                    if cap is not None:
                        cap.release()
            self.unavailable('USB 摄像头暂时无法采集，正在重试')
            time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, content_type, body):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == '/':
                self.respond(200, 'text/html; charset=utf-8', (ASSETS / 'control.html').read_bytes())
            elif path in ('/playground.js', '/playground.css'):
                kind = 'text/javascript' if path.endswith('.js') else 'text/css'
                self.respond(200, kind + '; charset=utf-8', (ASSETS / path[1:]).read_bytes())
            elif path == '/api/state':
                self.respond(200, 'application/json; charset=utf-8',
                             json.dumps(self.server.playground.state(), ensure_ascii=False).encode())
            elif path.startswith('/artifacts/'):
                name = path[len('/artifacts/'):]
                if Path(name).name != name or not name.endswith('.jpg'):
                    self.respond(404, 'text/plain', b'Not found')
                else:
                    file = self.server.playground.artifacts / name
                    self.respond(200 if file.is_file() else 404, 'image/jpeg',
                                 file.read_bytes() if file.is_file() else b'Not found')
            elif path.startswith('/manuals/'):
                relative = Path(path[len('/manuals/'):])
                manual_root = ASSETS / 'docs' / 'playground'
                if not manual_root.is_dir():
                    manual_root = ASSETS.parent / 'docs' / 'playground'
                file = manual_root / relative
                if '..' in relative.parts or not relative.name.endswith('.md') or not file.is_file():
                    self.respond(404, 'text/plain', b'Not found')
                else:
                    self.respond(200, 'text/plain; charset=utf-8', file.read_bytes())
            elif path == '/arm-adapter.js':
                self.respond(200, 'text/javascript; charset=utf-8', (ASSETS / 'arm_adapter.js').read_bytes())
            elif path == '/arm':
                self.send_response(302)
                self.send_header('Location', '/arm/')
                self.send_header('Content-Length', '0')
                self.end_headers()
            elif path.startswith('/arm/'):
                if self.server.arm is None:
                    self.respond(410, 'text/plain; charset=utf-8',
                                 '已迁移至串口 Playground，请使用首页'.encode())
                else:
                    self.respond(*self.server.arm.get(path[4:], urlsplit(self.path).query))
            elif path in ('/status', '/health'):
                self.respond(200, 'application/json; charset=utf-8',
                             json.dumps(self.server.camera.status(), ensure_ascii=False).encode())
            elif path in ('/snapshot.jpg', '/stream.mjpg'):
                camera = self.server.camera
                with camera.condition:
                    frame = camera.frame if camera.status()['ready'] else None
                if frame is None:
                    self.respond(503, 'text/plain; charset=utf-8', '摄像头尚未就绪'.encode())
                elif path == '/snapshot.jpg':
                    self.respond(200, 'image/jpeg', frame)
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.connection.settimeout(10)
                    sequence = -1
                    while True:
                        with camera.condition:
                            camera.condition.wait_for(
                                lambda: camera.sequence != sequence or camera.frame is None, timeout=5)
                            if not camera.status()['ready'] or camera.sequence == sequence:
                                break
                            frame, sequence = camera.frame, camera.sequence
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                         str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
                        self.wfile.flush()
            else:
                self.respond(404, 'text/plain', b'Not found')
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('JSON 请求大小应在 1..65536 字节')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('请求应为 JSON 对象')
            if path == '/api/action':
                result = self.server.playground.handle_action(data)
            elif path == '/api/perception':
                result = self.server.playground.perception(data)
            else:
                self.respond(404, 'application/json', b'{"ok":false,"error":"Unknown API"}')
                return
            body = dict(ok=True, result=result)
            status = 200
        except (ValueError, TypeError, KeyError) as exc:
            status, body = 400, dict(ok=False, error=str(exc))
        except Exception as exc:
            logging.exception('Playground action failed')
            status, body = 503, dict(ok=False, error=str(exc))
        try:
            self.respond(status, 'application/json; charset=utf-8',
                         json.dumps(body, ensure_ascii=False).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        if not self.path.startswith(('/status', '/health')):
            logging.info(fmt, *args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--device', help='Optional fixed /dev/videoN path; default: discover USB cameras')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--fps', type=int, default=15)
    parser.add_argument('--serial-device', help='ESP32 /dev/serial/by-id path; discover one CP2102N by default')
    parser.add_argument('--data-dir', default=str(ASSETS / 'playground-data'))
    parser.add_argument('--model-dir', default=str(ASSETS / 'models'))
    parser.add_argument('--director-url', default='', help='Local laptop OpenAI-compatible LLM /v1 URL')
    parser.add_argument('--director-model', default='qwen2.5-1.5b-instruct')
    parser.add_argument('--audio-device', default='hw:CARD=UQ212,DEV=0')
    parser.add_argument('--arm-url', default='http://192.168.112.156',
                        help='Configured arm HTTP origin; only known native routes are proxied')
    args = parser.parse_args()
    if min(args.width, args.height, args.fps) <= 0:
        parser.error('width, height and fps must be positive')
    arm_url = urlsplit(args.arm_url)
    if (arm_url.scheme not in ('http', 'https') or not arm_url.hostname or
            arm_url.path not in ('', '/') or arm_url.query or arm_url.fragment or
            arm_url.username or arm_url.password):
        parser.error('arm-url must be an HTTP(S) origin without credentials or a path')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.camera = Camera(args)
    from arm_serial import ArmController, SerialTransport
    from playground import Playground
    controller = ArmController(SerialTransport(args.serial_device))
    server.arm = None  # Runtime commands no longer traverse ESP32 Wi-Fi.
    server.playground = Playground(server.camera, controller, args.data_dir, args.model_dir,
                                   args.director_url, args.director_model,
                                   local_server='http://127.0.0.1:%s' % args.port,
                                   audio_device=args.audio_device)
    logging.info('Camera service listening on %s:%s', args.host, args.port)
    # systemd termination cancels the mode and holds the measured pose before exit.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    try:
        server.serve_forever()
    finally:
        try:
            server.playground.stop()
        finally:
            controller.close()


if __name__ == '__main__':
    main()
