# Paper A — ICC27 TLE/SGP4 Trajectory-Robustness Execution Brief

## Mission

Execute the compact cross-trajectory robustness campaign frozen in `docs/ICC27_TLE_TRAJECTORY_ROBUSTNESS.md`.

This is **Paper A only**. Its purpose is to remove the remaining single-trajectory generalizability limitation after the completed native-trajectory prospective confirmation.

Do not modify or invalidate the completed 18-run prospective-confirmation archive. Treat that campaign as immutable prior evidence.

## Branch

Run only on:

`paper-a-icc27-tle-robustness`

Do not switch into Paper-B work and do not merge Paper-B scientific logic.

## Preserve prior evidence

Before new work, verify and preserve:

- completed Paper-A prospective confirmation: 18/18 valid scientific slots;
- final QC PASS;
- archive and SHA-256;
- alternative native-trajectory engineering failures already documented;
- original Paper-A 600-km native trajectory evidence.

The new campaign is additive robustness evidence only.

## Reuse the existing TLE/SGP4 framework

Inspect the host and repository for the already-developed TLE/SGP4 components before writing new code, including where present:

- `src/ntn_telementoring/orbit.py`;
- `src/ntn_telementoring/passes.py`;
- CLI pass-selection/trace generation;
- local TLE-to-OAI adapter/controller;
- state-fidelity tooling;
- previously proven TLE engineering artifacts;
- OAI state-vector/SIB19 integration;
- current Paper-A supervisor, treatment gate, QC, dashboard and finalizer.

Do not create a second experiment framework if existing components can be safely composed.

Do not use `tc/netem` as the orbital model.

## Stage 1 — freeze orbital inputs and pass selection

Use the protocol and `config/icc27_tle_trajectory_robustness.example.yaml` as authoritative guardrails.

Use one frozen Starlink TLE snapshot. If an already archived, provenance-complete snapshot is suitable, prefer it. Otherwise obtain one using the established project mechanism and archive:

- source;
- retrieval UTC;
- raw private snapshot;
- SHA-256;
- observer coordinates;
- pass-selection code hash.

Do not commit raw TLE data publicly unless redistribution is explicitly appropriate.

Before application outcomes exist, enumerate passes over the frozen search horizon and select the first chronological eligible pass in each predeclared band:

- HIGH: max elevation >=75 deg;
- MEDIUM: max elevation 40–60 deg;
- LOW: max elevation 20–30 deg;
- elevation mask: 10 deg;
- minimum usable pre-boundary trace: 240 s.

If a band has no eligible pass, extend the search horizon transparently before any Paper-A application result is seen.

Freeze pass IDs and deterministic trace hashes before engineering validation.

## Stage 2 — TLE-to-OAI fidelity and lifecycle qualification

Determine the actual pinned-OAI replay mode and document it:

- continuous/epoch-based OAI propagation, or
- deterministic discrete external state updates.

Verify the TLE/SGP4 state genuinely controls the intended OAI NTN state. At minimum compare target versus applied/logged position/velocity, timing/delay, Doppler/frequency state and update timing where observable.

For each selected pass require 3 consecutive engineering-only lifecycle passes verifying:

- gNB healthy;
- UE healthy;
- RFsim connected;
- target/applied state fidelity passes the predeclared engineering criterion;
- PBCH/SIB19 behavior is normal for the controlled experiment;
- RRC attach;
- PDU session;
- UE tunnel;
- non-scientific application-path probe;
- observable T310 boundary;
- no unexplained SIGSEGV/assertion/process exit.

Do not launch the Paper-A scientific sender during engineering qualification.

If a pass is not stable, stop and diagnose. Do not retry until it happens to pass. Do not replace it based on application outcomes.

## Stage 3 — per-pass calibration

After 3/3 engineering qualification for a pass, run exactly three radio-only T310 calibrations for that pass.

Freeze the replay-dependent spread rule before calibration outcomes:

- continuous/epoch mode: <=0.10 s;
- discrete mode with update period dt: <=max(0.10 s, 1.25*dt).

Do not loosen the criterion after seeing values.

Record the three values, median, spread, state-fidelity status and engineering-pass count in a calibration JSON accepted by `scripts/plan_icc27_tle_trajectory_robustness.py`.

