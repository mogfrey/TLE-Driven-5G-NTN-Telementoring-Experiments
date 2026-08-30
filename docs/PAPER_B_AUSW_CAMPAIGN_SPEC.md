# Paper B — UCT AUSW Validation Campaign

## Purpose

Prospectively test a scientific claim that is **different from Paper A**:

> A Release-17 NTN link can remain RRC-connected and continue delivering some data after the bundled application has already left its application-usable service window (AUSW).

Paper A owns the service-continuity/failure-boundary contribution. This campaign uses that boundary only as an independently calibrated timing reference and positive control.

## Frozen design

1. Run **3 radio-only T310 calibration repetitions**. No application outcomes are examined to choose condition timings.
2. Derive all launch offsets only from the earliest/latest calibrated T310 boundary.
3. Run one engineering/instrumentation trial of each condition.
4. Freeze config, plan, threshold and workload hashes.
5. Execute **15 final runs**: 5 paired repetitions each of:
   - `nominal`: application ends at least 60 s before the earliest calibrated T310 boundary.
   - `degraded_connected`: application ends about 1 s before the earliest calibrated T310 boundary. It is valid only if RRC remains connected for the entire application interval.
   - `near_failure`: application crosses T310 by at least ~30 s; positive service-failure control.
6. The **desired application outcome is never a run-validity criterion**. If `degraded_connected` remains fully usable, preserve it as a valid negative result. Do not move the timing after seeing final outcomes.
7. No `tc/netem`, no arbitrary packet impairment, and no load tuning are permitted as the primary degradation mechanism.

## Primary Paper-B measurements

Per complete 1-second window after warm-up:

- video decoded/generated frame delivery ratio;
- uplink Opus RTP packet delivery ratio;
- downlink Opus RTP packet delivery ratio;
- telestration request/ack delivery ratio;
- maximum telestration request/ack RTT;
- RRC-connected state from the independently observed T310 boundary;
- whether any bundled application data remain alive.

AUSW is the intersection of the application gates while RRC is connected. RRC and data-plane windows are reported separately.

## Confirmatory result (predeclared)

A degraded-connected repetition supports the central claim when:

1. RRC is alive through the whole application interval;
2. AUSW ends before application end;
3. data continue for at least 0.5 s after AUSW ends; and
4. RRC remains alive for at least 0.5 s after AUSW ends.

Campaign-level confirmatory support is predeclared as **at least 4 of 5** valid degraded-connected repetitions satisfying the run-level criterion.

This rule is an analysis rule, not a rerun rule.
