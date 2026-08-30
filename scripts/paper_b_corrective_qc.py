#!/usr/bin/env python3
"""Strict instrumentation QC for the Paper-B AUSW corrective campaign.

This checker is intentionally separate from scientific AUSW outcomes. It answers
only whether the application harness was alive and capable of observing the
intended measurement interval. A scientifically negative result may still PASS
this QC. Conversely, a run with receiver processes that died before the
measurement interval ended, or with no multimodal traffic from startup, FAILS
instrumentation QC and must not enter the confirmatory dataset.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

PREMATURE_TIMEOUT_RE = re.compile(r"Killed\s+.*timeout\b.*ffmpeg|timeout:.*ffmpeg", re.I)
STREAM_KEYS = (
    "video_frame_delivery_ratio",
    "audio_uplink_packet_delivery_ratio",
    "audio_downlink_packet_delivery_ratio",
    "telestration_ack_delivery_ratio",
)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def log_has_premature_timeout(path: Path) -> bool:
    try:
        return bool(PREMATURE_TIMEOUT_RE.search(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def lifecycle_entries(app: Path) -> dict[str, dict[str, Any]]:
    """Read the new corrective receiver lifecycle artifact.

    Preferred schema:
      {
        "audio_uplink": {"wall_runtime_s": 181.2, "premature_timeout": false, ...},
        "audio_downlink": {...}
      }
    """
    value = load_json(app / "receiver_lifecycle.json")
    return {k: v for k, v in value.items() if isinstance(v, dict)}


def positive_startup(rows: list[dict[str, Any]], windows: int) -> tuple[bool, dict[str, Any]]:
    subset = rows[: max(1, windows)]
    detail: dict[str, Any] = {"windows_examined": len(subset), "streams": {}}
    if not subset:
        return False, detail
    overall = True
    for key in STREAM_KEYS:
        values = []
        for row in subset:
            metrics = row.get("metrics") or {}
            try:
                values.append(float(metrics.get(key, 0.0)))
            except (TypeError, ValueError):
                values.append(0.0)
        positive = sum(v > 0 for v in values)
        detail["streams"][key] = {"positive_windows": positive, "values": values}
        if positive == 0:
            overall = False
    return overall, detail


def evaluate(run_dir: Path, duration_s: float, startup_windows: int, lifetime_tolerance_s: float) -> dict[str, Any]:
    app = run_dir / "application"
    analysis = run_dir / "analysis"
    reasons: list[str] = []

    status = load_json(app / "run_status.json")
    if status.get("status") != "pass":
        reasons.append("run_status_not_pass")

    timeout_logs = []
    for name in ("bundled_workload_console.log", "endpoint_console.log"):
        path = app / name
        if log_has_premature_timeout(path):
            timeout_logs.append(name)
    if timeout_logs:
        reasons.append("legacy_or_premature_receiver_timeout_detected")

    rows = load_jsonl(analysis / "usability_windows.jsonl")
    startup_ok, startup_detail = positive_startup(rows, startup_windows)
    if not startup_ok:
        reasons.append("multimodal_path_not_alive_at_startup")

    life = lifecycle_entries(app)
    lifecycle_detail: dict[str, Any] = {}
    for key in ("audio_uplink", "audio_downlink"):
        entry = life.get(key)
        if not entry:
            reasons.append(f"missing_receiver_lifecycle:{key}")
            continue
        try:
            runtime = float(entry.get("wall_runtime_s"))
        except (TypeError, ValueError):
            runtime = math.nan
        premature = bool(entry.get("premature_timeout", False))
        survived = math.isfinite(runtime) and runtime + lifetime_tolerance_s >= duration_s
        lifecycle_detail[key] = {
            "wall_runtime_s": runtime if math.isfinite(runtime) else None,
            "premature_timeout": premature,
            "survived_measurement_interval": survived,
            "exit_reason": entry.get("exit_reason"),
        }
        if premature:
            reasons.append(f"premature_receiver_timeout:{key}")
        if not survived:
            reasons.append(f"receiver_lifetime_short:{key}")

    any_data = any(bool(row.get("data_plane_alive")) for row in rows)
    if not any_data:
        reasons.append("no_application_data_observed")

    valid = not reasons
    return {
        "schema_version": 1,
        "instrumentation_valid": valid,
        "reasons": sorted(set(reasons)),
        "duration_s": duration_s,
        "startup_windows": startup_windows,
        "startup_path_alive": startup_ok,
        "startup_detail": startup_detail,
        "receiver_lifecycle": lifecycle_detail,
        "premature_timeout_logs": timeout_logs,
        "any_application_data_observed": any_data,
        "scientific_outcome_used_for_qc": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Strict Paper-B corrective instrumentation QC")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--startup-windows", type=int, default=5)
    parser.add_argument("--lifetime-tolerance-s", type=float, default=1.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    report = evaluate(run_dir, args.duration, args.startup_windows, args.lifetime_tolerance_s)
    out = Path(args.output) if args.output else run_dir / "instrumentation_qc.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["instrumentation_valid"] else 2)


if __name__ == "__main__":
    main()
