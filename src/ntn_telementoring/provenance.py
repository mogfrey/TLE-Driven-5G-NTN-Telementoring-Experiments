from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _run(command: list[str], cwd: str | Path | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "error": str(exc)}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(path: str | Path) -> dict[str, Any]:
    repo = Path(path)
    if not repo.exists():
        return {"path": str(repo), "exists": False}
    return {
        "path": str(repo.resolve()),
        "exists": True,
        "head": _run(["git", "rev-parse", "HEAD"], repo),
        "describe": _run(["git", "describe", "--tags", "--always", "--dirty"], repo),
        "status": _run(["git", "status", "--porcelain"], repo),
        "remote": _run(["git", "remote", "get-url", "origin"], repo),
    }


def collect_manifest(
    *,
    config_path: str | Path,
    framework_root: str | Path,
    tle_path: str | Path | None = None,
) -> dict[str, Any]:
    config_path = Path(config_path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    oai_root = ((config.get("hosts") or {}).get("ran") or {}).get("oai_root")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "config": {
            "path": str(config_path.resolve()),
            "sha256": sha256_file(config_path),
        },
        "framework_git": git_state(framework_root),
        "oai_git": git_state(oai_root) if oai_root else {"configured": False},
        "commands": {
            "uname": _run(["uname", "-a"]),
            "chronyc_tracking": _run(["chronyc", "tracking"]),
            "ip_link": _run(["ip", "-details", "link", "show"]),
        },
    }

    if tle_path:
        tle = Path(tle_path)
        manifest["tle"] = {
            "path": str(tle.resolve()),
            "sha256": sha256_file(tle),
            "size_bytes": tle.stat().st_size,
        }

    return manifest


def write_manifest(manifest: dict[str, Any], output: str | Path) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
