# TLE-Driven 5G NTN Telementoring — Experiments

Public reproducibility tooling for cross-layer evaluation of telementoring-style multimodal traffic over 3GPP Release-17 transparent NTN with TLE-driven and controlled LEO dynamics.

This repository contains **experiment code and safe reproducibility documentation only**. Manuscript source, private raw results, credentials, real testbed addresses and internal working material are maintained separately.

## Intended experimental chain

`TLE / SGP4 -> orbital state -> Release-17 NTN state -> OAI radio/protocol telemetry -> transport -> telementoring application -> supportability analysis`

## Current focused continuity tooling

The repository also contains the frozen public tooling for the IEEE ICC 2027 UCT Release-17 NTN boundary-position sweep:

- `config/icc27_boundary_sweep.example.yaml` — seven placements, three fixed matched seeds, counterbalanced order and calibration tolerance;
- `scripts/plan_icc27_boundary_sweep.py` — rejects calibration/design drift and freezes the 21-slot matrix;
- `scripts/init_icc27_attempt.py` — initializes a physical attempt and enforces the one-retry rule;
- `scripts/qc_icc27_boundary_sweep.py` — verifies the artifact contract and selects exactly one valid attempt per planned slot;
- `scripts/analyze_icc27_boundary_sweep.py` — produces run/placement summaries and an explicitly optional descriptive hinge fit;
- `docs/ICC27_BOUNDARY_SWEEP.md` — scientific design, artifact schemas and execution contract.

This campaign is strictly a service-continuity/failure-boundary experiment. It does not introduce application-usability/AUSW claims into the continuity study.

## Broader components

- deterministic TLE/SGP4 pass and state-vector generation;
- experiment provenance capture;
- safe configuration templates;
- OAI/Open5GS preflight validation;
- Release-17 NTN experiment orchestration;
- TCP CUBIC/BBR and UDP measurement runners;
- video/audio/telestration workload generation;
- synchronized telemetry collection;
- run-level statistical analysis;
- quantitative supportability-envelope analysis;
- granular experiment runbook.

## Public/private boundary

Do not commit:

- credentials, IMSI keys, OP/OPc values or tokens;
- real private IP addresses unless explicitly safe for publication;
- patient-identifiable or non-redistributable media;
- private raw logs containing sensitive infrastructure details;
- manuscript source or unpublished reviewer material.

Use the public templates under `config/` and keep populated `*.local.yaml` files untracked.

## Status

The core Release-17 NTN continuity benchmark and the ICC 2027 boundary-sweep planning/QC/analysis tools are versioned. Host-specific orchestration remains local because it contains laboratory paths, process-control details and potentially sensitive infrastructure information.
