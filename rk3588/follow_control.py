"""Continuous image tracking with bounded angular speed, acceleration and jerk.

Detections update a fixed angular destination; ticks never integrate stale image
errors repeatedly. Positions here are commands, never measured robot feedback.
"""
import math


# Forty-Hz motion is independent of the detector and camera cadence.
CONTROL_INTERVAL = .025
# Degrees per normalized image offset; approximate camera geometry, not calibration.
IMAGE_GAIN = {'base': 60.0, 'elbow': 45.0}
# Joint profiles in degrees/s, degrees/s² and degrees/s³ respectively.
PROFILES = {'base': (45.0, 90.0, 600.0), 'elbow': (30.0, 70.0, 450.0)}
# Conservative tracking bounds leave room before the manufacturer's end stops.
TRACK_LIMITS = {'base': (-175.0, 175.0), 'elbow': (5.0, 170.0)}
# Stop using an old observation; tolerate ordinary 15-FPS inference jitter.
OBSERVATION_TIMEOUT = .45
# Retain the selected identity briefly through missed detections.
TARGET_RETENTION = .65
# Low-pass angular destinations, not raw pixels distorted by camera motion.
FILTER_TIME = .07
# Continuous search is deliberately slower than active tracking.
SCAN_SPEED = 12.0
# Reset only the camera axes before audience searching; other joints stay held.
SEARCH_HOME = {'base': 0.0, 'elbow': 90.0}
# Actual encoders only need coarse settling on this low-precision demonstration arm.
HOME_TOLERANCE = 3.0
# Damped position response; avoid chasing a destination at maximum speed until arrival.
RESPONSE_RATE = 4.5
# Keep the servo's internal braking profile from stopping at every tiny tick target.
LOOKAHEAD_TIME = .12
# T102 native units: steps/s and acceleration register (100 steps/s²).
SERVO_SPEED = 600
SERVO_ACCELERATION = 12
# Native encoder/goal resolution; identical servo-step goals need no retransmission.
SERVO_STEPS_PER_TURN = 4096


def clamp(value, low, high):
    """Limit a scalar to an inclusive interval."""
    return max(low, min(high, value))


