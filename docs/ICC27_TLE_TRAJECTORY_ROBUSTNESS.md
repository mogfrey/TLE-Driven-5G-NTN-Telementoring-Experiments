# Paper A — IEEE ICC 2027 TLE/SGP4 Trajectory-Robustness Protocol

## Purpose

Address the remaining Paper-A generalizability limitation: all publishable boundary evidence so far uses one validated native OAI `SAT_LEO_TRANS` deterministic trajectory.

This protocol adds a **secondary robustness campaign**, not a new Paper-A contribution. It tests whether the same measurement phenomenon reproduces on three independently selected TLE/SGP4-derived LEO pass geometries while preserving the Paper-A workload, continuity metrics, validity rules and Release-17 OAI/Open5GS architecture.

Paper A must not claim measurements of commercial Starlink service. Starlink TLE geometry is used only as a reproducible orbital-state input to OAI emulation.

## Scientific question

Does the Paper-A boundary result remain directionally consistent across independently selected orbital pass geometries?

Predeclared expectations:

1. whole-session delivery at `M05` is greater than or equal to `Z00`;
2. whole-session delivery at `Z00` is greater than or equal to `P05`;
3. receiver-visible prefix loss can remain insensitive to an undelivered terminal suffix;
4. application reception terminates before T310 and near independently observed radio-failure onset markers.

A surprising result is scientifically valid and must be preserved.

## Scope guardrail

This experiment does **not** turn Paper A into the TLE/SGP4 supportability paper. Do not add transport comparisons, CUBIC/BBR, QoE thresholds, OneWeb, supportability envelopes, elevation-to-performance models, handover claims, or constellation-performance claims.

The TLE/SGP4 path is used here only as an independent orbital-state generator for a compact robustness check of the existing Paper-A continuity measurement claim.

## Pass selection — frozen before application outcomes

Use one frozen Starlink TLE snapshot obtained before scientific execution. Archive source metadata, retrieval UTC and SHA-256. Do not refresh the TLE snapshot between repetitions.

Observer coordinates must be the UCT laboratory ground point already used by the TLE experiment framework.

Default elevation mask: `10 deg`.

Search horizon: `48 h`; extend transparently only if a required geometry band has no eligible pass.

Select the **first chronological eligible pass** in each band:

- `HIGH`: maximum elevation >= 75 deg;
- `MEDIUM`: maximum elevation 40–60 deg;
- `LOW`: maximum elevation 20–30 deg.

Eligibility additionally requires at least 240 s of usable pre-boundary trace after the pass enters the configured elevation mask, so the 180-s Paper-A workload can be positioned around the independently calibrated radio boundary.

If a band is unavailable, extend the search horizon before inspecting any application outcome. Do not manually pick a pass because it appears likely to produce a desired continuity result.

Freeze selected pass identifiers, TLE hash, trace hashes, pass-selection metadata and selection code hash before scientific runs.

## TLE-to-OAI fidelity gate

The TLE/SGP4 trace must drive the Release-17 NTN radio state; it must not be translated into arbitrary `tc/netem` rate/loss/jitter.

Before any calibration or application run, validate for every selected pass:

- controller target orbital state versus OAI-applied/logged state where observable;
- position/velocity mapping;
- delay/timing state;
- Doppler/frequency state;
- update timing and discontinuities;
- gNB/UE symmetry where required;
- RRC attach, PDU session, UE tunnel and application-path reachability;
- observable T310/radio boundary;
- no unexplained OAI crash, assertion or persistent synchronization failure.

Each selected pass must complete **3 consecutive engineering-only lifecycle validations**. These attempts are not scientific runs and the Paper-A sender must not run.

If any of the three engineering validations for a pass fails, stop that pass and diagnose. Do not rerun until a desirable result appears. If a selected pass cannot be made stable without changing the frozen scientific mechanism, stop the robustness campaign and report the implementation limitation.

## Replay mode and calibration-repeatability rule

