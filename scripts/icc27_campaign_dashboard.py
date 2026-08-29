#!/usr/bin/env python3
"""Read-only live dashboard for the ICC 2027 UCT boundary sweep.

This dashboard never mutates experiment state. Calibration progress is inferred
from the calibration artifacts themselves (qc.json + radio_boundary.json), not
from optional aggregate fields in campaign_status.json.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CAL_ARTIFACTS = ["gnb.log", "ue.log", "radio_boundary.json", "qc.json"]
SCI_ARTIFACTS = [
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
ELAPSED_RE = re.compile(r"elapsed=([0-9]+(?:\.[0-9]+)?)")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def esc(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return html.escape(default)
    return html.escape(str(value))


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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


def human(seconds: float | None) -> str:
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


def file_age(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def tail(path: Path, lines: int = 40) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for line in handle.readlines()[-lines:]]
    except OSError:
        return []


def latest_elapsed(path: Path) -> float | None:
    for line in reversed(tail(path, 200)):
        match = ELAPSED_RE.search(line)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def proc_snapshot() -> dict[str, list[int]]:
    result = {key: [] for key in PROCESS_MARKERS}
    proc = Path("/proc")
    if not proc.exists():
        return result
    for child in proc.iterdir():
        if not child.name.isdigit():
            continue
        try:
            cmd = (child / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
        except OSError:
            continue
        if not cmd or "icc27_campaign_dashboard.py" in cmd:
            continue
        for label, marker in PROCESS_MARKERS.items():
            if marker in cmd:
                result[label].append(int(child.name))
    return result


def calibration_dir(root: Path, run_id: str) -> Path:
    for base in (root / "calibration", root / "calibrations"):
        candidate = base / run_id
        if candidate.exists():
            return candidate
    return root / "calibration" / run_id


def attempt_dir(root: Path, run_id: str | None) -> Path | None:
    if not run_id:
        return None
    if run_id.startswith("CAL_"):
        path = calibration_dir(root, run_id)
        return path if path.exists() else None
    runs = root / "runs"
    if not runs.exists():
        return None
    candidates = [p for p in runs.iterdir() if p.is_dir() and (p.name == run_id or p.name.startswith(run_id + "_"))]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def artifact_rows(path: Path | None, names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for name in names:
        target = path / name if path else None
        exists = bool(target and target.exists())
        rows.append(
            {
                "name": name,
                "exists": exists,
                "size": target.stat().st_size if exists else None,
                "age": file_age(target) if exists else None,
            }
        )
    return rows


def calibration_record(root: Path, run_id: str, current: str | None) -> dict[str, Any]:
    path = calibration_dir(root, run_id)
    qc = load_json(path / "qc.json") or {}
    rb = load_json(path / "radio_boundary.json") or {}
    boundary = rb.get("boundary_elapsed_s")
    detected = rb.get("detected")
    valid = qc.get("valid") is True and boundary is not None and detected is not False
    invalid = qc.get("valid") is False
    if valid:
        state = "VALID"
    elif invalid:
        state = "INVALID"
    elif current == run_id:
        state = "RUNNING"
    elif path.exists() and any(path.iterdir()):
        state = "IN_PROGRESS"
    else:
        state = "PENDING"
    artifacts = artifact_rows(path if path.exists() else None, CAL_ARTIFACTS)
    elapsed = max(
        [value for value in (latest_elapsed(path / "gnb.log"), latest_elapsed(path / "ue.log")) if value is not None],
        default=None,
    )
    newest = None
    newest_age = None
    if path.exists():
        files = [p for p in path.iterdir() if p.is_file()]
        if files:
            newest_path = max(files, key=lambda p: p.stat().st_mtime)
            newest = newest_path.name
            newest_age = file_age(newest_path)
    return {
        "run_id": run_id,
        "state": state,
        "boundary_s": float(boundary) if boundary is not None else None,
        "valid": valid,
        "path": str(path),
        "artifacts": artifacts,
        "artifact_count": sum(1 for row in artifacts if row["exists"]),
        "elapsed_s": elapsed,
        "newest": newest,
        "activity_age": newest_age,
        "rule": rb.get("rule"),
    }


def scientific_matrix(root: Path, plan: dict[str, Any], current: str | None) -> list[dict[str, Any]]:
    matrix = []
    runs_root = root / "runs"
    for row in plan.get("runs", []) if isinstance(plan, dict) else []:
        rid = row.get("plan_run_id")
        attempts = []
        if rid and runs_root.exists():
            for path in sorted([p for p in runs_root.iterdir() if p.is_dir() and (p.name == rid or p.name.startswith(rid + "_"))]):
                q = load_json(path / "qc.json") or {}
                attempts.append({"name": path.name, "valid": q.get("valid")})
        if any(a.get("valid") is True for a in attempts):
            state = "VALID"
        elif any(a.get("valid") is False for a in attempts):
            state = "INVALID"
        elif rid == current:
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
                "state": state,
                "attempts": len(attempts),
            }
        )
    return matrix


def snapshot(root: Path) -> dict[str, Any]:
    status = load_json(root / "campaign_status.json") or {}
    plan = load_json(root / "campaign_plan.json") or {}
    current = status.get("current_plan_run_id")
    calibrations = [calibration_record(root, f"CAL_{i:02d}", current) for i in range(1, 4)]
    valid_boundaries = [r["boundary_s"] for r in calibrations if r["valid"] and r["boundary_s"] is not None]
    live_spread = max(valid_boundaries) - min(valid_boundaries) if len(valid_boundaries) >= 2 else None
    live_boundary = statistics.median(valid_boundaries) if len(valid_boundaries) == 3 else None

    current_path = attempt_dir(root, current)
    current_names = CAL_ARTIFACTS if current and current.startswith("CAL_") else SCI_ARTIFACTS
    current_artifacts = artifact_rows(current_path, current_names)
    current_elapsed = None
    if current_path:
        current_elapsed = max(
            [value for value in (latest_elapsed(current_path / "gnb.log"), latest_elapsed(current_path / "ue.log")) if value is not None],
            default=None,
        )
    reference_boundary = valid_boundaries[0] if valid_boundaries else status.get("calibrated_boundary_s")
    radio_progress = None
    if current and current.startswith("CAL_") and current_elapsed is not None and reference_boundary:
        radio_progress = max(0.0, min(100.0, 100.0 * current_elapsed / float(reference_boundary)))

    completed = int(status.get("completed_valid_slots") or 0)
    total = int(status.get("total_valid_slots") or plan.get("valid_runs_required") or 21)
    return {
        "status": status,
        "state": status.get("state") or status.get("phase") or "UNKNOWN",
        "current": current,
        "heartbeat_age": seconds_since(status.get("last_update_utc")),
        "campaign_elapsed": seconds_since(status.get("start_utc")),
        "calibrations": calibrations,
        "calibration_done": len(valid_boundaries),
        "live_spread": live_spread,
        "live_boundary": live_boundary,
        "official_boundary": status.get("calibrated_boundary_s"),
        "official_spread": status.get("calibration_spread_s"),
        "current_path": str(current_path) if current_path else None,
        "current_artifacts": current_artifacts,
        "current_elapsed": current_elapsed,
        "reference_boundary": reference_boundary,
        "radio_progress": radio_progress,
        "completed": completed,
        "total": total,
        "scientific_progress": 0.0 if total <= 0 else 100.0 * completed / total,
        "processes": proc_snapshot(),
        "matrix": scientific_matrix(root, plan, current),
        "last_error": status.get("last_error"),
    }


def cls(state: str) -> str:
    state = (state or "").upper()
    if state in {"VALID", "COMPLETE", "PASS"}:
        return "good"
    if state in {"INVALID", "FAIL", "CALIBRATION_FAILED", "STOPPED_ON_FAILURE"}:
        return "bad"
    if state in {"RUNNING", "IN_PROGRESS", "CALIBRATING", "PLAN_FROZEN", "QC", "ANALYZING", "PACKAGING"}:
        return "warn"
    return "muted"


def render_artifacts(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            f"<tr><td class={'good' if row['exists'] else 'muted'}>{'✓' if row['exists'] else '·'}</td>"
            f"<td>{esc(row['name'])}</td><td>{row['size'] if row['size'] is not None else '—'}</td>"
            f"<td>{human(row['age']) + ' ago' if row['age'] is not None else '—'}</td></tr>"
        )
    return "<table><tr><th></th><th>Artifact</th><th>Bytes</th><th>Last write</th></tr>" + "".join(body) + "</table>"


def render_matrix(matrix: list[dict[str, Any]]) -> str:
    if not matrix:
        return '<div class="muted">Scientific plan has not been frozen yet.</div>'
    cells = []
    for row in matrix:
        offset = row.get("offset_s")
        offset_text = f"{float(offset):+g}s" if offset is not None else "—"
        state = row.get("state", "PENDING")
        cells.append(
            f'<div class="slot {cls(state)}-border"><b>#{row.get("sequence")} {offset_text}</b>'
            f'<span class="{cls(state)}">S{esc(row.get("seed_group"))} · {esc(state)}</span>'
            f'<small>{esc(row.get("run_id"))}</small><small>attempts: {row.get("attempts", 0)}</small></div>'
        )
    return '<div class="slotgrid">' + "".join(cells) + "</div>"


def render_html(s: dict[str, Any]) -> str:
    cal_rows = []
    for r in s["calibrations"]:
        cal_rows.append(
            f"<tr><td>{esc(r['run_id'])}</td><td class={cls(r['state'])}>{esc(r['state'])}</td>"
            f"<td>{esc(r['boundary_s'])}</td><td>{r['artifact_count']}/4</td>"
            f"<td>{esc(r['elapsed_s'])}</td><td>{esc(r['newest'])}</td><td>{human(r['activity_age'])}</td></tr>"
        )
    proc_cards = []
    for label in ("supervisor", "gNB", "UE", "benchmark"):
        pids = s["processes"].get(label, [])
        proc_cards.append(
            f'<div class="mini"><span>{label}</span><b class={"good" if pids else "muted"}>{"UP" if pids else "DOWN"}</b><small>PID {", ".join(map(str,pids)) if pids else "—"}</small></div>'
        )
    rp = s.get("radio_progress")
    radio_block = ""
    if s.get("current") and str(s["current"]).startswith("CAL_"):
        radio_block = f"""
