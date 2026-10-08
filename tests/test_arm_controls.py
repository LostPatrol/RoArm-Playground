"""Factory controls and IK protocol tests use a recording transport, never hardware."""
import math
from pathlib import Path
import sys
import unittest

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
        self.assertEqual(self.arm.cartesian(310, 0, 235)['t'], math.pi)
        self.assertEqual(self.arm.cartesian_delta('x', 10)['t'], math.pi)

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
