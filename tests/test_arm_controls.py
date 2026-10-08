"""Factory controls and IK protocol tests use a recording transport, never hardware."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rk3588'))
from arm_serial import ArmController


class RecordingTransport:
    device = 'test-only'

    def __init__(self):
        self.commands = []
        self.feedback = dict(T=1051, b=0, s=0, e=math.pi/2, t=math.pi,
                             x=310.15, y=0, z=236.82)

    def command(self, command, feedback=False):
        self.commands.append(command)
        return dict(self.feedback) if feedback else None


class FactoryControls(unittest.TestCase):
    def setUp(self):
        self.transport = RecordingTransport()
        self.arm = ArmController(self.transport, poll=False)

    def test_factory_init_and_switches(self):
        self.arm.home()
        self.assertEqual(self.transport.commands[-1], dict(T=102, base=0, shoulder=0,
            elbow=1.5707965, hand=3.1415926, spd=0, acc=0))
        for enabled in (True, False):
            self.arm.torque(enabled)
            self.assertEqual(self.transport.commands[-1], dict(T=210, cmd=int(enabled)))
            self.arm.adaptive(enabled)
            self.assertEqual(self.transport.commands[-1], dict(T=112, mode=int(enabled),
                                                               b=60, s=110, e=50, h=50))

    def test_absolute_and_relative_coordinates_preserve_measured_clamp(self):
        goal = self.arm.cartesian(310, 10, 235, speed=.5)
        self.assertEqual(self.transport.commands[-1], dict(T=104, **goal))
        self.assertEqual(goal['t'], math.pi)
        self.assertLess(abs(self.arm.snapshot()['targets']['shoulder']), 1)
        for axis, delta in [('x', 10), ('y', -10), ('z', 10), ('t', -.1)]:
            goal = self.arm.cartesian_delta(axis, delta)
            self.assertAlmostEqual(goal[axis], self.transport.feedback[axis] + delta)
        self.transport.feedback['t'] = math.pi + .001
        self.arm.read()
        self.assertEqual(self.arm.cartesian(310, 0, 235)['t'], math.pi)
        self.assertEqual(self.arm.cartesian_delta('x', 10)['t'], math.pi)

    def test_absolute_targets_use_factory_speed_without_waiting_for_feedback(self):
        """A connected slider stream writes targets directly; measurements stay truthful."""
        self.arm.read()
        self.transport.commands.clear()
        self.arm.move('base', angle=12)
        self.arm.move('base', angle=18)
        self.assertEqual([command['T'] for command in self.transport.commands], [101, 101])
        self.assertTrue(all(command['spd'] == command['acc'] == 0
                            for command in self.transport.commands))
        self.assertEqual(self.arm.snapshot()['joints']['base'], 0)
        self.assertEqual(self.arm.snapshot()['targets']['base'], 18)

    def test_relative_target_reads_new_measured_reference(self):
        self.arm.read()
        self.transport.feedback['b'] = math.radians(25)
        self.transport.commands.clear()
        self.assertEqual(self.arm.move('base', delta=5), 30)
        self.assertEqual([command['T'] for command in self.transport.commands], [105, 101])
        self.assertAlmostEqual(self.transport.commands[-1]['rad'], math.radians(30))

    def test_simultaneous_pose_uses_one_full_axis_command_and_validates_first(self):
        self.arm.read()
        self.transport.commands.clear()
        self.arm.pose(dict(base=-12, elbow=98), simultaneous=True)
        self.assertEqual(self.transport.commands, [dict(T=102, base=math.radians(-12),
            shoulder=0, elbow=math.radians(98), hand=math.pi, spd=0, acc=0)])
        before = len(self.transport.commands)
        with self.assertRaises(ValueError):
            self.arm.pose(dict(base=5, elbow=-1), simultaneous=True)
        self.assertEqual(len(self.transport.commands), before)

    def test_direct_coordinate_stream_primes_once_then_uses_nonblocking_command(self):
        self.arm.read()
        self.transport.commands.clear()
        first = self.arm.cartesian(310, 0, 235, t=math.pi, direct=True)
        self.arm.cartesian(310, 5, 240, t=math.pi, direct=True)
        self.assertEqual([command['T'] for command in self.transport.commands], [102, 1041, 1041])
        self.assertEqual(self.transport.commands[0], dict(T=102, base=0, shoulder=0,
            elbow=math.pi / 2, hand=math.pi, spd=0, acc=0))
        self.assertEqual(self.transport.commands[1], dict(T=1041, x=310., y=0., z=235., t=math.pi))
        self.assertTrue(first['direct'])
        self.assertNotIn('spd', self.transport.commands[-1])
        self.assertEqual(self.arm.snapshot()['joints']['elbow'], 90)

    def test_direct_speed_is_reinitialized_after_stop_raw_or_slow_motion(self):
        self.arm.read()
        for interrupt in (self.arm.stop,
                          lambda: self.arm.raw(dict(T=101, joint=1, rad=0, spd=100, acc=5)),
                          lambda: self.arm.move('base', angle=0, speed=100)):
            self.arm.cartesian(310, 0, 235, t=math.pi, direct=True)
            interrupt()
            self.transport.commands.clear()
            self.arm.cartesian(310, 0, 235, t=math.pi, direct=True)
            self.assertEqual([command['T'] for command in self.transport.commands], [102, 1041])

    def test_measured_cache_only_reuses_recent_connected_feedback(self):
        self.arm.read()
        updated = self.arm.snapshot()['updated']
        self.transport.commands.clear()
        with patch('arm_serial.time.time', return_value=updated + .1):
            self.arm.measured()
        self.assertEqual(self.transport.commands, [])
        with patch('arm_serial.time.time', return_value=updated + .3):
            self.arm.measured()
        self.assertEqual(self.transport.commands, [dict(T=105)])

    def test_direct_flag_rejects_non_boolean_without_motion(self):
        for value in (1, 'true', None):
            with self.assertRaises(ValueError):
                self.arm.cartesian(310, 0, 235, t=math.pi, direct=value)
        self.assertFalse(any(command['T'] in (102, 104, 1041)
                             for command in self.transport.commands))

    def test_unreachable_or_invalid_goals_never_write_motion(self):
        for coordinates in [(1000, 0, 235), (0, 0, 0), (math.nan, 0, 200), (0, 0, -300)]:
            with self.assertRaises(ValueError):
                self.arm.cartesian(*coordinates)
        for t in (0, math.nan, 4):
            with self.assertRaises(ValueError):
                self.arm.cartesian(310, 0, 235, t=t)
        self.assertFalse(any(command['T'] == 104 for command in self.transport.commands))

    def test_raw_preserves_unicode_and_returns_true_feedback(self):
        result = self.arm.raw('{"T":202,"name":"a&b#c+d 空格.txt"}')
        self.assertEqual(result['sent']['name'], 'a&b#c+d 空格.txt')
        self.assertEqual(self.arm.raw('{"T":105}'), self.transport.feedback)
        for command in ('{"T":600}', '{"T":601}', '{"T":603}', '{"T":604}',
                        '{"T":true}', '{"T":114,"led":NaN}', '[]'):
            before = len(self.transport.commands)
            with self.assertRaises(ValueError):
                self.arm.raw(command)
            self.assertEqual(len(self.transport.commands), before)


if __name__ == '__main__':
    unittest.main()
