from __future__ import annotations

import json
import re
import shutil
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cli import (
    cli_health,
    get_key,
    inspect_package,
    install_package,
    launch_app,
    list_devices,
    list_installed,
    package_app_dir,
    parse_key_value_lines,
    remove_device,
    set_device_auth,
    set_default_device,
    system_info,
    upsert_device,
)
from .github_release import download_asset, resolve_source
from .troubleshooting import build_troubleshooting


BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
RUNTIME_DIR = BASE_DIR / "runtime"
ARTIFACTS_DIR = RUNTIME_DIR / "artifacts"
UNPACKED_DIR = RUNTIME_DIR / "unpacked"
ARTIFACTS_INDEX = RUNTIME_DIR / "artifacts.json"
HISTORY_INDEX = RUNTIME_DIR / "history.json"


def ensure_runtime_dirs() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    UNPACKED_DIR.mkdir(parents=True, exist_ok=True)
    if not ARTIFACTS_INDEX.exists():
        ARTIFACTS_INDEX.write_text("[]\n", encoding="utf-8")
    if not HISTORY_INDEX.exists():
        HISTORY_INDEX.write_text("[]\n", encoding="utf-8")


ensure_runtime_dirs()

app = FastAPI(title="webOS Sidecar", version="0.2.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class DevicePayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=128)
    port: int = 9922
    username: str = "prisoner"
    description: str = "LG webOS TV"
    set_default: bool = True


class PassphrasePayload(BaseModel):
    passphrase: str = Field(min_length=1, max_length=32)


class DefaultPayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SourcePayload(BaseModel):
    source: str = Field(min_length=1, max_length=500)


class DownloadPayload(BaseModel):
    url: str = Field(min_length=1, max_length=500)


class InstallPayload(BaseModel):
    device_name: str = Field(min_length=1, max_length=64)
    artifact_id: str = Field(min_length=1, max_length=64)
    launch_after_install: bool = True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_artifacts() -> list[dict[str, Any]]:
    records = load_json(ARTIFACTS_INDEX)
    live = [record for record in records if Path(record["path"]).exists()]
    if len(live) != len(records):
        write_json(ARTIFACTS_INDEX, live)
    return sorted(live, key=lambda record: record["created_at"], reverse=True)


def read_history() -> list[dict[str, Any]]:
    return sorted(load_json(HISTORY_INDEX), key=lambda record: record["created_at"], reverse=True)


def append_history(title: str, status: str, summary: str, details: dict[str, Any] | None = None) -> None:
    history = read_history()
    history.append(
        {
            "id": uuid.uuid4().hex[:10],
            "title": title,
            "status": status,
            "summary": summary,
            "details": details or {},
            "created_at": utc_now(),
        }
    )
    history = history[-20:]
    write_json(HISTORY_INDEX, history)


def save_artifact_record(record: dict[str, Any]) -> dict[str, Any]:
    records = read_artifacts()
    records = [item for item in records if item["id"] != record["id"]]
    records.append(record)
    write_json(ARTIFACTS_INDEX, records)
    return record


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned or f"artifact-{uuid.uuid4().hex[:8]}"


def package_summary(package_path: Path) -> dict[str, Any]:
    inspection = inspect_package(package_path)
    facts = inspection["facts"]
    packageinfo = inspection["sections"].get("packageinfo.json", {})
    appinfo = inspection["sections"].get("appinfo.json", {})
    return {
        "app_id": appinfo.get("id") or packageinfo.get("app") or packageinfo.get("id") or facts.get("package"),
        "version": appinfo.get("version") or packageinfo.get("version") or facts.get("version"),
        "title": appinfo.get("title"),
        "cli_output": inspection["result"]["combined"],
    }


def build_artifact_record(
    package_path: Path,
    source_kind: str,
    source_label: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    summary = package_summary(package_path)
    return {
        "id": uuid.uuid4().hex[:10],
        "filename": package_path.name,
        "path": str(package_path.resolve()),
        "size": package_path.stat().st_size,
        "source_kind": source_kind,
        "source_label": source_label,
        "warnings": warnings or [],
        "app_id": summary["app_id"],
        "version": summary["version"],
        "title": summary["title"],
        "created_at": utc_now(),
        "inspect_output": summary["cli_output"],
    }


def response_or_error(
    result: dict[str, Any],
    stage: str,
    suffix: str | None = None,
    file_suffix: str | None = None,
) -> None:
    resolved_suffix = file_suffix if file_suffix is not None else suffix
    if result["returncode"] == 0:
        return
    troubleshooting = build_troubleshooting(stage, result["combined"], file_suffix=resolved_suffix)
    raise HTTPException(
        status_code=400,
        detail={
            "message": result["combined"] or f"{stage} failed.",
            "troubleshooting": troubleshooting,
            "command": result["command"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        },
    )


def parse_system_info_output(raw_text: str) -> dict[str, str]:
    return parse_key_value_lines(raw_text)


def parse_privatekey_path(raw_text: str) -> Path | None:
    match = re.search(r"SSH Private Key:\s*(\S+)", raw_text)
    if not match:
        return None
    return Path(match.group(1)).expanduser()


def normalize_tv_passphrase(value: str) -> str:
    return value.strip().upper()


def resolve_privatekey_path(device_name: str, raw_text: str) -> Path | None:
    parsed = parse_privatekey_path(raw_text)
    if parsed is not None:
        return parsed

    fallback = Path.home() / ".ssh" / f"{device_name}_webos"
    if fallback.exists():
        return fallback
    return None


def clear_cached_privatekeys(device_name: str) -> list[Path]:
    removed: list[Path] = []
    candidates = {Path.home() / ".ssh" / f"{device_name}_webos"}
    saved_device = find_device_record(device_name)
    if saved_device is not None:
        saved_name = ((saved_device.get("details") or {}).get("privatekey") or "").strip()
        if saved_name:
            candidates.add(Path.home() / ".ssh" / saved_name)

    for candidate in candidates:
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate)
    return removed


def find_device_record(device_name: str) -> dict[str, Any] | None:
    return next((device for device in list_devices() if device.get("name") == device_name), None)


def device_link_issues(
    device: dict[str, Any] | None,
    *,
    expected_privatekey_name: str | None = None,
    require_passphrase: bool = False,
) -> list[str]:
    if device is None:
        return ["The saved TV entry no longer exists in the LG CLI device list."]

    details = device.get("details") or {}
    deviceinfo = device.get("deviceinfo") or {}
    issues: list[str] = []
    privatekey_name = (details.get("privatekey") or "").strip()
    passphrase = (details.get("passphrase") or "").strip()
    username = (deviceinfo.get("user") or deviceinfo.get("username") or "").strip()

    if expected_privatekey_name and privatekey_name != expected_privatekey_name:
        issues.append(
            f"The saved TV entry still points to {privatekey_name or 'no private key'}, not {expected_privatekey_name}."
        )

    if not privatekey_name:
        issues.append("The saved TV entry does not have an SSH private key name yet.")
    else:
        privatekey_path = Path.home() / ".ssh" / privatekey_name
        if not privatekey_path.exists():
            issues.append(f"The saved SSH private key file is missing: {privatekey_path}")

    if require_passphrase and username == "prisoner" and not passphrase:
        issues.append("The saved TV entry does not have the 6-character Key Server passphrase yet.")

    return issues


def verify_install(device_name: str, app_id: str | None) -> dict[str, Any]:
    listing = list_installed(device_name, detailed=True)
    verified = bool(app_id) and app_id in listing["combined"]
    return {
        "verified": verified,
        "app_id": app_id,
        "listing": listing,
    }


def should_retry_connection(raw_text: str) -> bool:
    lowered = raw_text.lower()
    return any(
        token in lowered
        for token in [
            "authentication",
            "publickey",
            "ssh exec failure",
            "all configured authentication methods failed",
            "timed out",
            "timeout",
            "refused",
        ]
    )


def probe_system_info(device_name: str, retries: int = 3, delay_seconds: float = 1.0) -> dict[str, Any]:
    latest = {"returncode": 1, "combined": "No connection probe attempted."}
    for attempt in range(retries):
        latest = system_info(device_name)
        if latest["returncode"] == 0:
            return latest
        if attempt < retries - 1 and should_retry_connection(latest["combined"]):
            time.sleep(delay_seconds)
            continue
        return latest
    return latest


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            member_path = destination / member.filename
            if not member_path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError("The uploaded zip contains an unsafe path.")
        archive.extractall(destination)


def find_packable_root(root: Path) -> Path:
    candidates = sorted(root.rglob("appinfo.json"), key=lambda path: len(path.parts))
    if not candidates:
        raise RuntimeError("No appinfo.json file was found in the uploaded archive.")
    return candidates[0].parent


def dashboard_state() -> dict[str, Any]:
    try:
        devices = list_devices()
    except Exception as exc:  # noqa: BLE001
        devices = []
    return {
        "server_time": utc_now(),
        "python_version": sys.version.split()[0],
        "cli": cli_health(),
        "devices": devices,
        "artifacts": read_artifacts(),
        "history": read_history(),
        "official_note": "LG webOS TV developer installs use .ipk packages over Developer Mode on port 9922.",
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content={"ok": False, **exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "message": str(exc.detail)})


@app.exception_handler(Exception)
async def unexpected_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    message = str(exc) or "Unexpected server error."
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "message": message,
            "troubleshooting": build_troubleshooting("server", message),
            "stage": "server",
        },
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(WEB_DIR / "favicon.svg")


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return {"ok": True, **dashboard_state()}


@app.get("/api/devices")
async def api_devices() -> dict[str, Any]:
    return {"ok": True, "devices": list_devices()}


@app.post("/api/devices")
async def api_upsert_device(payload: DevicePayload) -> dict[str, Any]:
    try:
        result = upsert_device(
            name=payload.name,
            host=payload.host,
            port=payload.port,
            username=payload.username,
            description=payload.description,
            set_default=payload.set_default,
        )
    except Exception as exc:  # noqa: BLE001
        output = str(exc)
        raise HTTPException(
            status_code=400,
            detail={
                "message": output,
                "troubleshooting": build_troubleshooting("device-setup", output),
            },
        ) from exc
    append_history("TV saved", "success", f"{payload.name} now points to {payload.host}:9922")
    return {"ok": True, "result": result, "devices": list_devices()}


@app.post("/api/devices/default")
async def api_default_device(payload: DefaultPayload) -> dict[str, Any]:
    result = set_default_device(payload.name)
    response_or_error(result, "device-setup")
    append_history("Default TV updated", "success", f"{payload.name} is now the default target.")
    return {"ok": True, "result": result, "devices": list_devices()}


@app.delete("/api/devices/{device_name}")
async def api_delete_device(device_name: str) -> dict[str, Any]:
    result = remove_device(device_name)
    response_or_error(result, "device-setup")
    append_history("TV removed", "success", f"{device_name} was removed from the CLI device list.")
    return {"ok": True, "result": result, "devices": list_devices()}


@app.post("/api/devices/{device_name}/key")
async def api_get_key(device_name: str, payload: PassphrasePayload) -> dict[str, Any]:
    normalized_passphrase = normalize_tv_passphrase(payload.passphrase)
    cleared_keys = clear_cached_privatekeys(device_name)
    key_result = get_key(device_name, normalized_passphrase)
    steps = []
    if cleared_keys:
        cleared_text = "\n".join(str(path) for path in cleared_keys)
        steps.append(
            {
                "label": "Clear stale local key",
                "ok": True,
                "command": f"Remove cached ~/.ssh key files for {device_name}",
                "combined": f"Removed old key files before fetching a fresh key:\n{cleared_text}",
                "stdout": cleared_text,
                "stderr": "",
            }
        )
    steps.append({"label": "Get key", "ok": key_result["returncode"] == 0, **key_result})
    if key_result["returncode"] != 0:
        raise HTTPException(
            status_code=400,
            detail={
                "message": key_result["combined"] or "Failed to get the SSH key from the TV.",
                "troubleshooting": build_troubleshooting("key-exchange", key_result["combined"]),
                "steps": steps,
                "stage": "key-link",
            },
        )

    privatekey_path = resolve_privatekey_path(device_name, key_result["combined"])
    if privatekey_path is None:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "The TV returned a key exchange response, but the dashboard could not locate the generated SSH key file.",
                "troubleshooting": build_troubleshooting(
                    "key-exchange",
                    "private key file or password does not exist\nmissing key path after getkey",
                ),
                "steps": steps,
                "stage": "key-link",
            },
        )

    try:
        auth_result = set_device_auth(device_name, privatekey_path.name, normalized_passphrase)
        saved_device = find_device_record(device_name)
        saved_issues = device_link_issues(
            saved_device,
            expected_privatekey_name=privatekey_path.name,
            require_passphrase=True,
        )
        register_step = {
            "label": "Register device credentials",
            "ok": not saved_issues,
            "command": f"ares-setup-device -m {device_name} -i privatekey={privatekey_path.name} -i passphrase=******",
            "combined": (
                f"{auth_result['combined']}\n"
                f"Saved private key: {(saved_device or {}).get('details', {}).get('privatekey') or '(missing)'}\n"
                f"Saved passphrase: {'yes' if (saved_device or {}).get('details', {}).get('passphrase') else 'no'}\n"
                f"Key path: {privatekey_path}"
            ).strip(),
            "stdout": auth_result["stdout"],
            "stderr": auth_result["stderr"],
        }
        steps.append(register_step)
        if not privatekey_path.exists():
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"The key exchange reported {privatekey_path}, but that file does not exist yet.",
                    "troubleshooting": build_troubleshooting(
                        "key-exchange",
                        f"private key file or password does not exist\nmissing key path: {privatekey_path}",
                    ),
                    "steps": steps,
                    "stage": "key-link",
                },
            )
        if saved_issues:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": saved_issues[0],
                    "troubleshooting": build_troubleshooting(
                        "key-exchange",
                        "private key file or password does not exist\n" + "\n".join(saved_issues),
                    ),
                    "steps": steps,
                    "stage": "key-link",
                },
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "troubleshooting": build_troubleshooting("key-exchange", str(exc)),
                "steps": steps,
                "stage": "key-link",
            },
        ) from exc

    info_result = probe_system_info(device_name)
    steps.append({"label": "Verify connection", "ok": info_result["returncode"] == 0, **info_result})
    if info_result["returncode"] != 0:
        raise HTTPException(
            status_code=400,
            detail={
                "message": info_result["combined"] or "The TV rejected the saved SSH key during verification.",
                "troubleshooting": build_troubleshooting("connection-check", info_result["combined"]),
                "steps": steps,
                "stage": "key-link",
            },
        )

    system_details = parse_system_info_output(info_result["combined"])
    append_history("TV linked", "success", f"SSH key exchange completed for {device_name}.")
    return {
        "ok": True,
        "key_result": key_result,
        "system_info": info_result,
        "system_details": system_details,
        "steps": steps,
    }


