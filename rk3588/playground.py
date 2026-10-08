"""Shared playground modes, cancellable action programs and honest demo state.

Only this coordinator issues demo motion. Perception may run on the board or
arrive from a laptop worker. Camera frames and measured angles stay authoritative.
"""
from collections import deque
import json
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import cv2
import numpy as np

from arm_serial import JOINTS, LIMITS
from vision import VisionEngine


MODES = ('manual', 'face', 'color', 'markers', 'objects', 'track',
         'gesture', 'rps', 'voice', 'clap', 'imu', 'foam')
DEMO_NAMES = ('寻找观众', '彩色指挥棒', '手势遥控', '中文语音', '拍手律动',
              '动作示教', '图形编程', '标记寻宝', '物品识别', '猜拳',
              '框选追踪', '全景摄影', '找不同', '三维机械臂', '语言导演',
              'Agent改规则', '黑泡沫抓取', '头部随动')
DEMO_KEYS = ('face', 'color', 'gesture', 'voice', 'clap', 'teach', 'program',
             'markers', 'objects', 'rps', 'track', 'panorama', 'difference',
             'digital', 'director', 'agent', 'foam', 'imu')


def validate_steps(steps, depth=0):
    """Validate the entire program before execution; bounded nesting for repeats."""
    if not isinstance(steps, list) or not steps or len(steps) > 100 or depth > 3:
        raise ValueError('程序需要 1..100 步，嵌套最多三层')
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('每步须为对象')
        kind = step.get('type')
        if kind == 'joint':
            joint = step.get('joint')
            if joint not in JOINTS:
                raise ValueError('未知关节')
            if ('angle' in step) == ('delta' in step):
                raise ValueError('关节动作需要 angle 或 delta 其中一个')
            value = float(step.get('angle', step.get('delta')))
            if not math.isfinite(value):
                raise ValueError('角度必须有限')
            if 'angle' in step and not LIMITS[joint][0] <= value <= LIMITS[joint][1]:
                raise ValueError('角度超出厂家范围')
            if 'delta' in step and abs(value) > 60:
                raise ValueError('单步相对运动最多 60 度')
        elif kind == 'pose':
            joints = step.get('joints', {})
            if not isinstance(joints, dict) or not joints:
                raise ValueError('姿态不能为空')
            for joint, value in joints.items():
                if joint not in LIMITS or not math.isfinite(float(value)) or not LIMITS[joint][0] <= float(value) <= LIMITS[joint][1]:
                    raise ValueError('姿态超出范围')
        elif kind == 'led':
            if not 0 <= int(step.get('value', -1)) <= 255:
                raise ValueError('LED 亮度超出范围')
        elif kind == 'wait':
            value = float(step.get('seconds', -1))
            if not math.isfinite(value) or not 0 <= value <= 60:
                raise ValueError('等待时间须在 0..60 秒')
        elif kind in ('repeat', 'if'):
            if kind == 'repeat' and (type(step.get('count')) is not int or not 1 <= step['count'] <= 20):
                raise ValueError('重复次数须在 1..20')
            if kind == 'if' and step.get('condition') not in ('face', 'color', 'marker'):
                raise ValueError('未知条件')
            validate_steps(step.get('steps'), depth + 1)
        elif kind != 'greet':
            raise ValueError('未知积木类型: %s' % kind)
    return steps


