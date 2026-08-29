# IEEE ICC 2027 UCT Release-17 NTN boundary-position sweep

## Purpose

This campaign extends the validated UCT SAFE-versus-BOUNDARY method into a controlled
seven-point sweep around the same deterministic Release-17 NTN service boundary.

Scientific question:

> How does whole-session completion change as the intended application end is moved
> across a calibrated Release-17 NTN service boundary, and does receiver-visible
> prefix loss remain insensitive to the resulting terminal truncation?

This is a **service-continuity/failure-boundary** experiment. It does not evaluate
application usability/AUSW, perceptual quality, or Málaga data.

## Frozen primary design

- same validated OAI/Open5GS Release-17 NTN environment and dynamic LEO trajectory;
- same 180-s combined audio/video/control UDP workload;
- SHSC disabled during the primary sweep;
- DSCP disabled;
- one-way delay disabled;
- three engineering-only boundary calibrations before scientific runs;
- calibration statistic: median;
- maximum accepted calibration spread: 0.10 s;
- intended application-end offsets: `-30, -15, -5, 0, +5, +15, +30 s`;
- three fixed workload seeds, reused at every placement;
- 21 valid scientific slots;
- at most one pre-authorized replacement for an invalid slot;
- validity must be based on instrumentation/protocol checks, never the scientific outcome.

The fixed counterbalanced order is:

- seed A: `-30, -15, -5, 0, +5, +15, +30`;
- seed B: `+30, +15, +5, 0, -5, -15, -30`;
- seed C: `0, -30, +30, -15, +15, -5, +5`.

## Public tools

### 1. Freeze the campaign plan

Copy the public template to an ignored local file:

```bash
cp config/icc27_boundary_sweep.example.yaml config/icc27_boundary_sweep.local.yaml
```

After three engineering-only boundary calibrations, fill
`calibration.boundary_times_s` and generate the frozen plan:

```bash
python scripts/plan_icc27_boundary_sweep.py \
  --config config/icc27_boundary_sweep.local.yaml \
  --output-json results/uct_icc27_boundary_sweep/campaign_plan.json \
  --output-csv results/uct_icc27_boundary_sweep/campaign_plan.csv
```

The planner refuses to emit a plan if the calibration spread exceeds the frozen
0.10-s tolerance or if the placement/seeding/counterbalancing matrix has drifted.

### 2. Initialize each physical attempt

```bash
python scripts/init_icc27_attempt.py \
  --plan results/uct_icc27_boundary_sweep/campaign_plan.json \
  --plan-run-id UCT_ICC27_M30_SA \
  --runs-root results/uct_icc27_boundary_sweep/runs
```

If and only if that original attempt is invalid under the prospective QC rule, one
replacement may be initialized with:

```bash
python scripts/init_icc27_attempt.py \
  --plan results/uct_icc27_boundary_sweep/campaign_plan.json \
  --plan-run-id UCT_ICC27_M30_SA \
  --runs-root results/uct_icc27_boundary_sweep/runs \
  --attempt retry1
```

The helper refuses to create `RETRY1` for a valid original attempt.

### 3. Campaign QC

After the orchestrator has produced all artifacts:

```bash
python scripts/qc_icc27_boundary_sweep.py \
  --plan results/uct_icc27_boundary_sweep/campaign_plan.json \
  --runs-root results/uct_icc27_boundary_sweep/runs \
  --output-json results/uct_icc27_boundary_sweep/campaign_qc.json \
  --output-csv results/uct_icc27_boundary_sweep/campaign_qc_attempts.csv
```

The QC command exits non-zero unless all 21 planned slots have one selected valid
attempt and the one-retry rule is respected.

### 4. Scientific summary

Only after campaign QC passes:

```bash
python scripts/analyze_icc27_boundary_sweep.py \
  --plan results/uct_icc27_boundary_sweep/campaign_plan.json \
  --campaign-qc results/uct_icc27_boundary_sweep/campaign_qc.json \
  --output-dir results/uct_icc27_boundary_sweep/analysis
```

It produces run-level and placement-level CSVs plus a JSON summary. It also evaluates
the candidate descriptive hinge relation

`CDD(delta) = max(0, delta + tau)`

without assuming that the model is valid. The fit is manuscript-eligible only if the
observed sweep and residuals support it.

## Required per-attempt artifact contract

Every physical attempt directory must contain:

```text
<run_id>/
├── run_manifest.json
├── sender.json
├── receiver.json
├── continuity_summary.json
├── radio_boundary.json
├── timing_alignment.json
├── gnb.log
├── ue.log
└── qc.json
```

The public planner initializes the frozen fields in `run_manifest.json`. The
host-specific orchestrator must additionally record exact experiment-framework/OAI
provenance, configuration hashes, UTC start/end, and final status.

### `timing_alignment.json`

The host-specific runner must normalize the cross-layer timestamps onto the same
radio-anchor time base:

```json
{
  "schema_version": 1,
  "application_start_s_from_radio_anchor": 0.0,
  "application_end_s_from_radio_anchor": 0.0,
  "service_boundary_s_from_radio_anchor": 0.0,
  "t310_expiry_s_from_radio_anchor": 0.0,
  "last_receive_s_from_radio_anchor": {
    "audio": 0.0,
    "video": 0.0,
    "control": 0.0
  }
}
```

Values shown above are schema examples, not experimental values. The service boundary
must be located from the independently frozen radio/log signature, not inferred from
application counters.

### `qc.json`

The host-specific orchestrator must write outcome-independent QC such as:

```json
{
  "schema_version": 1,
  "plan_run_id": "UCT_ICC27_M30_SA",
  "valid": true,
  "failure_classification": null,
  "checks": {
    "radio_condition_launched": true,
    "attach_pdu_ok": true,
    "workload_matches_plan": true,
    "sender_receiver_parse": true,
    "radio_logs_cover_interval": true,
    "boundary_located": true,
    "timing_alignment_ok": true,
    "instrumentation_ok": true
  }
}
```

A valid unexpected scientific result remains valid. Never rerun a valid slot because
its outcome is surprising.

## Primary outputs for the ICC paper

The campaign is designed to support:

1. whole-session delivery versus **measured** intended-end offset;
2. receiver-prefix loss versus the same offset;
3. continuity-deficit duration versus measured boundary overrun;
4. audio/video/control completion spread and last-receive skew;
5. final application receive time relative to the service boundary and T310;
6. an optional fixed-slope hinge description if supported by the observed data.

The statistical unit is the run. The three packets/flows inside a run are not
independent repetitions.
