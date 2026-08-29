#!/usr/bin/env python3
"""Lightweight live dashboard for the ICC 2027 UCT boundary sweep.

Reads only the campaign result artifacts and never mutates experiment state.
Uses the Python standard library so it can run on the RAN host without extra
packages. By default it serves a browser dashboard on localhost.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def text(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return default
    return str(value)


def pct(done: int, total: int) -> float:
    return 0.0 if total <= 0 else 100.0 * done / total


def snapshot(root: Path) -> dict[str, Any]:
    status = load_json(root / "campaign_status.json") or {}
    qc = load_json(root / "campaign_qc.json") or {}
    analysis = load_json(root / "analysis" / "icc27_boundary_sweep_summary.json") or {}

    completed = int(status.get("completed_valid_slots") or 0)
    total = int(status.get("total_valid_slots") or 21)
    calibration_times = status.get("calibration_boundary_times_s") or status.get("boundary_times_s") or []
    calibration_done = len(calibration_times) if isinstance(calibration_times, list) else 0

    snap = {
        "state": status.get("state") or status.get("phase") or "UNKNOWN",
        "phase": status.get("phase") or status.get("state") or "UNKNOWN",
        "campaign_name": status.get("campaign_name") or "UCT-ICC27-BOUNDARY-SWEEP",
        "start_utc": status.get("start_utc"),
        "last_update_utc": status.get("last_update_utc"),
        "current_plan_run_id": status.get("current_plan_run_id"),
        "completed_valid_slots": completed,
        "total_valid_slots": total,
        "progress_percent": pct(completed, total),
        "invalid_attempt_count": int(status.get("invalid_attempt_count") or 0),
        "retry_count": int(status.get("retry_count") or 0),
        "calibration_done": calibration_done,
        "calibration_planned": 3,
        "calibrated_boundary_s": status.get("calibrated_boundary_s"),
        "calibration_spread_s": status.get("calibration_spread_s"),
        "last_error": status.get("last_error"),
        "qc_available": bool(qc),
        "qc_passed": qc.get("passed") if qc else None,
        "analysis_available": bool(analysis),
        "analysis": analysis,
    }
    return snap


def render_html(s: dict[str, Any]) -> str:
    state = html.escape(text(s["state"]))
    progress = float(s["progress_percent"])
    error = html.escape(text(s.get("last_error"), "None"))
    current = html.escape(text(s.get("current_plan_run_id")))
    boundary = html.escape(text(s.get("calibrated_boundary_s")))
    spread = html.escape(text(s.get("calibration_spread_s")))
    updated = html.escape(text(s.get("last_update_utc")))
    qc = "PASS" if s.get("qc_passed") is True else ("FAIL" if s.get("qc_passed") is False else "Pending")

    analysis_block = ""
    if s.get("analysis_available"):
        payload = html.escape(json.dumps(s.get("analysis", {}), indent=2, sort_keys=True))
        analysis_block = f"<section><h2>Final analysis</h2><pre>{payload}</pre></section>"

    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<meta http-equiv=\"refresh\" content=\"5\">
<title>ICC27 Boundary Sweep</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#0b1020;color:#eef2ff}}
main{{max-width:1000px;margin:0 auto;padding:24px}}
h1{{margin-bottom:4px}} .muted{{color:#aab4d0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:20px 0}}
.card,section{{background:#151c32;border:1px solid #2a3558;border-radius:12px;padding:16px}}
.value{{font-size:1.55rem;font-weight:700;margin-top:6px}}
.bar{{height:18px;background:#27304c;border-radius:999px;overflow:hidden}}
.fill{{height:100%;width:{progress:.2f}%;background:#7aa2ff}}
.good{{color:#84f1a7}} .warn{{color:#ffd27a}} .bad{{color:#ff8d8d}}
pre{{white-space:pre-wrap;word-break:break-word;font-size:.82rem}}
</style>
</head>
<body><main>
<h1>UCT ICC 2027 Boundary Sweep</h1>
<div class=\"muted\">Auto-refresh: 5 s · last update {updated}</div>
<div class=\"grid\">
<div class=\"card\"><div class=\"muted\">State</div><div class=\"value\">{state}</div></div>
<div class=\"card\"><div class=\"muted\">Scientific slots</div><div class=\"value\">{s['completed_valid_slots']} / {s['total_valid_slots']}</div></div>
<div class=\"card\"><div class=\"muted\">Calibration</div><div class=\"value\">{s['calibration_done']} / 3</div></div>
<div class=\"card\"><div class=\"muted\">QC</div><div class=\"value\">{qc}</div></div>
<div class=\"card\"><div class=\"muted\">Current run</div><div class=\"value\">{current}</div></div>
<div class=\"card\"><div class=\"muted\">Invalid / retries</div><div class=\"value\">{s['invalid_attempt_count']} / {s['retry_count']}</div></div>
<div class=\"card\"><div class=\"muted\">Boundary (s)</div><div class=\"value\">{boundary}</div></div>
<div class=\"card\"><div class=\"muted\">Calibration spread (s)</div><div class=\"value\">{spread}</div></div>
</div>
<section><h2>Progress</h2><div class=\"bar\"><div class=\"fill\"></div></div><p>{progress:.1f}% complete</p></section>
<section><h2>Last error</h2><pre>{error}</pre></section>
{analysis_block}
</main></body></html>"""


def terminal(root: Path, interval: float) -> None:
    try:
        while True:
            s = snapshot(root)
            os.system("clear")
            print("UCT ICC 2027 BOUNDARY SWEEP")
            print("=" * 58)
            print(f"State              : {text(s['state'])}")
            print(f"Phase              : {text(s['phase'])}")
            print(f"Current run        : {text(s['current_plan_run_id'])}")
            print(f"Scientific progress: {s['completed_valid_slots']}/{s['total_valid_slots']} ({s['progress_percent']:.1f}%)")
            print(f"Calibration        : {s['calibration_done']}/3")
            print(f"Boundary (s)       : {text(s['calibrated_boundary_s'])}")
            print(f"Cal spread (s)     : {text(s['calibration_spread_s'])}")
            print(f"Invalid attempts   : {s['invalid_attempt_count']}")
            print(f"Retries            : {s['retry_count']}")
            print(f"Last update        : {text(s['last_update_utc'])}")
            print(f"Last error         : {text(s['last_error'], 'None')}")
            time.sleep(interval)
    except KeyboardInterrupt:
        return


def serve(root: Path, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/status":
                payload = json.dumps(snapshot(root), indent=2).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path not in {"/", "/index.html"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = render_html(snapshot(root)).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"dashboard: http://{host}:{port}")
    print(f"results root: {root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Live dashboard for the ICC27 boundary sweep")
    parser.add_argument("--results-root", default="results/uct_icc27_boundary_sweep")
    parser.add_argument("--terminal", action="store_true", help="use an updating terminal dashboard")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address; localhost by default")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    root = Path(args.results_root).expanduser().resolve()
    if args.terminal:
        terminal(root, max(args.interval, 0.5))
    else:
        serve(root, args.host, args.port)


if __name__ == "__main__":
    main()
