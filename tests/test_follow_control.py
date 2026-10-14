"""Core trajectory and target-association checks without robot hardware."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rk3588"))
from follow_control import (CONTROL_INTERVAL, IMAGE_GAIN, OBSERVATION_TIMEOUT,
                            PROFILES, TRACK_LIMITS, SmoothFollower)


def box(cx, cy=.5, size=.2, identity=None):
    """Build one normalized detector observation."""
    return dict(cx=cx, cy=cy, w=size, h=size, label="face", id=identity)


class FollowControlTests(unittest.TestCase):
    """Check visible motion behavior and the bounds that protect its trajectory."""

    def setUp(self):
        """Anchor each scenario at a regular, stationary joint pose."""
        self.follower = SmoothFollower()
        self.joints = dict(base=0.0, elbow=90.0)
        self.options = dict(pitch=True)
        self.follower.tick(self.joints, 0.0, "face", self.options)

    def step(self, now, camera_ready=True):
        """Tick the controller and use its last command as ideal feedback."""
        command = self.follower.tick(self.joints, now, "face", self.options, camera_ready)
        if command is not None:
            self.joints.update(command)
        return command

    def assert_profile(self, previous, dt):
        """Verify speed, acceleration, and nonterminal jerk bounds."""
        for joint, (speed, acceleration, jerk) in PROFILES.items():
            actual_speed = self.follower.velocity[joint]
            actual_acceleration = self.follower.acceleration[joint]
            self.assertLessEqual(abs(actual_speed), speed + 1e-8)
            self.assertLessEqual(abs(actual_acceleration), acceleration + 1e-8)
            # The final near-zero stop may snap acceleration to zero.
            if actual_speed != 0:
                self.assertLessEqual(abs(actual_acceleration - previous[joint]), jerk * dt + 1e-8)

    def test_start_reverse_and_stop_obey_motion_profiles(self):
        """Start and reverse through bounded ramps, then brake on camera loss."""
        velocities = []
        for index in range(1, 121):
            now = index * CONTROL_INTERVAL
            if index <= 60:
                target = .9 if index < 31 else .1
                self.follower.observe([box(target, .8)], self.joints, now, self.options)
            previous = dict(self.follower.acceleration)
            self.step(now, camera_ready=index <= 60)
            self.assert_profile(previous, CONTROL_INTERVAL)
            velocities.append(self.follower.velocity["base"])
        self.assertLess(velocities[0], 0)
        self.assertLess(abs(velocities[0]), PROFILES["base"][0] * .1)
        self.assertTrue(any(speed > 0 for speed in velocities[31:60]))
        self.assertEqual(self.follower.phase, "idle")
        self.assertTrue(all(abs(speed) < .05 for speed in self.follower.velocity.values()))

    def test_fifteen_fps_observations_produce_continuous_control(self):
        """Slow observations retain a fixed destination between forty-Hz ticks."""
        commands, observations, next_observation = 0, 0, 0.0
        for index in range(1, 21):
            now = index * CONTROL_INTERVAL
            if now >= next_observation:
                # Ideal camera motion shifts the image while the scene stays fixed.
                center = .85 + self.joints["base"] / IMAGE_GAIN["base"]
                self.follower.observe([box(center)], self.joints, now, self.options)
                observations += 1
                next_observation += 1 / 15
            commands += self.step(now) is not None
        self.assertGreater(commands, observations * 2)
        self.assertLess(self.joints["base"], -3)
        self.assertAlmostEqual(self.follower.goal["base"], -IMAGE_GAIN["base"] * (.85 - .5 - .02))

    def test_old_observation_does_not_accumulate_or_move_forever(self):
        """A single old frame keeps its original goal and eventually stops."""
        self.follower.observe([box(.9)], self.joints, 0.0, self.options)
        destination = dict(self.follower.goal)
        for index in range(1, 121):
            self.step(index * CONTROL_INTERVAL)
            self.assertEqual(self.follower.goal, destination)
        self.assertEqual(self.follower.phase, "idle")
        stopped = dict(self.joints)
        for index in range(121, 161):
            self.step(index * CONTROL_INTERVAL)
        for joint in PROFILES:
            self.assertAlmostEqual(self.joints[joint], stopped[joint], places=2)
        self.assertGreater(120 * CONTROL_INTERVAL, OBSERVATION_TIMEOUT)

    def test_target_remains_stable_when_other_face_grows(self):
        """Area changes do not replace the spatially associated audience member."""
        selected = self.follower.observe([box(.3, size=.25), box(.75, size=.15)],
                                         self.joints, 0.0, self.options)
        self.assertEqual(selected["cx"], .3)
        selected = self.follower.observe([box(.32, size=.18), box(.73, size=.4)],
                                         self.joints, .1, self.options)
        self.assertEqual(selected["cx"], .32)

    def test_pitch_disabled_and_joint_boundary(self):
        """Pitch stays still when disabled and base respects its tracking limit."""
        self.options["pitch"] = False
        self.joints["base"] = TRACK_LIMITS["base"][1] - .1
        self.follower.reset()
        self.follower.tick(self.joints, 0.0, "face", self.options)
        for index in range(1, 81):
            now = index * CONTROL_INTERVAL
            self.follower.observe([box(.1, .9)], self.joints, now, self.options)
            self.step(now)
            self.assertEqual(self.joints["elbow"], 90.0)
            self.assertLessEqual(self.joints["base"], TRACK_LIMITS["base"][1])
        self.assertAlmostEqual(self.joints["base"], TRACK_LIMITS["base"][1], places=1)

    def test_nearby_diagonal_reversal_keeps_the_same_target(self):
        """A quick two-axis movement must not trigger a retention-period pause."""
        self.follower.observe([box(.6, .65)], self.joints, 0.0, self.options)
        selected = self.follower.observe([box(.4, .45)], self.joints, .1, self.options)
        self.assertIsNotNone(selected)
        self.assertTrue(self.follower.visible)
        self.assertEqual(selected['cx'], .4)

    def test_scheduler_pause_does_not_jump_or_search_without_frames(self):
        """A stalled tick stays bounded, and a missing camera never starts search."""
        self.follower.observe([box(.9)], self.joints, 0.0, self.options)
        for index in range(1, 9):
            self.step(index * CONTROL_INTERVAL)
        previous = self.joints["base"]
        self.step(10.0)
        self.assertLessEqual(abs(self.joints["base"] - previous), PROFILES["base"][0] * .05)
        self.follower.reset()
        self.follower.tick(self.joints, 0.0, "face", self.options)
        self.follower.observe([], self.joints, 0.0, self.options)
        for index in range(1, 121):
            self.assertIsNone(self.step(index * CONTROL_INTERVAL))
            self.assertNotEqual(self.follower.phase, "searching")


if __name__ == "__main__":
    unittest.main()
