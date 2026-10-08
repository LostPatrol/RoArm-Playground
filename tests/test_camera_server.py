"""Local mock tests only: no commands are sent to the physical arm or camera."""

import importlib.util
import json
import threading
import time
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('camera_server', ROOT / 'rk3588/camera_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MockArm(BaseHTTPRequestHandler):
    """Record mock requests and return native-like pages and feedback."""

    calls = []
    entered = threading.Event()
    release = threading.Event()

    def do_GET(self):
        self.calls.append(self.path)
        path = urlsplit(self.path).path
        if path == '/js':
            command = json.loads(parse_qs(urlsplit(self.path).query)['json'][0])
            if command.get('hold'):
                self.entered.set()
                self.release.wait(2)
            body = json.dumps({'b': 0, 's': 0, 'e': 0, 't': 0, 'x': 0, 'y': 0, 'z': 0}).encode()
            content_type = 'application/json'
        else:
            body = b'<html><head></head><body><a href="/horiDrag">Drag</a><script>location.href="/"</script></body></html>'
            content_type = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class CameraStub:
    """Keep preview HTTP tests independent of USB hardware."""

    def status(self):
        return {'ready': False, 'error': 'mock disconnected', 'device': None}


class IntegrationTests(unittest.TestCase):
    def test_usb_discovery_after_hub_port_and_node_change(self):
        # Different USB path and video index must not pin capture to video40.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            nodes = root / 'video4linux'
            nodes.mkdir()
            usb = root / 'devices' / '2-1.4'
            usb.mkdir(parents=True)
            (usb / 'idVendor').write_text('1bcf')
            interface = usb / '2-1.4:1.0'
            interface.mkdir()
            for name in ('video99', 'video100'):
                node = nodes / name
                node.mkdir()
                (node / 'device').symlink_to(interface)
            isp = root / 'isp'
            isp.mkdir()
            node = nodes / 'video0'
            node.mkdir()
            (node / 'device').symlink_to(isp)
            with patch.object(module, 'Path', return_value=nodes):
                self.assertEqual(module.usb_cameras(), ['/dev/video99', '/dev/video100'])

    @classmethod
    def setUpClass(cls):
        cls.mock = ThreadingHTTPServer(('127.0.0.1', 0), MockArm)
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        cls.proxy = module.ArmProxy(f'http://127.0.0.1:{cls.mock.server_port}')
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        cls.http.camera, cls.http.arm = CameraStub(), cls.proxy
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.origin = f'http://127.0.0.1:{cls.http.server_port}'
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.mock.shutdown()
        cls.http.server_close()
        cls.mock.server_close()

    def request(self, path):
        try:
            with self.opener.open(self.origin + path) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()

    def test_native_routes_and_combined_page(self):
        status, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'src="/arm/"', body)
        self.assertIn(b'/stream.mjpg', body)
        self.assertEqual(self.request('/arm-adapter.js')[0], 200)
        for page in ('/arm/', '/arm/horiDrag', '/arm/vertDrag'):
            status, body = self.request(page)
            self.assertEqual(status, 200)
            self.assertIn(b'<base href="/arm/">', body)
            self.assertIn(b'href="/arm/horiDrag"', body)
            self.assertIn(b'location.href="/arm/"', body)
            self.assertIn(b'/arm-adapter.js', body)
        self.assertEqual(json.loads(self.request('/status')[1])['ready'], False)

    def test_prohibited_entries_do_not_reach_mock(self):
        for command in (600, 601, 603, 604):
            before = len(MockArm.calls)
            self.assertEqual(self.request('/arm/js?' + urlencode({'json': json.dumps({'T': command})}))[0], 403)
            self.assertEqual(len(MockArm.calls), before)
        before = len(MockArm.calls)
        self.assertEqual(self.request('/arm/getDevInfo')[0], 403)
        self.assertEqual(self.request('/arm/http://example.com')[0], 404)
        self.assertEqual(len(MockArm.calls), before)

    def test_parameters_and_special_characters(self):
        command = {'T': 202, 'name': 'a&b#c+d 空格.txt'}
        status, _ = self.request('/arm/js?' + urlencode({'json': json.dumps(command)}))
        self.assertEqual(status, 200)
        forwarded = json.loads(parse_qs(urlsplit(MockArm.calls[-1]).query)['json'][0])
        self.assertEqual(forwarded, command)
        for query in ('json=invalid', 'json=[]', 'json=%7B%22T%22%3A%22600%22%7D', 'json=%7B%22T%22%3A105%7D&target=http://example.com'):
            self.assertEqual(self.request('/arm/js?' + query)[0], 400)

    def test_start_finishes_before_stop_is_forwarded(self):
        query = lambda cmd: urlencode({'json': json.dumps(cmd)})
        MockArm.entered.clear()
        MockArm.release.clear()
        start = threading.Thread(target=self.proxy.get, args=('/js', query({'T':123, 'm':0, 'axis':1, 'cmd':1, 'hold':True})))
        start.start()
        self.assertTrue(MockArm.entered.wait(1))
        before = len(MockArm.calls)
        stop = threading.Thread(target=self.proxy.get, args=('/js', query({'T':123, 'm':0, 'axis':1, 'cmd':0})))
        stop.start()
        time.sleep(.05)
        self.assertEqual(len(MockArm.calls), before)
        MockArm.release.set()
        start.join(2)
        stop.join(2)
        self.assertEqual(json.loads(parse_qs(urlsplit(MockArm.calls[-1]).query)['json'][0])['cmd'], 0)

    def test_unreachable_arm_reports_failure(self):
        proxy = module.ArmProxy('http://127.0.0.1:1')
        self.assertEqual(proxy.get('/', '')[0], 502)

    def test_exit_stop_rejects_a_late_start(self):
        command = {'T':123, 'axis':1, 'm':0, 'cmd':0, '_ui_client':'test-exit', '_ui_sequence':2}
        self.assertEqual(self.request('/arm/js?' + urlencode({'json': json.dumps(command)}))[0], 200)
        forwarded = json.loads(parse_qs(urlsplit(MockArm.calls[-1]).query)['json'][0])
        self.assertNotIn('_ui_client', forwarded)
        before = len(MockArm.calls)
        command.update(cmd=1, _ui_sequence=1)
        self.assertEqual(self.request('/arm/js?' + urlencode({'json': json.dumps(command)}))[0], 409)
        self.assertEqual(len(MockArm.calls), before)
        command.update(axis=2, cmd=0, _ui_sequence=1)
        self.assertEqual(self.request('/arm/js?' + urlencode({'json': json.dumps(command)}))[0], 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