@app.get("/api/devices/{device_name}/system-info")
async def api_system_info(device_name: str) -> dict[str, Any]:
    result = system_info(device_name)
    response_or_error(result, "connection-check")
    return {"ok": True, "raw": result, "details": parse_system_info_output(result["combined"])}


@app.post("/api/sources/resolve")
async def api_resolve_source(payload: SourcePayload) -> dict[str, Any]:
    try:
        resolved = resolve_source(payload.source)
    except Exception as exc:  # noqa: BLE001
        output = str(exc)
        raise HTTPException(
            status_code=400,
            detail={"message": output, "troubleshooting": build_troubleshooting("download", output)},
        ) from exc
    asset_count = len(resolved.get("assets", []))
    status = "success" if asset_count else "warning"
    summary = resolved.get("advisory") or f"Found {asset_count} installable asset(s)."
    append_history("Release resolved", status, summary, resolved)
    return {"ok": True, "resolved": resolved}


@app.post("/api/sources/download")
async def api_download_source(payload: DownloadPayload) -> dict[str, Any]:
    try:
        package_path = download_asset(payload.url, ARTIFACTS_DIR)
        record = save_artifact_record(build_artifact_record(package_path, "download", payload.url))
    except Exception as exc:  # noqa: BLE001
        output = str(exc)
        raise HTTPException(
            status_code=400,
            detail={"message": output, "troubleshooting": build_troubleshooting("download", output)},
        ) from exc
    append_history("Package downloaded", "success", f"{record['filename']} is ready to install.", record)
    return {"ok": True, "artifact": record, "artifacts": read_artifacts()}


