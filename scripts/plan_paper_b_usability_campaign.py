#!/usr/bin/env python3
"""Freeze the Paper-B AUSW campaign from radio-only calibration evidence.

The planner never reads application outcomes. Condition timings are derived only
from the independently calibrated Timer-T310 service boundary.
"""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
import yaml

ORDERS = [
    ("nominal", "degraded_connected", "near_failure"),
    ("degraded_connected", "near_failure", "nominal"),
    ("near_failure", "nominal", "degraded_connected"),
    ("nominal", "near_failure", "degraded_connected"),
    ("degraded_connected", "nominal", "near_failure"),
]
ROLES = {
    "nominal": "negative_control",
    "degraded_connected": "primary_connected_but_unusable_test",
    "near_failure": "positive_service_failure_control",
}
PREFIX = {"nominal": "NOM", "degraded_connected": "DEG", "near_failure": "FAIL"}


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    p.add_argument('--calibration', required=True)
    p.add_argument('--output-json', required=True)
    p.add_argument('--output-csv', required=True)
    a=p.parse_args()
    cfg=yaml.safe_load(Path(a.config).read_text())
    cal=json.loads(Path(a.calibration).read_text())
    c=cfg['campaign']; duration=float(cfg['workload']['duration_s'])
    earliest=float(cal['earliest_s']); latest=float(cal['latest_s']); median=float(cal['median_s'])
    guard=float(c['scheduler_guard_s'])
    offsets={
      'nominal': max(0.0, earliest-duration-float(c['nominal_end_margin_s'])-guard),
      'degraded_connected': max(0.0, earliest-duration-float(c['degraded_connected_end_margin_s'])-guard),
      'near_failure': max(0.0, latest+float(c['near_failure_overrun_s'])-duration+guard),
    }
    seeds=list(c['paired_seeds']); reps=int(c['repetitions_per_condition'])
    if len(seeds) < reps: raise SystemExit('paired_seeds shorter than repetitions_per_condition')
    runs=[]; seq=1
    for rep in range(1,reps+1):
        order=ORDERS[(rep-1)%len(ORDERS)]
        for condition in order:
            offset=round(offsets[condition],3); end=round(offset+duration,3)
            run_id=f"PAPERB_{PREFIX[condition]}_R{rep:02d}"
            runs.append({
              'sequence':seq,'run_id':run_id,'condition':condition,'condition_role':ROLES[condition],
              'repetition':rep,'paired_seed':seeds[rep-1],'duration_s':duration,
              'application_launch_offset_s':offset,'planned_application_end_s':end,
              'expected_service_boundary_s':round(median,3),
              'planned_margin_to_earliest_boundary_s':round(earliest-end,3),
              'planned_overrun_from_latest_boundary_s':round(end-latest,3),
            }); seq+=1
    plan={
      'schema_version':1,'campaign_id':cfg['campaign_id'],
      'scientific_design':'prospective three-condition AUSW validation; timings frozen from radio-only T310 calibration, never application outcomes',
      'run_is_statistical_unit':True,'calibrated_earliest_boundary_s':earliest,
      'calibrated_latest_boundary_s':latest,'calibrated_median_boundary_s':median,
      'workload_duration_s':duration,'repetitions_per_condition':reps,'run_count':len(runs),
      'conditions':{
        'nominal':'ends >= nominal_end_margin before earliest calibrated T310 boundary',
        'degraded_connected':'ends shortly before earliest calibrated T310 boundary and must remain RRC-connected through workload end',
        'near_failure':'crosses the calibrated T310 boundary as a positive control',
      },'runs':runs,
    }
    outj=Path(a.output_json); outj.parent.mkdir(parents=True,exist_ok=True); outj.write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')
    outc=Path(a.output_csv); outc.parent.mkdir(parents=True,exist_ok=True)
    with outc.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(runs[0].keys())); w.writeheader(); w.writerows(runs)

if __name__=='__main__': main()
