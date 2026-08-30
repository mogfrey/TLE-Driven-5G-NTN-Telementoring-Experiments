#!/usr/bin/env python3
"""Outcome-blind campaign QC for the Paper-A ICC'27 second-geometry confirmation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", required=True)
    p.add_argument("--results-root", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    root = Path(args.results_root)
    required = [str(x) for x in plan["required_per_attempt"]]

    rows = []
    valid = 0
    for run in plan["runs"]:
        run_id = run["plan_run_id"]
        attempts = sorted([p for p in root.glob(f"{run_id}*") if p.is_dir()])
        attempt_rows = []
        accepted = False
        for attempt in attempts:
            missing = [name for name in required if not (attempt / name).exists()]
            ti_path = attempt / "treatment_integrity.json"
            ti_pass = False
            if ti_path.exists():
                try:
                    ti_pass = bool(json.loads(ti_path.read_text(encoding="utf-8")).get("pass"))
                except Exception:
                    ti_pass = False
            qc_path = attempt / "qc.json"
            qc_pass = False
            if qc_path.exists():
                try:
                    q = json.loads(qc_path.read_text(encoding="utf-8"))
                    qc_pass = str(q.get("status", q.get("qc", ""))).upper() in {"PASS", "VALID", "OK"} or bool(q.get("pass"))
                except Exception:
                    qc_pass = False
            this_valid = not missing and ti_pass and qc_pass
            accepted = accepted or this_valid
            attempt_rows.append({
                "attempt": attempt.name,
                "missing_required": missing,
                "treatment_integrity_pass": ti_pass,
                "qc_pass": qc_pass,
                "valid": this_valid,
            })
        if accepted:
            valid += 1
        rows.append({"run_id": run_id, "accepted": accepted, "attempts": attempt_rows})

    expected = int(plan.get("valid_runs_required", 18))
    campaign_pass = valid == expected
    report = {
        "schema_version": 1,
        "outcome_blind": True,
        "plan_sha256": sha256_file(plan_path),
        "expected_valid_slots": expected,
        "valid_slots": valid,
        "campaign_pass": campaign_pass,
        "slots": rows,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"campaign_pass": campaign_pass, "valid_slots": valid, "expected": expected}, indent=2))
    raise SystemExit(0 if campaign_pass else 2)


if __name__ == "__main__":
    main()
