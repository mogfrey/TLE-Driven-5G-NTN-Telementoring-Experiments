# TLE-Driven 5G NTN Telementoring — Experiments

Public reproducibility tooling for cross-layer evaluation of surgical telementoring over 3GPP Release-17 transparent NTN with TLE-driven LEO dynamics.

This repository contains **experiment code and safe reproducibility documentation only**. The manuscript, private raw results, credentials, real testbed addresses and internal working material are maintained separately.

## Intended experimental chain

`TLE / SGP4 -> orbital state -> Release-17 NTN state -> OAI radio/protocol telemetry -> transport -> telementoring application -> supportability analysis`

## Planned components

- deterministic TLE/SGP4 pass and state-vector generation;
- experiment provenance capture;
- safe configuration templates;
- OAI/Open5GS preflight validation;
- Release-17 NTN experiment orchestration;
- TCP CUBIC/BBR and UDP measurement runners;
- video/audio/telestration workload generation;
- synchronized telemetry collection;
- run-level statistical analysis and confidence intervals;
- quantitative supportability-envelope analysis;
- granular experiment runbook.

## Public/private boundary

Do not commit:

- credentials, IMSI keys, OP/OPc values or tokens;
- real private IP addresses unless explicitly safe for publication;
- patient-identifiable or non-redistributable media;
- private raw logs containing sensitive infrastructure details;
- manuscript source or unpublished reviewer material.

Use `config/testbed.example.yaml` as the public template and keep the populated local configuration untracked.

## Status

Initial framework construction. Do not use for final data collection until the preflight stage is marked frozen.
