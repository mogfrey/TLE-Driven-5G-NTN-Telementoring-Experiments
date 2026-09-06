#!/usr/bin/env python3
"""Freeze the Paper-A ICC27 TLE/SGP4 trajectory-robustness run matrix."""
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

PASS_NAMES = ("HIGH", "MEDIUM", "LOW")
PLACEMENTS = {"M05": -5.0, "Z00": 0.0, "P05": 5.0}
EXPECTED_BLOCK_ORDER = ["HA", "MD", "LG", "HB", "ME", "LH", "HC", "MF", "LI"]
EXPECTED_ORDERS = {
    "HA": ["M05", "Z00", "P05"],
    "HB": ["P05", "Z00", "M05"],
    "HC": ["Z00", "M05", "P05"],
    "MD": ["M05", "Z00", "P05"],
    "ME": ["P05", "Z00", "M05"],
    "MF": ["Z00", "M05", "P05"],
    "LG": ["M05", "Z00", "P05"],
    "LH": ["P05", "Z00", "M05"],
    "LI": ["Z00", "M05", "P05"],
}


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("config must be a YAML mapping")
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("calibration JSON must be an object")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def finite(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"{label} must be frozen before plan generation")
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"{label} must be finite")
    return x


def spread_limit(replay: dict[str, Any]) -> float:
    mode = str(replay.get("mode") or "")
    if mode == "continuous_epoch":
        return 0.10
    if mode == "discrete_external":
        dt = finite(replay.get("update_period_s"), "replay.update_period_s")
        if dt <= 0:
            raise ValueError("replay.update_period_s must be > 0")
        return max(0.10, 1.25 * dt)
    raise ValueError("replay.mode must be frozen as continuous_epoch or discrete_external")


