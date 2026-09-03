# Paper A — IEEE ICC 2027 Confirmatory Trajectory-B Execution Brief

## Mandatory project execution rule

Before doing anything else, read `docs/CODEX_PROJECT_EXECUTION_RULES.md` in full. Its no-babysitting rule is mandatory and overrides any temptation to wait, poll, tail, watch, sleep, or remain in the Codex session while unattended work progresses.

**After a durable supervisor/watchdog has been launched and its initial PID/status/heartbeat are verified, Codex MUST print the handoff block and EXIT the Codex session immediately.** It must not stay open waiting for geometry validation, calibration, scientific runs, QC, packaging, upload, or checksum verification.

## Mission

Execute one prospective, independent second-geometry confirmatory campaign for Paper A. The scientific question is whether the continuity characteristic observed in the original UCT Release-17 NTN boundary sweep reproduces on a genuinely different deterministic OAI RFsim LEO geometry.

This is **Paper A only**. Do not modify, execute, merge, or reinterpret Paper-B AUSW work. Do not introduce Málaga, QoE thresholds, SHSC, DSCP, one-way-delay analysis, congestion control, scheduler comparisons, or unrelated experiments.

## Repository and branch safety

The intended Git branch is `paper-a-icc27-confirmatory` in `mogfrey/TLE-Driven-5G-NTN-Telementoring-Experiments`.

Before doing any laboratory work:

1. print `pwd`, `git status --short --branch`, `git branch -a`, and `git rev-parse HEAD`;
2. verify the current branch is exactly `paper-a-icc27-confirmatory`;
3. refuse to run scientific experiments from any Paper-B branch;
4. preserve unrelated local work and never use destructive Git reset/clean commands on untracked scientific artifacts;
5. keep host-specific configuration in `config/icc27_trajectory_b_confirmatory.local.yaml`, which must remain untracked.

## Frozen scientific design

Use `config/icc27_trajectory_b_confirmatory.example.yaml` and `scripts/plan_icc27_trajectory_b_confirmatory.py` as authoritative guardrails.

Scientific matrix:

- placements: `-5 s`, `0 s`, `+5 s` relative to the newly calibrated T310 marker;
- six fresh matched seeds exactly as declared in the example config;
- exactly 18 valid scientific slots;
- fixed counterbalanced run order exactly as declared;
- one replacement maximum per invalid slot, using the identical seed, placement, workload, geometry and configuration;
- a surprising scientific outcome is never an invalidity criterion.

SHSC must be disabled. Workload remains the validated 180-s bundled audio/video/control UDP workload with the same generation rates used by Paper A. DSCP and one-way-delay analysis remain disabled.

## Geometry-B requirement

Discover a technically viable deterministic RFsim LEO geometry that is genuinely different from the original Paper-A geometry while preserving the same OAI/Open5GS Release-17 NTN architecture and workload.

The difference must be scientific and reproducible, not a cosmetic rename. Prefer an available OAI-supported change in satellite geometry/channel configuration that changes the deterministic service-boundary realization without changing the measurement question.

Before scientific outcomes are available:

1. document the original geometry parameters;
2. document the proposed Geometry-B parameters and why they are materially different;
3. verify OAI attachment, PDU session, UE tunnel, application path and dynamic NTN operation;
4. run exactly three engineering-only boundary calibrations;
5. do not inspect application completion outcomes to choose or tune the geometry or placements;
6. require calibration spread <= 0.10 s;
7. populate the local YAML with the three calibration times and Geometry-B ID/description;
8. freeze the local config and emitted plan hashes before the first scientific run.

If no genuinely different stable geometry can be validated, STOP and report that fact. Do not manufacture a second geometry by arbitrary packet shaping or N3 `tc/netem`.

## Treatment-integrity gate

The original Paper-A audit found 20/21 original sweep runs valid under a uniform pre-launch serving-context criterion and isolated one treatment-integrity failure. Therefore every new scientific attempt must run a live, outcome-blind gate immediately before sender launch.

Use `scripts/check_treatment_integrity.py` as a mandatory component. Integrate it with the proven local OAI log paths/process names. The gate must verify active serving context, OAI processes, UE tunnel, application path and anchor validity before launch. If the gate fails, do not launch the sender. Preserve the failed attempt and apply the one-replacement rule only to the same scientific slot.

