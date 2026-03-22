#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
NODE_BIN_DIR = ROOT_DIR / "node_modules" / ".bin"
NODE_COMPAT_SHIM = ROOT_DIR / "scripts" / "node-compat.cjs"
APP_URL = "http://127.0.0.1:3847"


def log(message: str) -> None:
    print(f"[webOS Sidecar] {message}", flush=True)


def fail(message: str) -> int:
    print(f"[webOS Sidecar] {message}", file=sys.stderr, flush=True)
    return 1


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def current_python_label() -> str:
    return f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ares_bin() -> Path:
    return NODE_BIN_DIR / ("ares.cmd" if os.name == "nt" else "ares")


def run_checked(parts: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(parts, cwd=ROOT_DIR, env=env, check=True)


def node_major_version() -> int:
    completed = subprocess.run(
        ["node", "-p", "process.versions.node.split('.')[0]"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=True,
    )
    return int(completed.stdout.strip())


def build_runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env["NO_UPDATE_NOTIFIER"] = "1"
    compat_option = f"--require={NODE_COMPAT_SHIM}"
    existing = env.get("NODE_OPTIONS", "").strip()
    if compat_option not in existing:
        env["NODE_OPTIONS"] = f"{compat_option} {existing}".strip()
    return env


def ensure_prerequisites() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    if not command_exists("node"):
        raise RuntimeError("Node.js is required.")
    if not command_exists("npm"):
        raise RuntimeError("npm is required.")


def ensure_venv() -> tuple[Path, bool]:
    created = False
    if not VENV_DIR.exists():
        log("Creating .venv")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
        created = True
    python_path = venv_python()
    if not python_path.exists():
        raise RuntimeError(f"Expected venv python at {python_path}")
    return python_path, created


def ensure_python_dependencies(python_path: Path, created_venv: bool) -> None:
    if created_venv:
        log("Upgrading pip in .venv")
        run_checked([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])
    log("Installing Python dependencies")
    run_checked([str(python_path), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])


def ensure_node_dependencies() -> None:
    if ares_bin().exists():
        return
    log("Installing @webos-tools/cli")
    run_checked(["npm", "install"])


def wait_for_ready(timeout_seconds: int = 20) -> bool:
    deadline = time.time() + timeout_seconds
    status_url = f"{APP_URL}/api/status"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(status_url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    return False


def start_server(python_path: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    parts = [
        str(python_path),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "3847",
        "--reload",
    ]
    kwargs: dict[str, object] = {
        "cwd": ROOT_DIR,
        "env": env,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["preexec_fn"] = os.setsid
    return subprocess.Popen(parts, **kwargs)


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
            time.sleep(1)
            if process.poll() is None:
                process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cross-platform launcher for webOS Sidecar.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Install and validate dependencies, but do not launch the dashboard.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the dashboard in a browser after startup.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ensure_prerequisites()
        major = node_major_version()
        log(f"{current_python_label()} detected")
        log(f"Node {major} detected")
        if major >= 25:
            log("Injecting the LG CLI compatibility shim for modern Node.")
        elif major < 20:
            log("Node 20+ is recommended. Node 22 is pinned in .nvmrc.")

        python_path, created_venv = ensure_venv()
        ensure_python_dependencies(python_path, created_venv)
        ensure_node_dependencies()

        if args.check:
            log("Checks passed. The dashboard is ready to launch.")
            return 0

        env = build_runtime_env()
        log(f"Launching dashboard on {APP_URL}")
        server = start_server(python_path, env)
    except subprocess.CalledProcessError as exc:
        return fail(f"Command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}")
    except RuntimeError as exc:
        return fail(str(exc))

    try:
        if not wait_for_ready():
            stop_server(server)
            return fail("The dashboard did not become ready in time.")
        if not args.no_browser:
            webbrowser.open(APP_URL)
        log(f"Dashboard ready at {APP_URL}")
        return server.wait()
    except KeyboardInterrupt:
        log("Stopping dashboard")
        stop_server(server)
        return 130
    finally:
        stop_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