<section><h2>Current radio calibration progress</h2>
<div class=bar><div class=fill style="width:{rp if rp is not None else 0:.1f}%"></div></div>
<p>Current radio elapsed: <b>{esc(s.get('current_elapsed'))} s</b> · reference boundary: <b>{esc(s.get('reference_boundary'))} s</b> · approximate progress: <b>{rp:.1f}%</b></p>
</section>""" if rp is not None else "<section><h2>Current radio calibration progress</h2><p>Waiting for elapsed-time log samples.</p></section>"
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><meta http-equiv=refresh content=3>
<title>ICC27 Boundary Sweep</title><style>
:root{{--bg:#0b1020;--panel:#151c32;--border:#2a3558;--text:#eef2ff;--muted:#aab4d0;--good:#84f1a7;--warn:#ffd27a;--bad:#ff8d8d;--accent:#7aa2ff}}*{{box-sizing:border-box}}body{{font-family:system-ui;margin:0;background:var(--bg);color:var(--text)}}main{{max-width:1250px;margin:auto;padding:20px}}h1{{margin:0}}h2{{font-size:1rem}}.muted{{color:var(--muted)}}.good{{color:var(--good)}}.warn{{color:var(--warn)}}.bad{{color:var(--bad)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:9px;margin:14px 0}}.card,section{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:13px;margin-top:10px}}.value{{font-size:1.3rem;font-weight:750}}.processes{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.mini{{background:#10172a;border:1px solid var(--border);border-radius:8px;padding:9px;display:flex;flex-direction:column}}table{{width:100%;border-collapse:collapse;font-size:.84rem}}th,td{{padding:6px;border-bottom:1px solid #28324f;text-align:left}}th{{color:var(--muted)}}.bar{{height:14px;background:#27304c;border-radius:999px;overflow:hidden}}.fill{{height:100%;background:var(--accent)}}.slotgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:7px}}.slot{{background:#10172a;border:1px solid var(--border);border-radius:8px;padding:8px;display:flex;flex-direction:column;font-size:.8rem}}.slot small{{color:var(--muted)}}.good-border{{border-color:#3f8060}}.warn-border{{border-color:#8a7139}}.bad-border{{border-color:#914c4c}}
</style></head><body><main>
<h1>UCT ICC 2027 Boundary Sweep</h1><div class=muted>Auto-refresh: 3 s · heartbeat age {human(s['heartbeat_age'])} · campaign elapsed {human(s['campaign_elapsed'])}</div>
<div class=grid><div class=card><div class=muted>State</div><div class='value {cls(s['state'])}'>{esc(s['state'])}</div></div><div class=card><div class=muted>Current run</div><div class=value>{esc(s['current'])}</div></div><div class=card><div class=muted>Calibration</div><div class=value>{s['calibration_done']} / 3</div></div><div class=card><div class=muted>Live spread</div><div class=value>{esc(s['live_spread'])}</div></div><div class=card><div class=muted>Scientific slots</div><div class=value>{s['completed']} / {s['total']}</div></div><div class=card><div class=muted>Last error</div><div class=value>{esc(s['last_error'], 'None')}</div></div></div>
<section><h2>Process health</h2><div class=processes>{''.join(proc_cards)}</div></section>
{radio_block}
<section><h2>Calibration detail — inferred from artifacts</h2><table><tr><th>Calibration</th><th>State</th><th>Boundary (s)</th><th>Artifacts</th><th>Latest elapsed</th><th>Newest file</th><th>Activity age</th></tr>{''.join(cal_rows)}</table></section>
<section><h2>Current attempt artifacts</h2><div class=muted>{esc(s['current_path'])}</div>{render_artifacts(s['current_artifacts'])}</section>
<section><h2>Scientific progress</h2><div class=bar><div class=fill style="width:{s['scientific_progress']:.1f}%"></div></div><p>{s['scientific_progress']:.1f}% complete</p></section>
<section><h2>21-slot scientific matrix</h2>{render_matrix(s['matrix'])}</section>
</main></body></html>"""


