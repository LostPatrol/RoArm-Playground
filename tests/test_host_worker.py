"""Interaction mode isolation, genuine model response parsing, and plan bounds."""
import array
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# Support both `python -m unittest ...` and `python tests/test_host_worker.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from host.director import compile_model_plan, plan, validate_plan
from host.worker import ClapDetector, Client, GestureLatch, audio_chunks, mono_pcm, pcm_levels, run_audio, speech_result
from host.manager import Manager


class InteractionsTest(unittest.TestCase):
    def setUp(self):
        self.mode, self.posts = "manual", []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"mode": owner.mode}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.posts.append((self.path, body))
                self.send_response(200)
                self.end_headers()
                if self.path.endswith("/chat/completions"):
                    content = json.dumps({"steps": [{"type": "led", "value": 200}],
                                          "explanation": "test response"})
                    self.wfile.write(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
                else:
                    self.wfile.write(b'{}')

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_inactive_and_changed_modes_never_send(self):
        client = Client(self.url)
        self.assertFalse(client.emit({"action": "clap"}, "clap"))
        self.mode = "gesture"
        self.assertEqual(client.mode(), "gesture")
        self.mode = "voice"
        self.assertFalse(client.emit({"action": "gesture", "gesture": "open"}, "gestures"))
        self.assertEqual(self.posts, [])
        self.assertTrue(client.emit({"action": "speech", "text": "灯亮"}, "speech"))
        self.assertEqual(len(self.posts), 1)

    def test_dry_run_has_no_network_write(self):
        self.assertTrue(Client(self.url, True).emit({"action": "clap"}, "clap"))
        self.assertEqual(self.posts, [])

    def test_gesture_stability_release_and_mode_change(self):
        latch = GestureLatch()
        self.assertFalse(latch.update("open", 0.9, "gesture", 0))
        self.assertFalse(latch.update("open", 0.9, "gesture", .1))
        self.assertTrue(latch.update("open", 0.9, "gesture", .2))
        self.assertFalse(latch.update("open", 0.9, "gesture", 10))
        latch.update(None, 0, "gesture", 11)
        for now in (12, 12.1):
            self.assertFalse(latch.update("open", 0.9, "gesture", now))
        self.assertTrue(latch.update("open", 0.9, "gesture", 12.2))
        self.assertFalse(latch.update("fist", 0.6, "rps", 20))

    def test_stereo_downmix_and_clap_edges(self):
        pcm = array.array("h", [1000, -1000, 2000, 0]).tobytes()
        self.assertEqual(list(array.array("h", mono_pcm(pcm, 2))), [0, 1000])
        detector = ClapDetector()
        quiet = array.array("h", [0] * 1600).tobytes()
        loud = array.array("h", [10000] * 1600).tobytes()
        self.assertFalse(detector.update(quiet, 0)[0])
        self.assertTrue(detector.update(loud, 1)[0])
        self.assertFalse(detector.update(loud, 2)[0])
        detector.update(quiet, 3)
        self.assertTrue(detector.update(loud, 4)[0])

    def test_microphone_startup_discard_and_recorder_cleanup(self):
        startup = array.array("h", [32767] * 1600).tobytes()
        normal = array.array("h", [100] * 1600).tobytes()
        process = Mock(stdout=io.BytesIO(startup + normal))
        args = SimpleNamespace(wav=None, audio_device="default", channels=1, audio_warmup=.1)
        with patch("host.worker.subprocess.Popen", return_value=process):
            stream = audio_chunks(args)
            self.assertEqual(next(stream), normal)
            stream.close()
        process.terminate.assert_called_once()

    def test_audio_heartbeat_does_not_activate_motion(self):
        args = SimpleNamespace(mode="clap", clap_threshold=.1, wav=None,
                               audio_device="default", channels=2, audio_warmup=.5)
        quiet = array.array("h", [0] * 1600).tobytes()
        with patch("host.worker.audio_chunks", return_value=[quiet]):
            run_audio(args, Client(self.url))
        self.assertEqual([path for path, _ in self.posts], ["/api/perception"])
        self.assertEqual(self.posts[0][1]["kind"], "clap")
        self.assertEqual(self.posts[0][1]["worker_status"], "running")
        self.assertEqual(self.posts[0][1]["clipped_fraction"], 0)

    def test_command_grammar_rejects_unknown_and_uncertain_decoder_results(self):
        self.mode = "voice"
        client = Client(self.url)
        for text, confidence in (("向 左", .5), ("[unk]向 左", .9), ("爪", .99)):
            speech_result({"text": text, "result": [{"conf": confidence}]}, client, True)
        self.assertTrue(all(path == "/api/perception" for path, _ in self.posts))
        self.assertTrue(all(not body["accepted"] for _, body in self.posts))
        speech_result({"text": "向 左", "result": [{"conf": .9}]}, client, True)
        self.assertEqual(self.posts[-1], ("/api/action", {"action": "speech", "text": "向左"}))

    def test_pcm_level_diagnostic_exposes_clipping(self):
        levels = pcm_levels(array.array("h", [32767, -32768, 0, 0]).tobytes())
        self.assertEqual(levels["clipped_fraction"], .5)
        self.assertAlmostEqual(levels["audio_rms"], 2**-.5, places=4)

    def test_manager_does_not_fake_missing_model_or_spawn_unknown_worker(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=str(root / "agent/codex")) as directory:
            manager = Manager(self.url, directory)
            with patch("host.manager.ROOT", Path(directory)), patch("host.manager.subprocess.Popen") as launch:
                with self.assertRaises(ValueError):
                    manager.start("unknown")
                with self.assertRaises(RuntimeError):
                    manager.start("gestures")
                launch.assert_not_called()

    def test_manager_tracks_actual_model_readiness_and_keeps_one_process(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=str(root / "agent/codex")) as directory:
            manager = Manager(self.url, directory)
            process = Mock(pid=123)
            process.poll.return_value = None
            with patch.object(manager, "requirements", return_value={"model_exists": True, "missing_dependencies": []}), \
                 patch.object(manager, "director_ready", return_value=False), \
                 patch("host.manager.subprocess.Popen", return_value=process) as launch:
                result = manager.start("gestures", self.url)
                self.assertEqual(result["workers"]["gestures"]["status"], "loading")
                manager.logs["gestures"].write_text('{"worker_status": "ready"}\n')
                result = manager.start("gestures", self.url)
                self.assertTrue(result["workers"]["gestures"]["ready"])
                launch.assert_called_once()
                manager.close()
                process.terminate.assert_called_once()

    def test_manager_restarts_failed_worker_with_the_same_rk_endpoint(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=str(root / "agent/codex")) as directory:
            manager = Manager(self.url, directory)
            old, new = Mock(pid=1), Mock(pid=2)
            old.poll.return_value = 1
            new.poll.return_value = None
            manager.processes["gestures"] = old
            manager.desired.add("gestures")
            manager.last_launch["gestures"] = 0
            stop = Mock()
            stop.wait.side_effect = [False, True]
            with patch.object(manager, "requirements", return_value={"model_exists": True, "missing_dependencies": []}), \
                 patch.object(manager, "director_ready", return_value=False), \
                 patch("host.manager.time.monotonic", return_value=10), \
                 patch("host.manager.subprocess.Popen", return_value=new) as launch:
                manager.supervise(stop)
                self.assertIs(manager.processes["gestures"], new)
                self.assertIn(self.url, launch.call_args.args[0])
                self.assertFalse(manager.status()["workers"]["gestures"]["ready"])
                manager.close()

    def test_real_api_path_schema_and_preview_only(self):
        output = plan("灯亮", self.url, "model-test")
        self.assertEqual(output["steps"], [{"type": "led", "value": 200}])
        self.assertEqual([p for p, _ in self.posts], ["/v1/chat/completions"])
        self.assertIn("schema", self.posts[0][1]["response_format"])

    def test_reject_unbounded_or_invented_model_actions(self):
        for step in ({"type": "joint", "joint": "base", "delta": 21},
                     {"type": "wait", "seconds": math.nan},
                     {"type": "led", "value": True},
                     {"type": "greet", "execute": True},
                     {"type": "grab", "target": "foam"}):
            with self.subTest(step=step), self.assertRaises(ValueError):
                validate_plan({"steps": [step], "explanation": "invalid"})
        with self.assertRaises(ValueError):
            validate_plan({"steps": [{"type": "greet"}] * 13, "explanation": "too long"})

    def test_model_directions_bind_to_physical_arm_convention(self):
        steps = [{"type": "joint", "direction": direction, "degrees": 10}
                 for joint, direction in [("base", "left"), ("base", "right"),
                                          ("gripper", "open"), ("gripper", "close"),
                                          ("elbow", "up"), ("elbow", "down")]]
        output = compile_model_plan({"steps": steps, "explanation": "semantic model output"})
        self.assertEqual([s["delta"] for s in output["steps"]], [10, -10, -10, 10, -10, 10])
        with self.assertRaises(ValueError):
            compile_model_plan({"steps": [{"type": "joint", "joint": "shoulder",
                                          "direction": "left", "degrees": 10}], "explanation": "bad pairing"})


if __name__ == "__main__":
    unittest.main()
