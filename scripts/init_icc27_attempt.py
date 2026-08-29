#!/usr/bin/env python3
"""Initialize one physical attempt for a planned ICC 2027 sweep slot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize an ICC 2027 sweep run directory")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--attempt", choices=["original", "retry1"], default="original")
    args = parser.parse_args()

    plan = load_json(Path(args.plan))
    run = next((r for r in plan.get("runs", []) if r.get("plan_run_id") == args.plan_run_id), None)
    if run is None:
        raise SystemExit(f"unknown plan_run_id: {args.plan_run_id}")

    root = Path(args.runs_root)
    original = root / args.plan_run_id
    physical_run_id = args.plan_run_id if args.attempt == "original" else f"{args.plan_run_id}_RETRY1"
    out = root / physical_run_id
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing attempt directory: {out}")

    replacement_of = None
    if args.attempt == "retry1":
        if not original.is_dir():
            raise SystemExit("RETRY1 requires the preserved original attempt directory")
        qc_path = original / "qc.json"
        if not qc_path.exists():
            raise SystemExit("RETRY1 requires original qc.json documenting invalidity")
        original_qc = load_json(qc_path)
        if original_qc.get("valid") is True:
            raise SystemExit("RETRY1 is forbidden because the original attempt is valid")
        if not original_qc.get("failure_classification"):
            raise SystemExit("RETRY1 requires a documented original failure_classification")
        replacement_of = args.plan_run_id

    out.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "campaign_name": plan.get("campaign_name"),
        "campaign_design_sha256": plan.get("design_sha256"),
        "plan_run_id": run["plan_run_id"],
        "run_id": physical_run_id,
        "attempt_kind": args.attempt,
        "replacement_of": replacement_of,
        "plan_sequence": run["sequence"],
        "placement_id": run["placement_id"],
        "placement_code": run["placement_code"],
        "seed_group": run["seed_group"],
        "paired_seed": run["paired_seed"],
        "workload": run["workload"],
        "workload_duration_s": run["workload_duration_s"],
        "planned_application_launch_offset_s": run["planned_application_launch_offset_s"],
        "planned_application_end_s_from_radio_anchor": run["planned_application_end_s_from_radio_anchor"],
        "planned_end_offset_s": run["planned_end_offset_s"],
        "calibrated_service_boundary_s_from_radio_anchor": run[
            "calibrated_service_boundary_s_from_radio_anchor"
        ],
        "status": "initialized",
        "provenance": {
            "experiment_framework_commit": None,
            "oai_commit": None,
            "oai_dirty_diff_sha256": None,
            "gnb_config_sha256": None,
            "ue_config_sha256": None,
        },
        "utc": {"attempt_initialized": None, "run_start": None, "run_end": None},
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"initialized: {out}")
    print("next: host orchestrator must fill provenance/timestamps and write the remaining artifacts")


if __name__ == "__main__":
    main()
