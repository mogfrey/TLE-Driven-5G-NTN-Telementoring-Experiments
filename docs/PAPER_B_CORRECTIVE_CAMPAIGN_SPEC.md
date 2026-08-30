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

The audio receivers may be armed before the measurement gate, but their watchdog/timeout budget MUST NOT begin consuming the 180 s measurement lifetime before the measurement gate.

Preferred implementation:

1. Start receivers and make them ready before the gate.
2. Wait for `WORKLOAD_START_GATE`.
3. From the gate time, allow the full 180 s measurement interval.
4. Only after measurement end plus a post-measurement guard (default 30 s) may a cleanup watchdog terminate a receiver that has not exited naturally.

Equivalent implementations are acceptable only if they prove the receiver process remained alive through the entire intended measurement interval.

Write `application/receiver_lifecycle.json` with at least:

```json
{
  "audio_uplink": {
    "wall_runtime_s": 181.2,
    "premature_timeout": false,
    "exit_reason": "normal_or_post_measurement_cleanup"
  },
  "audio_downlink": {
    "wall_runtime_s": 181.0,
    "premature_timeout": false,
    "exit_reason": "normal_or_post_measurement_cleanup"
  }
}
```

`wall_runtime_s` must be measured relative to the measurement gate for QC purposes, not merely from pre-gate process creation.

## Strict instrumentation QC

Every engineering/final run must execute `scripts/paper_b_corrective_qc.py` after the existing AUSW analysis.

A run is instrumentation-invalid if any of these occur:

- `run_status.json` does not report pass;
- audio receiver lifecycle artifact is missing;
- either audio receiver dies before the measurement interval ends;
- a receiver is killed by a timeout whose deadline occurred before measurement end;
- the first five complete post-warm-up windows show no traffic for any one of video, audio UL, audio DL, or telestration;
- no application data are observed anywhere in the run.

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
9. If engineering instrumentation QC fails, fix instrumentation only and restart engineering validation. Do not retime conditions to force an AUSW result.
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
