#!/usr/bin/env python3
"""Freeze and validate the matched UCT continuity-validation run matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("campaign config must be a YAML mapping")
    return payload


def require_number(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"{key} must be frozen before generating the final plan")
    return float(value)


def build_plan(config: dict[str, Any]) -> dict[str, Any]:
    campaign = config.get("campaign", {})
    workload = config.get("workload", {})
    conditions = config.get("conditions", {})

    repetitions = int(campaign.get("repetitions", 5))
    if repetitions != 5:
        raise ValueError("final matched validation campaign is frozen at exactly 5 repetitions")

    expected_boundary = require_number(campaign, "expected_service_boundary_s")
    safe_margin = require_number(campaign, "safe_end_margin_s")
    boundary_overrun = require_number(campaign, "boundary_min_overrun_s")
    duration = require_number(workload, "duration_s")
    seed_base = int(workload.get("seed_base", 4100))

    safe = conditions.get("leo_safe", {})
    boundary = conditions.get("leo_boundary", {})
    safe_offset = require_number(safe, "application_launch_offset_s")
    boundary_offset = require_number(boundary, "application_launch_offset_s")

    safe_end = safe_offset + duration
    boundary_end = boundary_offset + duration
    if safe_end > expected_boundary - safe_margin:
        raise ValueError(
            "leo_safe violates the frozen negative-control rule: application must finish at least "
            f"{safe_margin:g}s before the service boundary"
        )
    if boundary_end < expected_boundary + boundary_overrun:
        raise ValueError(
            "leo_boundary violates the frozen exposure rule: application must extend at least "
            f"{boundary_overrun:g}s beyond the service boundary"
        )

    default_pair_order = ["safe_first", "boundary_first", "safe_first", "boundary_first", "safe_first"]
    pair_order = campaign.get("pair_order", default_pair_order)
    if len(pair_order) != repetitions:
        raise ValueError("campaign.pair_order must contain one entry per repetition")
    if any(item not in {"safe_first", "boundary_first"} for item in pair_order):
        raise ValueError("pair_order entries must be safe_first or boundary_first")

    runs: list[dict[str, Any]] = []
    sequence = 0
    for repeat in range(1, repetitions + 1):
        seed = seed_base + repeat
        order = (
            ["leo_safe", "leo_boundary"]
            if pair_order[repeat - 1] == "safe_first"
            else ["leo_boundary", "leo_safe"]
        )
        for condition in order:
            sequence += 1
            condition_cfg = conditions[condition]
            launch_offset = float(condition_cfg["application_launch_offset_s"])
            runs.append(
                {
                    "sequence": sequence,
                    "run_id": f"UCT_{condition.upper()}_R{repeat:02d}",
                    "condition": condition,
                    "condition_role": condition_cfg.get("role"),
                    "repetition": repeat,
                    "paired_seed": seed,
                    "workload": workload.get("type", "combined"),
                    "duration_s": duration,
                    "application_launch_offset_s": launch_offset,
                    "expected_service_boundary_s": expected_boundary,
                    "planned_application_end_s": launch_offset + duration,
                    "planned_boundary_margin_s": expected_boundary - (launch_offset + duration),
                }
            )

    return {
        "schema_version": 1,
        "campaign_name": campaign.get("name", "uct-release17-continuity-validation"),
        "scientific_design": "paired matched LEO safe-vs-service-boundary validation",
        "repetitions_per_condition": repetitions,
        "run_count": len(runs),
        "expected_service_boundary_s": expected_boundary,
        "workload_duration_s": duration,
        "safe_end_margin_s": safe_margin,
        "boundary_min_overrun_s": boundary_overrun,
        "pair_order": pair_order,
        "runs": runs,
    }


def write_csv(plan: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = plan["runs"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the UCT matched continuity campaign matrix")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    plan = build_plan(config)
    plan["config_sha256"] = sha256_file(config_path)

    json_path = Path(args.output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    write_csv(plan, Path(args.output_csv))

    print(f"validated 10-run matched plan from {config_path}")
    print(f"config sha256: {plan['config_sha256']}")
    print(f"wrote: {json_path}")
    print(f"wrote: {args.output_csv}")


if __name__ == "__main__":
    main()
