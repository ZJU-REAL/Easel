#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Easel 一键安装
# 用法: git clone <repo> && cd Easel && bash setup.sh
#
# 环境隔离：所有 OpenClaw 配置存在 ~/.openclaw-easel/
# 不影响用户本机已有的 OpenClaw 配置
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROFILE="easel"
OC="openclaw --profile $PROFILE"

# macOS ships Bash 3.2; keep the installer portable to that baseline.
if [ -z "${BASH_VERSION:-}" ]; then
    echo "请使用 Bash 运行 setup.sh（bash setup.sh）" >&2
    exit 1
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
DIM='\033[2m'
NC='\033[0m'

info()  { echo -e "${CYAN}[easel]${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
ask()   { if [ -t 0 ]; then printf "${CYAN}  ?${NC} %s " "$1"; read -r REPLY; printf '%s' "$REPLY"; else printf ''; fi; }
step()  { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${MAGENTA}  [$1]${NC} ${CYAN}$2${NC}"; echo -e "${DIM}  $3${NC}"; }

clear 2>/dev/null || true
echo -e "\n${CYAN}╭────────────────────────────────────────────────────╮${NC}"
echo -e "${CYAN}│${NC}  ${MAGENTA}Easel${NC} · 社媒内容工作台安装向导                 ${CYAN}│${NC}"
echo -e "${CYAN}│${NC}  ${DIM}OpenClaw-powered · Linux / macOS${NC}                 ${CYAN}│${NC}"
echo -e "${CYAN}╰────────────────────────────────────────────────────╯${NC}"
echo -e "\n${DIM}  Easel 会使用独立 profile ~/.openclaw-${PROFILE}/，不会覆盖已有 OpenClaw。${NC}\n"

# ---- 1. Node.js >= 22.19 ----
step "1/8" "检查系统环境" "Python · Node.js · Git · FFmpeg"
info "检查 Node.js..."
NODE_OK=false
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    NODE_MINOR=$(echo "$NODE_VER" | cut -d. -f2)
    if [ "$NODE_MAJOR" -gt 22 ] || { [ "$NODE_MAJOR" -eq 22 ] && [ "$NODE_MINOR" -ge 19 ]; }; then
        NODE_OK=true
    fi
fi

if $NODE_OK; then
    ok "Node.js $NODE_VER"
else
    info "安装 Node.js 22..."
    if [ "$(uname -s)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install node@22
            export PATH="$(brew --prefix node@22)/bin:$PATH"
        else
            echo "macOS 未找到 Homebrew。请先安装 Node.js 22.19+（Homebrew: brew install node@22），再重新运行 setup.sh。" >&2
            exit 1
        fi
    else
        NODE_TARGET="v22.23.1"
        curl -fL --max-time 120 "https://nodejs.org/dist/${NODE_TARGET}/node-${NODE_TARGET}-linux-x64.tar.xz" -o /tmp/node22.tar.xz
        cd /tmp && tar xf node22.tar.xz
        cp -rf node-${NODE_TARGET}-linux-x64/bin/* /usr/local/bin/
        cp -rf node-${NODE_TARGET}-linux-x64/lib/* /usr/local/lib/
        rm -rf /tmp/node-${NODE_TARGET}-linux-x64 /tmp/node22.tar.xz
        cd "$PROJECT_ROOT"
    fi
    ok "Node.js $(node -v)"
fi
command -v python3 >/dev/null 2>&1 && ok "Python $(python3 --version 2>&1 | awk '{print $2}')" || warn "未找到 python3"
command -v git >/dev/null 2>&1 && ok "Git $(git --version | awk '{print $3}')" || warn "未找到 git"
command -v ffmpeg >/dev/null 2>&1 && ok "FFmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')" || warn "未找到 FFmpeg（媒体功能需要）"

# ---- 2. npm 源 ----
step "2/8" "准备 Node.js 工具链" "设置 npm registry"
npm config set registry https://registry.npmjs.org 2>/dev/null
ok "npm registry: npmjs.org"

# ---- 3. 检测/安装 OpenClaw（复用用户已有安装，不覆盖全局配置） ----
step "3/8" "检测 OpenClaw" "已有安装将直接复用"
info "检查 OpenClaw..."
if command -v openclaw >/dev/null 2>&1; then
    OPENCLAW_BIN="$(command -v openclaw)"
    ok "检测到 OpenClaw：$($OPENCLAW_BIN --version 2>&1 | head -1)"
else
    info "安装 OpenClaw..."
    npm install -g openclaw@latest --loglevel warn 2>&1 | tail -1
    OPENCLAW_BIN="$(command -v openclaw)"
    ok "OpenClaw 已安装：$($OPENCLAW_BIN --version 2>&1 | head -1)"
fi
OC="$OPENCLAW_BIN --profile $PROFILE"

# ---- 4. 初始化 Easel 专属 OpenClaw profile ----
step "4/8" "初始化 Easel profile" "独立配置、独立 workspace、独立 Gateway"
info "初始化 Easel profile (--profile $PROFILE)..."
if [ -f "$HOME/.openclaw-${PROFILE}/openclaw.json" ]; then
    ok "Profile 已存在"
else
    $OC setup --non-interactive --mode local --accept-risk 2>&1 | tail -2
    ok "Profile 初始化完成 → ~/.openclaw-${PROFILE}/"
fi

# ---- 5. 安装 easel CLI ----
step "5/8" "安装 Easel 运行依赖" "Web · 媒体 · 浏览器发布"
info "安装 easel CLI..."
pip install -e "$PROJECT_ROOT" --quiet 2>&1 | tail -1
ok "easel 命令可用"

# ---- 6. 构建 Web 前端（Node 已装 → easel web 直接出真 UI，无需手动构建） ----
step "6/8" "构建 Web 工作台" "React production bundle"
info "构建 Web 前端..."
if [ -d "$PROJECT_ROOT/web/frontend" ]; then
    (
        cd "$PROJECT_ROOT/web/frontend"
        if [ -f package-lock.json ]; then npm ci --silent || npm install --silent; else npm install --silent; fi
        npm run build
    ) >/dev/null 2>&1 || true
    if [ -f "$PROJECT_ROOT/web/frontend/dist/index.html" ]; then
        ok "前端已构建 → web/frontend/dist/"
    else
        warn "前端构建未完成，easel web 会回退简易页；可手动：cd web/frontend && npm ci && npm run build"
    fi
else
    warn "未找到 web/frontend，跳过前端构建"
fi

# ---- 7. 认证配置 ----
step "7/8" "配置模型服务" "复用已有模型，或现场输入 Anthropic 配置"
info "配置认证..."
if [ -f "$PROJECT_ROOT/.env" ]; then
    ok ".env 已存在"
else
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    warn "已创建 .env，请编辑并填入 API key："
    warn "  vim .env"
fi

# ---- 8. 同步 skills + workspace ----
info "同步 Easel skills..."
bash "$PROJECT_ROOT/openclaw/sync.sh" 2>&1 | grep -E '✓|→'

# ---- 9. 认证信息写入 Easel 专属 OpenClaw config ----
info "同步认证到 OpenClaw profile..."
source "$PROJECT_ROOT/.env" 2>/dev/null || true

# 若用户已有默认 OpenClaw 配置，复用其模型名称；密钥不会从别的 profile 复制。
if [ -z "${CLAUDE_MODEL:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -t 0 ]; then
    EXISTING_MODEL="$($OPENCLAW_BIN config get agents.defaults.model.primary 2>/dev/null || true)"
    if [ -n "$EXISTING_MODEL" ] && [ "$EXISTING_MODEL" != "null" ]; then
        echo "  检测到已有 OpenClaw 默认模型：$EXISTING_MODEL"
        USE_EXISTING="$(ask '复用这个模型到 Easel？[Y/n]')"
        case "${USE_EXISTING:-Y}" in
            n|N) ;;
            *) printf '\nCLAUDE_MODEL=%s\n' "$EXISTING_MODEL" >> "$PROJECT_ROOT/.env"; CLAUDE_MODEL="$EXISTING_MODEL"; ok "已复用模型配置" ;;
        esac
    fi
fi

# 首次安装时提供最小模型向导；非交互环境保留 .env.example 的默认行为。
if [ -t 0 ] && [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${EASEL_LLM_API_KEY:-}" ] \
   && [ -z "${OPENAI_MAAS_API_KEY:-}" ] && [ -z "${GEMINI_MAAS_API_KEY:-}" ]; then
    echo ""
    echo "  Easel 需要一个可用的模型服务才能对话。"
    MODEL_KEY="$(ask 'Anthropic API Key（直接回车可稍后配置）：')"
    if [ -n "$MODEL_KEY" ]; then
        printf '\nANTHROPIC_API_KEY=%s\n' "$MODEL_KEY" >> "$PROJECT_ROOT/.env"
        ANTHROPIC_API_KEY="$MODEL_KEY"
        MODEL_NAME="$(ask '模型名 [anthropic/claude-sonnet-4-6]：')"
        MODEL_NAME="${MODEL_NAME:-anthropic/claude-sonnet-4-6}"
        printf 'CLAUDE_MODEL=%s\n' "$MODEL_NAME" >> "$PROJECT_ROOT/.env"
        CLAUDE_MODEL="$MODEL_NAME"
        ok "模型配置已写入 Easel .env"
    else
        warn "暂未配置模型；可编辑 .env 后重新运行 bash setup.sh"
    fi
fi

DEFAULT_PRIMARY_MODEL="anthropic/claude-sonnet-4-6"
if [ -n "${OPENAI_MAAS_API_KEY:-}" ]; then
    OPENAI_PROVIDER="rednote-openai"
    OPENAI_MODEL="${OPENAI_MAAS_MODEL:-gpt-5.5}"
    OPENAI_PORT="${OPENAI_MAAS_ADAPTER_PORT:-18791}"
    OPENAI_ENDPOINT="${OPENAI_MAAS_ENDPOINT:?OPENAI_MAAS_ENDPOINT is required}"
    # A new custom provider must be written atomically or OpenClaw rejects the incomplete intermediate state.
    OPENAI_PROVIDER_CONFIG=$(python3 - "$PROJECT_ROOT" "$OPENAI_PORT" "$OPENAI_MODEL" \
        "$OPENAI_ENDPOINT" "$OPENAI_MAAS_API_KEY" "${OPENAI_MAAS_API_KEY_HEADER:-Authorization}" <<'PY'
import json
import sys

root, port, model, endpoint, api_key, api_key_header = sys.argv[1:]
print(json.dumps({
    "baseUrl": f"http://127.0.0.1:{port}/v1",
    "api": "openai-completions",
    "apiKey": "local-adapter",
    "timeoutSeconds": 600,
    "request": {"allowPrivateNetwork": True},
    "models": [{
        "id": model,
        "name": "OpenAI-compatible model",
        "reasoning": True,
        "input": ["text"],
    }],
    "localService": {
        "command": "/usr/bin/python3",
        "args": [f"{root}/scripts/openai_maas_adapter.py", "--port", port],
        "cwd": root,
        "healthUrl": f"http://127.0.0.1:{port}/health",
        "idleStopMs": 0,
        "env": {
            "OPENAI_MAAS_API_KEY": api_key,
            "OPENAI_MAAS_ENDPOINT": endpoint,
            "OPENAI_MAAS_MODEL": model,
            "OPENAI_MAAS_API_KEY_HEADER": api_key_header,
        },
    },
}))
PY
)
    $OC config set models.providers."$OPENAI_PROVIDER" "$OPENAI_PROVIDER_CONFIG" \
        --strict-json 2>&1 | tail -1
    DEFAULT_PRIMARY_MODEL="$OPENAI_PROVIDER/$OPENAI_MODEL"
    ok "OpenAI-compatible 服务已通过本地适配器同步"
elif [ -n "${GEMINI_MAAS_API_KEY:-}" ]; then
    GEMINI_PROVIDER="rednote-gemini"
    GEMINI_MODEL="${GEMINI_MAAS_MODEL:-gemini-3.1-pro-preview}"
    $OC config set models.providers."$GEMINI_PROVIDER".baseUrl \
        "http://127.0.0.1:${GEMINI_ADAPTER_PORT:-18790}/v1" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".api "openai-completions" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".apiKey "local-adapter" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".models \
        "[{\"id\":\"$GEMINI_MODEL\",\"name\":\"Gemini-compatible model\",\"reasoning\":true,\"input\":[\"text\",\"image\"],\"contextWindow\":1048576,\"maxTokens\":65535}]" \
        --strict-json 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".timeoutSeconds 600 --strict-json 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".request.allowPrivateNetwork true --strict-json 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.command "/usr/bin/python3" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.args \
        "[\"$PROJECT_ROOT/scripts/gemini_maas_adapter.py\",\"--port\",\"${GEMINI_ADAPTER_PORT:-18790}\"]" \
        --strict-json 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.cwd "$PROJECT_ROOT" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.healthUrl \
        "http://127.0.0.1:${GEMINI_ADAPTER_PORT:-18790}/health" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.idleStopMs 0 --strict-json 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_MAAS_API_KEY \
        "$GEMINI_MAAS_API_KEY" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_MAAS_ENDPOINT \
        "${GEMINI_MAAS_ENDPOINT:?GEMINI_MAAS_ENDPOINT is required}" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_MAAS_MODEL \
        "$GEMINI_MODEL" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_THINKING_LEVEL \
        "${GEMINI_THINKING_LEVEL:-HIGH}" 2>&1 | tail -1
    $OC config set models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_INCLUDE_THOUGHTS \
        "${GEMINI_INCLUDE_THOUGHTS:-true}" 2>&1 | tail -1
    DEFAULT_PRIMARY_MODEL="$GEMINI_PROVIDER/$GEMINI_MODEL"
    ok "Gemini-compatible 服务已通过本地适配器同步"
elif [ -n "${EASEL_LLM_API_KEY:-}" ]; then
    $OC config set models.providers.anthropic.apiKey "$EASEL_LLM_API_KEY" 2>&1 | tail -1
    $OC config set models.providers.anthropic.baseUrl "$EASEL_LLM_BASE_URL" 2>&1 | tail -1
    $OC config set models.providers.anthropic.headers."${EASEL_LLM_API_KEY_HEADER:-api-key}" \
        "$EASEL_LLM_API_KEY" 2>&1 | tail -1
    $OC config set models.providers.anthropic.headers.anthropic-version \
        "${EASEL_LLM_ANTHROPIC_VERSION:-2023-06-01}" 2>&1 | tail -1
    # Switching away from CodeWiz must remove its provider-specific headers.
    $OC config unset models.providers.anthropic.headers.Cookie >/dev/null 2>&1 || true
    $OC config unset models.providers.anthropic.headers.X-Adapter-Source >/dev/null 2>&1 || true
    $OC config unset models.providers.anthropic.headers.X-Adapter-Scenario >/dev/null 2>&1 || true
    $OC config unset models.providers.anthropic.headers.X-Adapter-Source-Version >/dev/null 2>&1 || true
    ok "自定义 Anthropic 兼容 MaaS 认证已同步"
elif [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "$ANTHROPIC_API_KEY" != "sk-ant-REPLACE_ME" ]; then
    $OC config set models.providers.anthropic.apiKey "$ANTHROPIC_API_KEY" 2>&1 | tail -1
    ok "API key 已同步"
else
    warn "认证未配置 — 编辑 .env 后重新运行 bash setup.sh"
fi

# ---- 10. OpenClaw agent 模型 + 超时 ----
# CLAUDE_MODEL 保留旧变量名以兼容现有环境，值必须是 OpenClaw 的 provider/model。
# 不要填内部 proxy 映射名（如 claude-4.6-opus-google），否则 OpenClaw 不认识。
$OC config set agents.defaults.model.primary "${CLAUDE_MODEL:-$DEFAULT_PRIMARY_MODEL}" 2>&1 | tail -1
# 整个 agent run 的总时长上限。制作层任务（OpenClaw 自执行短剧/长稿/多镜）很久 → 给足。
$OC config set agents.defaults.timeoutSeconds 7200 2>&1 | tail -1
# Easel 使用 profiles/<当前画像>/memory.md；关闭 OpenClaw 全局记忆索引，避免旧索引跨画像召回。
# memorySearch was removed from the current OpenClaw schema; clear legacy values.
$OC config unset agents.defaults.memorySearch >/dev/null 2>&1 || true
# 单次 LLM 请求的「空闲超时」（等模型开始/继续产出 token 的最长时间）。内部网关对大上下文/带思考的
# 请求首 token 可能较慢，不设会用默认较短值 → 报「model did not produce a response before the model
# idle timeout」而中断整个 run。与 agents.defaults.timeoutSeconds 是两回事，provider 超时不能延长整个 run。
$OC config set models.providers.anthropic.timeoutSeconds 600 2>&1 | tail -1
$OC config set gateway.mode local 2>&1 | tail -1
$OC config set gateway.bind loopback 2>&1 | tail -1

# Refuse to start with a config rejected by the installed OpenClaw version.
# This catches schema changes early instead of producing opaque Gateway errors.
if ! $OC config validate; then
    echo "OpenClaw 配置校验失败：请检查上方报错，并确认使用受支持的 OpenClaw 版本。" >&2
    exit 1
fi
ok "OpenClaw 配置校验通过"

# ---- 11. 启动 gateway ----
step "8/8" "启动并验证" "配置校验 · Chromium · Gateway health"
info "启动 Easel gateway..."
bash "$PROJECT_ROOT/scripts/gateway.sh" start

# Playwright is a runtime dependency for browser login/publishing.
if python3 -c 'import playwright' >/dev/null 2>&1; then
    python3 -m playwright install chromium >/dev/null 2>&1 || warn "Chromium 安装失败，请手动运行：python3 -m playwright install chromium"
else
    warn "未找到 Playwright CLI；请检查 Python 依赖安装结果"
fi

echo -e "\n${GREEN}╭────────────────────────────────────────────────────╮${NC}"
echo -e "${GREEN}│${NC}  ${GREEN}✓ Easel 安装完成${NC}                              ${GREEN}│${NC}"
echo -e "${GREEN}╰────────────────────────────────────────────────────╯${NC}"
echo -e "\n  ${CYAN}开始使用：${NC}"
echo "    easel web                    # 启动 Web 工作台"
echo "    easel chat                   # 终端对话"
echo "    easel doctor                 # 检查环境"
echo "    easel ping                   # Gateway 连通性"
echo -e "\n  ${DIM}Easel profile：~/.openclaw-${PROFILE}/${NC}"
echo -e "  ${DIM}项目目录：$PROJECT_ROOT${NC}\n"
