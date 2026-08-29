#!/usr/bin/env python3
"""Freeze the IEEE ICC 2027 UCT NTN boundary-position sweep.

The planner enforces the predeclared 7-placement x 3-seed design and rejects
unstable boundary calibration before any scientific run matrix is emitted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

import yaml

EXPECTED_OFFSETS = [-30.0, -15.0, -5.0, 0.0, 5.0, 15.0, 30.0]
EXPECTED_ORDERS = {
    "A": ["P1", "P2", "P3", "P4", "P5", "P6", "P7"],
    "B": ["P7", "P6", "P5", "P4", "P3", "P2", "P1"],
    "C": ["P4", "P1", "P7", "P2", "P6", "P3", "P5"],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("campaign config must be a YAML mapping")
    return payload


def finite_number(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"{label} must be frozen before plan generation")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def validate_and_build(config: dict[str, Any]) -> dict[str, Any]:
    campaign = config.get("campaign", {})
    calibration = config.get("calibration", {})
    workload = config.get("workload", {})
    placements_cfg = config.get("placements", [])
    seeds_cfg = config.get("seed_groups", [])
    run_order = config.get("run_order", {})
    outputs = config.get("outputs", {})

    repetitions = int(campaign.get("repetitions", 3))
    if repetitions != 3:
        raise ValueError("ICC 2027 primary sweep is frozen at exactly 3 seed groups")
    replacement_limit = int(campaign.get("replacement_limit_per_slot", 1))
    if replacement_limit != 1:
        raise ValueError("replacement_limit_per_slot is frozen at exactly 1")

    boundary_times_raw = calibration.get("boundary_times_s")
    if not isinstance(boundary_times_raw, list) or len(boundary_times_raw) != 3:
        raise ValueError("calibration.boundary_times_s must contain exactly 3 values")
    boundary_times = [
        finite_number(value, f"calibration.boundary_times_s[{i}]")
        for i, value in enumerate(boundary_times_raw)
    ]
    spread = max(boundary_times) - min(boundary_times)
    max_spread = finite_number(calibration.get("max_spread_s", 0.1), "calibration.max_spread_s")
    if max_spread <= 0:
        raise ValueError("calibration.max_spread_s must be > 0")
    if spread > max_spread + 1e-12:
        raise ValueError(
            f"boundary calibration spread {spread:.6f}s exceeds frozen tolerance {max_spread:.6f}s"
        )
    statistic = str(calibration.get("statistic", "median")).lower()
    if statistic != "median":
        raise ValueError("calibration.statistic is frozen as 'median'")
    boundary = float(statistics.median(boundary_times))

    duration = finite_number(workload.get("duration_s"), "workload.duration_s")
    if duration != 180.0:
        raise ValueError("ICC 2027 primary sweep workload duration is frozen at 180 s")
    if bool(workload.get("qos_dscp_enabled", False)):
        raise ValueError("qos_dscp_enabled must remain false for the primary sweep")
    if bool(workload.get("record_one_way_delay", False)):
        raise ValueError("record_one_way_delay must remain false for the primary sweep")

    if not isinstance(placements_cfg, list) or len(placements_cfg) != 7:
        raise ValueError("placements must contain exactly 7 entries")
    placements: dict[str, dict[str, Any]] = {}
    offsets: list[float] = []
    for item in placements_cfg:
        if not isinstance(item, dict):
            raise ValueError("each placement must be a mapping")
        pid = str(item.get("id", ""))
        code = str(item.get("code", ""))
        if not pid or not code:
            raise ValueError("each placement requires id and code")
        if pid in placements:
            raise ValueError(f"duplicate placement id: {pid}")
        offset = finite_number(item.get("intended_end_offset_s"), f"placement {pid} offset")
        placements[pid] = {"id": pid, "code": code, "intended_end_offset_s": offset}
        offsets.append(offset)
    if sorted(offsets) != EXPECTED_OFFSETS:
        raise ValueError(f"placement offsets must be exactly {EXPECTED_OFFSETS}")

    if not isinstance(seeds_cfg, list) or len(seeds_cfg) != 3:
        raise ValueError("seed_groups must contain exactly 3 entries")
    seeds: dict[str, int] = {}
    for item in seeds_cfg:
        if not isinstance(item, dict):
            raise ValueError("each seed group must be a mapping")
        label = str(item.get("label", ""))
        if label not in EXPECTED_ORDERS:
            raise ValueError("seed labels must be A, B, and C")
        seed = int(item.get("seed"))
        if seed in seeds.values():
            raise ValueError("seed values must be unique")
        seeds[label] = seed
    if set(seeds) != set(EXPECTED_ORDERS):
        raise ValueError("seed groups must contain labels A, B, and C")

    for label, expected in EXPECTED_ORDERS.items():
        actual = run_order.get(label)
        if actual != expected:
            raise ValueError(f"run_order.{label} must be frozen as {expected}")
        if set(actual) != set(placements):
            raise ValueError(f"run_order.{label} does not cover every placement exactly once")

    required = outputs.get("required_per_attempt", [])
    if not isinstance(required, list) or not required:
        raise ValueError("outputs.required_per_attempt must be a non-empty list")
    required = [str(name) for name in required]

    runs: list[dict[str, Any]] = []
    sequence = 0
    for label in ("A", "B", "C"):
        for pid in run_order[label]:
            sequence += 1
            p = placements[pid]
            end_offset = float(p["intended_end_offset_s"])
            launch = boundary + end_offset - duration
            planned_end = launch + duration
            code = p["code"]
            run_id = f"UCT_ICC27_{code}_S{label}"
            runs.append(
                {
                    "sequence": sequence,
                    "plan_run_id": run_id,
                    "placement_id": pid,
                    "placement_code": code,
                    "seed_group": label,
                    "paired_seed": seeds[label],
                    "workload": workload.get("type", "combined"),
                    "workload_duration_s": duration,
                    "planned_application_launch_offset_s": launch,
                    "planned_application_end_s_from_radio_anchor": planned_end,
                    "planned_end_offset_s": end_offset,
                    "calibrated_service_boundary_s_from_radio_anchor": boundary,
                    "replacement_limit": replacement_limit,
                }
            )

    plan: dict[str, Any] = {
        "schema_version": 1,
        "campaign_name": campaign.get("name", "uct-icc27-boundary-sweep"),
        "scientific_design": "7-placement x 3-seed UCT Release-17 NTN boundary-position sweep",
        "statistical_unit": "run",
        "run_count": len(runs),
        "valid_runs_required": 21,
        "replacement_limit_per_slot": replacement_limit,
        "calibration": {
            "boundary_times_s": boundary_times,
            "statistic": statistic,
            "calibrated_service_boundary_s": boundary,
            "spread_s": spread,
            "max_spread_s": max_spread,
        },
        "workload": workload,
        "placements": [placements[f"P{i}"] for i in range(1, 8)],
        "seed_groups": [{"label": label, "seed": seeds[label]} for label in ("A", "B", "C")],
        "run_order": {label: run_order[label] for label in ("A", "B", "C")},
        "required_per_attempt": required,
        "runs": runs,
    }
    plan["design_sha256"] = canonical_sha256(plan)
    return plan


def write_csv(plan: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = plan["runs"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the UCT ICC 2027 NTN boundary sweep")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    config_path = Path(args.config)
    plan = validate_and_build(load_config(config_path))
    plan["config_sha256"] = sha256_file(config_path)

    json_path = Path(args.output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    write_csv(plan, Path(args.output_csv))

    c = plan["calibration"]
    print(f"validated {plan['run_count']}-run ICC 2027 sweep")
    print(f"calibrated boundary: {c['calibrated_service_boundary_s']:.6f}s")
    print(f"calibration spread: {c['spread_s']:.6f}s <= {c['max_spread_s']:.6f}s")
    print(f"config sha256: {plan['config_sha256']}")
    print(f"design sha256: {plan['design_sha256']}")
    print(f"wrote: {json_path}")
    print(f"wrote: {args.output_csv}")


if __name__ == "__main__":
    main()