Determine the actual pinned-OAI replay mechanism before calibration and freeze it in provenance.

- If OAI propagates continuously from an epoch/state input, calibration spread must be <= 0.10 s.
- If deterministic external discrete updates are required at period `dt`, the calibration spread limit is `max(0.10 s, 1.25 * dt)`.

This rule is fixed before calibration outcomes. Do not loosen it after seeing calibration values.

Prefer the highest already-validated deterministic update cadence supported by the existing TLE-to-OAI framework; do not introduce a new cadence solely to make a pass succeed.

## Per-pass calibration

For each of `HIGH`, `MEDIUM`, and `LOW` after 3/3 engineering validation:

1. run exactly three radio-only boundary calibrations;
2. extract T310 using the same Paper-A definition;
3. require the replay-mode-specific spread criterion above;
4. freeze the median boundary and all relevant hashes before that pass's scientific runs.

No application outcome may be inspected to choose the boundary or placement.

## Frozen scientific matrix

Three pass geometries x three placements x three fresh matched seeds = **27 valid scientific slots**.

Placements relative to each pass's independently calibrated T310 marker:

- `M05`: intended application end at -5 s;
- `Z00`: intended application end at 0 s;
- `P05`: intended application end at +5 s.

Fresh seed groups are frozen in `config/icc27_tle_trajectory_robustness.example.yaml`. Seeds are unique across passes.

Within each pass, placement order is counterbalanced across its three seed groups. The frozen campaign order interleaves pass blocks to reduce long-duration host/order confounding.

The run is the statistical unit. Packet/frame observations are not independent replicates.

## Workload and measurement invariants

Keep Paper A unchanged:

- same 180-s combined UDP workload;
- audio interval 20 ms;
- control 100 Hz;
- video 30 fps;
- SHSC disabled;
- DSCP disabled;
- one-way-delay analysis disabled;
- same sender/receiver and continuity definitions;
- same whole-session delivery metric;
- receiver-prefix loss reported separately;
- same CDD definition;
- same radio/timing extraction where available.

## Treatment-integrity gate

Immediately before every scientific sender launch require the prospective gate to PASS:

- active RRC serving context;
- active PDU session;
- GTP/UE tunnel present;
- OAI processes alive;
- no unrecovered pre-launch release;
- application path reachable;
- valid radio anchor/replay state;
- launch timing consistent with the frozen pass-specific boundary.

If the gate fails, do not launch the sender. Preserve the physical attempt. A maximum of one identical same-slot replacement is allowed. Scientific outcome is never a validity criterion.

## Primary robustness analysis

Report each pass separately and also the pooled directional robustness across the nine pass-seed matched triplets.

Per pass:

- M05/Z00/P05 whole-session delivery;
- terminal missing fraction;
- receiver-prefix loss;
- CDD;
- final application reception relative to T310;
- first PBCH/radio-failure marker relative to T310 where extractable;
- multimodal completion spread;
- last-receive skew.

Across all nine matched triplets:

- count directionally consistent `M05 >= Z00` comparisons;
- count directionally consistent `Z00 >= P05` comparisons;
- exact two-sided sign test over non-tied pass-seed matched comparisons;
- report pass heterogeneity descriptively rather than fitting a new post-hoc universal model.

Do not refit a hinge model and present it as prospective.

## Paper positioning if successful

The paper may claim robustness across **four orbital realizations**: the original native OAI circular trajectory plus three prospectively selected TLE/SGP4-derived pass geometries.

It must still say these are laboratory OAI emulations, not measurements of commercial satellite service.

## Operational rule

`CODEX DOES THE THINKING; THE HOST DOES THE WAITING.`

Codex must launch durable host-side selector/supervisor/watchdog/dashboard processes, verify the initial heartbeat once, print ordinary-shell monitoring commands, and exit. Codex must not poll, sleep, `watch`, `tail -f`, or babysit long-running engineering/calibration/scientific/package/upload phases.
