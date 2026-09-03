# Project Codex Execution Rules

These rules apply to every Codex prompt and unattended experiment in this 5G/NTN research project.

## Absolute rule: Codex must not babysit experiments

Codex is for reasoning, implementation, diagnosis, validation, and handoff. It is **not** a process monitor.

Whenever work contains a long-running operation such as radio calibration, OAI experiment execution, multi-run campaigns, packaging, uploads, model fitting, or any other process that can continue without active reasoning, Codex MUST:

1. create or reuse a durable host-side supervisor/watchdog;
2. launch the long-running work outside the Codex process using an appropriate durable mechanism such as `systemd`, `tmux`, or `nohup`;
3. write machine-readable status/heartbeat files and durable logs;
4. verify only that the supervisor started successfully, has a live PID/process, and has produced its initial status/heartbeat;
5. print concise commands the operator can use later to inspect status;
6. **exit the Codex session immediately after that handoff.**

Codex MUST NOT remain attached merely to observe progress.

### Prohibited babysitting behavior

After durable handoff, Codex must not:

- run `watch` itself;
- run `tail -f` / `journalctl -f` itself for ongoing monitoring;
- use polling loops to wait for campaign progress;
- repeatedly `cat`, `jq`, `stat`, or inspect status files without a new diagnostic reason;
- issue long `sleep` commands while waiting for experiments;
- keep a foreground shell command open just to wait for completion;
- consume inference tokens narrating or checking routine progress;
- stay in the Codex TUI waiting for the supervisor to finish;
- wait for calibration, scientific runs, packaging, rclone upload, checksum verification, or other unattended phases that the supervisor can perform itself.

A `watch`, `tail`, or status command may be **printed for the human operator to run in a normal shell**, but Codex must not execute it as a waiting strategy.

## When Codex may be invoked again

Start a new Codex invocation only when useful reasoning is required, for example:

- the supervisor reports `FAILED`, `BLOCKED`, or an explicit attention-required state;
- a watchdog detects a genuine stall;
- a run fails an objective QC/treatment-integrity gate and the framework cannot apply the frozen rule automatically;
- the campaign completes and analysis/packaging requires reasoning not already automated;
- the operator explicitly asks Codex to inspect a checkpoint or change code.

Routine progress is not a reason to keep Codex alive.

## Supervisor requirements

The durable supervisor/watchdog should own, as applicable:

- calibration progression;
- run sequencing;
- treatment-integrity/preflight gates;
- retries/replacements allowed by the frozen protocol;
- OAI process health checks;
- stall detection and safe failure;
- QC invocation;
- packaging;
- upload;
- checksum verification;
- final status generation.

Its progress indicator must reflect real state transitions and observable work, not an artificial timer.

## Required Codex handoff block

Before exiting after a long-running launch, Codex should print a concise handoff containing:

- supervisor PID/service/tmux session;
- campaign/status file path;
- heartbeat/watchdog path if applicable;
- log path;
- one normal-shell status command;
- one normal-shell log-inspection command;
- the condition under which Codex should be invoked again.

Then Codex MUST EXIT.

## Scientific integrity

This no-babysitting rule never permits the supervisor to alter a frozen scientific design based on observed outcomes. Objective predeclared QC, treatment-integrity rules, replacement limits, and stop conditions remain authoritative.
