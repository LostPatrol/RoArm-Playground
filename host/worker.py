"""Real MediaPipe/Vosk/PCM interaction sources; only the active mode sends actions.

Run with the project's Python. --dry-run prints results without any POST or motion.
"""
import argparse
import array
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener
import wave

ROOT = Path(__file__).resolve().parent.parent
# Model classes are mapped explicitly; Thumb_Up/Down serve as left/right buttons.
GESTURES = {"Open_Palm": "open", "Closed_Fist": "fist", "Victory": "victory",
            "Thumb_Up": "left", "Thumb_Down": "right"}
MODES = {"gestures": ("gesture", "rps"), "speech": ("voice",), "clap": ("clap",)}
# Space-separated model vocabulary is intentional: small-cn has no 向左/夹爪 tokens.
SPEECH_PHRASES = ("停止", "停下", "找 人", "打招呼", "向 左", "左转", "向右", "右转",
                  "抬头", "低头", "张开", "打开 夹 爪", "合拢", "关闭 夹 爪",
                  "灯 亮", "开灯", "灯 灭", "关灯")


def pcm_levels(pcm):
    """Expose microphone signal quality without silently amplifying noise."""
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    count = max(1, len(samples))
    rms = math.sqrt(sum(s*s for s in samples) / count) / 32768
    return {"audio_rms": round(rms, 5),
            "audio_dbfs": round(20 * math.log10(rms), 1) if rms else None,
            "audio_peak": round(max((abs(s) for s in samples), default=0) / 32768, 5),
            "clipped_fraction": round(sum(abs(s) >= 32760 for s in samples) / count, 5)}


class Client:
    """Keep camera, mode checks and actions on the same configured RK endpoint."""
    def __init__(self, server, dry_run=False):
        self.server = server.rstrip("/")
        self.dry_run = dry_run
        self.http = build_opener(ProxyHandler({}))

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.server + path, data, {"Content-Type": "application/json"})
        with self.http.open(request, timeout=4) as response:
            return response.read()

    def mode(self):
        if self.dry_run:
            return "dry-run"
        return json.loads(self.request("/api/state")).get("mode")

    def emit(self, payload, worker_mode):
        """Fresh mode check prevents a stale audio/vision result changing modes."""
        if self.dry_run:
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return True
        if self.mode() in MODES[worker_mode]:
            self.request("/api/action", payload)
            return True
        return False


class GestureLatch:
    """Require three stable frames; hold a pose once until release or mode change."""
    def __init__(self, frames=3, cooldown=1.5):
        self.frames, self.cooldown = frames, cooldown
        self.candidate, self.count, self.sent, self.mode = None, 0, None, None
        self.last_time = -math.inf

    def update(self, gesture, confidence, mode, now):
        if mode != self.mode:
            self.candidate, self.count, self.sent = None, 0, None
            self.mode = mode
        if not gesture or confidence < 0.65:
            self.candidate, self.count, self.sent = None, 0, None
            return False
        self.count = self.count + 1 if gesture == self.candidate else 1
        self.candidate = gesture
        if self.count >= self.frames and gesture != self.sent and now - self.last_time >= self.cooldown:
            self.sent, self.last_time = gesture, now
            return True
        return False


def gesture_result(result):
    """Expose real model confidence and normalized landmark bounding boxes."""
    detections = []
    best, confidence = None, 0.0
    for landmarks, categories in zip(result.hand_landmarks, result.gestures):
        category = categories[0] if categories else None
        gesture = GESTURES.get(category.category_name) if category else None
        score = float(category.score) if category else 0.0
        xs = [max(0., min(1., p.x)) for p in landmarks]
        ys = [max(0., min(1., p.y)) for p in landmarks]
        detections.append({"x": min(xs), "y": min(ys), "w": max(xs)-min(xs),
                           "h": max(ys)-min(ys), "label": gesture or "hand", "confidence": score})
        if gesture and score > confidence:
            best, confidence = gesture, score
    return {"kind": "hands", "detections": detections, "gesture": best, "confidence": confidence}


