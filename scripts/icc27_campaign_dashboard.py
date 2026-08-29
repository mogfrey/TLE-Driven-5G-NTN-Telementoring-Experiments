#!/usr/bin/env python3
"""Read-only live dashboard for the ICC 2027 UCT boundary sweep.

The dashboard never mutates experiment state. It derives progress from campaign
artifacts, file activity, the supervisor log, and local process presence. It uses
only the Python standard library so it can run beside an active campaign without
installing packages.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REQUIRED_ARTIFACTS = [
    "run_manifest.json",
    "sender.json",
    "receiver.json",
    "continuity_summary.json",
    "radio_boundary.json",
    "timing_alignment.json",
    "gnb.log",
    "ue.log",
    "qc.json",
]

PROCESS_MARKERS = {
    "supervisor": "icc27_boundary_sweep_supervisor.py",
    "gNB": "nr-softmodem",
    "UE": "nr-uesoftmodem",
    "benchmark": "continuity_benchmark.py",
}


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


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def seconds_since(value: Any) -> float | None:
    dt = parse_utc(value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def tail_lines(path: Path, limit: int = 30) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return [line.rstrip("\n") for line in lines[-limit:]]
    except OSError:
        return []


def proc_snapshot() -> dict[str, list[int]]:
    found = {key: [] for key in PROCESS_MARKERS}
    proc = Path("/proc")
    if not proc.exists():
        return found
    try:
        children = list(proc.iterdir())
    except OSError:
        return found
    for child in children:
        if not child.name.isdigit():
            continue
        try:
            cmdline = (child / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8", errors="ignore"
            )
        except OSError:
            continue
        if not cmdline:
            continue
        for label, marker in PROCESS_MARKERS.items():
            if marker in cmdline and "icc27_campaign_dashboard.py" not in cmdline:
                found[label].append(int(child.name))
    return found


def dir_activity(path: Path) -> tuple[float | None, str | None]:
    if not path or not path.exists():
        return None, None
    newest_mtime = None
    newest_name = None
    try:
        for item in path.iterdir():
            if not item.is_file():
                continue
            try:
                mtime = item.stat().st_mtime
            except OSError:
                continue
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime
                newest_name = item.name
    except OSError:
        return None, None
    if newest_mtime is None:
        return None, newest_name
    return max(0.0, time.time() - newest_mtime), newest_name


def candidate_attempt_dirs(root: Path, run_id: str | None) -> list[Path]:
    if not run_id:
        return []
    candidates: list[Path] = []
    search_roots = [root / "runs", root / "calibration", root / "calibrations"]
    for base in search_roots:
        if not base.exists():
            continue
        try:
            for child in base.iterdir():
                if child.is_dir() and (child.name == run_id or child.name.startswith(run_id + "_")):
                    candidates.append(child)
        except OSError:
            pass
    if not candidates:
        try:
            for child in root.glob(f"**/{run_id}*"):
                if child.is_dir():
                    candidates.append(child)
        except OSError:
            pass
    unique = {str(path.resolve()): path for path in candidates}
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def attempt_details(root: Path, run_id: str | None) -> dict[str, Any]:
    candidates = candidate_attempt_dirs(root, run_id)
    attempt = candidates[0] if candidates else None
    artifacts: list[dict[str, Any]] = []
    if attempt:
        for name in REQUIRED_ARTIFACTS:
            path = attempt / name
            exists = path.exists()
            size = None
            age = None
            if exists:
                try:
                    stat = path.stat()
                    size = stat.st_size
                    age = max(0.0, time.time() - stat.st_mtime)
                except OSError:
                    pass
            artifacts.append({"name": name, "exists": exists, "size": size, "age_s": age})
    activity_age, newest_file = dir_activity(attempt) if attempt else (None, None)
    manifest = load_json(attempt / "run_manifest.json") if attempt else None
    qc = load_json(attempt / "qc.json") if attempt else None
    return {
        "path": str(attempt) if attempt else None,
        "artifacts": artifacts,
        "artifact_count": sum(1 for item in artifacts if item["exists"]),
        "artifact_total": len(REQUIRED_ARTIFACTS),
        "activity_age_s": activity_age,
        "newest_file": newest_file,
        "manifest": manifest or {},
        "qc": qc or {},
    }


def run_matrix(root: Path, plan: dict[str, Any], current_run: str | None) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    runs_root = root / "runs"
    for row in plan.get("runs", []) if isinstance(plan, dict) else []:
        rid = row.get("plan_run_id")
        attempts: list[dict[str, Any]] = []
        if rid and runs_root.exists():
            try:
                dirs = [p for p in runs_root.iterdir() if p.is_dir() and (p.name == rid or p.name.startswith(rid + "_"))]
            except OSError:
                dirs = []
            for path in sorted(dirs, key=lambda p: p.name):
                q = load_json(path / "qc.json") or {}
                attempts.append(
                    {
                        "name": path.name,
                        "valid": q.get("valid"),
                        "failure": q.get("failure_classification"),
                    }
                )
        if any(item.get("valid") is True for item in attempts):
            state = "VALID"
        elif any(item.get("valid") is False for item in attempts):
            state = "INVALID"
        elif rid == current_run:
            state = "RUNNING"
        elif attempts:
            state = "IN_PROGRESS"
        else:
            state = "PENDING"
        matrix.append(
            {
                "sequence": row.get("sequence"),
                "run_id": rid,
                "offset_s": row.get("planned_end_offset_s"),
                "seed_group": row.get("seed_group"),
                "seed": row.get("paired_seed"),
                "state": state,
                "attempts": attempts,
            }
        )
    return matrix


def calibration_records(root: Path, status: dict[str, Any]) -> list[dict[str, Any]]:
    times = status.get("calibration_boundary_times_s") or status.get("boundary_times_s") or []
    if not isinstance(times, list):
        times = []
    records = []
    for index in range(3):
        rid = f"CAL_{index + 1:02d}"
        value = times[index] if index < len(times) else None
        details = attempt_details(root, rid)
        records.append(
            {
                "run_id": rid,
                "boundary_s": value,
                "state": "VALID" if value is not None else ("RUNNING" if status.get("current_plan_run_id") == rid else "PENDING"),
                "artifact_count": details["artifact_count"],
                "artifact_total": details["artifact_total"],
                "activity_age_s": details["activity_age_s"],
                "newest_file": details["newest_file"],
            }
        )
    return records


def snapshot(root: Path) -> dict[str, Any]:
    status = load_json(root / "campaign_status.json") or {}
    qc = load_json(root / "campaign_qc.json") or {}
    analysis = load_json(root / "analysis" / "icc27_boundary_sweep_summary.json") or {}
    plan = load_json(root / "campaign_plan.json") or {}

    completed = int(status.get("completed_valid_slots") or 0)
    total = int(status.get("total_valid_slots") or plan.get("valid_runs_required") or 21)
    calibration_times = status.get("calibration_boundary_times_s") or status.get("boundary_times_s") or []
    calibration_done = len(calibration_times) if isinstance(calibration_times, list) else 0
    current = status.get("current_plan_run_id")
    current_details = attempt_details(root, current)
    processes = proc_snapshot()
    log_path = root / "supervisor.log"
    log_tail = tail_lines(log_path, 35)
    log_age = None
    if log_path.exists():
        try:
            log_age = max(0.0, time.time() - log_path.stat().st_mtime)
        except OSError:
            pass

    snap = {
        "state": status.get("state") or status.get("phase") or "UNKNOWN",
        "phase": status.get("phase") or status.get("state") or "UNKNOWN",
        "campaign_name": status.get("campaign_name") or "UCT-ICC27-BOUNDARY-SWEEP",
        "start_utc": status.get("start_utc"),
        "last_update_utc": status.get("last_update_utc"),
        "heartbeat_age_s": seconds_since(status.get("last_update_utc")),
        "campaign_elapsed_s": seconds_since(status.get("start_utc")),
        "current_plan_run_id": current,
        "completed_valid_slots": completed,
        "total_valid_slots": total,
        "progress_percent": pct(completed, total),
        "invalid_attempt_count": int(status.get("invalid_attempt_count") or 0),
        "retry_count": int(status.get("retry_count") or 0),
        "calibration_done": calibration_done,
        "calibration_planned": 3,
        "calibration_times_s": calibration_times if isinstance(calibration_times, list) else [],
        "calibrated_boundary_s": status.get("calibrated_boundary_s"),
        "calibration_spread_s": status.get("calibration_spread_s"),
        "last_error": status.get("last_error"),
        "qc_available": bool(qc),
        "qc_passed": qc.get("passed") if qc else None,
        "analysis_available": bool(analysis),
        "analysis": analysis,
        "plan_available": bool(plan),
        "matrix": run_matrix(root, plan, current),
        "calibrations": calibration_records(root, status),
        "current_attempt": current_details,
        "processes": processes,
        "supervisor_log_tail": log_tail,
        "supervisor_log_age_s": log_age,
    }
    return snap


def escape(value: Any, default: str = "—") -> str:
    return html.escape(text(value, default))


def state_class(state: str) -> str:
    value = (state or "").upper()
    if value in {"VALID", "COMPLETE", "PASS", "ANALYZING", "PACKAGING"}:
        return "good"
    if value in {"INVALID", "FAIL", "CALIBRATION_FAILED", "STOPPED_ON_FAILURE"}:
        return "bad"
    if value in {"RUNNING", "IN_PROGRESS", "CALIBRATING", "QC", "PLAN_FROZEN"}:
        return "warn"
    return "muted"


def render_processes(processes: dict[str, list[int]]) -> str:
    cards = []
    for label in ("supervisor", "gNB", "UE", "benchmark"):
        pids = processes.get(label, [])
        status = "UP" if pids else "DOWN"
        klass = "good" if pids else "muted"
        pid_text = ", ".join(str(pid) for pid in pids) if pids else "—"
        cards.append(
            f'<div class="mini"><span>{html.escape(label)}</span><b class="{klass}">{status}</b><small>PID {pid_text}</small></div>'
        )
    return "".join(cards)


def render_artifacts(details: dict[str, Any]) -> str:
    artifacts = details.get("artifacts", [])
    if not artifacts:
        return '<div class="muted">Current attempt directory not yet discovered.</div>'
    rows = []
    for item in artifacts:
        exists = item.get("exists")
        symbol = "✓" if exists else "·"
        klass = "good" if exists else "muted"
        size = item.get("size")
        size_text = "—" if size is None else (f"{size / 1024:.1f} KiB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MiB")
        age = human_duration(item.get("age_s")) if exists else "—"
        rows.append(
            f'<tr><td class="{klass}">{symbol}</td><td>{html.escape(item["name"])}</td><td>{size_text}</td><td>{age} ago</td></tr>'
        )
    return '<table><thead><tr><th></th><th>Artifact</th><th>Size</th><th>Last write</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"


def render_calibrations(records: list[dict[str, Any]]) -> str:
    rows = []
    for record in records:
        state = record["state"]
        rows.append(
            "<tr>"
            f'<td>{escape(record["run_id"])}</td>'
            f'<td class="{state_class(state)}">{escape(state)}</td>'
            f'<td>{escape(record.get("boundary_s"))}</td>'
            f'<td>{record.get("artifact_count", 0)}/{record.get("artifact_total", 0)}</td>'
            f'<td>{escape(record.get("newest_file"))}</td>'
            f'<td>{human_duration(record.get("activity_age_s")) if record.get("activity_age_s") is not None else "—"}</td>'
            "</tr>"
        )
    return '<table><thead><tr><th>Calibration</th><th>State</th><th>Boundary (s)</th><th>Artifacts</th><th>Newest file</th><th>Activity age</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"


def render_matrix(matrix: list[dict[str, Any]]) -> str:
    if not matrix:
        return '<div class="muted">Scientific plan has not been frozen yet.</div>'
    cells = []
    for row in matrix:
        state = row.get("state", "PENDING")
        klass = state_class(state)
        offset = row.get("offset_s")
        offset_text = f"{float(offset):+g}s" if offset is not None else "—"
        attempts = len(row.get("attempts", []))
        cells.append(
            f'<div class="slot {klass}-border">'
            f'<b>#{row.get("sequence")} {offset_text}</b>'
            f'<span>S{escape(row.get("seed_group"))} · {escape(state)}</span>'
            f'<small>{escape(row.get("run_id"))}</small>'
            f'<small>attempts: {attempts}</small>'
            "</div>"
        )
    return '<div class="slotgrid">' + "".join(cells) + "</div>"


def render_html(s: dict[str, Any]) -> str:
    state = escape(s["state"])
    progress = float(s["progress_percent"])
    error = escape(s.get("last_error"), "None")
    current = escape(s.get("current_plan_run_id"))
    boundary = escape(s.get("calibrated_boundary_s"))
    spread = escape(s.get("calibration_spread_s"))
    updated = escape(s.get("last_update_utc"))
    heartbeat_age = human_duration(s.get("heartbeat_age_s"))
    elapsed = human_duration(s.get("campaign_elapsed_s"))
    log_age = human_duration(s.get("supervisor_log_age_s"))
    qc = "PASS" if s.get("qc_passed") is True else ("FAIL" if s.get("qc_passed") is False else "Pending")
    qc_class = "good" if qc == "PASS" else ("bad" if qc == "FAIL" else "muted")
    current_attempt = s.get("current_attempt", {})
    current_path = escape(current_attempt.get("path"))
    newest = escape(current_attempt.get("newest_file"))
    current_activity = human_duration(current_attempt.get("activity_age_s"))
    log_payload = html.escape("\n".join(s.get("supervisor_log_tail", [])) or "No supervisor log lines available yet.")

    analysis_block = ""
    if s.get("analysis_available"):
        payload = html.escape(json.dumps(s.get("analysis", {}), indent=2, sort_keys=True))
        analysis_block = f"<section><h2>Final analysis</h2><pre>{payload}</pre></section>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="3">
<title>ICC27 Boundary Sweep</title>
<style>
:root{{--bg:#0b1020;--panel:#151c32;--border:#2a3558;--text:#eef2ff;--muted:#aab4d0;--good:#84f1a7;--warn:#ffd27a;--bad:#ff8d8d;--accent:#7aa2ff}}
*{{box-sizing:border-box}} body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:var(--bg);color:var(--text)}}
main{{max-width:1280px;margin:0 auto;padding:22px}} h1{{margin:0 0 4px}} h2{{margin:0 0 12px;font-size:1.05rem}}
.muted{{color:var(--muted)}} .good{{color:var(--good)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:10px;margin:16px 0}}
.card,section{{background:var(--panel);border:1px solid var(--border);border-radius:11px;padding:14px}}
.value{{font-size:1.35rem;font-weight:750;margin-top:4px}} .bar{{height:14px;background:#27304c;border-radius:999px;overflow:hidden}}
.fill{{height:100%;width:{progress:.2f}%;background:var(--accent)}} .two{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}
.processes{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}} .mini{{background:#10172a;border:1px solid var(--border);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:3px}}
.mini small,.slot small{{color:var(--muted)}} table{{width:100%;border-collapse:collapse;font-size:.86rem}} th,td{{text-align:left;padding:6px 7px;border-bottom:1px solid #28324f}} th{{color:var(--muted);font-weight:600}}
.slotgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px}} .slot{{background:#10172a;border:1px solid var(--border);border-radius:8px;padding:9px;display:flex;flex-direction:column;gap:3px;font-size:.82rem}}
.good-border{{border-color:#3f8060}} .warn-border{{border-color:#8a7139}} .bad-border{{border-color:#914c4c}}
pre{{white-space:pre-wrap;word-break:break-word;font-size:.78rem;line-height:1.35;max-height:420px;overflow:auto;background:#0d1324;padding:10px;border-radius:7px}}
.meta{{display:flex;gap:18px;flex-wrap:wrap;font-size:.84rem;margin-top:5px}}
@media(max-width:800px){{.two{{grid-template-columns:1fr}}.processes{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body><main>
<h1>UCT ICC 2027 Boundary Sweep</h1>
<div class="muted">Auto-refresh: 3 s · status timestamp {updated}</div>
<div class="meta"><span>Heartbeat age: <b>{heartbeat_age}</b></span><span>Campaign elapsed: <b>{elapsed}</b></span><span>Supervisor log activity: <b>{log_age} ago</b></span></div>
<div class="grid">
<div class="card"><div class="muted">State</div><div class="value {state_class(s['state'])}">{state}</div></div>
<div class="card"><div class="muted">Scientific slots</div><div class="value">{s['completed_valid_slots']} / {s['total_valid_slots']}</div></div>
<div class="card"><div class="muted">Calibration</div><div class="value">{s['calibration_done']} / 3</div></div>
<div class="card"><div class="muted">QC</div><div class="value {qc_class}">{qc}</div></div>
<div class="card"><div class="muted">Current run</div><div class="value">{current}</div></div>
<div class="card"><div class="muted">Invalid / retries</div><div class="value">{s['invalid_attempt_count']} / {s['retry_count']}</div></div>
<div class="card"><div class="muted">Boundary (s)</div><div class="value">{boundary}</div></div>
<div class="card"><div class="muted">Calibration spread (s)</div><div class="value">{spread}</div></div>
</div>
<section><h2>Scientific progress</h2><div class="bar"><div class="fill"></div></div><p>{progress:.1f}% complete</p></section>
<div class="two">
<section><h2>Process health</h2><div class="processes">{render_processes(s.get('processes', {}))}</div></section>
<section><h2>Current attempt activity</h2><div><b>{current}</b></div><div class="muted">{current_path}</div><p>Artifacts: <b>{current_attempt.get('artifact_count', 0)}/{current_attempt.get('artifact_total', 0)}</b> · newest: <b>{newest}</b> · last file activity: <b>{current_activity} ago</b></p></section>
</div>
<section style="margin-top:12px"><h2>Calibration detail</h2>{render_calibrations(s.get('calibrations', []))}</section>
<div class="two">
<section><h2>Current attempt artifacts</h2>{render_artifacts(current_attempt)}</section>
<section><h2>Last error</h2><pre>{error}</pre></section>
</div>
<section style="margin-top:12px"><h2>21-slot scientific matrix</h2>{render_matrix(s.get('matrix', []))}</section>
<section style="margin-top:12px"><h2>Live supervisor log · last 35 lines</h2><pre>{log_payload}</pre></section>
{analysis_block}
</main></body></html>"""


