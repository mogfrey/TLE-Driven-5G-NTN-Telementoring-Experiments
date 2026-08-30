# Paper B AUSW Corrective Campaign V2

## Why a corrective campaign is required

The completed V1 campaign is preserved as a pilot/audit dataset, but it is not the final confirmatory dataset. Forensic inspection found two instrumentation-integrity defects that are independent of the scientific hypothesis:

1. The audio receiver processes were launched before the measurement gate under a wall-clock `timeout` budget. The budget expired roughly 15 s before the 180 s application interval ended. This created an artificial common AUSW termination near media time 165 s in otherwise healthy NOMINAL runs.
2. At least one V1 run (`PAPERB_DEG_R03`, with a similar whole-session zero-data anomaly in `PAPERB_FAIL_R03`) contained no received audio/video/control application data from startup but passed the original run-validity QC because timing and file-presence checks were insufficient.

The correction is an instrumentation/QC correction only. It must not tune the scientific hypothesis, AUSW thresholds, condition timing, seeds, or result interpretation.

## Non-negotiable scientific freeze

Keep unchanged from V1 unless a genuine laboratory-interface incompatibility makes execution impossible:

- scientific question;
- primary hypothesis;
- AUSW gate thresholds;
- 180 s bundled workload and 10 s warm-up;
- radio-only T310 calibration methodology;
- NOMINAL / DEGRADED_CONNECTED / NEAR_FAILURE definitions;
- paired seeds and counterbalancing logic;
- 5 final repetitions per condition;
- confirmatory rule (>=4/5 DEGRADED_CONNECTED runs);
- no `tc/netem`, arbitrary loss/jitter, or cross-traffic treatment.

## Required receiver-lifetime fix

The audio receivers may be armed before the measurement gate, but their watchdog/timeout budget MUST NOT begin consuming the intended observation lifetime before the measurement gate.

For NOMINAL and DEGRADED_CONNECTED, the required observation lifetime is the full 180 s application interval because both conditions are intended to remain RRC-connected through workload end.

For NEAR_FAILURE, the application intentionally crosses the independently measured T310 boundary before workload end. Instrumentation validity therefore requires the receiver harness to remain observable through the independently measured service boundary, not necessarily through the full 180 s after service has intentionally failed. This shorter required lifetime must be derived solely from the run's radio timing (T310 relative to application start) and never from application/AUSW outcomes. A genuine premature receiver timeout remains invalid under every condition.

Preferred implementation:

1. Start receivers and make them ready before the gate.
2. Wait for `WORKLOAD_START_GATE`.
3. From the gate time, start the receiver observation watchdog.
4. For NOMINAL / DEGRADED_CONNECTED, require the full 180 s interval.
5. For NEAR_FAILURE, require observation through the independently measured T310 boundary; post-boundary receiver termination caused by the positive-control service failure is not itself an instrumentation defect.
6. Only after the required observation interval plus a cleanup guard may a cleanup watchdog terminate a receiver that remains blocked.

Write `application/receiver_lifecycle.json` with gate-relative lifetime, timeout state, exit reason and exit code.

## Strict instrumentation QC

Every engineering/final run must execute `scripts/paper_b_corrective_qc.py` after the existing AUSW analysis.

A run is instrumentation-invalid if any of these occur:

- `run_status.json` does not report pass;
- audio receiver lifecycle artifact is missing;
- either audio receiver dies before the condition-specific required observation interval;
- a receiver is killed by a genuinely premature timeout;
- the first five complete post-warm-up windows show no traffic for any one of video, audio UL, audio DL, or telestration;
- no application data are observed anywhere in the run.

The checker defaults to the full duration. A shorter `--required-lifetime-s` may be supplied only for the predeclared NEAR_FAILURE positive control and must be derived solely from the independently measured radio boundary.

These checks are independent of whether AUSW supports the hypothesis.

A valid run that is fully usable in DEGRADED_CONNECTED remains a VALID NEGATIVE scientific result and must not be repeated merely to improve the conclusion.

## Execution sequence

1. Preserve V1 read-only and write a forensic audit/deviation note.
2. Fix receiver lifetime handling and add lifecycle evidence.
3. Integrate strict corrective QC into the locally evolved Paper-B supervisor.
4. Unit-test and shell-check.
5. Run one local workload-only smoke test if possible without radio, proving both audio receivers survive the full requested gated interval.
6. Run 3 fresh radio-only calibrations.
7. Freeze V2 plan and hashes before inspecting application outcomes.
8. Run exactly 1 engineering run per condition.
9. If engineering instrumentation QC fails, diagnose whether the cause is a real instrumentation fault or a condition-aware QC defect. Fix only instrumentation/QC semantics before any final runs; document the correction. Do not retime conditions to force an AUSW result.
10. Run 5 valid final repetitions per condition under the unattended tmux supervisor.
11. Preserve all physical attempts; replace only instrumentation/lab-invalid attempts.
12. Analyze using the run as the statistical unit.
13. Package V2 separately from V1 and upload ZIP + SHA-256 to a new Google Drive subfolder.

## Completion requirement

The V2 campaign may be marked complete only after:

- 3 valid fresh calibrations;
- 3 instrumentation-valid engineering runs;
- 15 instrumentation-valid final runs;
- final analysis;
- package + SHA-256;
- verified rclone upload;
- `upload_report.json` recorded.

Do not overwrite the V1 package or results tree.
