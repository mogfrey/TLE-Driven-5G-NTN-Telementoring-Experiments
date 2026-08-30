#!/usr/bin/env python3
"""Freeze the Paper-A ICC'27 second-geometry confirmatory campaign.

This planner enforces the predeclared 3-placement x 6-seed design and rejects
unstable boundary calibration before emitting any scientific run matrix.
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

EXPECTED_PLACEMENTS = {"M05": -5.0, "Z00": 0.0, "P05": 5.0}
EXPECTED_LABELS = ["A", "B", "C", "D", "E", "F"]
EXPECTED_ORDERS = {
    "A": ["M05", "Z00", "P05"],
    "B": ["P05", "Z00", "M05"],
    "C": ["Z00", "M05", "P05"],
    "D": ["Z00", "P05", "M05"],
    "E": ["M05", "P05", "Z00"],
    "F": ["P05", "M05", "Z00"],
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def finite(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"{label} must be frozen before plan generation")
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"{label} must be finite")
    return x


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must be a YAML mapping")
    return data


def validate_and_build(cfg: dict[str, Any]) -> dict[str, Any]:
    campaign = cfg.get("campaign", {})
    sci = cfg.get("scientific_design", {})
    cal = cfg.get("calibration", {})
    workload = cfg.get("workload", {})
    outputs = cfg.get("outputs", {})
    lab = cfg.get("lab", {})

    if int(campaign.get("valid_runs_required", 0)) != 18:
        raise ValueError("confirmatory campaign is frozen at exactly 18 valid runs")
    if int(campaign.get("replacement_limit_per_slot", 0)) != 1:
        raise ValueError("replacement limit is frozen at exactly one per slot")

    placements = [float(x) for x in sci.get("placements_s", [])]
    if placements != [-5.0, 0.0, 5.0]:
        raise ValueError("placements_s must remain exactly [-5, 0, +5]")

    seeds_cfg = sci.get("seed_groups", [])
    if not isinstance(seeds_cfg, list) or len(seeds_cfg) != 6:
        raise ValueError("exactly six fresh seed groups are required")
    seeds: dict[str, int] = {}
    for item in seeds_cfg:
        label = str(item.get("label"))
        seed = int(item.get("seed"))
        if label in seeds or seed in seeds.values():
            raise ValueError("seed labels and values must be unique")
        seeds[label] = seed
    if list(seeds.keys()) != EXPECTED_LABELS:
        raise ValueError(f"seed labels must be {EXPECTED_LABELS}")

    orders = sci.get("run_order", {})
    for label, expected in EXPECTED_ORDERS.items():
        if orders.get(label) != expected:
            raise ValueError(f"run_order.{label} must remain {expected}")

    boundary_times = cal.get("boundary_times_s")
    if not isinstance(boundary_times, list) or len(boundary_times) != 3:
        raise ValueError("calibration.boundary_times_s must contain exactly three values")
    boundary_times = [finite(v, f"calibration.boundary_times_s[{i}]") for i, v in enumerate(boundary_times)]
    spread = max(boundary_times) - min(boundary_times)
    max_spread = finite(cal.get("max_spread_s", 0.10), "calibration.max_spread_s")
    if spread > max_spread + 1e-12:
        raise ValueError(f"calibration spread {spread:.6f}s exceeds {max_spread:.6f}s")
    if str(cal.get("statistic", "median")).lower() != "median":
        raise ValueError("calibration statistic is frozen as median")
    boundary = float(statistics.median(boundary_times))

    duration = finite(workload.get("duration_s"), "workload.duration_s")
    if duration != 180.0:
        raise ValueError("workload duration is frozen at 180 s")
    if bool(workload.get("qos_dscp_enabled", False)):
        raise ValueError("DSCP must remain disabled")
    if bool(workload.get("record_one_way_delay", False)):
        raise ValueError("one-way-delay analysis must remain disabled")
    if bool(workload.get("shsc_enabled", False)):
        raise ValueError("SHSC must remain disabled for the confirmatory campaign")

    geometry_id = lab.get("geometry_id")
    geometry_desc = lab.get("geometry_description")
    if not geometry_id or not geometry_desc:
        raise ValueError("lab.geometry_id and geometry_description must be frozen before planning")

    required = [str(x) for x in outputs.get("required_per_attempt", [])]
    if "treatment_integrity.json" not in required:
        raise ValueError("treatment_integrity.json is mandatory")

    runs: list[dict[str, Any]] = []
    seq = 0
    for label in EXPECTED_LABELS:
        for code in EXPECTED_ORDERS[label]:
            seq += 1
            offset = EXPECTED_PLACEMENTS[code]
            launch = boundary + offset - duration
            runs.append({
                "sequence": seq,
                "plan_run_id": f"UCT_ICC27_TB_{code}_S{label}",
                "placement_code": code,
                "planned_end_offset_s": offset,
                "seed_group": label,
                "paired_seed": seeds[label],
                "workload_duration_s": duration,
                "planned_application_launch_offset_s": launch,
                "planned_application_end_s_from_radio_anchor": launch + duration,
                "calibrated_service_boundary_s_from_radio_anchor": boundary,
                "geometry_id": str(geometry_id),
                "replacement_limit": 1,
            })

    plan: dict[str, Any] = {
        "schema_version": 1,
        "campaign_name": campaign.get("name"),
        "paper": "A",
        "target": "IEEE ICC 2027",
        "scientific_design": "independent second-geometry 3-placement x 6-seed confirmation",
        "statistical_unit": "run",
        "valid_runs_required": 18,
        "geometry": {"id": str(geometry_id), "description": str(geometry_desc)},
        "calibration": {
            "boundary_times_s": boundary_times,
            "calibrated_service_boundary_s": boundary,
            "spread_s": spread,
            "max_spread_s": max_spread,
        },
        "workload": workload,
        "required_per_attempt": required,
        "runs": runs,
    }
    plan["design_sha256"] = canonical_sha256(plan)
    return plan


def write_csv(plan: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = plan["runs"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--output-json", required=True)
    p.add_argument("--output-csv", required=True)
    args = p.parse_args()

    config_path = Path(args.config)
    plan = validate_and_build(load_yaml(config_path))
    plan["config_sha256"] = sha256_file(config_path)

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    write_csv(plan, Path(args.output_csv))

    print(f"validated {plan['valid_runs_required']}-run Paper-A confirmatory plan")
    print(f"geometry: {plan['geometry']['id']}")
    print(f"boundary: {plan['calibration']['calibrated_service_boundary_s']:.6f}s")
    print(f"spread: {plan['calibration']['spread_s']:.6f}s")
    print(f"design sha256: {plan['design_sha256']}")


if __name__ == "__main__":
    main()