class SmoothFollower:
    """Match targets and integrate a jerk-limited joint trajectory."""

    def __init__(self):
        """Start inactive; the first control tick anchors to measured angles."""
        self.reset()

    def reset(self):
        """Forget motion and observations when another action owns the robot."""
        self.position = {}
        self.hold = {}
        self.velocity = dict(base=0.0, elbow=0.0)
        self.acceleration = dict(base=0.0, elbow=0.0)
        self.goal = {}
        self.target = None
        self.target_joints = {}
        self.last_seen = self.observed = self.tick_time = self.lost_since = None
        self.visible = False
        self.scan_direction = 1
        self.search_stage = None
        self.phase = 'idle'

    def observe(self, targets, joints, stamp, options):
        """Associate boxes and map their centers to capture-time joint angles."""
        previous_time = self.observed
        self.observed = stamp
        candidates = [box for box in targets if all(
            isinstance(box.get(key), (int, float)) and math.isfinite(box[key])
            for key in ('cx', 'cy', 'w', 'h')) and box['w'] > 0 and box['h'] > 0]
        target = None
        if self.target and self.last_seen is not None and stamp - self.last_seen < TARGET_RETENTION:
            # Compensate expected pixel displacement caused by our own camera motion.
            expected_x = self.target['cx'] + (joints['base'] - self.target_joints['base']) / IMAGE_GAIN['base']
            sign = float(options.get('pitch_direction', 1))
            expected_y = self.target['cy'] - sign * (joints['elbow'] - self.target_joints['elbow']) / IMAGE_GAIN['elbow']
            same = [box for box in candidates if box.get('label') == self.target.get('label')
                    and box.get('id') == self.target.get('id')]
            if same:
                nearest = min(same, key=lambda box: math.hypot(box['cx'] - expected_x, box['cy'] - expected_y))
                distance = math.hypot(nearest['cx'] - expected_x, nearest['cy'] - expected_y)
                if distance < max(.25, min(.45, 1.5 * max(self.target['w'], self.target['h']))):
                    target = nearest
        elif candidates:
            target = max(candidates, key=lambda box: box['w'] * box['h'])
        self.visible = target is not None
        if target is None:
            if self.lost_since is None:
                self.lost_since = stamp
            return None
        self.lost_since = None
        new_target = self.target is None or self.last_seen is None or stamp - self.last_seen >= TARGET_RETENTION
        alpha = 1.0 if new_target or previous_time is None else 1 - math.exp(-max(0, stamp - previous_time) / FILTER_TIME)
        for joint, coordinate, sign in (('base', 'cx', -1),
                                       ('elbow', 'cy', float(options.get('pitch_direction', 1)))):
            # A soft image deadband avoids a discontinuous velocity jump at its edge.
            error = target[coordinate] - .5
            error = math.copysign(max(0, abs(error) - .02), error)
            low, high = TRACK_LIMITS[joint]
            destination = clamp(joints[joint] + sign * IMAGE_GAIN[joint] * error, low, high)
            self.goal[joint] = destination if joint not in self.goal or new_target else (
                self.goal[joint] + alpha * (destination - self.goal[joint]))
        self.target, self.target_joints = dict(target), dict(joints)
        self.last_seen = stamp
        return target

    def tick(self, joints, now, mode, options, camera_ready=True):
        """Generate smooth tracking, camera-reset and horizontal-search goals."""
        if not self.position:
            self.position = {joint: float(joints[joint]) for joint in PROFILES}
            self.hold = dict(joints)
            self.tick_time = now
            return None
        elapsed = now - self.tick_time
        self.tick_time = now
        if elapsed <= 0:
            return None
        # Do not catch up a scheduling stall by jumping through a long trajectory.
        dt = min(elapsed, .05)
        fresh = camera_ready and self.observed is not None and 0 <= now - self.observed <= OBSERVATION_TIMEOUT
        tracking = fresh and self.visible
        can_search = fresh and not self.visible and mode in ('face', 'markers') and (
            self.lost_since is not None and now - self.lost_since > 1.2)
        if tracking:
            self.search_stage = None
        if can_search and mode == 'face' and self.search_stage is None:
            self.search_stage = 'homing'
        homing = can_search and mode == 'face' and self.search_stage == 'homing'
        if homing and all(abs(self.position[joint] - angle) < .1
                          and abs(self.velocity[joint]) < .4
                          and abs(joints[joint] - angle) <= HOME_TOLERANCE
                          for joint, angle in SEARCH_HOME.items()):
            self.search_stage = 'searching'
            # Horizontal scanning holds pitch at the reset destination throughout.
            self.position['elbow'] = SEARCH_HOME['elbow']
            self.velocity['elbow'] = self.acceleration['elbow'] = 0.0
            homing = False
        searching = can_search and (mode == 'markers' or self.search_stage == 'searching')
        if tracking:
            self.phase = 'tracking'
        elif homing:
            self.phase = 'homing'
        elif searching:
            self.phase = 'searching'
        else:
            self.phase = 'braking'
        old = dict(self.position)
        for joint, (max_speed, max_acceleration, max_jerk) in PROFILES.items():
            speed, acceleration = self.velocity[joint], self.acceleration[joint]
            wanted = 0.0
            positioning = homing or (tracking and (joint == 'base' or options.get('pitch', True)))
            if positioning:
                destination = SEARCH_HOME[joint] if homing else self.goal[joint]
                error = destination - self.position[joint]
                # Critically damped position control brakes before reaching the destination.
                wanted = clamp(RESPONSE_RATE * error, -max_speed, max_speed)
            if searching and joint == 'base':
                low, high = float(options.get('scan_min', -60)), float(options.get('scan_max', 60))
                if not -175 <= low < high <= 175:
                    raise ValueError('扫描范围须在 -175..175 度且起点小于终点')
                margin = speed * speed / (2 * max_acceleration) + abs(speed) * .15 + .5
                if self.position[joint] >= high - margin:
                    self.scan_direction = -1
                elif self.position[joint] <= low + margin:
                    self.scan_direction = 1
                wanted = self.scan_direction * SCAN_SPEED
            if positioning:
                desired_acceleration = RESPONSE_RATE ** 2 * error - 2 * RESPONSE_RATE * speed
            else:
                desired_acceleration = 5.0 * (wanted - speed)
            desired_acceleration = clamp(desired_acceleration, -max_acceleration, max_acceleration)
            acceleration += clamp(desired_acceleration - acceleration, -max_jerk * dt, max_jerk * dt)
            new_speed = speed + acceleration * dt
            # End the ramp without repeatedly oscillating around zero velocity.
            if wanted == 0 and abs(new_speed) < .01 and abs(acceleration) < .1:
                new_speed = acceleration = 0.0
            new_speed = clamp(new_speed, -max_speed, max_speed)
            low, high = TRACK_LIMITS[joint]
            # An initial pose outside the tracking envelope must not jump on activation.
            low, high = min(low, self.hold[joint]), max(high, self.hold[joint])
            position = clamp(self.position[joint] + (speed + new_speed) * .5 * dt, low, high)
            if (position == low and new_speed < 0) or (position == high and new_speed > 0):
                new_speed = acceleration = 0.0
            self.position[joint], self.velocity[joint], self.acceleration[joint] = position, new_speed, acceleration
        if all(abs(self.velocity[joint]) < .05 for joint in PROFILES) and not tracking and not homing and not searching:
            self.phase = 'idle'
        # Avoid duplicate writes while stationary; quantization remains the servo's job.
        if not any(abs(old[joint] - self.position[joint]) > .0001 for joint in PROFILES):
            return None
        return {joint: clamp(self.position[joint] + self.velocity[joint] * LOOKAHEAD_TIME,
                             min(TRACK_LIMITS[joint][0], self.hold[joint]),
                             max(TRACK_LIMITS[joint][1], self.hold[joint])) for joint in PROFILES}

    def status(self):
        """Expose command diagnostics separately from measured arm state."""
        return dict(phase=self.phase, target=self.target if self.visible else None,
                    velocity=dict(self.velocity), acceleration=dict(self.acceleration))
