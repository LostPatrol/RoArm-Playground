"""Protocol/program tests use a pseudo-terminal and fake arm, never the real robot."""
import json
import math
import os
from pathlib import Path
import pty
import select
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rk3588'))
from arm_serial import ArmController, SerialTransport
from playground import Playground, validate_steps


class FakeTransport:
    """Immediate measured responses make program ordering independently observable."""
    device = 'test-only'

    def __init__(self):
        self.calls = []
        self.raw = dict(T=1051, b=0, s=0, e=math.pi / 2, t=math.pi)

    def command(self, command, feedback=False):
        self.calls.append(dict(command))
        if command['T'] == 101:
            self.raw[('b', 's', 'e', 't')[command['joint'] - 1]] = command['rad']
        return dict(self.raw) if feedback else None

    def close(self):
        pass


class CameraStub:
    def __init__(self):
        self.condition = threading.Condition()
        self.sequence = 1
        image = np.full((240, 320, 3), 180, np.uint8)
        cv2.rectangle(image, (50, 60), (100, 120), (0, 0, 255), -1)
        self.frame = cv2.imencode('.jpg', image)[1].tobytes()

    def status(self):
        return dict(ready=True, fps=15)


class ProtocolTests(unittest.TestCase):
    def test_fragmented_feedback_and_no_initialization_write(self):
        master, slave = pty.openpty()
        transport = SerialTransport(os.ttyname(slave), timeout=.6)
        captured = []
        try:
            transport.open()
            self.assertFalse(select.select([master], [], [], .03)[0])
            def device():
                captured.append(os.read(master, 4096))
                os.write(master, b'noise\n{"T":1051,"b":0,')
                time.sleep(.01)
                os.write(master, b'"s":0,"e":1.5,"t":3.1}\n')
            thread = threading.Thread(target=device)
            thread.start()
            result = transport.command({'T': 105}, feedback=True)
            thread.join(1)
            self.assertEqual(result['e'], 1.5)
            self.assertEqual(json.loads(captured[0]), {'T': 105})
        finally:
            transport.close()
            os.close(slave)
            os.close(master)

    def test_degrees_to_radians_and_joint_limits(self):
        transport = FakeTransport()
        arm = ArmController(transport, poll=False)
        arm.move('base', angle=30)
        self.assertAlmostEqual(transport.calls[-1]['rad'], math.pi / 6)
        for joint, value in [('base', 181), ('elbow', -1), ('gripper', 0)]:
            before = len([c for c in transport.calls if c['T'] == 101])
            with self.assertRaises(ValueError):
                arm.move(joint, angle=value)
            self.assertEqual(before, len([c for c in transport.calls if c['T'] == 101]))

    def test_stop_all_axes_then_supersede_absolute_targets(self):
        transport = FakeTransport()
        arm = ArmController(transport, poll=False)
        arm.stop()
        self.assertEqual([c['axis'] for c in transport.calls if c['T'] == 123], [1, 2, 3, 4])
        self.assertEqual(transport.calls[-1]['T'], 102)
        self.assertEqual(transport.calls[-1]['hand'], math.pi)
        self.assertEqual(set(transport.calls[-1]), {'T', 'base', 'shoulder', 'elbow', 'hand', 'spd', 'acc'})
        self.assertEqual(transport.calls[-1]['spd'], 100)


class ProgramTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.transport = FakeTransport()
        self.arm = ArmController(self.transport, poll=False)
        self.arm.read()
        self.app = Playground(CameraStub(), self.arm, self.temporary.name, ROOT / 'models')

    def tearDown(self):
        self.app.stop(hold=False)
        self.temporary.cleanup()

    def test_managed_audio_home_and_failed_worker_are_reported(self):
        """DynamicUser has no passwd entry; Vosk must receive a writable HOME."""
        self.app.local_server = 'http://unused-test-server'
        process = Mock()
        process.poll.return_value = None
        with patch('playground.subprocess.Popen', return_value=process) as spawn:
            self.app._start_audio('clap')
        self.assertEqual(spawn.call_args.kwargs['env']['HOME'], self.temporary.name)
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])
        process.returncode = 7
        process.poll.return_value = 7
        state = self.app.state()
        self.assertEqual(state['workers']['clap']['worker_status'], 'failed')
        self.assertEqual(state['workers']['clap']['exit_code'], 7)
        self.assertFalse(state['capabilities']['clap']['available'])
        self.assertIsNone(self.app.audio_worker)

    def test_manual_joint_closes_active_microphone_mode(self):
        self.app.mode = 'voice'
        with patch.object(self.app, '_stop_audio') as close_audio:
            self.app.handle_action(dict(action='joint', joint='base', delta=5))
        close_audio.assert_called_once()
        self.assertEqual(self.app.mode, 'manual')
        self.assertTrue(self.app.cancel.is_set())

    def test_record_measured_pose_and_persistent_program(self):
        self.app.action(dict(action='record', name='我的动作'))
        saved = json.loads((Path(self.temporary.name) / 'programs.json').read_text())
        self.assertEqual(saved['我的动作'][0]['joints']['elbow'], 90)
        self.assertEqual(saved['我的动作'][0]['joints']['gripper'], 180)

    def test_reject_invalid_program_before_start(self):
        cases = [[dict(type='joint', joint='gripper', angle=300)],
                 [dict(type='wait', seconds=float('nan'))],
                 [dict(type='repeat', count=0, steps=[dict(type='greet')])],
                 [dict(type='joint', joint='base', angle=10, delta=10)]]
        for steps in cases:
            with self.assertRaises(ValueError):
                self.app.action(dict(action='program_run', steps=steps))
        self.assertFalse(any(c['T'] == 101 for c in self.transport.calls))

    def test_cancellation_prevents_later_motion(self):
        self.app.action(dict(action='program_run', steps=[dict(type='wait', seconds=10),
                             dict(type='joint', joint='base', delta=20)]))
        self.app.stop()
        self.app.job.join(1)
        self.assertFalse(self.app.job.is_alive())
        self.assertFalse(any(c['T'] == 101 for c in self.transport.calls))

    def test_conditional_program_uses_real_image_color_detection(self):
        steps = [dict(type='if', condition='color', steps=[dict(type='led', value=155)])]
        validate_steps(steps)
        self.app._execute(steps, threading.Event())
        self.assertTrue(any(c == {'T': 114, 'led': 155} for c in self.transport.calls))

    def test_voice_is_gated_by_active_mode(self):
        result = self.app.action(dict(action='speech', text='向左看'))
        self.assertTrue(result['ignored'])
        self.assertFalse(any(c['T'] == 101 for c in self.transport.calls))

    def test_difference_rejects_changed_camera_pose(self):
        self.app.action(dict(action='difference_capture'))
        self.arm.move('base', angle=10)
        with self.assertRaisesRegex(ValueError, '姿态'):
            self.app.action(dict(action='difference_compare'))

    def test_imu_requires_mode_and_calibration(self):
        result = self.app.action(dict(action='imu', yaw=25, pitch=5, simulated=True))
        self.assertFalse(result['motion'])
        self.assertFalse(any(c['T'] == 101 for c in self.transport.calls))

    def test_parallel_jobs_reserve_only_one_token(self):
        entered = threading.Barrier(3)
        results = []
        def start():
            entered.wait()
            try:
                self.app._start_job('并发测试', lambda token: token.wait(5))
                results.append('started')
            except RuntimeError:
                results.append('rejected')
        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        entered.wait()
        for thread in threads:
            thread.join(1)
        self.assertCountEqual(results, ['started', 'rejected'])
        self.app.stop()
        self.app.job.join(1)
        self.assertFalse(self.app.job.is_alive())

    def test_waiting_clap_cannot_move_after_stop(self):
        self.app.action(dict(action='mode', mode='clap'))
        self.transport.calls.clear()
        with self.app.action_lock:
            thread = threading.Thread(target=self.app.action, args=(dict(action='clap'),))
            thread.start()
            time.sleep(.02)
            self.app.stop()
        thread.join(1)
        self.assertFalse(any(c['T'] in (101, 114) for c in self.transport.calls))

    def test_late_program_request_after_newer_stop_is_rejected(self):
        self.app.handle_action(dict(action='stop', _ui_client='tab', _ui_sequence=2))
        with self.assertRaisesRegex(ValueError, '过期'):
            self.app.handle_action(dict(action='program_run', steps=[dict(type='greet')],
                                       _ui_client='tab', _ui_sequence=1))
        self.assertIsNone(self.app.job)

    def test_voice_stop_remains_available_during_voice_job(self):
        self.app.action(dict(action='mode', mode='voice'))
        self.app._start_job('语音测试', lambda token: token.wait(5), mode='voice')
        self.app.action(dict(action='speech', text='停止'))
        self.app.job.join(1)
        self.assertFalse(self.app.job.is_alive())
        self.assertEqual(self.app.mode, 'manual')

    def test_old_color_result_cannot_control_restarted_color_mode(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(frame, mode, options):
            if options.get('color') == 'red':
                entered.set()
                release.wait(1)
                return dict(detections=[dict(label='red', x=.8, y=.2, w=.1, h=.1, cx=.85, cy=.25)], width=320, height=240)
            return dict(detections=[], width=320, height=240, color='blue')
        self.app.vision_engine.process = delayed
        self.app.action(dict(action='mode', mode='color', options=dict(color='red')))
        self.assertTrue(entered.wait(1))
        self.app.action(dict(action='mode', mode='color', options=dict(color='blue', motion=False)))
        release.set()
        self.app.camera.sequence += 1
        time.sleep(.3)
        self.assertFalse(any(c['T'] == 101 for c in self.transport.calls))
        self.assertNotEqual(self.app.vision.get('detections', [{}])[0].get('label') if self.app.vision.get('detections') else '', 'red')

    def test_grasp_without_calibrated_positions_never_moves(self):
        with self.assertRaisesRegex(RuntimeError, '示教'):
            self.app.action(dict(action='grasp'))
        self.assertFalse(any(c['T'] == 101 for c in self.transport.calls))

    def test_grasp_calibration_uses_measured_pose_and_persists(self):
        self.app.action(dict(action='grasp_calibrate', stage='observe'))
        saved = json.loads((Path(self.temporary.name) / 'grasp.json').read_text())
        self.assertEqual(saved['observe']['elbow'], 90)
        self.assertEqual(set(saved), {'observe'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
