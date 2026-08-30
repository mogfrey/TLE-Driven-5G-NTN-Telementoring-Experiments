#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=${PAPER_B_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}
CFG=${PAPER_B_CONFIG:-$ROOT/config/paper_b_usability.local.yaml}
SESSION=paper_b_ausw
RESULTS=$ROOT/results/paper_b_ausw_validation
PY=${PYTHON:-$ROOT/.venv/bin/python}
[[ -x "$PY" ]] || PY=python3
cmd=${1:-status}
case "$cmd" in
  start)
    [[ -f "$CFG" ]] || { echo "Missing $CFG" >&2; exit 2; }
    tmux has-session -t "$SESSION" 2>/dev/null && { echo "$SESSION already running"; exit 1; }
    mkdir -p "$RESULTS"
    tmux new-session -d -s "$SESSION" "cd '$ROOT' && exec '$PY' scripts/paper_b_campaign_supervisor.py --config '$CFG' all >> '$RESULTS/supervisor.log' 2>&1"
    echo "Started $SESSION"
    ;;
  preflight|calibrate|dry-run|campaign|summary|package|upload)
    cd "$ROOT"; exec "$PY" scripts/paper_b_campaign_supervisor.py --config "$CFG" "$cmd" ;;
  status)
    echo "tmux: $(tmux has-session -t "$SESSION" 2>/dev/null && echo running || echo not-running)"
    [[ -f "$RESULTS/campaign_state.json" ]] && "$PY" -m json.tool "$RESULTS/campaign_state.json" || true
    ;;
  watch)
    watch -n 5 "$0 status" ;;
  logs)
    tail -n 120 -f "$RESULTS/supervisor.log" ;;
  attach)
    exec tmux attach -t "$SESSION" ;;
  stop)
    tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION" || true
    sudo -n pkill -INT -x nr-uesoftmodem 2>/dev/null || true
    sudo -n pkill -INT -x nr-softmodem 2>/dev/null || true
    ;;
  *) echo "usage: $0 {start|status|watch|logs|attach|stop|preflight|calibrate|dry-run|campaign|summary|package|upload}" >&2; exit 2 ;;
esac
