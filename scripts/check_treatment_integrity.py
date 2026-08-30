#!/usr/bin/env python3
"""Evaluate pre-launch serving-context integrity for a Paper-A scientific attempt.

The script is intentionally outcome-blind: it consumes only setup/control evidence
and the scheduled application-launch epoch. It must be run before sender launch.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

ESTABLISH_PATTERNS = [
    re.compile(r"RRC.*(setup|establish|connected)", re.I),
    re.compile(r"PDU session.*(establish|accept|active)", re.I),
]
LOSS_PATTERNS = [
    re.compile(r"RRC Release", re.I),
    re.compile(r"Timer T310 expired", re.I),
    re.compile(r"PDU session.*(release|delete|deactivate)", re.I),
    re.compile(r"GTP.*(delete|removed|release)", re.I),
]


def run_ok(cmd: list[str], timeout: float = 5.0) -> tuple[bool, str]:
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return cp.returncode == 0, (cp.stdout + cp.stderr).strip()
    except Exception as exc:
        return False, str(exc)


def scan_log(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    establish_hits = [m.group(0) for p in ESTABLISH_PATTERNS for m in p.finditer(text)]
    loss_hits = [m.group(0) for p in LOSS_PATTERNS for m in p.finditer(text)]
    return {
        "path": str(path),
        "exists": path.exists(),
        "establish_hit_count": len(establish_hits),
        "loss_hit_count": len(loss_hits),
        "last_establish_hit": establish_hits[-1] if establish_hits else None,
        "last_loss_hit": loss_hits[-1] if loss_hits else None,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gnb-log", required=True)
    p.add_argument("--ue-log", required=True)
    p.add_argument("--ue-tunnel", required=True)
    p.add_argument("--remote-ip", required=True)
    p.add_argument("--gnb-process-regex", default="nr-softmodem")
    p.add_argument("--ue-process-regex", default="nr-uesoftmodem")
    p.add_argument("--anchor-valid-file")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    gnb = scan_log(Path(args.gnb_log))
    ue = scan_log(Path(args.ue_log))
    gnb_proc, gnb_proc_detail = run_ok(["pgrep", "-af", args.gnb_process_regex])
    ue_proc, ue_proc_detail = run_ok(["pgrep", "-af", args.ue_process_regex])
    tunnel_ok, tunnel_detail = run_ok(["ip", "link", "show", args.ue_tunnel])
    ping_ok, ping_detail = run_ok(["ping", "-c", "1", "-W", "2", args.remote_ip])

    anchor_ok = True
    anchor_detail = None
    if args.anchor_valid_file:
        anchor_path = Path(args.anchor_valid_file)
        anchor_ok = anchor_path.exists()
        anchor_detail = str(anchor_path)

    # This live gate is deliberately conservative: any loss signature already
    # present in the active attempt logs before launch is treated as failure.
    checks = {
        "gnb_log_present": gnb["exists"],
        "ue_log_present": ue["exists"],
        "serving_context_evidence_present": (gnb["establish_hit_count"] + ue["establish_hit_count"]) > 0,
        "no_prelaunch_loss_signature": (gnb["loss_hit_count"] + ue["loss_hit_count"]) == 0,
        "gnb_process_alive": gnb_proc,
        "ue_process_alive": ue_proc,
        "ue_tunnel_present": tunnel_ok,
        "application_path_ping": ping_ok,
        "anchor_valid": anchor_ok,
    }
    passed = all(checks.values())
    result = {
        "schema_version": 1,
        "evaluated_unix_s": time.time(),
        "phase": "immediately_pre_application_launch",
        "outcome_blind": True,
        "pass": passed,
        "checks": checks,
        "gnb_log": gnb,
        "ue_log": ue,
        "details": {
            "gnb_process": gnb_proc_detail,
            "ue_process": ue_proc_detail,
            "ue_tunnel": tunnel_detail,
            "ping": ping_detail,
            "anchor": anchor_detail,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": passed, "checks": checks}, indent=2))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
