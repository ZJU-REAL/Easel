#!/usr/bin/env bash
set -euo pipefail

# Easel — OpenClaw gateway 管理脚本（隔离模式）
# 所有操作通过 --profile easel 隔离，不影响用户自己的 OpenClaw
# 用法: ./scripts/gateway.sh {start|stop|restart|status|logs}

PROFILE="easel"
OC="openclaw --profile $PROFILE"
LOGFILE="/tmp/easel-gateway.log"
ADAPTER_LOGFILE="/tmp/easel-openai-maas-adapter.log"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gateway_live() {
    curl -sf --max-time 2 http://localhost:18789/healthz > /dev/null 2>&1
}

gateway_pid() {
    ss -ltnp 2>/dev/null \
        | sed -n 's/.*127\.0\.0\.1:18789.*pid=\([0-9][0-9]*\).*/\1/p' \
        | head -n 1
}

adapter_port() {
    sed -n 's/^OPENAI_MAAS_ADAPTER_PORT=//p' "$PROJECT_ROOT/.env" 2>/dev/null | tail -n 1
}

adapter_pid() {
    local port="${1:-18791}"
    ss -ltnp 2>/dev/null \
        | sed -n "s/.*127\\.0\\.0\\.1:${port}.*pid=\\([0-9][0-9]*\\).*/\\1/p" \
        | head -n 1
}

start_adapter() {
    grep -q '^OPENAI_MAAS_API_KEY=' "$PROJECT_ROOT/.env" 2>/dev/null || return 0
    local port pid
    port="$(adapter_port)"
    port="${port:-18791}"
    pid="$(adapter_pid "$port")"
    if [ -n "$pid" ]; then
        return 0
    fi
    setsid -f /usr/bin/python3 "$PROJECT_ROOT/scripts/openai_maas_adapter.py" \
        --env-file "$PROJECT_ROOT/.env" --port "$port" >"$ADAPTER_LOGFILE" 2>&1
    for _ in $(seq 1 20); do
        curl -sf --max-time 1 "http://127.0.0.1:${port}/health" >/dev/null && return 0
        sleep 0.25
    done
    echo "[easel] OpenAI MaaS adapter may not be ready — check: $ADAPTER_LOGFILE"
}

stop_adapter() {
    local port pid cmdline
    port="$(adapter_port)"
    port="${port:-18791}"
    pid="$(adapter_pid "$port")"
    [ -n "$pid" ] || return 0
    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmdline" == *"openai_maas_adapter.py"* ]]; then
        kill "$pid" 2>/dev/null || true
    fi
}

# ---- 项目根（供委派的 shared 脚本按 env 定位 outputs/，见 manifest.py/log.py）----
# workspace 拍平副本按 __file__ 会把根算成 ~/.openclaw，故用 env 钉死正确项目根
export EASEL_ROOT="$PROJECT_ROOT"

# ---- 外网代理 ----
# 公司开发机需要走正向代理才能访问外网（weibo/bilibili/douyin 等）
# no_proxy 排除内网，避免影响 LLM proxy 和内部服务
export http_proxy="${http_proxy:-${EASEL_PROXY:-}}"
export https_proxy="${https_proxy:-${EASEL_PROXY:-}}"
export no_proxy="${no_proxy:-localhost,127.0.0.1,*.xiaohongshu.com,*.devops.xiaohongshu.com,10.*}"

case "${1:-status}" in
    start)
        start_adapter
        if gateway_live; then
            PID="$(gateway_pid)"
            echo "[easel] Gateway already running${PID:+ (PID $PID)}"
            exit 0
        fi
        echo "[easel] Starting Easel gateway (profile: $PROFILE)..."
        setsid -f openclaw --profile "$PROFILE" gateway run --force > "$LOGFILE" 2>&1
        sleep 4
        if gateway_live; then
            PID="$(gateway_pid)"
            echo "[easel] Gateway started${PID:+ (PID $PID)}"
        else
            echo "[easel] Gateway may not be ready yet — check: tail -f $LOGFILE"
        fi
        ;;
    stop)
        PID="$(gateway_pid)"
        if [ -n "$PID" ] && kill "$PID" 2>/dev/null; then
            echo "[easel] Gateway stopped"
        else
            echo "[easel] Gateway was not running"
        fi
        stop_adapter
        ;;
    restart)
        "$0" stop
        sleep 2
        "$0" start
        ;;
    status)
        if gateway_live; then
            PID="$(gateway_pid)"
            HEALTH=$(curl -sf http://localhost:18789/healthz 2>&1 || echo '{"ok":false}')
            echo "[easel] Gateway running${PID:+ (PID $PID)}, profile: $PROFILE"
            echo "  health: $HEALTH"
        else
            echo "[easel] Gateway not running"
        fi
        ;;
    logs)
        tail -f "$LOGFILE"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