def run_gestures(args, client):
    """Use the real bundled gesture classifier, not hand-color heuristics."""
    import cv2
    import mediapipe as mp
    import numpy as np
    options = mp.tasks.vision.GestureRecognizerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=args.gesture_model),
        running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=2)
    latch = GestureLatch()
    with mp.tasks.vision.GestureRecognizer.create_from_options(options) as recognizer:
        print(json.dumps({"mode": "gestures", "worker_status": "ready"}), flush=True)
        last_heartbeat = -math.inf
        while True:
            start = time.monotonic()
            if not client.dry_run and start - last_heartbeat >= 2:
                try:
                    client.request("/api/perception", {"kind": "hands", "worker_status": "running"})
                    last_heartbeat = start
                except (OSError, ValueError):
                    # RK reboot must not unload the model or permanently kill this worker.
                    time.sleep(1)
                    continue
            if args.image:
                image = cv2.imread(args.image)
            else:
                try:
                    data = client.request("/snapshot.jpg")
                except OSError:
                    time.sleep(1)
                    continue
                image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise RuntimeError("camera image could not be decoded")
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            result = recognizer.recognize_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(start * 1000))
            perception = gesture_result(result)
            mode = client.mode()
            if client.dry_run:
                print(json.dumps(perception, ensure_ascii=False), flush=True)
            elif mode in MODES["gestures"]:
                client.request("/api/perception", perception)
            if latch.update(perception["gesture"], perception["confidence"], mode, start):
                client.emit({"action": "gesture", "gesture": perception["gesture"],
                             "confidence": perception["confidence"]}, "gestures")
            if args.image:
                break
            time.sleep(max(0., 1 / args.fps - (time.monotonic() - start)))


def mono_pcm(data, channels):
    """Downmix the UQ212's optional stereo PCM without adding NumPy on RK3588."""
    samples = array.array("h", data)
    if sys.byteorder != "little":
        samples.byteswap()
    if channels == 1:
        return data
    output = array.array("h", (int((samples[i] + samples[i+1]) / 2)
                              for i in range(0, len(samples)-1, 2)))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


class ClapDetector:
    """A brief volume rise with cooldown; this is not a neural sound classifier."""
    def __init__(self, threshold=0.10):
        self.threshold, self.baseline, self.last = threshold, 0.01, -math.inf
        self.previous_rms = 0.0

    def update(self, pcm, now):
        samples = array.array("h", pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(s*s for s in samples) / max(1, len(samples))) / 32768
        detected = (rms >= self.threshold and self.previous_rms < self.threshold
                    and rms >= self.baseline*3 and now-self.last >= 0.6)
        self.baseline = self.baseline * 0.95 + min(rms, self.threshold) * 0.05
        self.previous_rms = rms
        if detected:
            self.last = now
        return detected, rms


