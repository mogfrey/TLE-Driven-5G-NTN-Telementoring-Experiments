#!/usr/bin/env python3
"""Campaign-level QC for the UCT ICC 2027 boundary-position sweep.

Validity is intentionally outcome-independent. Each physical attempt must carry a
qc.json written by the host orchestrator from instrumentation/protocol checks.
This tool verifies the artifact contract, frozen plan identity, and one-retry rule.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

MANDATORY_QC_CHECKS = (
    "radio_condition_launched",
    "attach_pdu_ok",
    "workload_matches_plan",
    "sender_receiver_parse",
    "radio_logs_cover_interval",
    "boundary_located",
    "timing_alignment_ok",
    "instrumentation_ok",
)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def same_number(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        aa, bb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return math.isfinite(aa) and math.isfinite(bb) and abs(aa - bb) <= tol


def validate_manifest(manifest: dict[str, Any], run: dict[str, Any], design_sha: str) -> list[str]:
    errors: list[str] = []
    expected_pairs = {
        "plan_run_id": run["plan_run_id"],
        "placement_id": run["placement_id"],
        "seed_group": run["seed_group"],
        "paired_seed": run["paired_seed"],
        "campaign_design_sha256": design_sha,
    }
    for key, expected in expected_pairs.items():
        if manifest.get(key) != expected:
            errors.append(f"manifest {key}={manifest.get(key)!r}, expected {expected!r}")
    numeric_pairs = {
        "planned_end_offset_s": run["planned_end_offset_s"],
        "planned_application_launch_offset_s": run["planned_application_launch_offset_s"],
        "workload_duration_s": run["workload_duration_s"],
    }
    for key, expected in numeric_pairs.items():
        if not same_number(manifest.get(key), expected):
            errors.append(f"manifest {key}={manifest.get(key)!r}, expected {expected!r}")
    return errors


def inspect_attempt(path: Path, run: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    required = [str(x) for x in plan["required_per_attempt"]]
    missing = [name for name in required if not (path / name).exists()]
    result: dict[str, Any] = {
        "attempt_dir": str(path),
        "exists": path.is_dir(),
        "missing_files": missing,
        "valid": False,
        "failure_classification": None,
        "errors": [],
    }
    if not path.is_dir():
        result["errors"].append("attempt directory missing")
        return result
    if missing:
        result["errors"].append("required artifact(s) missing")
        return result

    try:
        manifest = load_json(path / "run_manifest.json")
        qc = load_json(path / "qc.json")
        load_json(path / "sender.json")
        load_json(path / "receiver.json")
        load_json(path / "continuity_summary.json")
        load_json(path / "radio_boundary.json")
        load_json(path / "timing_alignment.json")
    except Exception as exc:
        result["errors"].append(f"JSON parse error: {type(exc).__name__}: {exc}")
        return result

    result["errors"].extend(validate_manifest(manifest, run, plan["design_sha256"]))
    if qc.get("plan_run_id") != run["plan_run_id"]:
        result["errors"].append("qc plan_run_id does not match planned slot")
    checks = qc.get("checks")
    if not isinstance(checks, dict):
        result["errors"].append("qc.checks must be a mapping")
        checks = {}
    failed_checks = [name for name in MANDATORY_QC_CHECKS if checks.get(name) is not True]
    result["failed_checks"] = failed_checks
    declared_valid = qc.get("valid") is True
    result["failure_classification"] = qc.get("failure_classification")

    if declared_valid and failed_checks:
        result["errors"].append("qc.valid=true but one or more mandatory QC checks are not true")
    if declared_valid and result["failure_classification"] not in (None, "", "none"):
        result["errors"].append("valid attempt must not carry a failure_classification")
    if not declared_valid and not result["failure_classification"]:
        result["errors"].append("invalid attempt must carry a failure_classification")

    result["valid"] = declared_valid and not failed_checks and not result["errors"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="QC the 21-slot UCT ICC 2027 boundary sweep")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    plan = load_json(Path(args.plan))
    root = Path(args.runs_root)
    rows: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    campaign_errors: list[str] = []

    for run in plan.get("runs", []):
        slot = str(run["plan_run_id"])
        original_path = root / slot
        retry_path = root / f"{slot}_RETRY1"
        original = inspect_attempt(original_path, run, plan) if original_path.exists() else None
        retry = inspect_attempt(retry_path, run, plan) if retry_path.exists() else None

        if (root / f"{slot}_RETRY2").exists():
            campaign_errors.append(f"{slot}: RETRY2 exists but only one replacement is authorized")
        if original is None:
            campaign_errors.append(f"{slot}: original physical attempt is missing")
            choice = None
        elif original["valid"]:
            if retry is not None:
                campaign_errors.append(f"{slot}: retry exists even though original attempt is valid")
            choice = original
        else:
            if retry is None:
                campaign_errors.append(f"{slot}: invalid original has no valid pre-authorized replacement yet")
                choice = None
            elif retry["valid"]:
                choice = retry
            else:
                campaign_errors.append(f"{slot}: original and RETRY1 are both invalid/incomplete")
                choice = None

        for attempt_index, attempt in enumerate([original, retry]):
            if attempt is None:
                continue
            rows.append(
                {
                    "plan_run_id": slot,
                    "attempt": "original" if attempt_index == 0 else "retry1",
                    "attempt_dir": attempt["attempt_dir"],
                    "valid": attempt["valid"],
                    "failure_classification": attempt.get("failure_classification"),
                    "failed_checks": ";".join(attempt.get("failed_checks", [])),
                    "errors": ";".join(attempt.get("errors", [])),
                }
            )
        if choice is not None:
            selected.append(
                {
                    "plan_run_id": slot,
                    "selected_attempt_dir": choice["attempt_dir"],
                    "placement_id": run["placement_id"],
                    "seed_group": run["seed_group"],
                    "paired_seed": run["paired_seed"],
                }
            )

    complete = len(selected) == int(plan.get("valid_runs_required", 21)) and not campaign_errors
    result = {
        "schema_version": 1,
        "campaign_name": plan.get("campaign_name"),
        "campaign_design_sha256": plan.get("design_sha256"),
        "complete": complete,
        "valid_slots_selected": len(selected),
        "valid_slots_required": plan.get("valid_runs_required", 21),
        "campaign_errors": campaign_errors,
        "selected_attempts": selected,
    }

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = ["plan_run_id", "attempt", "attempt_dir", "valid", "failure_classification", "failed_checks", "errors"]
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"selected valid slots: {len(selected)}/{result['valid_slots_required']}")
    print(f"campaign complete: {complete}")
    print(f"wrote: {out_json}")
    print(f"wrote: {out_csv}")
    if not complete:
        for error in campaign_errors:
            print(f"ERROR: {error}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
