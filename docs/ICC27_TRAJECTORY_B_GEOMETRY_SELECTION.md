# ICC 2027 Paper A — Replacement Geometry-B Selection Rule

## Status before replacement selection

The first candidate Geometry-B used a symmetric 400-km RFsim LEO configuration on gNB and UE after an initial engineering fix exposed an asymmetric gNB/UE geometry mismatch.

That 400-km candidate is **abandoned for scientific use**.

Preserved evidence:

- two valid engineering calibration observations near the T310 boundary;
- one CAL_03 failure in which the UE exited after repeated initial synchronization attempts;
- one CAL_03 retry that terminated `nr-uesoftmodem` with exit code 139 / SIGSEGV during initial synchronization;
- diagnosis classified the candidate as Geometry-B/OAI radio instability;
- scientific progress remained 0/18;
- no scientific application outcome was observed;
- the failed candidate must never be silently reused or counted as confirmatory evidence.

## Prospective replacement rule

Replacement Geometry-B must be selected using **engineering feasibility only**. Application completion, delivery, CDD, prefix loss, or any other Paper-A scientific outcome must not be generated or inspected during candidate selection.

### Candidate enumeration

Before launching any new candidate, Codex must inspect the installed OAI/RFsim configuration and identify technically supported deterministic LEO geometry candidates that can be configured consistently on both gNB and UE.

Exclude:

1. the original Paper-A 600-km geometry;
2. the abandoned 400-km candidate;
3. any candidate requiring `tc/netem`, arbitrary packet shaping, or a different measurement architecture.

Freeze the eligible candidate list **before testing any candidate**.

If candidates can be parameterized by altitude, sort them deterministically by:

1. smallest absolute altitude difference from the original 600 km;
2. lower altitude before higher altitude when distances tie.

Do not reorder candidates after observing engineering behavior.

### Candidate qualification

Test candidates sequentially in the frozen order. Stop at the **first** candidate that passes qualification.

Each candidate must complete **three consecutive engineering-only lifecycle validations** under identical candidate configuration. These are not scientific runs and are not calibration observations.

Each lifecycle validation must demonstrate:

- gNB starts and remains healthy;
- UE starts and remains healthy;
- RFsim connects normally;
- dynamic NTN geometry is active and matches on gNB and UE;
- PBCH/SIB19 processing proceeds normally;
- RRC attachment succeeds;
- PDU session succeeds;
- UE tunnel exists;
- application path is reachable by a non-scientific connectivity probe;
- the expected radio boundary/T310 event can be observed;
- no OAI crash, SIGSEGV, assertion, unexplained process exit, or unrecovered synchronization failure occurs.

Do **not** launch the Paper-A application sender during candidate qualification.

If any one of the three qualification attempts fails, preserve the attempt, mark that candidate unsuitable, and move to the next frozen candidate. Do not retry a failed candidate until it happens to pass.

### Crash observability

Because the 400-km candidate exposed a UE SIGSEGV with core dumps disabled, engineering candidate qualification must enable host crash observability before testing:

- enable core dumps where permitted (`ulimit -c unlimited` or the host-equivalent mechanism);
- preserve `coredumpctl`/journal evidence when available;
- preserve exact gNB and UE command lines, config hashes, OAI commit, and RFsim parameters for every attempt.

This observability change is diagnostic only and does not alter the scientific radio treatment.

## Freeze after qualification

Once the first candidate passes all three consecutive engineering lifecycle validations:

1. record Geometry-B ID and complete material difference from Geometry A;
2. freeze exact gNB and UE geometry/configuration hashes;
3. freeze OAI/framework commits and launch procedure;
4. restart calibration from scratch as fresh `CAL_01`, `CAL_02`, and `CAL_03` under this qualified geometry;
5. require three valid homogeneous calibration repetitions and spread <= 0.10 s;
6. only after calibration QC passes, populate/freeze the confirmatory local config and emit the 18-slot plan.

The abandoned 400-km calibration values must not be mixed with the replacement geometry.

## Codex execution rule

`CODEX DOES THE THINKING; THE HOST DOES THE WAITING.`

Candidate lifecycle validations, calibration, scientific runs, QC, packaging, and upload must be owned by durable host processes. Codex may diagnose, implement, launch, verify one heartbeat, print dashboard/status commands, and exit. It must not poll or babysit long-running work.