def terminal(root: Path, interval: float) -> None:
    try:
        while True:
            s = snapshot(root)
            os.system("clear")
            print("UCT ICC 2027 BOUNDARY SWEEP — GRANULAR STATUS")
            print("=" * 72)
            print(f"State              : {text(s['state'])}")
            print(f"Phase              : {text(s['phase'])}")
            print(f"Current run        : {text(s['current_plan_run_id'])}")
            print(f"Campaign elapsed   : {human_duration(s['campaign_elapsed_s'])}")
            print(f"Heartbeat age      : {human_duration(s['heartbeat_age_s'])}")
            print(f"Supervisor log age : {human_duration(s['supervisor_log_age_s'])}")
            print(f"Scientific progress: {s['completed_valid_slots']}/{s['total_valid_slots']} ({s['progress_percent']:.1f}%)")
            print(f"Calibration        : {s['calibration_done']}/3 {s['calibration_times_s']}")
            print(f"Boundary (s)       : {text(s['calibrated_boundary_s'])}")
            print(f"Cal spread (s)     : {text(s['calibration_spread_s'])}")
            print(f"Invalid / retries  : {s['invalid_attempt_count']} / {s['retry_count']}")
            print(f"Processes          : {s['processes']}")
            current = s.get("current_attempt", {})
            print(f"Attempt artifacts  : {current.get('artifact_count', 0)}/{current.get('artifact_total', 0)}")
            print(f"Newest artifact    : {text(current.get('newest_file'))}")
            print(f"File activity age  : {human_duration(current.get('activity_age_s'))}")
            print(f"Last error         : {text(s['last_error'], 'None')}")
            print("\nSupervisor log tail:")
            for line in s.get("supervisor_log_tail", [])[-12:]:
                print(line)
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
    parser = argparse.ArgumentParser(description="Granular live dashboard for the ICC27 boundary sweep")
    parser.add_argument("--results-root", default="results/uct_icc27_boundary_sweep")
    parser.add_argument("--terminal", action="store_true", help="use an updating terminal dashboard")
    parser.add_argument("--interval", type=float, default=3.0)
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