def audio_chunks(args):
    """Read 100ms blocks of 16kHz S16_LE audio, from ALSA or a test WAV."""
    if args.wav:
        with wave.open(args.wav, "rb") as audio:
            if audio.getsampwidth() != 2 or audio.getframerate() != 16000 or audio.getnchannels() not in (1, 2):
                raise ValueError("WAV must be 16kHz, 16-bit, mono/stereo")
            while True:
                block = audio.readframes(1600)
                if not block:
                    break
                yield mono_pcm(block, audio.getnchannels())
        return
    command = ["arecord", "-q", "-D", args.audio_device, "-t", "raw", "-f", "S16_LE",
               "-r", "16000", "-c", str(args.channels)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # UQ212 has a measured 0.3s startup saturation; never feed it to an action source.
    warmup_bytes = int(args.audio_warmup * 16000) * 2 * args.channels
    try:
        while True:
            block = process.stdout.read(3200 * args.channels)
            if not block:
                message = process.stderr.read().decode(errors="replace")
                raise RuntimeError("arecord stopped: " + message)
            if warmup_bytes:
                discard = min(warmup_bytes, len(block))
                block, warmup_bytes = block[discard:], warmup_bytes - discard
                if not block:
                    continue
            yield mono_pcm(block, args.channels)
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def speech_result(result, client, constrained=False, confidence_min=.6):
    """Keep actual decoder text visible; reject unknown/uncertain command guesses."""
    text = result.get("text", "").replace(" ", "")
    confidences = [word["conf"] for word in result.get("result", []) if "conf" in word]
    confidence = sum(confidences) / len(confidences) if confidences else None
    accepted = bool(text) and (not constrained or (
        "[unk]" not in text and text in {p.replace(" ", "") for p in SPEECH_PHRASES}
        and confidence is not None and confidence >= confidence_min))
    if not client.dry_run:
        client.request("/api/perception", {"kind": "speech", "worker_status": "running",
                       "text": text, "confidence": confidence, "accepted": accepted,
                       "speech_grammar": "commands" if constrained else "full"})
    elif text and not accepted:
        print(json.dumps({"speech_text": text, "accepted": False, "confidence": confidence},
                         ensure_ascii=False), flush=True)
    if accepted:
        client.emit({"action": "speech", "text": text}, "speech")


def run_audio(args, client):
    """ASR uses Vosk's genuine decoder; clap detection uses PCM energy."""
    recognizer = None
    if args.mode == "speech":
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        # Default live recognition is a command grammar; file regression keeps full dictation.
        grammar = getattr(args, "speech_grammar", "auto")
        constrained = grammar == "commands" or (grammar == "auto" and not args.wav)
        model = Model(args.speech_model)
        if constrained:
            recognizer = KaldiRecognizer(model, 16000,
                json.dumps(list(SPEECH_PHRASES) + ["[unk]"], ensure_ascii=False))
        else:
            recognizer = KaldiRecognizer(model, 16000)
        recognizer.SetWords(True)
    clap = ClapDetector(args.clap_threshold)
    previous_mode = None
    last_heartbeat = -math.inf
    elapsed_audio = 0.0
    for pcm in audio_chunks(args):
        now = time.monotonic()
        if not client.dry_run and now - last_heartbeat >= 2:
            client.request("/api/perception", {
                "kind": args.mode, "worker_status": "running",
                "source": "wav" if args.wav else "microphone",
                "audio_device": args.audio_device, "channels": args.channels,
                "warmup_seconds": args.audio_warmup,
                "speech_grammar": "commands" if recognizer and constrained else "full",
                **pcm_levels(pcm)})
            last_heartbeat = now
        mode = client.mode()
        active = client.dry_run or mode in MODES[args.mode]
        if recognizer and mode != previous_mode:
            recognizer.Reset()
        previous_mode = mode
        if not active:
            continue
        if recognizer:
            if recognizer.AcceptWaveform(pcm):
                speech_result(json.loads(recognizer.Result()), client, constrained,
                              getattr(args, "speech_confidence", .6))
        else:
            detected, rms = clap.update(pcm, elapsed_audio if args.wav else time.monotonic())
            if detected:
                client.emit({"action": "clap"}, "clap")
                print(json.dumps({"audio_rms": round(rms, 4)}), flush=True)
        elapsed_audio += len(pcm) / 32000
    if recognizer:
        speech_result(json.loads(recognizer.FinalResult()), client, constrained,
                      getattr(args, "speech_confidence", .6))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://192.168.112.122:8080")
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--gesture-model", default=str(ROOT / "models/gesture_recognizer.task"))
    parser.add_argument("--speech-model", default=str(ROOT / "models/vosk-model-small-cn-0.22"))
    parser.add_argument("--speech-grammar", choices=("auto", "commands", "full"), default="auto",
                        help="auto: live command vocabulary, WAV full dictation")
    parser.add_argument("--speech-confidence", type=float, default=.6,
                        help="Minimum decoder word confidence for command grammar")
    parser.add_argument("--audio-device", default="default")
    parser.add_argument("--channels", type=int, choices=(1, 2), default=1)
    parser.add_argument("--audio-warmup", type=float, default=0.5,
                        help="Discard live microphone startup seconds; WAV files stay intact")
    parser.add_argument("--clap-threshold", type=float, default=0.10)
    parser.add_argument("--fps", type=float, default=8)
    parser.add_argument("--image", help="One image instead of the RK camera; use with --dry-run")
    parser.add_argument("--wav", help="16kHz test WAV instead of a microphone")
    parser.add_argument("--dry-run", action="store_true", help="No POST and no hardware action")
    args = parser.parse_args()
    if (args.fps <= 0 or not 0 < args.clap_threshold <= 1 or args.audio_warmup < 0
            or not 0 <= args.speech_confidence <= 1):
        parser.error("fps must be positive, audio-warmup nonnegative, clap-threshold in (0,1]")
    try:
        client = Client(args.server, args.dry_run)
        (run_gestures if args.mode == "gestures" else run_audio)(args, client)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        parser.exit(1, "worker stopped: %s\n" % error)


if __name__ == "__main__":
    main()