def serve(root: Path, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            snap = snapshot(root)
            if self.path == "/api/status":
                payload = json.dumps(snap, indent=2).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
            elif self.path in {"/", "/index.html"}:
                payload = render_html(snap).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"dashboard: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def terminal(root: Path, interval: float) -> None:
    try:
        while True:
            s = snapshot(root)
            os.system("clear")
            print("UCT ICC 2027 BOUNDARY SWEEP")
            print("=" * 68)
            print(f"State: {s['state']}  Current: {s['current']}")
            print(f"Calibration: {s['calibration_done']}/3  boundaries={[r['boundary_s'] for r in s['calibrations'] if r['valid']]}")
            print(f"Live spread: {s['live_spread']}  official boundary: {s['official_boundary']}")
            print(f"Current radio elapsed: {s['current_elapsed']}  approx progress: {s['radio_progress']}")
            print(f"Scientific: {s['completed']}/{s['total']} ({s['scientific_progress']:.1f}%)")
            print(f"Processes: {s['processes']}")
            print(f"Last error: {s['last_error']}")
            time.sleep(interval)
    except KeyboardInterrupt:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Live dashboard for the ICC27 boundary sweep")
    parser.add_argument("--results-root", default="results/uct_icc27_boundary_sweep")
    parser.add_argument("--terminal", action="store_true")
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = Path(args.results_root).expanduser().resolve()
    if args.terminal:
        terminal(root, max(0.5, args.interval))
    else:
        serve(root, args.host, args.port)


if __name__ == "__main__":
    main()
