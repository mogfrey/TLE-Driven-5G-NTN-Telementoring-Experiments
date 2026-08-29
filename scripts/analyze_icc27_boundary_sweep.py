#!/usr/bin/env python3
"""Summarize the UCT ICC 2027 boundary-position sweep from normalized artifacts."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def stdev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def flow_prefix_pct(summary: dict[str, Any]) -> tuple[float | None, float | None]:
    vals = []
    for flow in summary.get("flows", {}).values():
        value = flow.get("receiver_prefix_loss_fraction")
        if value is not None:
            vals.append(100.0 * float(value))
    return (mean(vals), max(vals) if vals else None)


def derive_row(plan_run: dict[str, Any], attempt_dir: Path) -> dict[str, Any]:
    summary = load_json(attempt_dir / "continuity_summary.json")
    timing = load_json(attempt_dir / "timing_alignment.json")
    aggregate = summary.get("aggregate", {})

    app_end = float(timing["application_end_s_from_radio_anchor"])
    boundary = float(timing["service_boundary_s_from_radio_anchor"])
    last_by_flow = timing.get("last_receive_s_from_radio_anchor", {})
    if not isinstance(last_by_flow, dict) or not last_by_flow:
        raise ValueError(f"{attempt_dir}: timing_alignment last_receive_s_from_radio_anchor missing")
    last_values = [float(v) for v in last_by_flow.values() if v is not None]
    if not last_values:
        raise ValueError(f"{attempt_dir}: no per-flow last-receive times")
    last_app = max(last_values)
    t310_raw = timing.get("t310_expiry_s_from_radio_anchor")
    t310 = float(t310_raw) if t310_raw is not None else None

    completion = aggregate.get("mean_session_completion_ratio")
    completion_f = float(completion) if completion is not None else None
    prefix_mean, prefix_max = flow_prefix_pct(summary)
    return {
        "plan_run_id": plan_run["plan_run_id"],
        "physical_attempt_dir": str(attempt_dir),
        "placement_id": plan_run["placement_id"],
        "placement_code": plan_run["placement_code"],
        "seed_group": plan_run["seed_group"],
        "paired_seed": plan_run["paired_seed"],
        "planned_end_offset_s": float(plan_run["planned_end_offset_s"]),
        "measured_end_offset_s": app_end - boundary,
        "whole_session_delivery_pct": 100.0 * completion_f if completion_f is not None else None,
        "whole_session_missing_pct": 100.0 * (1.0 - completion_f) if completion_f is not None else None,
        "receiver_prefix_loss_mean_pct": prefix_mean,
        "receiver_prefix_loss_max_pct": prefix_max,
        "mean_continuity_deficit_s": aggregate.get("mean_continuity_deficit_duration_s"),
        "cross_stream_completion_spread_pp": (
            100.0 * float(aggregate["cross_stream_completion_spread"])
            if aggregate.get("cross_stream_completion_spread") is not None else None
        ),
        "cross_stream_last_receive_skew_ms": aggregate.get("cross_stream_last_receive_skew_ms"),
        "last_application_receive_relative_boundary_s": last_app - boundary,
        "last_application_receive_before_t310_s": (t310 - last_app) if t310 is not None else None,
        "service_boundary_s_from_radio_anchor": boundary,
        "t310_expiry_s_from_radio_anchor": t310,
    }


def fit_hinge(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    obs = [
        (float(r["measured_end_offset_s"]), float(r["mean_continuity_deficit_s"]))
        for r in rows
        if r.get("mean_continuity_deficit_s") is not None
    ]
    if len(obs) < 3:
        return None
    lower = min(-x for x, _ in obs) - 10.0
    upper = max(y - x for x, y in obs) + 10.0
    if upper <= lower:
        upper = lower + 20.0
    steps = max(1, int(math.ceil((upper - lower) * 1000.0)))
    best_tau = lower
    best_sse = math.inf
    for i in range(steps + 1):
        tau = lower + i / 1000.0
        sse = 0.0
        for x, y in obs:
            pred = max(0.0, x + tau)
            sse += (y - pred) ** 2
        if sse < best_sse:
            best_sse, best_tau = sse, tau
    residuals = [y - max(0.0, x + best_tau) for x, y in obs]
    rmse = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    mae = sum(abs(r) for r in residuals) / len(residuals)
    ybar = statistics.mean(y for _, y in obs)
    sst = sum((y - ybar) ** 2 for _, y in obs)
    r2 = None if sst == 0 else 1.0 - best_sse / sst
    return {
        "model": "CDD(delta) = max(0, delta + tau)",
        "status": "candidate_descriptive_model_only",
        "n_runs": len(obs),
        "tau_s": best_tau,
        "rmse_s": rmse,
        "mae_s": mae,
        "r_squared": r2,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the UCT ICC 2027 boundary sweep")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--campaign-qc", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    plan = load_json(Path(args.plan))
    qc = load_json(Path(args.campaign_qc))
    if qc.get("complete") is not True:
        raise SystemExit("campaign QC is not complete; refusing scientific summary")
    if qc.get("campaign_design_sha256") != plan.get("design_sha256"):
        raise SystemExit("campaign QC design hash does not match campaign plan")

    plan_by_id = {r["plan_run_id"]: r for r in plan["runs"]}
    sequence_by_id = {r["plan_run_id"]: int(r["sequence"]) for r in plan["runs"]}
    rows: list[dict[str, Any]] = []
    for selected in qc.get("selected_attempts", []):
        plan_id = selected["plan_run_id"]
        if plan_id not in plan_by_id:
            raise ValueError(f"selected attempt references unknown plan slot {plan_id}")
        rows.append(derive_row(plan_by_id[plan_id], Path(selected["selected_attempt_dir"])))
    rows.sort(key=lambda r: sequence_by_id[r["plan_run_id"]])
    if len(rows) != int(plan.get("valid_runs_required", 21)):
        raise SystemExit(f"expected 21 selected valid rows; got {len(rows)}")

    grouped: list[dict[str, Any]] = []
    for placement in plan["placements"]:
        subset = [r for r in rows if r["placement_id"] == placement["id"]]
        if len(subset) != 3:
            raise ValueError(f"placement {placement['id']} has {len(subset)} valid rows; expected 3")

        def vals(key: str) -> list[float]:
            return [float(r[key]) for r in subset if r.get(key) is not None]

        prefix_vals = vals("receiver_prefix_loss_max_pct")
        grouped.append({
            "placement_id": placement["id"],
            "placement_code": placement["code"],
            "planned_end_offset_s": float(placement["intended_end_offset_s"]),
            "n": len(subset),
            "measured_end_offset_mean_s": mean(vals("measured_end_offset_s")),
            "measured_end_offset_sd_s": stdev(vals("measured_end_offset_s")),
            "delivery_mean_pct": mean(vals("whole_session_delivery_pct")),
            "delivery_sd_pct": stdev(vals("whole_session_delivery_pct")),
            "missing_mean_pct": mean(vals("whole_session_missing_pct")),
            "cdd_mean_s": mean(vals("mean_continuity_deficit_s")),
            "cdd_sd_s": stdev(vals("mean_continuity_deficit_s")),
            "prefix_loss_max_pct": max(prefix_vals) if prefix_vals else None,
            "cross_stream_skew_mean_ms": mean(vals("cross_stream_last_receive_skew_ms")),
            "last_receive_relative_boundary_mean_s": mean(vals("last_application_receive_relative_boundary_s")),
            "last_receive_before_t310_mean_s": mean(vals("last_application_receive_before_t310_s")),
        })

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "icc27_boundary_sweep_run_summary.csv", rows, list(rows[0].keys()))
    write_csv(
        output / "icc27_boundary_sweep_placement_summary.csv", grouped, list(grouped[0].keys())
    )
    model = fit_hinge(rows)
    summary = {
        "schema_version": 1,
        "campaign_name": plan.get("campaign_name"),
        "campaign_design_sha256": plan.get("design_sha256"),
        "valid_runs": len(rows),
        "placements": grouped,
        "candidate_hinge_model": model,
        "interpretation_guardrail": (
            "The hinge fit is descriptive only. Use it in a manuscript only if residuals and the observed "
            "boundary transition support the fixed-slope model; do not force the model onto the data."
        ),
    }
    (output / "icc27_boundary_sweep_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"summarized {len(rows)} valid runs across {len(grouped)} placements")
    if model:
        print(f"candidate hinge tau={model['tau_s']:.3f}s, RMSE={model['rmse_s']:.3f}s")
    print(f"wrote outputs under: {output}")


if __name__ == "__main__":
    main()