Do not weaken the gate after seeing outcomes.

## Required orchestration work

Reuse the existing validated ICC27 campaign tooling wherever possible. Inspect the existing planner, attempt initializer, dashboard, QC and analysis scripts before writing new orchestration.

Implement only the minimum host-side wiring required to:

1. perform Geometry-B engineering validation and calibration;
2. freeze the local config and 18-run plan;
3. initialize each attempt with provenance and hashes;
4. start/stop OAI safely using the already-proven laboratory procedure;
5. execute the pre-launch treatment-integrity gate;
6. launch the exact frozen workload only after a passing gate;
7. collect sender, receiver, radio and timing artifacts;
8. perform outcome-blind QC;
9. enforce the one-replacement limit;
10. expose a truthful campaign dashboard/watchdog with current phase, slot, attempt, elapsed time, last activity, OAI health, gate state and completed/18 progress;
11. detect stalls and fail safely rather than displaying false progress;
12. package all physical attempts, the frozen plan/config hashes, QC, logs and analyses;
13. upload the final archive to the existing Paper-A ICC27 Google Drive location using the already-configured rclone workflow;
14. verify the remote SHA-256 after upload.

### Absolute no-babysitting handoff

All long-running phases above must be owned by a durable host-side supervisor/watchdog, not by Codex.

Once Codex has:

- launched the supervisor durably (for example via `nohup`, `setsid`, `tmux`, or `systemd`);
- verified the supervisor process/PID is alive;
- verified the initial machine-readable status/heartbeat exists and is advancing normally;
- printed the status path, log path, PID/service/session, and normal-shell inspection commands;

Codex's active work is finished for that invocation.

It MUST then **EXIT THE CODEX SESSION IMMEDIATELY** and return control to the ordinary shell.

Codex MUST NOT execute `watch`, `tail -f`, `journalctl -f`, polling loops, repeated `cat/jq/stat` checks, or long `sleep` commands to observe routine progress. It MUST NOT remain open waiting for engineering validation, calibration, scientific runs, QC, packaging, upload, or checksum verification. Those are supervisor responsibilities.

Monitoring commands may be printed for the human operator, but Codex must not execute them as a waiting strategy.

A later fresh Codex invocation is appropriate only when the supervisor reports a real `FAILED`, `BLOCKED`, or attention-required state, the operator explicitly requests diagnosis, or completed artifacts require reasoning that was not already automated.

## Confirmatory analysis

After all valid slots are complete, analyze the frozen 18-run matrix without changing hypotheses.

Primary checks:

- compare whole-session delivery across `M05`, `Z00`, `P05` within each of the six matched seeds;
- report receiver-visible prefix loss separately;
- report continuity-deficit duration;
- report application cutoff relative to T310 and available radio-failure onset markers such as first PBCH decoding failure;
- report multimodal completion spread and last-receive skew;
- use matched-seed summaries and exact sign tests where applicable;
- do not refit a new model and then present it as prospectively hypothesized;
- preserve any negative or contradictory result.

The expected directional pattern is a hypothesis, not a validity rule: `M05 >= Z00 >= P05` in whole-session delivery, while receiver-prefix loss may remain insensitive to the missing terminal suffix.

## Required completion report

When the campaign is fully packaged and remotely verified, print exactly one concise final block containing:

- `PAPER_A_BRANCH`
- `FRAMEWORK_COMMIT`
- `OAI_COMMIT`
- `GEOMETRY_B_ID`
- `GEOMETRY_B_DIFFERENCE`
- `CALIBRATION_TIMES_S`
- `CALIBRATION_SPREAD_S`
- `PLAN_SHA256`
- `VALID_SLOTS`
- `PHYSICAL_ATTEMPTS`
- `TREATMENT_GATE_FAILURES`
- `REPLACEMENTS_USED`
- `QC_STATUS`
- `ARCHIVE_PATH`
- `ARCHIVE_SHA256`
- `REMOTE_DESTINATION`
- `REMOTE_SHA256_VERIFIED`
- `ANALYSIS_SUMMARY_PATH`
- `DASHBOARD_OR_STATUS_PATH`

Do not edit the Paper-A manuscript based on confirmatory outcomes in this execution session. Preserve and report the scientific evidence first; manuscript integration happens separately after review.
