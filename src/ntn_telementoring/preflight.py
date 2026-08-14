from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from .provenance import git_state


def _check(name: str, ok: bool, detail: Any = None, required: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "required": required,
        "detail": detail,
    }


def run_preflight(config_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    checks: list[dict[str, Any]] = []
    observer = config.get("observer") or {}
    for field in ("latitude_deg", "longitude_deg", "altitude_m"):
        checks.append(
            _check(
                f"observer.{field}",
                observer.get(field) is not None,
                observer.get(field),
                required=False,
            )
        )

    ran = ((config.get("hosts") or {}).get("ran") or {})
    oai_root_value = ran.get("oai_root")
    oai_root = Path(oai_root_value).expanduser() if oai_root_value else None
    checks.append(_check("hosts.ran.oai_root configured", oai_root is not None, oai_root_value))
    checks.append(
        _check(
            "OAI root exists",
            bool(oai_root and oai_root.exists()),
            str(oai_root) if oai_root else None,
        )
    )

    gnb_binary = None
    ue_binary = None
    if oai_root:
        build_dir = oai_root / "cmake_targets" / "ran_build" / "build"
        gnb = build_dir / "nr-softmodem"
        ue = build_dir / "nr-uesoftmodem"
        if gnb.exists():
            gnb_binary = str(gnb)
        if ue.exists():
            ue_binary = str(ue)

    checks.append(_check("nr-softmodem built", gnb_binary is not None, gnb_binary))
    checks.append(_check("nr-uesoftmodem built", ue_binary is not None, ue_binary))

    for command, required in (("git", True), ("ip", True), ("chronyc", False), ("python3", True)):
        resolved = shutil.which(command)
        checks.append(_check(f"command:{command}", resolved is not None, resolved, required=required))

    oai_git = git_state(oai_root) if oai_root and oai_root.exists() else {"available": False}
    dirty = False
    status = oai_git.get("status") if isinstance(oai_git, dict) else None
    if isinstance(status, dict) and status.get("stdout"):
        dirty = True
    checks.append(_check("OAI checkout clean", not dirty, status, required=False))

    required_failures = [item for item in checks if item["required"] and not item["ok"]]
    warnings = [item for item in checks if not item["required"] and not item["ok"]]

    return {
        "schema_version": 1,
        "ready": len(required_failures) == 0,
        "required_failure_count": len(required_failures),
        "warning_count": len(warnings),
        "checks": checks,
        "oai_git": oai_git,
        "notes": [
            "This preflight is read-only and does not start or modify OAI/Open5GS.",
            "Observer coordinates may be left unset for the first inventory pass but must be frozen before TLE experiments.",
            "chronyc is optional at this stage but required before one-way-latency measurements.",
        ],
    }


def write_preflight(report: dict[str, Any], output: str | Path) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
