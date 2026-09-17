#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi
PORT="${EASEL_OPENCODE_PORT:-18789}"
LOGFILE="${TMPDIR:-/tmp}/easel-opencode.log"
PIDFILE="${TMPDIR:-/tmp}/easel-opencode.pid"

live() {
  local auth=()
  if [ -n "${OPENCODE_SERVER_PASSWORD:-}" ]; then
    auth=(-u "${OPENCODE_SERVER_USERNAME:-opencode}:${OPENCODE_SERVER_PASSWORD}")
  fi
  curl -sf --max-time 2 "${auth[@]}" "http://127.0.0.1:${PORT}/global/health" >/dev/null 2>&1
}
pid() { [ -f "$PIDFILE" ] && cat "$PIDFILE" || true; }

case "${1:-status}" in
  start)
    if live; then echo "[easel] OpenCode server already running"; exit 0; fi
    command -v opencode >/dev/null || { echo "[easel] OpenCode CLI not found" >&2; exit 1; }
    nohup opencode serve --hostname 127.0.0.1 --port "$PORT" >"$LOGFILE" 2>&1 &
    echo $! >"$PIDFILE"
    for _ in $(seq 1 20); do live && { echo "[easel] OpenCode server started (PID $(pid))"; exit 0; }; sleep 0.25; done
    echo "[easel] OpenCode server failed to start; check $LOGFILE" >&2; exit 1 ;;
  stop)
    p="$(pid)"; if [ -n "$p" ] && kill "$p" 2>/dev/null; then echo "[easel] OpenCode server stopped"; else echo "[easel] OpenCode server was not running"; fi
    rm -f "$PIDFILE" ;;
  restart) "$0" stop; "$0" start ;;
  status) if live; then echo "[easel] OpenCode server running (PID $(pid))"; else echo "[easel] OpenCode server not running"; exit 1; fi ;;
  logs) tail -f "$LOGFILE" ;;
  *) echo "Usage: $0 {start|stop|restart|status|logs}" >&2; exit 1 ;;
esac