@app.post("/api/artifacts/upload")
async def api_upload_artifact(file: UploadFile = File(...), source_label: str = Form("upload")) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    safe_name = safe_filename(file.filename or f"upload-{uuid.uuid4().hex[:8]}")
    upload_path = ARTIFACTS_DIR / safe_name
    with upload_path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    if suffix == ".wgt":
        upload_path.unlink(missing_ok=True)
        message = "LG webOS TV sideloading expects an .ipk package, not a .wgt."
        raise HTTPException(
            status_code=400,
            detail={"message": message, "troubleshooting": build_troubleshooting("upload", message, file_suffix=suffix)},
        )

    if suffix == ".ipk":
        record = save_artifact_record(build_artifact_record(upload_path, "upload", source_label))
        append_history("Package uploaded", "success", f"{record['filename']} is queued for installation.", record)
        return {"ok": True, "artifact": record, "artifacts": read_artifacts()}

    if suffix != ".zip":
        upload_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Upload an .ipk package or a .zip that contains a buildable webOS app.",
                "troubleshooting": build_troubleshooting("upload", "unsupported upload type"),
            },
        )

    extract_dir = UNPACKED_DIR / uuid.uuid4().hex[:10]
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        safe_extract_zip(upload_path, extract_dir)
        app_dir = find_packable_root(extract_dir)
        packaged = package_app_dir(app_dir, ARTIFACTS_DIR)
        response_or_error(packaged["result"], "package")
        if not packaged["package_path"]:
            raise RuntimeError("Packaging finished without producing an .ipk file.")
        record = save_artifact_record(
            build_artifact_record(
                packaged["package_path"],
                "zip-package",
                source_label,
                warnings=["Packaged from an uploaded zip archive."],
            )
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        output = str(exc)
        raise HTTPException(
            status_code=400,
            detail={"message": output, "troubleshooting": build_troubleshooting("package", output)},
        ) from exc
    finally:
        upload_path.unlink(missing_ok=True)
    append_history("Zip packaged", "success", f"{record['filename']} was built from a zip upload.", record)
    return {"ok": True, "artifact": record, "artifacts": read_artifacts()}


@app.get("/api/artifacts")
async def api_artifacts() -> dict[str, Any]:
    return {"ok": True, "artifacts": read_artifacts()}


@app.get("/api/history")
async def api_history() -> dict[str, Any]:
    return {"ok": True, "history": read_history()}


@app.post("/api/install")
async def api_install(payload: InstallPayload) -> dict[str, Any]:
    artifact = next((item for item in read_artifacts() if item["id"] == payload.artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail={"message": "That artifact no longer exists."})

    saved_device = find_device_record(payload.device_name)
    preflight_issues = device_link_issues(saved_device, require_passphrase=True)
    if preflight_issues:
        raise HTTPException(
            status_code=400,
            detail={
                "message": preflight_issues[0],
                "troubleshooting": build_troubleshooting(
                    "install",
                    "private key file or password does not exist\n" + "\n".join(preflight_issues),
                ),
                "steps": [
                    {
                        "label": "Preflight",
                        "ok": False,
                        "command": f"Validate saved TV credentials for {payload.device_name}",
                        "combined": "\n".join(preflight_issues),
                    }
                ],
            },
        )

    package_path = Path(artifact["path"])
    install_result = install_package(payload.device_name, package_path)
    response_or_error(install_result, "install", file_suffix=package_path.suffix.lower())

    verification = verify_install(payload.device_name, artifact.get("app_id"))
    steps = [
        {"label": "Install", "ok": True, **install_result},
        {"label": "Verify", "ok": verification["verified"], **verification["listing"]},
    ]

    launch_result = None
    if verification["verified"] and payload.launch_after_install and artifact.get("app_id"):
        launch_result = launch_app(payload.device_name, artifact["app_id"])
        response_or_error(launch_result, "launch")
        steps.append({"label": "Launch", "ok": True, **launch_result})

    if verification["verified"]:
        append_history(
            "Install verified",
            "success",
            f"{artifact.get('app_id') or artifact['filename']} is confirmed on {payload.device_name}.",
            {"device_name": payload.device_name, "artifact": artifact},
        )
    else:
        append_history(
            "Install needs manual confirmation",
            "warning",
            f"{artifact['filename']} installed, but verification could not confirm the app id on {payload.device_name}.",
            {"device_name": payload.device_name, "artifact": artifact},
        )

    troubleshooting = []
    if not verification["verified"]:
        troubleshooting = build_troubleshooting(
            "verify",
            verification["listing"]["combined"] or "verification could not find the app id in the installed app list",
        )

    return {
        "ok": True,
        "artifact": artifact,
        "device_name": payload.device_name,
        "verified": verification["verified"],
        "app_id": artifact.get("app_id"),
        "steps": steps,
        "launch_result": launch_result,
        "troubleshooting": troubleshooting,
    }
