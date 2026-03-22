from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "webos-sidecar",
}


def _open_json(url: str, allow_404: bool = False) -> Any:
    request = urllib.request.Request(url, headers=GITHUB_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore")
        if allow_404 and exc.code == 404:
            return None
        raise RuntimeError(payload or f"GitHub API returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error while reaching {url}: {exc.reason}") from exc


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=GITHUB_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
            handle.write(response.read())
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(payload or f"Download failed with HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error while downloading {url}: {exc.reason}") from exc


def normalize_source(source: str) -> dict[str, str | None]:
    cleaned = source.strip().rstrip("/")
    if not cleaned:
        return {"kind": "empty"}
    if cleaned.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            if cleaned.lower().endswith(".ipk"):
                return {"kind": "direct-ipk", "url": cleaned}
            return {"kind": "unsupported"}
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 1:
            return {"kind": "owner", "owner": parts[0]}
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1].removesuffix(".git")
            tag = None
            if len(parts) >= 5 and parts[2] == "releases" and parts[3] == "tag":
                tag = parts[4]
            return {"kind": "repo", "owner": owner, "repo_name": repo, "repo": f"{owner}/{repo}", "tag": tag}
        return {"kind": "unsupported"}
    if cleaned.lower().endswith(".ipk"):
        return {"kind": "direct-ipk", "url": cleaned}
    if re.fullmatch(r"[\w.-]+/[\w.-]+", cleaned):
        owner, repo = cleaned.split("/", 1)
        return {"kind": "repo", "owner": owner, "repo_name": repo, "repo": cleaned, "tag": None}
    if re.fullmatch(r"[\w.-]+", cleaned):
        return {"kind": "owner", "owner": cleaned}
    return {"kind": "unsupported"}


def _list_owner_repos(owner: str) -> list[dict[str, Any]]:
    endpoints = [
        f"https://api.github.com/orgs/{owner}/repos?per_page=30&sort=updated",
        f"https://api.github.com/users/{owner}/repos?per_page=30&sort=updated",
    ]
    for endpoint in endpoints:
        payload = _open_json(endpoint, allow_404=True)
        if isinstance(payload, list):
            return payload
    raise RuntimeError(f"GitHub owner or organization '{owner}' was not found.")


def _repo_rank(repo: dict[str, Any]) -> tuple[int, str]:
    name = str(repo.get("name", "")).lower()
    keywords = ["webos", "smart-tv", "smart", "tv", "lg"]
    score = sum(10 for keyword in keywords if keyword in name)
    return (-score, str(repo.get("pushed_at", "")))


def _latest_release(repo: str, tag: str | None = None) -> dict[str, Any] | None:
    if tag:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    payload = _open_json(url, allow_404=True)
    return payload if isinstance(payload, dict) else None


def _extract_ipk_assets(release_payload: dict[str, Any], repo: str) -> list[dict[str, Any]]:
    release_name = release_payload.get("name") or release_payload.get("tag_name") or "GitHub release"
    tag_name = release_payload.get("tag_name")
    assets = []
    for asset in release_payload.get("assets", []):
        name = asset.get("name") or ""
        if name.lower().endswith(".ipk"):
            assets.append(
                {
                    "name": name,
                    "download_url": asset.get("browser_download_url"),
                    "size": asset.get("size"),
                    "repo": repo,
                    "tag_name": tag_name,
                    "release_name": release_name,
                    "release_url": release_payload.get("html_url"),
                }
            )
    return assets