Only after all three selected passes qualify and calibrate may the scientific matrix be emitted.

## Stage 4 — freeze 27-run scientific matrix

Populate a local untracked config from `config/icc27_tle_trajectory_robustness.example.yaml`.

Run the public planner and freeze:

- local config SHA-256;
- calibration-input SHA-256;
- design SHA-256;
- emitted JSON/CSV plan;
- all orbital trace hashes;
- framework and OAI commit identifiers.

The matrix is fixed at 27 valid scientific slots:

- 3 pass geometries;
- 3 placements (`M05`, `Z00`, `P05`);
- 3 fresh unique matched seeds per pass;
- exact block and placement order declared in the config.

No scientific outcome may modify this plan.

## Stage 5 — execute Paper-A workload

Use the same Paper-A 180-s combined UDP workload and measurement definitions as the completed prospective confirmation.

Do not import the separate TLE-paper application/QoE claims.

Before every sender launch run the existing prospective Paper-A treatment-integrity gate. Require:

- RRC serving context;
- PDU session;
- UE/GTP tunnel;
- gNB/UE processes alive;
- no unrecovered pre-launch release;
- application path reachable;
- valid pass-specific radio anchor;
- replay controller/state-fidelity health;
- frozen launch timing.

Gate failure prevents sender launch. Preserve the attempt. Maximum one identical same-slot replacement. Scientific outcome is never a validity criterion.

## Stage 6 — robustness analysis

After 27 valid slots:

Report each pass independently and the pooled nine pass-seed matched triplets.

Required metrics:

- whole-session delivery by M05/Z00/P05;
- terminal missing fraction;
- receiver-prefix loss separately;
- CDD;
- final app reception relative to T310;
- PBCH/radio-failure timing where extractable;
- cross-stream completion spread;
- last-receive skew.

Predeclared directional checks:

- `M05 >= Z00`;
- `Z00 >= P05`.

Use exact two-sided sign tests over non-tied pass-seed matched comparisons. Report pass heterogeneity descriptively. Do not create a post-hoc universal fit and call it prospective.

## Stage 7 — final QC, package and upload

Final QC must verify:

- 27 valid frozen slots;
- complete 3-pass x 3-placement x 3-seed matrix;
- selected-pass provenance and trace hashes;
- state-fidelity PASS for all scientific pass configurations;
- per-pass calibration QC;
- treatment-integrity PASS for every valid scientific attempt;
- replacement rules respected;
- all required artifacts complete;
- plan/config/OAI/framework hashes match;
- outcome-blind validity preserved.

Package all attempts, orbital inputs/provenance, traces, engineering validation, calibration, scientific artifacts, analysis and QC. Upload to the existing Paper-A Drive hierarchy in a clearly separate TLE robustness folder. Verify remote SHA-256 before declaring COMPLETE.

## Dashboard

Reuse the existing Paper-A dashboard. Adapt it to show:

- `TLE_INPUT_FREEZE`;
- `PASS_SELECTION`;
- `STATE_FIDELITY`;
- `ENGINEERING_VALIDATION`;
- `CALIBRATION`;
- `SCIENTIFIC_ROBUSTNESS`;
- `QC`;
- `PACKAGING`;
- `UPLOADING`;
- `COMPLETE`/`FAILED`.

Show pass band/ID, trace hash short form, qualification x/3, calibration x/3, scientific completed/27, treatment gate, OAI/replay health, watchdog heartbeat, invalid attempts/replacements and final upload verification.

Progress must represent real completed work, never elapsed-time fiction.

## Mandatory execution rule

`CODEX DOES THE THINKING; THE HOST DOES THE WAITING.`

Codex may inspect, reason, implement missing host wiring, launch durable supervisor/watchdog/dashboard, verify the initial PID/heartbeat/dashboard once, print ordinary-shell monitoring commands, and then **EXIT**.

No `watch`, `tail -f`, polling loop or sleeping while pass selection, engineering runs, calibration, scientific runs, packaging or upload are executing.

If the TLE-to-OAI path cannot pass state fidelity and lifecycle qualification without materially changing the scientific mechanism, stop and report the limitation rather than manufacturing a result.