class Playground:
    def __init__(self, camera, arm, data_dir, model_dir, director_url='', director_model='',
                 local_server='', audio_device='hw:CARD=UQ212,DEV=0'):
        self.camera, self.arm = camera, arm
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.data_dir / 'artifacts'
        self.artifacts.mkdir(exist_ok=True)
        self.vision_engine = VisionEngine(model_dir=model_dir)
        self.model_dir = Path(model_dir)
        self.local_server, self.audio_device = local_server, audio_device
        self.audio_worker = None
        self.audio_kind = ''
        self.vision_lock = threading.Lock()
        self.lock = threading.RLock()
        self.action_lock = threading.RLock()
        self.events = deque(maxlen=80)
        self.mode, self.options = 'manual', {}
        self.vision = dict(detections=[], width=640, height=480)
        self.programs = self._load_programs()
        self.cancel = threading.Event()
        self.job = None
        self.job_name = ''
        self.reference = None
        self.reference_joints = None
        self.panorama = {}
        self.difference = {}
        self.imu = dict(simulated=True, calibrated=False, yaw=0, pitch=0)
        self.imu_neutral = (0, 0)
        self.imu_pose = None
        self.voice, self.host, self.director = {}, {}, {}
        self.workers = {}
        grasp_file = self.data_dir / 'grasp.json'
        try:
            poses = json.loads(grasp_file.read_text()) if grasp_file.exists() else {}
        except (ValueError, OSError):
            poses = {}
        self.grasp = dict(poses=poses, status='developing', message='需示教观察、接近和抬起三个姿态')
        self.director_url, self.director_model = director_url, director_model
        self.last_motion = self.last_seen = self.last_trigger = 0
        self.scan_direction = 1
        self.face_greeted = False
        self.last_greet = self.last_target_light = 0
        self.clap_count = 0
        self.client_sequences = {}
        self.event('Playground 已启动，等待串口实测反馈')
        threading.Thread(target=self._vision_loop, daemon=True).start()

    def event(self, message, level='info'):
        with self.lock:
            self.events.append(dict(time=time.time(), message=message, level=level))

    def _load_programs(self):
        path = self.data_dir / 'programs.json'
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}

    def _save_programs(self):
        path = self.data_dir / 'programs.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.programs, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)

    def frame(self):
        with self.camera.condition:
            if not self.camera.status()['ready'] or self.camera.frame is None:
                raise RuntimeError('摄像头未就绪')
            encoded = self.camera.frame
        image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError('摄像头图像解码失败')
        return image

    def state(self):
        with self.lock:
            process = self.audio_worker
            if process and process.poll() is not None and self.audio_worker is process:
                code = process.returncode
                self.workers.setdefault(self.audio_kind, {}).update(
                    updated=0, worker_status='failed', exit_code=code)
                self.event('板端音频进程退出，检查设备服务日志：%s' % code, 'warning')
                self.audio_worker = None
            result = dict(mode=self.mode, options=dict(self.options), vision=self.vision,
                          events=list(self.events), programs=[dict(name=k, steps=v) for k, v in self.programs.items()],
                          panorama=self.panorama, difference=self.difference, imu=self.imu,
                          voice=self.voice, host=self.host, director=self.director,
                          workers=self.workers,
                          grasp=self.grasp,
                          running=bool(self.job and self.job.is_alive()), job=self.job_name)
            result = json.loads(json.dumps(result))
        result['arm'] = self.arm.snapshot()
        result['camera'] = self.camera.status()
        result['capabilities'] = self.vision_engine.capabilities()
        result['capabilities'].update(director=bool(self.director_url), serial=True,
                                      host_worker=time.time() - result['host'].get('updated', 0) < 5)
        # Software readiness and physical acceptance are intentionally separate.
        result['demo_status'] = {DEMO_KEYS[i]: dict(name=name,
            status='developing' if i >= 16 else 'software',
            message='待硬件接入' if i == 17 else '需现场验收') for i, name in enumerate(DEMO_NAMES)}
        for key in ('face', 'color', 'markers', 'objects', 'track'):
            available = result['capabilities'][key]['available']
            result['demo_status'][key].update(status='ready' if available else 'blocked',
                message='软件就绪 · 待现场验收' if available else '缺少模型或算法依赖')
        for key in ('gesture', 'rps'):
            fresh = result['capabilities']['host_worker']
            result['demo_status'][key].update(status='ready' if fresh else 'requires_worker',
                message='手势推理在线' if fresh else '需启动手势 worker')
        for key in ('voice', 'clap'):
            kind = 'speech' if key == 'voice' else 'clap'
            fresh = time.time() - result['workers'].get(kind, {}).get('updated', 0) < 5
            result['capabilities'][key] = dict(available=fresh, backend='Vosk CPU' if key == 'voice' else 'PCM energy')
            result['demo_status'][key].update(message='音频服务在线 · 待真人测试' if fresh else '需启动音频 worker · 待真人测试')
        result['demo_status']['director'].update(status='ready' if self.director_url else 'requires_worker',
            message='本地模型已配置 · 预览后执行' if self.director_url else '需配置本地模型服务')
        result['demo_status']['foam'].update(message='正在开发 · 已有暗轮廓检测，抓取未验收')
        return result

    def stop(self, hold=True):
        with self.action_lock:
            self.cancel.set()
            self._stop_audio()
            with self.lock:
                self.mode = 'manual'
                self.vision = dict(detections=[], width=self.vision.get('width', 640),
                                   height=self.vision.get('height', 480))
                if self.grasp.get('status') == 'attempting':
                    self.grasp.update(status='developing', message='抓取尝试已取消，未判定成功')
            if hold:
                self.arm.stop()
        self.event('模式和动作程序已停止')

    def _stop_audio(self):
        """The worker and arecord share one process group; close the microphone too."""
        process = self.audio_worker
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1.5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if self.audio_kind in self.workers:
            self.workers[self.audio_kind].update(updated=0, worker_status='stopped')
        self.audio_worker = None

    def _start_audio(self, mode):
        if not self.local_server:
            return  # Tests/laptop deployments may use an independent worker instead.
        import importlib.util
        if mode == 'voice' and (not importlib.util.find_spec('vosk') or
                              not (self.model_dir / 'vosk-model-small-cn-0.22').is_dir()):
            self.event('板端语音依赖或模型未安装，可使用上位机音频 worker', 'warning')
            return
        worker = Path(__file__).resolve().parent / 'host' / 'worker.py'
        if not worker.is_file():
            worker = Path(__file__).resolve().parent.parent / 'host' / 'worker.py'
        self.audio_kind = 'speech' if mode == 'voice' else 'clap'
        # Vosk resolves its cache through Path.home(); DynamicUser may lack passwd.
        environment = dict(os.environ, HOME=str(self.data_dir))
        self.audio_worker = subprocess.Popen([sys.executable, str(worker), '--server', self.local_server,
            '--mode', self.audio_kind, '--speech-model', str(self.model_dir / 'vosk-model-small-cn-0.22'),
            '--audio-device', self.audio_device, '--channels', '2'],
            start_new_session=True, env=environment)
        self.event('正在启动板端音频：' + self.audio_kind)

    def _start_job(self, name, function, mode='manual'):
        def run(token):
            self.event('开始：' + name)
            try:
                function(token)
                self.event(('取消：' if token.is_set() else '完成：') + name)
            except Exception as exc:
                self.event(name + '失败：' + str(exc), 'error')
            finally:
                with self.lock:
                    self.job_name = ''
        # Reserve and publish the one job while holding both locks, before another
        # request or stop can observe the token. Starting the daemon is atomic here.
        with self.action_lock, self.lock:
            if self.job and self.job.is_alive():
                raise RuntimeError('已有动作程序运行，请先停止')
            self.cancel = threading.Event()
            token = self.cancel
            self.job_name = name
            self.mode = mode
            self.job = threading.Thread(target=run, args=(token,), daemon=True)
            self.job.start()
        return dict(started=name)

    def _step_motion(self, token, function):
        with self.action_lock:
            if token.is_set():
                return False
            function()
            return True

    def _wait_targets(self, token, seconds=8):
        # Low-precision arm: settling within 3 degrees is sufficient for demos.
        deadline = time.monotonic() + seconds
        while not token.wait(.15):
            state = self.arm.snapshot()
            if not state['connected']:
                raise RuntimeError('运动期间串口反馈中断')
            errors = [abs(state['joints'][key] - angle) for key, angle in state['targets'].items()]
            if errors and max(errors) <= 3:
                token.wait(.35)
                return
            if time.monotonic() >= deadline:
                self.event('本步未在等待期内进入 3° 范围，保留实际反馈', 'warning')
                return

    def _greet(self, token):
        initial = self.arm.read()['joints']
        # A small elbow nod preserves the base direction and avoids changing torque.
        target = max(5, min(170, initial['elbow'] - 12))
        self._step_motion(token, lambda: self.arm.led(180))
        self._step_motion(token, lambda: self.arm.move('elbow', angle=target))
        self._wait_targets(token)
        if not token.is_set():
            self._step_motion(token, lambda: self.arm.move('elbow', angle=initial['elbow']))
            self._wait_targets(token)

    def _execute(self, steps, token):
        for step in steps:
            if token.is_set():
                return
            kind = step['type']
            self.event('执行积木：' + kind)
            if kind == 'wait':
                token.wait(float(step['seconds']))
            elif kind == 'repeat':
                for _ in range(step['count']):
                    if token.is_set():
                        break
                    self._execute(step['steps'], token)
            elif kind == 'if':
                mode = {'face': 'face', 'color': 'color', 'marker': 'markers'}[step['condition']]
                with self.vision_lock:
                    found = self.vision_engine.process(self.frame(), mode, self.options)['detections']
                self.event('条件 %s：%s' % (step['condition'], '成立' if found else '未成立'))
                if found:
                    self._execute(step['steps'], token)
            elif kind == 'greet':
                self._greet(token)
            elif kind == 'led':
                self._step_motion(token, lambda: self.arm.led(step['value']))
            elif kind == 'pose':
                self._step_motion(token, lambda: self.arm.pose(step['joints']))
                self._wait_targets(token)
            else:
                self._step_motion(token, lambda: self.arm.move(step['joint'],
                    angle=step.get('angle'), delta=step.get('delta')))
                self._wait_targets(token)

    def perception(self, data):
        with self.lock:
            kind = data.get('kind', 'unknown')
            self.workers[kind] = dict(self.workers.get(kind, {}), **data, updated=time.time())
            if kind == 'hands':
                self.host.update(data, updated=time.time())
        return dict(received=True)

    def _follow(self, mode, options, targets, token, now):
        """Refresh proportional image-centering goals without waiting for joint arrival.

        Goals always start at actual feedback; 100 ms updates and larger servo speed
        replace the old 600 ms / tiny-step movement. A greeting owns motion until it ends.
        """
        if self.job and self.job.is_alive():
            return
        with self.action_lock:
            if mode != self.mode or token is not self.cancel or token.is_set():
                return
            # Manual joint control keeps mode/token for perception, but disables
            # motion. Re-read that flag after waiting for the same action lock.
            if not self.options.get('motion', True) or (self.job and self.job.is_alive()):
                return
            if targets:
                self.last_seen = now
            elif mode == 'face' and now - self.last_seen > 2:
                self.face_greeted = False
            if now - self.last_motion < .10:
                return
            state = self.arm.snapshot()
            if not state['connected']:
                return
            if targets:
                target = max(targets, key=lambda item: item['w'] * item['h'])
                if mode in ('face', 'markers') and now - self.last_target_light > 1:
                    self.arm.led(160)
                    self.last_target_light = now
                horizontal, vertical = target['cx'] - .5, target['cy'] - .5
                centered = abs(horizontal) <= .06 and abs(vertical) <= .08
                # Positive base turns left; positive elbow tilts the mounted camera down.
                for joint, error, gain, limit, sign, low, high in (
                        ('base', horizontal, 24, 8, -1, -175, 175),
                        ('elbow', vertical, 18, 6, float(options.get('pitch_direction', 1)), 5, 170)):
                    if joint == 'elbow' and not options.get('pitch', True):
                        continue
                    angle = state['joints'].get(joint)
                    if angle is not None and abs(error) > .04:
                        angle = max(low, min(high, angle + sign * max(-limit, min(limit, error * gain))))
                        self.arm.move(joint, angle=angle, speed=500)
                if (mode == 'face' and centered and options.get('greet', True)
                        and not self.face_greeted and now - self.last_greet > 8):
                    self.face_greeted = True
                    self.last_greet = now
                    self.event('找到观众，亮灯并点头致意；之后继续识别与跟随')
                    # _start_job defaults to manual: explicitly retain face mode and
                    # perception, otherwise the first greeting permanently stops detection.
                    self._start_job('人脸致意', self._greet, mode='face')
            elif mode in ('face', 'markers') and now - self.last_seen > 1:
                angle = state['joints'].get('base')
                if angle is not None:
                    low, high = float(options.get('scan_min', -60)), float(options.get('scan_max', 60))
                    if not -175 <= low < high <= 175:
                        raise ValueError('扫描范围须在 -175..175 度且起点小于终点')
                    if angle >= high:
                        self.scan_direction = -1
                    elif angle <= low:
                        self.scan_direction = 1
                    self.arm.move('base', angle=max(low, min(high, angle + self.scan_direction * 6)), speed=500)
            self.last_motion = now

    def _vision_loop(self):
        previous_sequence = -1
        while True:
            time.sleep(.025)
            with self.lock:
                mode, options = self.mode, dict(self.options)
                token = self.cancel
            if mode not in ('face', 'color', 'markers', 'objects', 'track', 'foam'):
                continue
            if self.camera.sequence == previous_sequence:
                continue
            try:
                image = self.frame()
                previous_sequence = self.camera.sequence
                with self.vision_lock:
                    result = self.vision_engine.process(image, mode, options)
                now = time.monotonic()
                with self.lock:
                    if mode != self.mode or token is not self.cancel or token.is_set():
                        continue
                    self.vision = result
                    if result.get('detections'):
                        self.last_seen = now
                targets = result.get('detections', [])
                # Perception-only modes never move the arm automatically.
                if mode in ('objects', 'foam') or not options.get('motion', True):
                    continue
                self._follow(mode, options, targets, token, now)
            except Exception as exc:
                with self.lock:
                    if mode != self.mode or token is not self.cancel or token.is_set():
                        continue
                    self.vision = dict(detections=[], error=str(exc), width=640, height=480)
                if time.monotonic() - self.last_trigger > 3:
                    self.event(str(exc), 'error')
                    self.last_trigger = time.monotonic()

    def _panorama(self, data, token):
        start, end, step = (float(data.get(k, v)) for k, v in [('start', -45), ('end', 45), ('step', 15)])
        if not -175 <= start < end <= 175 or not 5 <= step <= 45:
            raise ValueError('全景起终点须在 -175..175 度，步长 5..45 度')
        initial = self.arm.read()['joints']['base']
        frames, angles, source_urls = [], [], []
        stamp = str(int(time.time()))
        try:
            angle = start
            while angle <= end + .01 and not token.is_set():
                self._step_motion(token, lambda a=angle: self.arm.move('base', angle=a))
                self._wait_targets(token, 45)
                if token.is_set():
                    return
                image = self.frame()
                path = self.artifacts / ('panorama-%s-%02d.jpg' % (stamp, len(frames)))
                cv2.imwrite(str(path), image)
                frames.append(image)
                angles.append(self.arm.read()['joints']['base'])
                source_urls.append('/artifacts/' + path.name)
                with self.lock:
                    self.panorama = dict(status='capturing', count=len(frames), angles=angles[:], sources=source_urls[:])
                angle += step
            if token.is_set():
                return
            with self.vision_lock:
                stitched, error = self.vision_engine.stitch(frames)
            if stitched is None:
                with self.lock:
                    self.panorama.update(status='failed', error=error,
                        note='原始分段照片已保存；没有将拼贴冒充全景拼接')
                self.event('全景拼接失败：' + error, 'warning')
            else:
                path = self.artifacts / ('panorama-%s.jpg' % stamp)
                cv2.imwrite(str(path), stitched)
                with self.lock:
                    self.panorama.update(status='complete', image='/artifacts/' + path.name, error='')
        finally:
            if not token.is_set():
                self._step_motion(token, lambda: self.arm.move('base', angle=initial))

    def _speech(self, text):
        with self.lock:
            self.voice = dict(text=text, updated=time.time())
        if self.mode != 'voice':
            return dict(ignored=True, reason='中文语音模式未启动')
        self.event('听到：' + text)
        rules = [('停止', 'stop'), ('停下', 'stop'), ('找人', 'face'), ('打招呼', 'greet'),
                 ('向左', 'left'), ('左转', 'left'), ('向右', 'right'), ('右转', 'right'),
                 ('抬头', 'up'), ('低头', 'down'), ('张开', 'open'), ('打开夹爪', 'open'),
                 ('合拢', 'close'), ('关闭夹爪', 'close'), ('灯亮', 'light'), ('开灯', 'light'),
                 ('灯灭', 'dark'), ('关灯', 'dark')]
        command = next((command for phrase, command in rules if phrase in text), None)
        if not command:
            self.event('口令未匹配，未执行动作', 'warning')
            return dict(matched=False)
        if command == 'stop':
            self.stop(hold=self.arm.snapshot()['connected'])
        elif command == 'face':
            self.action(dict(action='mode', mode='face'))
        elif command in ('light', 'dark'):
            self.arm.led(180 if command == 'light' else 0)
        else:
            steps = {'left': [{'type': 'joint', 'joint': 'base', 'delta': 15}],
                     'right': [{'type': 'joint', 'joint': 'base', 'delta': -15}],
                     'up': [{'type': 'joint', 'joint': 'elbow', 'delta': -10}],
                     'down': [{'type': 'joint', 'joint': 'elbow', 'delta': 10}],
                     'open': [{'type': 'joint', 'joint': 'gripper', 'angle': 60}],
                     'close': [{'type': 'joint', 'joint': 'gripper', 'angle': 175}],
                     'greet': [{'type': 'greet'}]}[command]
            # Keep the voice mode after the program so subsequent commands are heard.
            def run(token):
                self._execute(steps, token)
                with self.lock:
                    if not token.is_set() and token is self.cancel:
                        self.mode = 'voice'
            self._start_job('语音：' + command, run, mode='voice')
        return dict(matched=True, command=command)

    def _gesture(self, gesture):
        if self.mode not in ('gesture', 'rps'):
            return dict(ignored=True, reason='手势模式未启动')
        if self.mode == 'rps':
            player = {'fist': 'rock', 'open': 'paper', 'victory': 'scissors'}.get(gesture)
            if not player:
                return dict(ignored=True)
            robot = random.choice(('rock', 'paper', 'scissors'))
            win = {('rock', 'scissors'), ('paper', 'rock'), ('scissors', 'paper')}
            outcome = '平局' if player == robot else '你赢了' if (player, robot) in win else '机器人赢了'
            self.host.update(rps=dict(player=player, robot=robot, outcome=outcome))
            self.arm.led(200 if outcome == '你赢了' else 80)
            self.event('猜拳：%s / %s → %s' % (player, robot, outcome))
            return self.host['rps']
        mapping = {'open': ('gripper', 60), 'fist': ('gripper', 175)}
        if gesture in mapping:
            joint, angle = mapping[gesture]
            self.arm.move(joint, angle=angle)
        elif gesture in ('left', 'right'):
            self.arm.move('base', delta=10 if gesture == 'left' else -10)
        elif gesture == 'victory':
            self.arm.led(180)
        else:
            return dict(ignored=True)
        self.event('手势：' + gesture)
        return dict(gesture=gesture)

    def handle_action(self, data):
        """Reject a client's earlier start arriving after its newer stop request."""
        client, sequence = data.get('_ui_client'), data.get('_ui_sequence')
        # Long model inference cannot delay a concurrent stop; it has no motion.
        if data.get('action') in ('director', 'host_connect'):
            return self.action(data)
        with self.action_lock:
            if client is not None:
                if not isinstance(client, str) or type(sequence) is not int or sequence < 0:
                    raise ValueError('请求序号错误')
                if sequence <= self.client_sequences.get(client, -1):
                    raise ValueError('已忽略过期请求，较新的停车或动作已生效')
                self.client_sequences[client] = sequence
            return self.action(data)

    def action(self, data):
        """All public actions; called by browser and laptop workers alike."""
        action = data.get('action')
        if action == 'camera_config':
            if self.job and self.job.is_alive():
                raise RuntimeError('请先停止动作程序，再切换摄像头规格')
            result = self.camera.configure(data)
            self.stop(hold=self.arm.snapshot()['connected'])
            self.event('摄像头规格已提交，重新采集期间识别暂停')
            return result
        if action == 'host_connect':
            # The user's browser machine hosts the optional worker/model manager.
            host_url = str(data.get('host_url') or 'http://%s:8082' % data.get('_client_host', '127.0.0.1')).rstrip('/')
            parsed = urlsplit(host_url)
            if parsed.scheme != 'http' or not parsed.hostname or parsed.path or parsed.username or parsed.query:
                raise ValueError('上位机地址应为 http://IP:8082')
            worker = data.get('worker', 'gestures')
            if worker not in ('gestures', 'director', 'status'):
                raise ValueError('未知上位机 worker')
            try:
                path = '/api/status' if worker == 'status' else '/api/start'
                body = None if worker == 'status' else b''
                # A loopback RK address cannot be used by a laptop worker.
                if body is not None:
                    server = data.get('_rk_origin') or data.get('server') or self.local_server
                    body = json.dumps(dict(worker=worker, server=server)).encode()
                request = Request(host_url + path, data=body, headers={'Content-Type': 'application/json'})
                with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
                    result = json.load(response)
            except HTTPError as exc:
                # An installed manager reports missing models/dependencies in its body.
                # Preserve concrete setup instructions instead of calling this a LAN outage.
                try:
                    result = json.load(exc)
                except (ValueError, UnicodeError):
                    raise RuntimeError('上位机管理服务返回 HTTP %s' % exc.code)
            except OSError as exc:
                raise RuntimeError('无法连接上位机8082管理服务。请在上位机项目目录运行 '
                                   '.venv/bin/python -m host.manager --host 0.0.0.0；'
                                   '依赖和模型安装见 /manuals/host.md。原因：%s' % exc)
            if worker == 'director':
                self.director_url = 'http://%s:%s/v1' % (parsed.hostname, result.get('director_port', 8081))
            self.event('已连接上位机服务：' + worker)
            return result
        if action == 'stop':
            connected = self.arm.snapshot()['connected']
            self.stop(hold=connected)
            return dict(stopped=True, hold_sent=connected)
        if action == 'mode':
            mode = data.get('mode')
            if mode not in MODES:
                raise ValueError('未知模式')
            options = data.get('options', {})
            if not isinstance(options, dict):
                raise ValueError('模式参数须为 JSON 对象')
            if mode == 'foam':
                options = dict({'roi': [0, .35, 1, .65]}, **options)
            self.stop(hold=self.arm.snapshot()['connected'])
            with self.lock:
                self.cancel = threading.Event()
                self.mode, self.options = mode, options
                self.vision = dict(detections=[], width=640, height=480)
                self.face_greeted = False
                self.last_seen = time.monotonic()
            if mode in ('voice', 'clap'):
                self._start_audio(mode)
            self.event('切换模式：' + mode)
            return dict(mode=mode)
        if action in ('joint', 'home', 'led', 'torque', 'adaptive', 'cartesian', 'cartesian_delta', 'raw'):
            if self.job and self.job.is_alive():
                raise RuntimeError('程序运行中，请先停止再手动控制')
            with self.action_lock:
                if action == 'led':
                    return dict(value=self.arm.led(data.get('value', 0)))
                if self.mode in ('face', 'color', 'markers', 'objects', 'track', 'foam'):
                    # Manual motion takes precedence while image inference keeps running.
                    if self.options.get('motion', True) and self.mode not in ('objects', 'foam'):
                        self.options = dict(self.options, motion=False)
                        self.event('手动控制接管运动，视觉识别继续；重新启动跟随可恢复自动运动')
                elif self.mode != 'manual':
                    self.stop(hold=self.arm.snapshot()['connected'])
                if action == 'home':
                    self.arm.home()
                    return dict(requested=True)
                if action in ('torque', 'adaptive'):
                    if type(data.get('enabled')) is not bool:
                        raise ValueError('开关需要布尔 enabled')
                    if action == 'torque':
                        self.stop(hold=False)
                    return dict(enabled=getattr(self.arm, action)(data['enabled']))
                if action == 'cartesian':
                    return dict(target=self.arm.cartesian(data['x'], data['y'], data['z'],
                                data.get('t'), speed=data.get('spd', .25)))
                if action == 'cartesian_delta':
                    return dict(target=self.arm.cartesian_delta(data.get('axis'), data.get('delta'),
                                speed=data.get('spd', .25)))
                if action == 'raw':
                    return dict(response=self.arm.raw(data.get('command', '')))
                return dict(target=self.arm.move(data.get('joint'), data.get('angle'), data.get('delta')))
        if action == 'record':
            if self.job and self.job.is_alive():
                raise RuntimeError('请先停止动作程序，再记录示教姿态')
            name = str(data.get('name', '我的动作')).strip()[:80]
            joints = self.arm.read()['joints']
            with self.lock:
                self.programs.setdefault(name, []).append(dict(type='pose', joints=joints))
                self._save_programs()
            self.event('已记录真实姿态：' + name)
            return dict(name=name, joints=joints)
        if action in ('program_save', 'program_delete'):
            name = str(data.get('name', '')).strip()[:80]
            if not name:
                raise ValueError('需要程序名称')
            with self.lock:
                if action == 'program_save':
                    self.programs[name] = validate_steps(data.get('steps'))
                else:
                    self.programs.pop(name, None)
                self._save_programs()
            return dict(name=name)
        if action in ('program_run', 'director_run'):
            steps = data.get('steps') or self.programs.get(data.get('name'))
            validate_steps(steps)
            return self._start_job(data.get('name', '动作程序'), lambda token: self._execute(steps, token))
        if action == 'track_target':
            self.action(dict(action='mode', mode='track', options=data.get('options', {})))
            with self.vision_lock:
                self.vision_engine.set_target(self.frame(), data.get('box'))
            return dict(target=data.get('box'))
        if action == 'difference_capture':
            self.stop()
            self.reference = self.frame()
            self.reference_joints = self.arm.read()['joints']
            self.difference = dict(status='reference', message='基准已记录，请保持机械臂姿态不变')
            return self.difference
        if action == 'difference_compare':
            if self.reference is None:
                raise ValueError('请先记录基准照片')
            current = self.arm.read()['joints']
            if any(abs(current[key] - self.reference_joints[key]) > 1.5 for key in JOINTS):
                raise ValueError('相机姿态已变化，请重新记录基准照片')
            with self.vision_lock:
                result = self.vision_engine.difference(self.reference, self.frame())
            self.difference = result
            return result
        if action == 'panorama':
            return self._start_job('全景摄影', lambda token: self._panorama(data, token))
        if action == 'speech':
            return self._speech(str(data.get('text', '')))
        if action == 'gesture':
            with self.action_lock:
                return self._gesture(data.get('gesture'))
        if action == 'clap':
            with self.action_lock:
                if self.mode != 'clap' or self.cancel.is_set():
                    return dict(ignored=True)
                self.clap_count += 1
                self.arm.led(200 if self.clap_count % 2 else 20)
                state = self.arm.read()
                angle = state['joints']['base'] + (6 if self.clap_count % 2 else -6)
                self.arm.move('base', angle=max(-175, min(175, angle)))
            self.event('节拍 #%s' % self.clap_count)
            return dict(count=self.clap_count)
        if action == 'imu_calibrate':
            self.imu_neutral = (self.imu.get('yaw', 0), self.imu.get('pitch', 0))
            self.imu_pose = self.arm.read()['joints']
            self.imu.update(calibrated=True)
            return dict(neutral=self.imu_neutral)
        if action == 'imu':
            yaw, pitch = float(data.get('yaw', 0)), float(data.get('pitch', 0))
            if not all(math.isfinite(v) for v in (yaw, pitch)):
                raise ValueError('姿态角必须有限')
            self.imu.update(yaw=yaw, pitch=pitch, simulated=bool(data.get('simulated', False)), updated=time.time())
            if self.mode != 'imu' or self.imu_pose is None:
                return dict(received=True, motion=False, note='启动随动并校准后才运动')
            if time.monotonic() - self.last_motion >= .4:
                with self.action_lock:
                    if self.mode != 'imu':
                        return dict(received=True, motion=False)
                    base = max(-170, min(170, self.imu_pose['base'] + yaw - self.imu_neutral[0]))
                    elbow = max(5, min(175, self.imu_pose['elbow'] + pitch - self.imu_neutral[1]))
                    self.arm.move('base', angle=base)
                    self.arm.move('elbow', angle=elbow)
                    self.last_motion = time.monotonic()
            return dict(received=True, motion=True)
        if action == 'director':
            if not self.director_url:
                raise RuntimeError('请先运行本地语言模型服务并配置 --director-url')
            from host.director import plan
            result = plan(str(data.get('text', '')), self.director_url, self.director_model)
            if result['steps']:
                validate_steps(result['steps'])
            self.director = dict(result, updated=time.time())
            self.event('语言模型生成动作预览，等待执行')
            return result
        if action == 'greet':
            return self._start_job('致意', self._greet)
        if action == 'grasp_calibrate':
            stage = data.get('stage')
            if stage not in ('observe', 'approach', 'lift'):
                raise ValueError('需要 observe/approach/lift 示教阶段')
            self.stop()
            pose = self.arm.read()['joints']
            validate_steps([dict(type='pose', joints=pose)])
            with self.lock:
                self.grasp['poses'][stage] = pose
                path = self.data_dir / 'grasp.json'
                path.write_text(json.dumps(self.grasp['poses'], ensure_ascii=False, indent=2) + '\n')
                self.grasp.update(message='已记录 %s 的真实关节姿态' % stage)
            return self.grasp
        if action == 'grasp':
            poses = json.loads(json.dumps(self.grasp['poses']))
            if any(stage not in poses for stage in ('observe', 'approach', 'lift')):
                raise RuntimeError('正在开发：请先人工示教观察、接近与抬起位置')
            validate_steps([dict(type='pose', joints=pose) for pose in poses.values()])
            def attempt(token):
                self.grasp.update(status='attempting', message='移动至已示教的观察姿态')
                self._execute([dict(type='pose', joints=poses['observe'])], token)
                if token.is_set():
                    return
                with self.vision_lock:
                    detection = self.vision_engine.process(self.frame(), 'foam', self.options)
                with self.lock:
                    self.vision = detection
                if not detection['detections']:
                    self.grasp.update(status='developing', message='未检测到暗块候选，停止尝试')
                    raise RuntimeError('观察姿态没有暗块候选')
                self.grasp.update(message='执行固定位置接近、闭爪与抬起；结果需录像确认')
                approach = dict(poses['approach'], gripper=60)
                lift = dict(poses['lift'], gripper=175)
                self._execute([dict(type='joint', joint='gripper', angle=60),
                    dict(type='pose', joints=approach), dict(type='joint', joint='gripper', angle=175),
                    dict(type='pose', joints=lift)], token)
                self.grasp.update(status='developing', message='尝试已结束；不能据关节到位认定抓取成功')
            return self._start_job('人工示教定点抓取尝试', attempt)
        raise ValueError('未知动作：' + str(action))