def _resolve_repo(repo: str, tag: str | None = None) -> dict[str, Any]:
    release_payload = _latest_release(repo, tag=tag)
    if not release_payload:
        return {
            "kind": "github-repo",
            "repo": repo,
            "assets": [],
            "advisory": f"{repo} is reachable, but GitHub does not show a public latest release for it yet.",
            "help_steps": [
                "If this is an organization or user page, paste that full owner URL instead so the dashboard can scan its repos.",
                "If the project publishes a direct .ipk asset somewhere else, paste that exact asset URL.",
                "If you only have source code, upload a zip and let the dashboard package the webOS app.",
            ],
        }

    assets = _extract_ipk_assets(release_payload, repo)
    if assets:
        help_steps = [
            "Pick the .ipk asset and download it into the dashboard.",
            "If the same release also ships .wgt files, ignore those for LG TVs.",
        ]
        if repo.lower() == "moazsalem/litefin":
            help_steps = [
                "Choose the Litefin webOS .ipk that matches your TV generation: es6-webos for newer webOS builds, legacy-webos for older sets, ultra-legacy-webos for the oldest supported models.",
                "Ignore Litefin .wgt files here because those are for Samsung/Tizen, not LG webOS.",
                "Download the chosen .ipk into the dashboard, then install it after the TV link check passes.",
            ]
        return {
            "kind": "github-repo",
            "repo": repo,
            "tag_name": release_payload.get("tag_name"),
            "release_name": release_payload.get("name") or release_payload.get("tag_name"),
            "assets": assets,
            "advisory": f"Found {len(assets)} LG/webOS .ipk asset(s) in {repo}.",
            "help_steps": help_steps,
        }

    return {
        "kind": "github-repo",
        "repo": repo,
        "tag_name": release_payload.get("tag_name"),
        "release_name": release_payload.get("name") or release_payload.get("tag_name"),
        "assets": [],
        "advisory": f"{repo} has a latest release, but that release does not include an LG/webOS .ipk file.",
        "help_steps": [
            "Look for the Smart-TV or webOS-specific repo if this project is split across platforms.",
            "If the release only contains .wgt, that build is for Samsung/Tizen, not LG webOS.",
            "If the project is source-only, upload a zip and package it here instead.",
        ],
    }


def _resolve_owner(owner: str) -> dict[str, Any]:
    repos = _list_owner_repos(owner)
    ordered_repos = sorted(repos, key=_repo_rank)[:12]
    scanned_repos: list[str] = []
    matched_assets: list[dict[str, Any]] = []
    matched_repos: list[str] = []

    for repo in ordered_repos:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        scanned_repos.append(full_name)
        release_payload = _latest_release(full_name)
        if not release_payload:
            continue
        assets = _extract_ipk_assets(release_payload, full_name)
        if assets:
            matched_assets.extend(assets)
            matched_repos.append(full_name)

    if matched_assets:
        return {
            "kind": "github-owner-scan",
            "owner": owner,
            "assets": matched_assets,
            "matched_repos": matched_repos,
            "scanned_repos": scanned_repos,
            "advisory": f"Scanned {owner} and found LG/webOS .ipk assets in {', '.join(matched_repos)}.",
            "help_steps": [
                "Use the Smart-TV or webOS repo result below. That is the one that ships LG packages.",
                "For Moonfin-style projects, the dashboard can scan the org page first, then route you to the right repo automatically.",
                "If more than one asset appears, choose the .ipk that matches the TV platform, not the .wgt.",
            ],
        }

    return {
        "kind": "github-owner-scan",
        "owner": owner,
        "assets": [],
        "matched_repos": [],
        "scanned_repos": scanned_repos,
        "advisory": f"Scanned {owner}, but none of the checked repos exposed a public LG/webOS .ipk asset in their latest release.",
        "help_steps": [
            "Try the exact Smart-TV or webOS repo if the project separates clients by platform.",
            "Try the repo's releases page or a direct .ipk asset URL instead of the owner page.",
            "If the project does not publish a release asset, upload a buildable zip and let the dashboard package it.",
        ],
    }


def resolve_source(source: str) -> dict[str, Any]:
    normalized = normalize_source(source)
    kind = normalized.get("kind")
    if kind == "empty":
        raise RuntimeError("Paste a GitHub repo, GitHub org/user page, releases page, or direct .ipk asset URL.")
    if kind == "direct-ipk":
        url = normalized["url"] or source.strip()
        name = Path(urllib.parse.urlparse(url).path).name
        return {
            "kind": "direct-ipk",
            "label": name,
            "release_name": "Direct download",
            "assets": [{"name": name, "download_url": url, "size": None, "repo": "direct-url"}],
            "advisory": "Direct .ipk URL detected. You can download it straight into the dashboard.",
            "help_steps": ["Download the .ipk, then install it to your TV after linking Key Server."],
        }
    if kind == "owner":
        return _resolve_owner(normalized["owner"] or "")
    if kind == "repo":
        return _resolve_repo(normalized["repo"] or "", tag=normalized.get("tag"))
    raise RuntimeError("Paste a GitHub repo, GitHub org/user page, releases page, or direct .ipk asset URL.")


def download_asset(asset_url: str, destination_dir: Path) -> Path:
    filename = Path(urllib.parse.urlparse(asset_url).path).name
    if not filename.lower().endswith(".ipk"):
        raise RuntimeError("LG webOS TV sideloading expects an .ipk package.")
    destination = destination_dir / filename
    _download(asset_url, destination)
    return destination
