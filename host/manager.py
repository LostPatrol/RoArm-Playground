"""Discover and load local interaction models for the RK webpage; supervise workers."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent


class Manager:
    """Own model processes; restarts keep a transient RK outage from disabling gestures."""
    def __init__(self, server, log_dir, director_port=8081):
        self.server = server.rstrip("/")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.director_port = director_port
        self.processes, self.desired, self.logs, self.last_launch = {}, set(), {}, {}
        self.lock = threading.RLock()

    def requirements(self, worker):
        """Report concrete missing artifacts; never download or install during an HTTP request."""
        if worker == "gestures":
            model = ROOT / "models/gesture_recognizer.task"
            missing = [name for name in ("mediapipe", "cv2", "numpy")
                       if importlib.util.find_spec(name) is None]
            setup = ".venv/bin/python -m pip install -r host/requirements.txt; bash scripts/fetch_interaction_models.sh gestures"
        elif worker == "director":
            model = Path(os.environ.get("DIRECTOR_MODEL_FILE", str(ROOT / "models/qwen2.5-1.5b-instruct-q4_k_m.gguf")))
            source = Path(os.environ.get("LLAMA_SOURCE_DIR", str(ROOT / "agent/codex/llama.cpp-b4514")))
            binary = Path(os.environ.get("LLAMA_SERVER", str(source / "build-cpu/bin/llama-server")))
            missing = [] if binary.is_file() else [str(binary)]
            setup = "bash scripts/fetch_interaction_models.sh llm; bash host/build_director.sh cpu"
        else:
            raise ValueError("worker must be gestures or director")
        return {"model": str(model), "model_exists": model.is_file(),
                "missing_dependencies": missing, "setup": setup, "project_dir": str(ROOT)}

    def director_ready(self):
        """Probe real llama.cpp readiness, independent of a merely live PID."""
        try:
            with build_opener(ProxyHandler({})).open(
                    "http://127.0.0.1:%d/health" % self.director_port, timeout=1) as response:
                return json.load(response).get("status") == "ok"
        except (OSError, ValueError):
            return False

    def status(self):
        with self.lock:
            workers = {}
            for worker in ("gestures", "director"):
                process = self.processes.get(worker)
                alive = process is not None and process.poll() is None
                loaded = self.director_ready() if worker == "director" else False
                if worker == "gestures" and alive and worker in self.logs:
                    loaded = '"worker_status": "ready"' in self.logs[worker].read_text(errors="replace")
                workers[worker] = {**self.requirements(worker), "running": alive,
                    "ready": loaded, "pid": process.pid if alive else None,
                    "exit_code": process.poll() if process is not None and not alive else None,
                    "log": str(self.logs[worker]) if worker in self.logs else "",
                    "status": "ready" if loaded else "loading" if alive else "stopped"}
            return {"service": "roarm-host-manager", "server": self.server,
                    "director_port": self.director_port, "workers": workers}

    def start(self, worker, server=None):
        """Start only known modules; loading does not activate a robot interaction mode."""
        with self.lock:
            requirements = self.requirements(worker)
            if server:
                parsed = urlsplit(server)
                if parsed.scheme != "http" or not parsed.hostname or parsed.path not in ("", "/"):
                    raise ValueError("server must be an HTTP RK root URL")
                if worker == "gestures" and server.rstrip("/") != self.server:
                    old = self.processes.get(worker)
                    if old and old.poll() is None:
                        old.terminate()
                        old.wait(timeout=3)
                    self.server = server.rstrip("/")
            if worker == "director" and self.director_ready():
                return self.status()
            if not requirements["model_exists"] or requirements["missing_dependencies"]:
                raise RuntimeError("模型/依赖未安装：%s；工程目录 %s；运行 %s" %
                    (requirements["model"], ROOT, requirements["setup"]))
            self.desired.add(worker)
            process = self.processes.get(worker)
            if process and process.poll() is None:
                return self.status()
            log_path = self.log_dir / ("%s-%s.log" % (worker, time.time_ns()))
            command = ([sys.executable, "-m", "host.worker", "--server", self.server,
                        "--mode", "gestures"] if worker == "gestures" else
                       ["bash", str(ROOT / "host/run_director.sh"), "cpu"])
            environment = dict(os.environ, DIRECTOR_HOST="0.0.0.0",
                               DIRECTOR_PORT=str(self.director_port), PYTHONUNBUFFERED="1")
            with log_path.open("ab") as log:
                self.processes[worker] = subprocess.Popen(command, cwd=str(ROOT), env=environment,
                    stdout=log, stderr=subprocess.STDOUT)
            self.logs[worker], self.last_launch[worker] = log_path, time.monotonic()
            return self.status()

    def supervise(self, stop):
        """Retry after 5 seconds, including failed initialization and transient camera errors."""
        while not stop.wait(2):
            with self.lock:
                for worker in tuple(self.desired):
                    process = self.processes.get(worker)
                    if process and process.poll() is not None and time.monotonic() - self.last_launch[worker] >= 5:
                        try:
                            self.start(worker)
                        except (OSError, ValueError, RuntimeError) as error:
                            print("worker restart failed: %s" % error, flush=True)

    def close(self):
        """Only stop processes created by this manager; external model services stay intact."""
        with self.lock:
            self.desired.clear()
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def handler_for(manager):
    """Small LAN API consumed through the RK backend, avoiding browser localhost restrictions."""
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/api/status":
                return self.reply(404, {"error": "unknown endpoint"})
            self.reply(200, manager.status())

        def do_POST(self):
            if self.path != "/api/start":
                return self.reply(404, {"error": "unknown endpoint"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 4096:
                    raise ValueError("invalid body size")
                data = json.loads(self.rfile.read(length))
                self.reply(200, manager.start(data.get("worker"), data.get("server")))
            except (ValueError, TypeError, AttributeError) as error:
                self.reply(400, {"error": str(error)})
            except (OSError, RuntimeError) as error:
                self.reply(503, {"error": str(error), **manager.status()})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--server", default="http://192.168.112.122:8080")
    parser.add_argument("--director-port", type=int, default=8081)
    parser.add_argument("--log-dir", default=str(ROOT / "agent/codex/host-manager"))
    parser.add_argument("--start-director", action="store_true")
    args = parser.parse_args()
    manager = Manager(args.server, args.log_dir, args.director_port)
    stop = threading.Event()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(manager))
    if args.start_director:
        try:
            manager.start("director")
        except (OSError, RuntimeError) as error:
            print("director startup: %s" % error, flush=True)
    thread = threading.Thread(target=manager.supervise, args=(stop,), daemon=True)
    thread.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        thread.join()
        manager.close()
        server.server_close()


if __name__ == "__main__":
    main()
