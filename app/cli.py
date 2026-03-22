from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
NODE_BIN_DIR = ROOT_DIR / "node_modules" / ".bin"
NODE_COMPAT_SHIM = ROOT_DIR / "scripts" / "node-compat.cjs"


def _command_path(name: str) -> str:
    candidates = [NODE_BIN_DIR / name]
    if platform.system().lower().startswith("win"):
        candidates.append(NODE_BIN_DIR / f"{name}.cmd")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return name


def _format_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def run_raw(parts: list[str], input_text: str | None = None, timeout: int = 120) -> dict[str, Any]:
    env = os.environ.copy()
    env["NO_UPDATE_NOTIFIER"] = "1"
    existing_node_options = env.get("NODE_OPTIONS", "").strip()
    compat_option = f"--require={NODE_COMPAT_SHIM}"
    if compat_option not in existing_node_options:
        env["NODE_OPTIONS"] = f"{compat_option} {existing_node_options}".strip()
    completed = subprocess.run(
        parts,
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    return {
        "command": _format_command(parts),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "combined": "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip(),
    }


def run_cli(command_name: str, *args: str, input_text: str | None = None, timeout: int = 120) -> dict[str, Any]:
    return run_raw([_command_path(command_name), *args], input_text=input_text, timeout=timeout)


def parse_json_blob(raw_text: str) -> Any:
    match = re.search(r"(\{.*\}|\[.*\])", raw_text, re.DOTALL)
    if not match:
        raise ValueError("No JSON payload found in CLI output.")
    return json.loads(match.group(1))


def parse_key_value_lines(raw_text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        cleaned = value.strip().rstrip(",").strip()
        if cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1]
        data[normalized] = cleaned
    return data


def parse_named_json_sections(raw_text: str) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    pattern = re.compile(r"<\s*([^>]+)\s*>\s*(\{.*?\})(?=\n\s*<|\Z)", re.DOTALL)
    for name, block in pattern.findall(raw_text):
        try:
            sections[name.strip()] = json.loads(block)
        except json.JSONDecodeError:
            continue
    return sections


def cli_health() -> dict[str, Any]:
    node = run_raw(["node", "--version"])
    npm = run_raw(["npm", "--version"])
    ares = run_cli("ares", "--version")
    return {
        "node": node,
        "npm": npm,
        "ares": ares,
        "ok": node["returncode"] == 0 and npm["returncode"] == 0 and ares["returncode"] == 0,
    }


def list_devices() -> list[dict[str, Any]]:
    result = run_cli("ares-setup-device", "--listfull")
    if result["returncode"] != 0:
        raise RuntimeError(result["combined"] or "Failed to list devices.")
    payload = parse_json_blob(result["stdout"] or result["combined"])
    return payload if isinstance(payload, list) else []


def upsert_device(
    name: str,
    host: str,
    port: int = 9922,
    username: str = "prisoner",
    description: str = "LG webOS TV",
    set_default: bool = True,
) -> dict[str, Any]:
    existing = {device.get("name"): device for device in list_devices()}
    info_args = [
        "-i",
        f"host={host}",
        "-i",
        f"port={port}",
        "-i",
        f"username={username}",
        "-i",
        f"description={description}",
        "-i",
        "password=",
        "-i",
        "privatekey=",
        "-i",
        "passphrase=",
    ]
    if name in existing:
        remove_result = run_cli("ares-setup-device", "-r", name)
        if remove_result["returncode"] != 0:
            raise RuntimeError(remove_result["combined"] or f"Failed to replace {name}.")
    if set_default:
        info_args.extend(["-i", "default=true"])
    result = run_cli("ares-setup-device", "-a", name, *info_args)
    if result["returncode"] != 0:
        raise RuntimeError(result["combined"] or "Failed to save device.")
    if set_default:
        set_default_device(name)
    return result


def set_device_privatekey(device_name: str, privatekey_name: str) -> dict[str, Any]:
    result = run_cli("ares-setup-device", "-m", device_name, "-i", f"privatekey={privatekey_name}")
    if result["returncode"] != 0:
        raise RuntimeError(result["combined"] or f"Failed to set the private key for {device_name}.")
    return result


def set_device_auth(device_name: str, privatekey_name: str, passphrase: str) -> dict[str, Any]:
    result = run_cli(
        "ares-setup-device",
        "-m",
        device_name,
        "-i",
        f"privatekey={privatekey_name}",
        "-i",
        f"passphrase={passphrase}",
    )
    if result["returncode"] != 0:
        raise RuntimeError(result["combined"] or f"Failed to save the SSH credentials for {device_name}.")
    return result


def set_default_device(name: str) -> dict[str, Any]:
    result = run_cli("ares-setup-device", "-f", name)
    if result["returncode"] != 0:
        raise RuntimeError(result["combined"] or f"Failed to set {name} as default device.")
    return result


def remove_device(name: str) -> dict[str, Any]:
    result = run_cli("ares-setup-device", "-r", name)
    if result["returncode"] != 0:
        raise RuntimeError(result["combined"] or f"Failed to remove {name}.")
    return result


def get_key(device_name: str, passphrase: str) -> dict[str, Any]:
    return run_cli(
        "ares-novacom",
        "--device",
        device_name,
        "--getkey",
        input_text=f"{passphrase}\n",
        timeout=180,
    )


def system_info(device_name: str) -> dict[str, Any]:
    return run_cli("ares-device", "--system-info", "--device", device_name, timeout=120)


def list_installed(device_name: str, detailed: bool = False) -> dict[str, Any]:
    args = ["-F", "-l"] if detailed else ["-l"]
    return run_cli("ares-install", *args, "--device", device_name, timeout=120)


def install_package(device_name: str, package_path: Path) -> dict[str, Any]:
    return run_cli("ares-install", str(package_path), "--device", device_name, timeout=300)


def launch_app(device_name: str, app_id: str) -> dict[str, Any]:
    return run_cli("ares-launch", app_id, "--device", device_name, timeout=120)


def inspect_package(package_path: Path) -> dict[str, Any]:
    result = run_cli("ares-package", "-I", str(package_path), timeout=120)
    control_block = result["combined"].split("< packageinfo.json >", 1)[0]
    facts = parse_key_value_lines(control_block)
    sections = parse_named_json_sections(result["combined"])
    return {"result": result, "facts": facts, "sections": sections}


def package_app_dir(app_dir: Path, output_dir: Path) -> dict[str, Any]:
    started_at = time.time()
    result = run_cli("ares-package", str(app_dir), "-o", str(output_dir), timeout=300)
    candidates = sorted(output_dir.glob("*.ipk"), key=lambda path: path.stat().st_mtime if path.exists() else 0)
    fresh_files = [path for path in candidates if path.exists() and path.stat().st_mtime >= started_at - 1]
    package_path = (fresh_files or candidates or [None])[-1]
    return {
        "result": result,
        "package_path": package_path,
    }