def validate(config: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any]:
    campaign = config.get("campaign", {})
    if int(campaign.get("valid_runs_required", 0)) != 27:
        raise ValueError("campaign.valid_runs_required is frozen at 27")
    if int(campaign.get("replacement_limit_per_slot", -1)) != 1:
        raise ValueError("replacement_limit_per_slot is frozen at 1")

    selection = config.get("pass_selection", {})
    if str(selection.get("rule")) != "first_chronological_eligible_pass_per_band":
        raise ValueError("pass-selection rule may not change")
    if finite(selection.get("elevation_mask_deg"), "pass_selection.elevation_mask_deg") != 10.0:
        raise ValueError("elevation mask is frozen at 10 deg")
    if finite(selection.get("minimum_usable_preboundary_s"), "minimum_usable_preboundary_s") < 240.0:
        raise ValueError("minimum usable pre-boundary interval must be >=240 s")
    tle_sha = str(selection.get("tle_snapshot_sha256") or "")
    if len(tle_sha) != 64:
        raise ValueError("freeze pass_selection.tle_snapshot_sha256 before planning")

    bands = selection.get("bands", {})
    pass_meta: dict[str, dict[str, Any]] = {}
    for name in PASS_NAMES:
        band = bands.get(name)
        if not isinstance(band, dict):
            raise ValueError(f"missing band {name}")
        pid = str(band.get("selected_pass_id") or "")
        trace = str(band.get("selected_trace_file") or "")
        trace_sha = str(band.get("selected_trace_sha256") or "")
        if not pid or not trace or len(trace_sha) != 64:
            raise ValueError(f"freeze selected pass/trace/hash for {name}")
        pass_meta[name] = {
            "pass_id": pid,
            "trace_file": trace,
            "trace_sha256": trace_sha,
            "band_min_max_elevation_deg": finite(band.get("min_max_elevation_deg"), f"{name}.min"),
            "band_max_max_elevation_deg": finite(band.get("max_max_elevation_deg"), f"{name}.max"),
        }

    replay = config.get("replay", {})
    limit = spread_limit(replay)
    by_pass = calibration.get("by_pass")
    if not isinstance(by_pass, dict):
        raise ValueError("calibration JSON requires by_pass mapping")
    cal_summary: dict[str, dict[str, Any]] = {}
    for name in PASS_NAMES:
        item = by_pass.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"calibration missing {name}")
        times = item.get("boundary_times_s")
        if not isinstance(times, list) or len(times) != 3:
            raise ValueError(f"{name} requires exactly 3 calibration boundary times")
        values = [finite(v, f"{name}.boundary_times_s") for v in times]
        spread = max(values) - min(values)
        if spread > limit + 1e-12:
            raise ValueError(f"{name} calibration spread {spread:.6f}s exceeds {limit:.6f}s")
        if item.get("engineering_validation_passes") != 3:
            raise ValueError(f"{name} must have exactly 3 engineering-validation passes")
        if item.get("state_fidelity_pass") is not True:
            raise ValueError(f"{name} state fidelity must pass")
        cal_summary[name] = {
            "boundary_times_s": values,
            "median_boundary_s": float(statistics.median(values)),
            "spread_s": spread,
            "spread_limit_s": limit,
        }

    design = config.get("scientific_design", {})
    if [float(x) for x in design.get("placements_s", [])] != [-5.0, 0.0, 5.0]:
        raise ValueError("placements are frozen at -5,0,+5 s")
    if design.get("block_order") != EXPECTED_BLOCK_ORDER:
        raise ValueError(f"block_order must remain {EXPECTED_BLOCK_ORDER}")
    orders = design.get("placement_order", {})
    for label, expected in EXPECTED_ORDERS.items():
        if orders.get(label) != expected:
            raise ValueError(f"placement_order.{label} must remain {expected}")

    seed_by_label: dict[str, tuple[str, int]] = {}
    seen_seeds: set[int] = set()
    groups = design.get("pass_seed_groups", {})
    prefixes = {"HIGH": "H", "MEDIUM": "M", "LOW": "L"}
    for pass_name in PASS_NAMES:
        entries = groups.get(pass_name)
        if not isinstance(entries, list) or len(entries) != 3:
            raise ValueError(f"{pass_name} must have exactly 3 seed groups")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("seed entry must be a mapping")
            label = str(entry.get("label") or "")
            seed = int(entry.get("seed"))
            if not label.startswith(prefixes[pass_name]):
                raise ValueError(f"seed label {label} does not belong to {pass_name}")
            if label in seed_by_label or seed in seen_seeds:
                raise ValueError("seed labels and seed values must be unique")
            seed_by_label[label] = (pass_name, seed)
            seen_seeds.add(seed)
    if set(seed_by_label) != set(EXPECTED_BLOCK_ORDER):
        raise ValueError("frozen seed labels must match block order")

    workload = config.get("workload", {})
    if finite(workload.get("duration_s"), "workload.duration_s") != 180.0:
        raise ValueError("workload duration is frozen at 180 s")
    if bool(workload.get("qos_dscp_enabled")) or bool(workload.get("record_one_way_delay")) or bool(workload.get("shsc_enabled")):
        raise ValueError("DSCP, one-way delay and SHSC must remain disabled")

    runs: list[dict[str, Any]] = []
    sequence = 0
    for label in EXPECTED_BLOCK_ORDER:
        pass_name, seed = seed_by_label[label]
        boundary = cal_summary[pass_name]["median_boundary_s"]
        for placement in EXPECTED_ORDERS[label]:
            sequence += 1
            offset = PLACEMENTS[placement]
            launch = boundary + offset - 180.0
            runs.append({
                "sequence": sequence,
                "run_id": f"UCT_ICC27_TLE_{pass_name}_{placement}_{label}",
                "pass_band": pass_name,
                "pass_id": pass_meta[pass_name]["pass_id"],
                "trace_file": pass_meta[pass_name]["trace_file"],
                "trace_sha256": pass_meta[pass_name]["trace_sha256"],
                "seed_group": label,
                "paired_seed": seed,
                "placement_code": placement,
                "planned_end_offset_s": offset,
                "calibrated_t310_boundary_s": boundary,
                "planned_application_launch_s": launch,
                "planned_application_end_s": launch + 180.0,
                "replacement_limit": 1,
            })
    if len(runs) != 27:
        raise AssertionError("planner must emit exactly 27 runs")

    plan: dict[str, Any] = {
        "schema_version": 1,
        "campaign_name": campaign.get("name"),
        "scientific_design": "3 prospectively selected TLE/SGP4 pass geometries x 3 placements x 3 fresh matched seeds",
        "statistical_unit": "run",
        "valid_runs_required": 27,
        "replacement_limit_per_slot": 1,
        "tle_snapshot_sha256": tle_sha,
        "replay": {"mode": replay.get("mode"), "update_period_s": replay.get("update_period_s"), "calibration_spread_limit_s": limit},
        "pass_metadata": pass_meta,
        "calibration": cal_summary,
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
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--calibration-json", required=True)
    p.add_argument("--output-json", required=True)
    p.add_argument("--output-csv", required=True)
    args = p.parse_args()

    config_path = Path(args.config)
    calibration_path = Path(args.calibration_json)
    plan = validate(load_yaml(config_path), load_json(calibration_path))
    plan["config_sha256"] = sha256_file(config_path)
    plan["calibration_input_sha256"] = sha256_file(calibration_path)

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    write_csv(plan, Path(args.output_csv))

    print(f"validated {len(plan['runs'])}-run Paper-A TLE robustness plan")
    print(f"design sha256: {plan['design_sha256']}")
    print(f"config sha256: {plan['config_sha256']}")
    for name in PASS_NAMES:
        c = plan['calibration'][name]
        print(f"{name}: boundary={c['median_boundary_s']:.6f}s spread={c['spread_s']:.6f}s limit={c['spread_limit_s']:.6f}s")


if __name__ == "__main__":
    main()
