"""RoArm-M2 USB JSON transport and measured joint control, without boot writes.

Angles exposed to the playground are degrees; firmware T101/T102 use radians.
The serial descriptor stays open and never deliberately toggles DTR or RTS.
"""
import fcntl
import glob
import json
import math
import os
import select
import termios
import threading
import time


JOINTS = ('base', 'shoulder', 'elbow', 'gripper')
FEEDBACK_KEYS = ('b', 's', 'e', 't')
# Manufacturer clamp mode: decreasing HAND angle opens the jaws, 45..180 degrees.
LIMITS = {'base': (-180, 180), 'shoulder': (-90, 90),
          'elbow': (0, 180), 'gripper': (45, 180)}
# Clamp-mode linkage dimensions from the manufacturer firmware (millimetres).
LINK2 = math.hypot(236.82, 30)
LINK3 = math.hypot(280.15, 1.73)
SHOULDER_OFFSET = math.atan2(30, 236.82)
ELBOW_OFFSET = math.atan2(1.73, 280.15)
BLOCKED_COMMANDS = {600, 601, 603, 604}


class SerialTransport:
    """Serialize complete writes/feedback reads, including fragmented JSON lines."""

    def __init__(self, device=None, timeout=1.2):
        self.device = device
        self.timeout = timeout
        self.fd = None
        self.lock = threading.RLock()

    def open(self):
        if self.fd is not None:
            return
        paths = glob.glob('/dev/serial/by-id/*CP2102N*')
        device = self.device or (paths[0] if len(paths) == 1 else None)
        if not device:
            raise OSError('未找到唯一 ESP32 串口，请指定 --serial-device')
        fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, termios.TIOCEXCL)
            attrs = termios.tcgetattr(fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
            attrs[4] = attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            os.close(fd)
            raise
        self.fd, self.device = fd, device

    def close(self):
        with self.lock:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None

    def command(self, command, feedback=False):
        with self.lock:
            try:
                self.open()
                if feedback:
                    termios.tcflush(self.fd, termios.TCIFLUSH)
                packet = (json.dumps(command, separators=(',', ':')) + '\n').encode()
                deadline = time.monotonic() + self.timeout
                while packet:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('串口写入超时')
                    if select.select([], [self.fd], [], .1)[1]:
                        packet = packet[os.write(self.fd, packet):]
                if not feedback:
                    return None
                buffer = b''
                while time.monotonic() < deadline:
                    if not select.select([self.fd], [], [], .1)[0]:
                        continue
                    chunk = os.read(self.fd, 4096)
                    if not chunk:
                        continue
                    buffer += chunk
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        try:
                            state = json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if (isinstance(state, dict) and state.get('T') == 1051 and
                                all(isinstance(state.get(k), (float, int)) and
                                    math.isfinite(state[k]) for k in FEEDBACK_KEYS)):
                            return state
                    if len(buffer) > 65536:
                        buffer = b''
                raise TimeoutError('未收到机械臂 T1051 实测反馈')
            except (OSError, TimeoutError):
                self.close()
                raise


class ArmController:
    """Keep measured feedback separate from requested targets; no fake connection."""

    def __init__(self, transport, poll=True):
        self.transport = transport
        self.lock = threading.RLock()
        self.state = dict(connected=False, transport='usb-serial', joints={},
                          targets={}, raw={}, error='正在读取串口', updated=0)
        self.closed = threading.Event()
        if poll:
            threading.Thread(target=self._poll, daemon=True).start()

    def read(self):
        try:
            raw = self.transport.command({'T': 105}, feedback=True)
            with self.lock:
                self.state.update(connected=True, raw=raw, updated=time.time(), error='',
                                  device=self.transport.device,
                                  joints={name: round(math.degrees(raw[key]), 3)
                                          for name, key in zip(JOINTS, FEEDBACK_KEYS)})
            return self.snapshot()
        except Exception as exc:
            with self.lock:
                self.state.update(connected=False, error=str(exc))
            raise

    def _poll(self):
        while not self.closed.is_set():
            try:
                self.read()
            except Exception:
                pass
            self.closed.wait(.3 if self.state['connected'] else 1)

    def snapshot(self):
        with self.lock:
            result = json.loads(json.dumps(self.state))
        if time.time() - result['updated'] > 2:
            result['connected'] = False
        return result

    def move(self, joint, angle=None, delta=None, speed=100):
        if joint not in JOINTS:
            raise ValueError('未知关节')
        state = self.read()
        if angle is None:
            if delta is None:
                raise ValueError('需要 angle 或 delta')
            angle = state['joints'][joint] + float(delta)
        angle = float(angle)
        low, high = LIMITS[joint]
        if not math.isfinite(angle) or not low <= angle <= high:
            raise ValueError('%s 角度须在 %s..%s 度内' % (joint, low, high))
        self.transport.command({'T': 101, 'joint': JOINTS.index(joint) + 1,
                                'rad': math.radians(angle), 'spd': speed, 'acc': 5})
        with self.lock:
            self.state['targets'][joint] = angle
            self.state.pop('cartesian_target', None)
        return angle

    def pose(self, joints):
        # Validate the whole pose before moving any joint.
        if not isinstance(joints, dict) or not joints:
            raise ValueError('姿态不能为空')
        for name, angle in joints.items():
            if name not in LIMITS or not math.isfinite(float(angle)) or not LIMITS[name][0] <= float(angle) <= LIMITS[name][1]:
                raise ValueError('姿态关节或角度超出范围')
        for name, angle in joints.items():
            self.move(name, angle=angle)

    def led(self, value):
        value = int(value)
        if not 0 <= value <= 255:
            raise ValueError('LED 亮度须在 0..255 内')
        self.transport.command({'T': 114, 'led': value})
        return value

    def home(self):
        """Use INIT from the factory web UI: firmware maximum speed/acceleration."""
        self.transport.command({'T': 102, 'base': 0, 'shoulder': 0,
                                'elbow': 1.5707965, 'hand': 3.1415926,
                                'spd': 0, 'acc': 0})
        with self.lock:
            self.state['targets'] = dict(base=0, shoulder=0, elbow=90, gripper=180)
            self.state.pop('cartesian_target', None)

    def torque(self, enabled):
        self.transport.command({'T': 210, 'cmd': int(bool(enabled))})
        return bool(enabled)

    def adaptive(self, enabled):
        # Keep the original web UI's per-axis DEFA thresholds.
        self.transport.command({'T': 112, 'mode': int(bool(enabled)),
                                'b': 60, 's': 110, 'e': 50, 'h': 50})
        return bool(enabled)

    def cartesian(self, x, y, z, t=None, speed=.25):
        """Factory IK moves XYZ in mm, preserving the measured clamp angle by default."""
        x, y, z, speed = (float(value) for value in (x, y, z, speed))
        if not all(math.isfinite(value) for value in (x, y, z, speed)) or not 0 < speed <= 1:
            raise ValueError('XYZ 须为有效毫米数，坐标速度须在 0..1 内')
        radius = math.hypot(x, y)
        length = math.hypot(radius, z)
        if not abs(LINK3 - LINK2) < length < LINK3 + LINK2:
            raise ValueError('目标坐标超出机械臂连杆可达范围')
        # Match simpleLinkageIkRad() so impossible goals cannot be reported as accepted.
        psi = math.acos(max(-1, min(1, (LINK2**2 + length**2 - LINK3**2) / (2 * LINK2 * length)))) + SHOULDER_OFFSET
        omega = math.acos(max(-1, min(1, (LINK3**2 + length**2 - LINK2**2) / (2 * length * LINK3))))
        target = dict(base=math.degrees(math.atan2(y, x)),
                      shoulder=90 - math.degrees(math.atan2(z, radius) + psi),
                      elbow=math.degrees(psi + omega - ELBOW_OFFSET))
        if any(not LIMITS[name][0] <= value <= LIMITS[name][1] for name, value in target.items()):
            raise ValueError('目标坐标对应的关节角度超出范围')
        if t is None:
            # Encoder noise near the jaw limits must not make XYZ-only moves unusable.
            t = max(math.radians(45), min(math.pi, self.read()['raw']['t']))
        t = float(t)
        if not math.isfinite(t) or not math.radians(45) <= t <= math.pi + 1e-6:
            raise ValueError('夹爪 t 须在 45..180 度对应的弧度范围内')
        self.transport.command({'T': 104, 'x': x, 'y': y, 'z': z, 't': t, 'spd': speed})
        target['gripper'] = math.degrees(t)
        with self.lock:
            self.state['targets'].update(target)
            self.state['cartesian_target'] = dict(x=x, y=y, z=z, t=t)
        return dict(x=x, y=y, z=z, t=t, spd=speed)

    def cartesian_delta(self, axis, delta, speed=.25):
        if axis not in ('x', 'y', 'z', 't') or not math.isfinite(float(delta)):
            raise ValueError('坐标增量须使用 x/y/z/t 和有效数值')
        raw = self.read()['raw']
        if not all(isinstance(raw.get(key), (float, int)) for key in ('x', 'y', 'z', 't')):
            raise ValueError('机械臂未返回 XYZ 坐标反馈')
        goal = {key: raw[key] for key in ('x', 'y', 'z', 't')}
        goal[axis] += float(delta)
        if axis != 't':
            goal['t'] = max(math.radians(45), min(math.pi, goal['t']))
        return self.cartesian(**goal, speed=speed)

    def raw(self, command):
        """Send the original JSON command string; retain the established BOOT/reset block."""
        if isinstance(command, str):
            command = json.loads(command)
        if not isinstance(command, dict) or type(command.get('T')) is not int:
            raise ValueError('命令须为包含整数 T 的 JSON 对象')
        if command['T'] in BLOCKED_COMMANDS:
            raise ValueError('此入口不执行重启、Flash/NVS 清空或 BOOT 重置命令')
        json.dumps(command, allow_nan=False)
        if command['T'] == 105:
            return self.read()['raw']
        self.transport.command(command)
        return dict(sent=command)

    def stop(self):
        # T123 stops increments; holding measured angles also supersedes T101 goals.
        for axis in range(1, 5):
            self.transport.command({'T': 123, 'm': 0, 'axis': axis, 'cmd': 0, 'spd': 0})
        raw = self.read()['raw']
        # T102 uses full joint names and integer servo steps/s, unlike T122's b/s/e/h.
        self.transport.command({'T': 102, 'base': raw['b'], 'shoulder': raw['s'],
                                'elbow': raw['e'], 'hand': raw['t'], 'spd': 100, 'acc': 5})
        with self.lock:
            self.state['targets'] = dict(self.state['joints'])
            self.state.pop('cartesian_target', None)

    def close(self):
        self.closed.set()
        self.transport.close()
