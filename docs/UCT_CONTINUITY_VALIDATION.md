# UCT Release-17 NTN continuity validation

## Purpose

This focused campaign independently validates a measurement effect first observed in archived Málaga Amarisoft NTN runs:

> Receiver-visible sequence-gap loss can remain near zero while an application session is incomplete because an unobserved terminal suffix lies outside the receiver's inferred sequence space.

The UCT experiment is deliberately small and controlled. It is **not** a replacement for the larger TLE/SGP4 campaign and it must not be presented as a Release-18 handover experiment.

## Scientific design

Use the working UCT Release-17 transparent NTN/OAI native-LEO condition (B3) as the radio environment.

Run two matched conditions, five repetitions each:

1. **LEO-safe negative control** — the complete multimodal application session ends at least 60 s before the frozen serving-link boundary.
2. **LEO-boundary exposure** — the identical multimodal application session is scheduled to continue at least 30 s beyond the same frozen serving-link boundary.

The application duration, workload parameters, software versions, OAI configuration and paired random seed must remain identical between the two conditions. The intended experimental difference is only application timing relative to the deterministic service boundary.

The five pairs use counterbalanced run order:

- pair 1: safe, boundary
- pair 2: boundary, safe
- pair 3: safe, boundary
- pair 4: boundary, safe
- pair 5: safe, boundary

## Boundary calibration gate

Before final runs, perform engineering-only calibration of the B3/native-LEO service boundary. Freeze:

- the exact OAI commit and local diff;
- gNB/UE launch configuration;
- the radio/trajectory time anchor used to measure elapsed time;
- the expected service-boundary time relative to that anchor;
- the radio-log signature used to identify the boundary;
- application launch offsets for the safe and boundary conditions.

This calibration must use radio/geometry state, not final application outcomes.

Copy `config/uct_continuity.example.yaml` to an ignored local file, for example:

```bash
cp config/uct_continuity.example.yaml config/uct_continuity.local.yaml
```

Fill the three `null` timing values after the engineering calibration, then freeze the final matrix:

```bash
python scripts/plan_continuity_campaign.py \
  --config config/uct_continuity.local.yaml \
  --output-json results/uct_continuity_validation/campaign_plan.json \
  --output-csv results/uct_continuity_validation/campaign_plan.csv
```

The planner rejects a final matrix that does not preserve the negative-control margin or boundary overrun.

## Portable workload

`scripts/continuity_benchmark.py` is a host-neutral revision of the Málaga synthetic multimodal workload. It retains:

- Opus-like audio at 20-ms packetization by default;
- synthetic control/telestration-style traffic at 100 Hz by default;
- compressed-video-like GOP traffic at 30 fps by default;
- optional DSCP marking.

For this continuity paper, one-way delay is not required. Do not enable or publish one-way delay unless clock synchronization has independently passed the study threshold.

Example receiver:

```bash
python scripts/continuity_benchmark.py \
  --mode server \
  --run-id UCT_LEO_SAFE_R01 \
  --workload combined \
  --duration 210 \
  --bind-ip 0.0.0.0 \
  --output receiver.json
```

The receiver should normally run longer than the client session so it does not itself create the terminal cutoff.

Example sender:

```bash
python scripts/continuity_benchmark.py \
  --mode client \
  --run-id UCT_LEO_SAFE_R01 \
  --workload combined \
  --duration 180 \
  --server <REMOTE_APPLICATION_IP> \
  --seed 4101 \
  --output sender.json
```

Codex must replace host/interface/IP details with values discovered on the UCT system. Do not commit private addresses or subscriber credentials.

## Continuity reconciliation

After both endpoint JSON files are local in the run directory:

```bash
python scripts/reconcile_continuity.py \
  --sender sender.json \
  --receiver receiver.json \
  --output continuity_summary.json
```

The analysis separates:

- **receiver prefix loss** — missing sequence numbers up to the receiver's highest observed sequence;
- **Session Completion Ratio (SCR)** — receiver unique units / application-generated units;
- **Terminal Censoring Fraction (TCF)** — application-generated units above the receiver's highest observed sequence / application-generated units;
- **Continuity Deficit Duration (CDD)** — terminal suffix units / sender achieved generation rate;
- **cross-stream last-receive skew** where the portable benchmark provides receive timestamps.

The reconciliation script is also compatible with the archived Málaga sender/server JSON schema.

## Required per-run artifact contract

Every final UCT run should contain at minimum:

```text
<run_id>/
├── run_manifest.json
├── sender.json
├── receiver.json
├── continuity_summary.json
├── radio_boundary.json
├── gnb.log
├── ue.log
└── qc.json
```

`run_manifest.json` should record:

- run ID, condition and paired repetition;
- UTC start/end;
- paired seed;
- application duration and scheduled launch offset;
- frozen expected service-boundary time;
- experiment-framework commit;
- OAI commit and dirty-state hash;
- relevant configuration hashes;
- run status and any failure classification.

`radio_boundary.json` should record the independently observed radio boundary, including the matching raw-log timestamp/signature. Do not infer the radio boundary from application delivery counters.

## Run validity

A final run is valid only if:

- the intended B3/native-LEO condition launched;
- attach/PDU connectivity formed;
- the paired workload configuration/seed matches the plan;
- sender and receiver JSONs exist and parse;
- radio logs cover the intended interval;
- the boundary can be independently located for boundary-exposure runs;
- the safe run demonstrably finishes before the frozen boundary;
- no instrumentation failure explains application termination.

Keep failed/invalid runs. Do not rerun until a desired result appears.

## Expected scientific comparison

The hypothesis is predeclared:

- **safe control:** receiver prefix loss and sender/receiver reconciled session delivery should agree closely, with SCR near 1 if the link remains healthy;
- **boundary exposure:** the deterministic NTN service boundary may create a terminal suffix that receiver-only prefix-loss accounting does not represent.

A result that does not support this hypothesis must be retained and reported.

## Relation to Release 17/18

The UCT campaign validates an application-measurement method on a Release-17 NTN implementation. It does **not** claim evaluation of Release-18 handover or satellite-switch procedures.

The eventual paper may use Release-18 mobility/service-continuity mechanisms as motivation for why boundary-aware application KPIs are useful when validating whether radio-level mobility actually preserves application sessions.

## Codex handoff objective

Codex should now add only the UCT-host-specific orchestration needed to:

1. reproduce the known-good B3/native-LEO radio condition;
2. calibrate/freeze the deterministic service-boundary anchor;
3. place the same 180-s workload safely before or deliberately across that boundary;
4. run the frozen 10-run counterbalanced matrix without interactive waiting;
5. collect the required run artifacts and stop automatically on unexpected failure;
6. package the campaign for `rclone` transfer to the designated Drive location.

Do not redesign the scientific matrix unless an engineering limitation makes it impossible. Any such change must be documented before final runs.
