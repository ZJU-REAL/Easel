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
OPENCLAW_BIN="openclaw"
oc() { "$OPENCLAW_BIN" --profile "$PROFILE" "$@"; }

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
ask()   { if [ -t 0 ]; then printf "${CYAN}  ?${NC} %s " "$1" >&2; read -r REPLY; printf '%s' "$REPLY"; else printf ''; fi; }
step()  { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${MAGENTA}  [$1]${NC} ${CYAN}$2${NC}"; echo -e "${DIM}  $3${NC}"; }

run_with_progress() {
    local label log_file pid started elapsed frame
    label="$1"
    shift
    log_file="$(mktemp "${TMPDIR:-/tmp}/easel-install.XXXXXX")"
    "$@" >"$log_file" 2>&1 &
    pid=$!
    started=$(date +%s)
    frame=0
    # 非 TTY（CI、重定向到文件）下不要转圈：1Hz 的 \r 会刷出几千行无用日志。
    if [ -t 2 ]; then
        while kill -0 "$pid" 2>/dev/null; do
            elapsed=$(( $(date +%s) - started ))
            case $((frame % 4)) in
                0) progress='[>   ]' ;;
                1) progress='[=>  ]' ;;
                2) progress='[==> ]' ;;
                *) progress='[===>]' ;;
            esac
            printf '\r  %s 进行中 %s 已运行 %ss' "$progress" "$label" "$elapsed" >&2
            frame=$((frame + 1))
            sleep 1
        done
    else
        # 这里不能自己 wait：后面的 `if wait "$pid"` 才是取退出码的地方，
        # 提前 wait 会把进程回收掉，使那句 wait 返回 127 而把成功判成失败。
        printf '  [....] %s 开始（非交互终端，不显示进度）\n' "$label" >&2
    fi
    if wait "$pid"; then
        printf '\r  [====] %s 完成                         \n' "$label" >&2
        rm -f "$log_file"
        return 0
    fi
    printf '\r  [FAIL] %s 失败                         \n' "$label" >&2
    tail -40 "$log_file" >&2 || true
    rm -f "$log_file"
    return 1
}

# ============================================================
# 安装模式、失败收集、以及对 OpenClaw 版本差异的容忍层
#
# 为什么需要这一层：本脚本对 OpenClaw 的 config schema 和子命令做了大量版本假设
# （memorySearch 的位置、provider 的默认 api、config validate 是否存在、--replace
# 是否存在……），每个假设只对某个版本区间成立。而脚本是 set -euo pipefail —— 任何
# 一个假设落空，以前都是整个安装当场中断，用户只看到一行 openclaw 的英文报错。
# 这类「小毛病搞挂整个安装」是本脚本历史上最主要的故障模式。
# ============================================================

# check：跑完所有探测与分支，但不真的改变任何状态，只向 stdout 吐 JSON 动作流。
# CI 用它在 ubuntu 与 windows 上验证安装逻辑，不需要下载近 1GB 的依赖。
SETUP_MODE="${EASEL_SETUP_MODE:-run}"
# 把所有警告升回致命。给依赖「失败即非零退出」的自动化/provisioning 脚本用。
SETUP_STRICT="${EASEL_SETUP_STRICT:-}"

_json_esc() {
    local s=$1
    s=${s//\\/\\\\}; s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}; s=${s//$'\t'/\\t}; s=${s//$'\r'/\\r}
    printf '%s' "$s"
}

# 动作流只在 check 模式下输出，而它会进 CI 日志，所以脱敏不能只看 key 名：
# 整块写 provider 时 key 是 models.providers.anthropic，密钥藏在 value 的 JSON 里
# （实测会把 apiKey 明文打进日志）。key 和 value 两侧都要判。
emit_action() {
    [ "$SETUP_MODE" = check ] || return 0
    local action="$1" key="${2:-}" value="${3:-}"
    case "$key" in
        *[Kk]ey*|*[Tt]oken*|*[Ss]ecret*|*[Pp]assword*|*headers*) value='<redacted>' ;;
    esac
    # value 侧只按「真的像凭据」的形态匹配，不能用裸 token 子串 ——
    # provider 的 models JSON 里有 maxTokens，会被连带遮掉，而那是该看见的信息
    # （contextWindow / maxTokens 没声明会让部分网关直接 400，正是要能核对的东西）。
    case "$value" in
        *'"apiKey"'*|*apiKey=*|*api_key*|*apikey=*|*Authorization*|*Bearer\ *|\
        *'"token"'*|*token=*|*[Ss]ecret*|*[Pp]assword*)
            value='<redacted>' ;;
    esac
    printf '{"action":"%s","key":"%s","value":"%s"}\n' \
        "$(_json_esc "$action")" "$(_json_esc "$key")" "$(_json_esc "$value")"
}

# ---- 失败收集 ----
# Bash 3.2（macOS 自带）没有关联数组，用三个平行索引数组。
WARN_LABELS=(); WARN_DETAILS=(); WARN_FIXES=(); WARN_SEVERITY=()

# 即时打印 + 记录。只记不printf 本身就是一种失败模式：用户盯着十几分钟的安装，
# 问题发生时就该看见，而不是只在最后的汇总里（还可能被滚屏冲掉）。
warn_collect() {   # $1 label  $2 detail  [$3 fix 命令]  [$4 severity=low]
    WARN_LABELS+=("$1"); WARN_DETAILS+=("$2")
    WARN_FIXES+=("${3:-}"); WARN_SEVERITY+=("${4:-low}")
    warn "$1：$2"
    [ -n "${3:-}" ] && echo -e "${DIM}      → ${3}${NC}" >&2
    # strict 模式下警告即致命，立刻中断并给出同样的提示。
    if [ -n "$SETUP_STRICT" ]; then
        fatal "$1：$2（EASEL_SETUP_STRICT=1 下警告视为致命）"
    fi
    return 0
}

fatal() {
    echo -e "\n${RED}  ✗ 安装中止${NC}：$*" >&2
    write_install_report "$*" 2>/dev/null || true
    # check 模式用 2 与「真实安装失败」区分：CI 据此判断是逻辑走到了致命分支，
    # 而不是环境本身装不上。
    [ "$SETUP_MODE" = check ] && exit 2
    exit 1
}

# ---- OpenClaw 能力探测（带记忆）----
# 复用本脚本已验证可行的做法：读 --help 判断某个子命令/标志在当前版本上是否存在。
# 比「先调用、失败再回退」可靠 —— 后者分不清「不支持该功能」和「这次配置真的错了」，
# 历史上 setup.ps1 正是因此把 2026.9.x 的拒绝写入误报成「老版本不支持 --batch-file」。
oc_supports() {   # $1 子命令（如 "config" / "config set"）  $2 要找的词
    local cache_var rc
    cache_var="OC_CAP_$(printf '%s_%s' "$1" "$2" | tr -c 'A-Za-z0-9' '_')"
    eval "rc=\${$cache_var:-}"
    if [ -z "$rc" ]; then
        # shellcheck disable=SC2086  # $1 可能是 "config set" 两个词，需要分词
        if oc $1 --help 2>&1 | grep -q -- "$2"; then rc=yes; else rc=no; fi
        eval "$cache_var=\$rc"
    fi
    [ "$rc" = yes ]
}

# 捕获到变量再判退出码。不要写成 `$OC config set ... 2>&1 | sed ...`：
# pipefail 下 sed 挡不住 openclaw 的非零退出，而管道里的 sed 只是在过滤噪音
# —— 这正是历史上多处「config set 失败 → 整个安装中断」的成因。
OC_LAST_OUT=""
_oc_run() {   # $1 key  $2 value  [$3 --json|--json-replace]
    local json_flag="" rc
    case "${3:-}" in
        --json)         json_flag="--strict-json" ;;
        # --replace 明确声明「有意整块替换」。2026.9.x 起，整块写入若会删掉 provider 下
        # 已存在的子键会被拒绝，而本脚本后面自己会写 timeoutSeconds —— 不声明就会首次
        # 安装能过、第二次重跑必失败（不可重入）。老版本没有该标志，由调用方先探测。
        --json-replace) json_flag="--strict-json --replace" ;;
    esac
    if [ "$SETUP_MODE" = check ]; then
        emit_action config_set "$1" "$2"
        OC_LAST_OUT=""
        return 0
    fi
    set +e
    # shellcheck disable=SC2086  # json_flag 为空时不能留下空参数
    OC_LAST_OUT="$(oc config set "$1" "$2" $json_flag 2>&1)"
    rc=$?
    set -e
    return $rc
}

# 静默尝试，只返回成败。用于探测哪套 schema 被接受。
oc_try() { _oc_run "$@" >/dev/null 2>&1; }

# 尽力而为的写入：失败记一条警告，绝不中断安装。
#
# 注意这里**必须返回 0**，哪怕写入失败。调用点形如 `oc_set '标签' some.key value`，
# 在 set -e 下语句级的非零返回会直接中断脚本 —— 返回 1 等于根本没做 fail-soft
# （只有 check 模式恰好看不出来，因为那条路径恒成功）。失败信息由 warn_collect
# 记录并最终进汇总表，调用点不需要再分流。
oc_set() {   # $1 label  $2 key  $3 value  [$4 --json|--json-replace]  [$5 severity]
    local label="$1" severity="${5:-low}"
    shift
    if _oc_run "$@"; then
            [ -n "$OC_LAST_OUT" ] && printf '%s\n' "$OC_LAST_OUT" | sed -e '/^No change$/d' -e '/^$/d'
        return 0
    fi
    warn_collect "$label" "openclaw 不接受 $1（$(printf '%s' "$OC_LAST_OUT" | head -1)）" \
        "" "$severity"
    return 0
}

# 依次尝试多套候选 key，第一个成功即止；全失败只报一条警告（按意图而非按 key 计数）。
# 用于那些「配置项位置随 OpenClaw 版本搬过家」的场景。
oc_set_first() {   # $1 label  $2 value  $3 --json|--  然后是候选 key 列表
    local label="$1" value="$2" json_flag="$3" k
    shift 3
    for k in "$@"; do
        if [ "$json_flag" = "--json" ]; then
            oc_try "$k" "$value" --json && { emit_action config_set_first_hit "$k" "$value"; return 0; }
        else
            oc_try "$k" "$value" && { emit_action config_set_first_hit "$k" "$value"; return 0; }
        fi
    done
    # 同 oc_set：必须返回 0，否则 set -e 下会中断安装。
    warn_collect "$label" "当前 OpenClaw 不接受任何已知写法（已试 $*）"
    return 0
}

# 会改变状态的外部命令统一走这里，check 模式下只记录不执行。
run_step() {   # $1 label  其余为命令
    local label="$1"
    shift
    if [ "$SETUP_MODE" = check ]; then
        emit_action run_step "$label" "$*"
        return 0
    fi
    "$@"
}

# ---- 安装报告 ----
# 把本次安装的遗留问题落盘，供 `easel doctor` 复述。这样「装完还差什么」不依赖用户
# 记住十几分钟前滚过去的终端输出。
INSTALL_REPORT="$PROJECT_ROOT/outputs/_install/last-install.json"
write_install_report() {   # [$1 fatal 原因]
    [ "$SETUP_MODE" = check ] && return 0
    local i n fatal_json="null"
    [ -n "${1:-}" ] && fatal_json="\"$(_json_esc "$1")\""
    mkdir -p "$(dirname "$INSTALL_REPORT")" 2>/dev/null || return 0
    {
        printf '{\n'
        printf '  "ts": %s,\n' "$(date +%s)"
        printf '  "installer": "setup.sh",\n'
        printf '  "openclaw": "%s",\n' "$(_json_esc "${OPENCLAW_VERSION_STR:-unknown}")"
        printf '  "node": "%s",\n' "$(_json_esc "$(node -v 2>/dev/null || echo unknown)")"
        printf '  "fatal": %s,\n' "$fatal_json"
        printf '  "warnings": ['
        n=${#WARN_LABELS[@]}
        i=0
        while [ "$i" -lt "$n" ]; do
            [ "$i" -gt 0 ] && printf ','
            printf '\n    {"label":"%s","detail":"%s","fix":"%s","severity":"%s"}' \
                "$(_json_esc "${WARN_LABELS[$i]}")" \
                "$(_json_esc "${WARN_DETAILS[$i]}")" \
                "$(_json_esc "${WARN_FIXES[$i]}")" \
                "$(_json_esc "${WARN_SEVERITY[$i]}")"
            i=$((i + 1))
        done
        [ "$n" -gt 0 ] && printf '\n  '
        printf ']\n}\n'
    } > "$INSTALL_REPORT" 2>/dev/null || true
}

# ---- 结尾汇总 ----
# 变宽内容不套框线：CJK 是双宽字符，用字符数做 padding 的 ASCII 框线一定错位
# （本脚本开头那两个框就是错位的）。框线只留给纯 ASCII 的标题行。
print_summary() {
    local n i sev
    n=${#WARN_LABELS[@]}
    echo ""
    if [ "$n" -eq 0 ]; then
        echo -e "${GREEN}  ✓ Easel 安装完成${NC}"
    else
        echo -e "${YELLOW}  ✓ Easel 安装完成（有 ${n} 项降级）${NC}"
    fi
    if [ "$n" -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}  需要处理（${n}）：${NC}"
        # high 先于 low
        for sev in high low; do
            i=0
            while [ "$i" -lt "$n" ]; do
                if [ "${WARN_SEVERITY[$i]}" = "$sev" ]; then
                    echo -e "   ${YELLOW}⚠${NC} ${WARN_LABELS[$i]} — ${WARN_DETAILS[$i]}"
                    [ -n "${WARN_FIXES[$i]}" ] && echo -e "       ${DIM}→ ${WARN_FIXES[$i]}${NC}"
                fi
                i=$((i + 1))
            done
        done
        echo ""
        echo -e "${DIM}  以上均不影响已装好的部分；逐项修完可用 easel doctor 复检。${NC}"
        echo -e "${DIM}  若希望这些问题直接让安装失败（CI/自动化场景）：EASEL_SETUP_STRICT=1 bash setup.sh${NC}"
    fi
}


clear 2>/dev/null || true
echo -e "\n${CYAN}╭────────────────────────────────────────────────────╮${NC}"
echo -e "${CYAN}│${NC}  ${MAGENTA}Easel${NC} · 社媒内容工作台安装向导                 ${CYAN}│${NC}"
echo -e "${CYAN}│${NC}  ${DIM}OpenClaw-powered · Linux / macOS${NC}                 ${CYAN}│${NC}"
echo -e "${CYAN}╰────────────────────────────────────────────────────╯${NC}"
echo -e "\n${DIM}  Easel 会使用独立 profile ~/.openclaw-${PROFILE}/，不会覆盖已有 OpenClaw。${NC}\n"

# ---- 1. Node.js >= 24.16 ----
# 跟随 openclaw@latest 的引擎要求：当前 2026.9.x 需要 Node >=24.16.0 <25 || >=26.1.0
# （注意 25.x 与 26.0 被排除）。setup 默认安装 openclaw@latest，故 Node 下限对齐到 24.16。
# 默认先走国内镜像再回落 nodejs.org：实测同一个包 nodejs.org ~20KB/s（20 分钟都下不完），
# 阿里云 ~590KB/s（53 秒）。EASEL_NODE_MIRROR 可覆盖，镜像目录结构需与 nodejs.org/dist 一致。
NODE_MIRROR_DEFAULT="https://mirrors.aliyun.com/nodejs-release"
step "1/8" "检查系统环境" "Python · Node.js · Git · FFmpeg"
info "检查 Node.js..."
node_version_ok() {  # $1=major $2=minor
    { [ "$1" -eq 24 ] && [ "$2" -ge 16 ]; } \
        || { [ "$1" -eq 26 ] && [ "$2" -ge 1 ]; } \
        || [ "$1" -ge 27 ]
}
NODE_OK=false
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    NODE_MINOR=$(echo "$NODE_VER" | cut -d. -f2)
    if node_version_ok "$NODE_MAJOR" "$NODE_MINOR"; then
        NODE_OK=true
    fi
fi

if $NODE_OK; then
    ok "Node.js $NODE_VER"
else
    if [ -n "${NODE_VER:-}" ]; then
        info "Node.js $NODE_VER 过旧（openclaw@latest 需要 24.16+），安装 Node.js 24..."
    else
        info "安装 Node.js 24..."
    fi
    if [ "$(uname -s)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install node@24
            BREW_NODE24_PREFIX="$(brew --prefix node@24)"
            export PATH="$BREW_NODE24_PREFIX/bin:$PATH"
        else
            echo "macOS 未找到 Homebrew。请先安装 Node.js 24.16+（Homebrew: brew install node@24），再重新运行 setup.sh。" >&2
            exit 1
        fi
    else
        NODE_TARGET="v24.21.0"
        NODE_DIR="node-${NODE_TARGET}-linux-x64"
        # 已有 nvm 就装进用户目录：不需要 root，也不覆盖系统 node。
        if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
            # shellcheck disable=SC1091
            . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
            NVM_NODEJS_ORG_MIRROR="${EASEL_NODE_MIRROR:-$NODE_MIRROR_DEFAULT}" \
                nvm install "${NODE_TARGET#v}" >/dev/null 2>&1 || nvm install "${NODE_TARGET#v}"
            # --delete-prefix 必须在版本号之前；放在后面 nvm 会静默不切换，甚至让 node 从
            # PATH 上消失。它用来盖掉 ~/.npmrc 里与 nvm 冲突的 prefix/globalconfig 设置。
            nvm use --delete-prefix "${NODE_TARGET#v}" >/dev/null 2>&1 \
                || nvm use "${NODE_TARGET#v}"
        else
            # 原来写死 --max-time 120：这个包 30MB，nodejs.org 在国内链路常跌到 ~20KB/s，
            # 120 秒必然超时，配合 set -euo pipefail 让整个安装从第 1 步就断掉。
            # 改成多镜像依次重试（npm registry 那边早就有镜像回退，这里缺了）+ 放宽超时。
            NODE_OK_DL=false
            for base in "${EASEL_NODE_MIRROR:-$NODE_MIRROR_DEFAULT}" "https://nodejs.org/dist"; do
                if curl -fL --connect-timeout 15 --max-time 900 --retry 2 --retry-delay 3 \
                    "$base/${NODE_TARGET}/${NODE_DIR}.tar.xz" -o /tmp/node24.tar.xz; then
                    NODE_OK_DL=true; break
                fi
                warn "从 $base 下载 Node 失败，尝试下一个源"
            done
            if [ "$NODE_OK_DL" != true ]; then
                echo "Node.js ${NODE_TARGET} 下载失败。请手动安装 Node 24.16+ 后重新运行，或用" >&2
                echo "  EASEL_NODE_MIRROR=<镜像地址> bash setup.sh   指定可用镜像。" >&2
                exit 1
            fi
            cd /tmp && tar xf node24.tar.xz
            # /usr/local 对非 root 不可写，原来的裸 cp 必然 permission denied。
            NODE_SUDO=""
            if [ "$(id -u)" -ne 0 ]; then
                if command -v sudo >/dev/null 2>&1; then
                    NODE_SUDO="sudo"
                else
                    echo "需要 root 才能写入 /usr/local，且未找到 sudo。请手动安装 Node 24.16+ 后重试。" >&2
                    exit 1
                fi
            fi
            $NODE_SUDO cp -rf "${NODE_DIR}/bin/." /usr/local/bin/
            $NODE_SUDO cp -rf "${NODE_DIR}/lib/." /usr/local/lib/
            rm -rf "/tmp/${NODE_DIR}" /tmp/node24.tar.xz
            cd "$PROJECT_ROOT"
        fi
    fi
    ok "Node.js $(node -v)"
fi
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    PYTHON_OK=$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')
    if [ "$PYTHON_OK" -eq 1 ]; then
        ok "Python $(python3 --version 2>&1 | awk '{print $2}')"
    else
        echo "Python 版本过低：检测到 ${PYTHON_VER}，需要 Python 3.10+。" >&2
        exit 1
    fi
else
    echo "未找到 python3；Easel 需要 Python 3.10+。" >&2
    exit 1
fi
if [ -t 0 ]; then
    USE_VENV="$(ask '使用项目虚拟环境 .venv 安装 Python 依赖？[Y/n]')"
    case "${USE_VENV:-Y}" in
        n|N) warn "将使用当前 Python 环境" ;;
        *)
            if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
                if ! python3 -c 'import venv' >/dev/null 2>&1; then
                    echo "当前 Python 缺少 venv 模块，无法创建虚拟环境。" >&2
                    echo "Debian/Ubuntu 请运行：sudo apt install python3-venv" >&2
                    echo "RHEL/CentOS 请安装对应的 python3 virtualenv/venv 包后重试。" >&2
                    exit 1
                fi
                info "创建虚拟环境 .venv..."
                python3 -m venv "$PROJECT_ROOT/.venv"
            fi
            # shellcheck disable=SC1091
            source "$PROJECT_ROOT/.venv/bin/activate"
            if ! python3 -m pip --version >/dev/null 2>&1; then
                echo "虚拟环境已创建但缺少 pip，请检查系统 Python 的 ensurepip/venv 包后重试。" >&2
                exit 1
            fi
            ok "已使用虚拟环境：$PROJECT_ROOT/.venv"
            ;;
    esac
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    # Non-interactive runs reuse an existing project environment when available.
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.venv/bin/activate"
    info "检测到 .venv，非交互模式自动使用项目虚拟环境"
else
    warn "当前为非交互模式且未找到 .venv，将使用系统 Python；建议先创建 Python 3.10+ 虚拟环境"
fi
command -v git >/dev/null 2>&1 && ok "Git $(git --version | awk '{print $3}')" || warn "未找到 git"
if command -v ffmpeg >/dev/null 2>&1; then
    ok "FFmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
else
    info "安装 FFmpeg（媒体功能必需）..."
    if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    elif command -v apt-get >/dev/null 2>&1; then
        if [ "$(id -u)" -eq 0 ]; then apt-get update && apt-get install -y ffmpeg
        elif command -v sudo >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y ffmpeg
        fi
    elif command -v dnf >/dev/null 2>&1; then
        if [ "$(id -u)" -eq 0 ]; then dnf install -y ffmpeg
        elif command -v sudo >/dev/null 2>&1; then sudo dnf install -y ffmpeg
        fi
    elif command -v yum >/dev/null 2>&1; then
        if [ "$(id -u)" -eq 0 ]; then yum install -y ffmpeg
        elif command -v sudo >/dev/null 2>&1; then sudo yum install -y ffmpeg
        fi
    fi
    if command -v ffmpeg >/dev/null 2>&1; then
        ok "FFmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
    else
        # 降级而非中断：缺 ffmpeg 只影响视频/音频类技能，对话与图文发布照常。
        warn_collect 'FFmpeg' '自动安装失败，视频/音频类技能不可用' \
            '手动安装 ffmpeg 后重新运行 bash setup.sh'
    fi
fi

# ---- 2. npm 源 ----
# 镜像选择：EASEL_NPM_REGISTRY 显式指定 > 连通性探测自动选择 > 默认官方源。
# 国内网络直连 registry.npmjs.org 经常极慢或超时（OpenClaw 安装是全流程最常
# 失败的一步），探测成功（≤3s）才用官方源；失败自动回落 npmmirror。
# 注意不再 `npm config set registry` 写用户全局配置 —— 改为安装命令上挂
# --registry，只影响本次安装，装完用户 npm 配置一个字节都没动。
step "2/8" "准备 Node.js 工具链" "选择 npm registry"
NPM_REGISTRY="${EASEL_NPM_REGISTRY:-}"
if [ -z "$NPM_REGISTRY" ]; then
    if npm ping --registry https://registry.npmjs.org --fetch-timeout=5000 \
        --fetch-retries=0 --fetch-retry-mintimeout=0 >/dev/null 2>&1; then
        NPM_REGISTRY="https://registry.npmjs.org"
        ok "npm registry: npmjs.org（连通性正常）"
    else
        NPM_REGISTRY="https://registry.npmmirror.com"
        warn "npmjs.org 连通性差，自动使用国内镜像 npmmirror.com（可用 EASEL_NPM_REGISTRY 覆盖）"
    fi
else
    ok "npm registry: $NPM_REGISTRY（EASEL_NPM_REGISTRY 指定）"
fi
NPM_REGISTRY_ARGS=(--registry "$NPM_REGISTRY")

# ---- 3. 检测/安装 OpenClaw（复用用户已有安装，不覆盖全局配置） ----
step "3/8" "检测 OpenClaw" "已有安装将直接复用"
info "检查 OpenClaw..."
if command -v openclaw >/dev/null 2>&1; then
    OPENCLAW_BIN="$(command -v openclaw)"
    OPENCLAW_VERSION_STR="$("$OPENCLAW_BIN" --version 2>&1 | head -1)"
    ok "检测到 OpenClaw：$OPENCLAW_VERSION_STR"
else
    info "安装 OpenClaw..."
    run_step 'openclaw 全局安装' \
        npm install -g openclaw@latest --loglevel warn "${NPM_REGISTRY_ARGS[@]}"
    # npm 全局 bin 目录未必在当前 shell 的 PATH 上：macOS Homebrew 的 Node 会把全局包装到
    # $(npm prefix -g)/bin（如 /opt/homebrew/Cellar/node/<ver>/bin），而 /opt/homebrew/bin 里
    # 并没有 openclaw 链接。此时 command -v 拿到空值，后面 $OPENCLAW_BIN --version 会直接崩。
    # 先把 npm 全局 bin 补进 PATH 再检测。
    if ! command -v openclaw >/dev/null 2>&1; then
        NPM_GLOBAL_BIN="$(npm prefix -g 2>/dev/null)/bin"
        if [ -x "$NPM_GLOBAL_BIN/openclaw" ]; then
            export PATH="$NPM_GLOBAL_BIN:$PATH"
        fi
    fi
    OPENCLAW_BIN="$(command -v openclaw)"
    if [ -z "$OPENCLAW_BIN" ]; then
        echo "OpenClaw 安装后仍未在 PATH 中找到。请把 npm 全局 bin 目录（$(npm prefix -g 2>/dev/null)/bin）加入 PATH 后重新运行 setup.sh（幂等，会跳过已装部分）。" >&2
        exit 1
    fi
    ok "OpenClaw 已安装：$("$OPENCLAW_BIN" --version 2>&1 | head -1)"
fi

# ---- 4. 初始化 Easel 专属 OpenClaw profile ----
step "4/8" "初始化 Easel profile" "独立配置、独立 workspace、独立 Gateway"
info "初始化 Easel profile (--profile $PROFILE)..."
if [ -f "$HOME/.openclaw-${PROFILE}/openclaw.json" ]; then
    ok "Profile 已存在"
else
    ONBOARD_HELP="$("$OPENCLAW_BIN" onboard --help 2>/dev/null || true)"
    if [ -n "$ONBOARD_HELP" ]; then
        ONBOARD_ARGS=(onboard --non-interactive --mode local --accept-risk)
        for optional_arg in --skip-health --skip-channels --skip-skills \
            --skip-ui --skip-hooks --skip-search; do
            if printf '%s\n' "$ONBOARD_HELP" | grep -q -- "$optional_arg"; then
                ONBOARD_ARGS+=("$optional_arg")
            fi
        done
        if printf '%s\n' "$ONBOARD_HELP" | grep -q -- '--skip-daemon'; then
            ONBOARD_ARGS+=(--skip-daemon)
        elif printf '%s\n' "$ONBOARD_HELP" | grep -q -- '--no-install-daemon'; then
            ONBOARD_ARGS+=(--no-install-daemon)
        fi
        run_step 'openclaw onboard' \
            "$OPENCLAW_BIN" --profile "$PROFILE" "${ONBOARD_ARGS[@]}"
    elif "$OPENCLAW_BIN" setup --help >/dev/null 2>&1; then
        run_step 'openclaw setup' oc setup --non-interactive --mode local --accept-risk
    else
        echo "当前 OpenClaw 不支持可用的非交互初始化命令，请升级 OpenClaw 后重试。" >&2
        exit 1
    fi
    ok "Profile 初始化完成 → ~/.openclaw-${PROFILE}/"
fi

# ---- 5. 安装 easel CLI ----
step "5/8" "安装 Easel 运行依赖" "Web · 媒体 · 浏览器发布"
info "[1/2] 安装 Python 依赖与 easel CLI..."
# pip 镜像：EASEL_PIP_INDEX 显式指定 > 官方源连通性探测 > 默认官方源（同 npm 逻辑）。
# 国内直连 pypi.org 装依赖（fastapi/playwright 等）经常超时；探测失败自动回落清华源。
PIP_INDEX="${EASEL_PIP_INDEX:-}"
if [ -z "$PIP_INDEX" ]; then
    # timeout 8 兜底：urlopen 的 timeout=4 不含 DNS 解析卡死等极端情形（macOS 无
    # coreutils timeout，command -v 判空时退化为仅靠 urlopen 自身超时）。
    if command -v timeout >/dev/null 2>&1; then
        PYPI_PROBE=(timeout 8 python3 -c "import urllib.request;urllib.request.urlopen('https://pypi.org/simple/', timeout=4)")
    else
        PYPI_PROBE=(python3 -c "import urllib.request;urllib.request.urlopen('https://pypi.org/simple/', timeout=4)")
    fi
    if "${PYPI_PROBE[@]}" >/dev/null 2>&1; then
        PIP_INDEX_ARGS=()
        ok "PyPI: pypi.org（连通性正常）"
    else
        PIP_INDEX_ARGS=(-i "https://pypi.tuna.tsinghua.edu.cn/simple")
        warn "pypi.org 连通性差，自动使用清华镜像（可用 EASEL_PIP_INDEX 覆盖）"
    fi
else
    PIP_INDEX_ARGS=(-i "$PIP_INDEX")
    ok "PyPI: $PIP_INDEX（EASEL_PIP_INDEX 指定）"
fi
# --prefer-binary: 新版 biliup 常先发 sdist 后补 wheel，源码构建要求最新 rustc；优先选有 wheel 的旧版本
PIP_ARGS=(install -e "$PROJECT_ROOT" --prefer-binary --progress-bar on ${PIP_INDEX_ARGS[@]+"${PIP_INDEX_ARGS[@]}"})
if [ "$(id -u)" -eq 0 ]; then
    PIP_ARGS+=(--root-user-action=ignore)
    warn "当前以 root 安装；生产服务器建议使用虚拟环境"
fi
run_step 'pip install' run_with_progress "Python 依赖安装" python3 -m pip "${PIP_ARGS[@]}"
# check 模式下 pip 安装被跳过，easel 自然不会出现 —— 这里不能当成失败，否则 check
# 模式必然在第 5 步中断，整个「不下载依赖也能验证安装逻辑」的用途就没了。
if [ "$SETUP_MODE" != check ] && ! command -v easel >/dev/null 2>&1; then
    fatal "easel 命令未找到；请检查 Python 环境和 PATH（重试：bash setup.sh）"
fi
ok "[2/2] easel 命令可用"

# ---- 6. 构建 Web 前端（Node 已装 → easel web 直接出真 UI，无需手动构建） ----
step "6/8" "构建 Web 工作台" "React production bundle"
info "构建 Web 前端..."
if [ -d "$PROJECT_ROOT/web/frontend" ]; then
    if [ "$SETUP_MODE" = check ]; then
        emit_action run_step '前端依赖与构建' '依赖安装 + production bundle'
    elif ! (
        cd "$PROJECT_ROOT/web/frontend"
        if [ -f package-lock.json ]; then npm ci --no-audit --no-fund "${NPM_REGISTRY_ARGS[@]}" || npm install --no-audit --no-fund "${NPM_REGISTRY_ARGS[@]}"; else npm install --no-audit --no-fund "${NPM_REGISTRY_ARGS[@]}"; fi
        npm run build
    ); then
        echo "前端依赖安装或构建失败；请检查 Node.js/npm 网络后重新运行 bash setup.sh。" >&2
        exit 1
    fi
    ok "前端已构建 → web/frontend/dist/"
else
    echo "未找到 web/frontend，无法完成 Web 工作台安装。" >&2
    exit 1
fi

# ---- 7. 认证配置 ----
step "7/8" "同步模型配置" "把 .env 里的认证写进 OpenClaw profile"
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
# 不要把 stderr 并进管道：sync.sh 解析不出 workspace 时那条警告只走 stderr，且不含 ✓/→，
# 一并 grep 就被整条吃掉 —— 装完什么都没说，技能却同步到了 agent 不读的目录（issue #19
# 的失败模式在这一层原样重建）。stdout 照旧过滤噪音，stderr 直通用户。
# 注意两点：stderr 不能并进管道（见上），且 grep 无匹配时退出 1 —— 在 pipefail 下
# 那会把一次成功的同步变成「安装中断」。先捕获 stdout，再分别判同步本身的成败。
SYNC_RC=0
SYNC_OUT="$(run_step 'openclaw/sync.sh' bash "$PROJECT_ROOT/openclaw/sync.sh")" || SYNC_RC=$?
printf '%s\n' "$SYNC_OUT" | grep -E '✓|→' || true
if [ "$SYNC_RC" -ne 0 ]; then
    warn_collect '技能同步' "openclaw/sync.sh 退出码 $SYNC_RC；技能可能没进 agent 实际读取的 workspace" \
        'bash openclaw/sync.sh' high
fi

# ---- 9. 认证信息写入 Easel 专属 OpenClaw config ----
info "同步认证到 OpenClaw profile..."
source "$PROJECT_ROOT/.env" 2>/dev/null || true

# 部分 OpenClaw 版本执行 config unset 后会把字段留成 null 而非真正删除该键，
# 一旦落盘就再也无法通过 config set/doctor --fix 修复（每次校验都先失败）。
# 这里在写入任何配置前，先把 models.providers.* 下残留的 null 叶子节点原地清空。
OPENCLAW_JSON="$HOME/.openclaw-${PROFILE}/openclaw.json"
if [ -f "$OPENCLAW_JSON" ]; then
    python3 - "$OPENCLAW_JSON" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path) as f:
    config = json.load(f)


def strip_nulls(node):
    if isinstance(node, dict):
        changed = False
        for key in list(node.keys()):
            value = node[key]
            if value is None:
                del node[key]
                changed = True
            elif strip_nulls(value):
                changed = True
        return changed
    return False


providers = config.get("models", {}).get("providers", {})
if strip_nulls(providers):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
PY
fi

# 原子写入 anthropic provider。部分 OpenClaw 版本（如 2026.3.x）的 schema 要求 provider 一次性带齐
# baseUrl + models，逐字段 config set 会因中间态缺字段而整体校验失败（baseUrl/models: received undefined）。
# 这里用一次 --json 原子写入建好完整 provider；整块替换也会顺带清掉旧的 Cookie/X-Adapter-* 等残留 header。
# 用法：oc_write_anthropic <baseUrl> <apiKey> [apiKeyHeader] [anthropicVersion]
oc_write_anthropic() {
    local seed
    seed="$(A_BASE_URL="$1" A_API_KEY="$2" A_HDR="${3:-}" A_VER="${4:-}" python3 -c '
import json, os
# api 必须显式写死：不写时 OpenClaw 2026.2.x 会把这个 provider 当成 openai-responses，
# 请求打到 /responses，上游只报「does not support the responses interface」，而 gateway
# 把它当正常回复塞进 choices[0].message.content → Web 对话静默显示「（无输出）」。
p = {"baseUrl": os.environ["A_BASE_URL"], "apiKey": os.environ["A_API_KEY"],
     "api": "anthropic-messages", "models": []}
hdr = os.environ.get("A_HDR"); ver = os.environ.get("A_VER")
if hdr or ver:
    h = {}
    if hdr: h[hdr] = os.environ["A_API_KEY"]
    if ver: h["anthropic-version"] = ver
    p["headers"] = h
print(json.dumps(p))')"
    # 2026.9.x 起，--json 整块写入若会删掉 provider 下已存在的子键会被直接拒绝
    # （"Refusing to replace ...; it would remove existing entries: timeoutSeconds"）。
    # 而 timeoutSeconds 正是本脚本后面自己设的 —— 于是首次安装能过、第二次重跑必失败，
    # setup.sh 变成不可重入。这里的语义本来就是「有意整块替换」（顺带清掉旧的
    # Cookie/X-Adapter-* 残留 header），所以显式声明 --replace；老版本没这个标志，
    # 探测不到就沿用裸 --json（那些版本也不会拒绝替换）。
    if oc_supports 'config set' '--replace'; then
        oc_set '模型 provider（anthropic）' models.providers.anthropic "$seed" --json-replace '' high
    else
        oc_set '模型 provider（anthropic）' models.providers.anthropic "$seed" --json '' high
    fi
}

# .env.example 里的 key 带的是占位符，所以「变量有值」≠「这个 key 能用」。
# 认证判定一律走这里，别再各写各的 -n/-z：之前下面那段用 `-z ANTHROPIC_API_KEY`
# 判「没配 Anthropic」，占位符行一留就永远不成立，整条 OpenAI 分支被跳过，
# 最后只写了个指向不存在 provider 的 primary，对话直接报
# "No route-compatible authentication source is configured for openai"。
# 语义与 setup.ps1 的 Is-UsableKey 保持一致。
usable_key() {
    [ -n "${1:-}" ] || return 1
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        *replace_me*|*your-api-key*|*your_api_key*|*"your api key"*) return 1 ;;
    esac
    return 0
}

MODEL_CONFIGURED=false
if usable_key "${ANTHROPIC_API_KEY:-}"; then
    MODEL_CONFIGURED=true
elif usable_key "${EASEL_LLM_API_KEY:-}" && [ -n "${EASEL_LLM_BASE_URL:-}" ]; then
    MODEL_CONFIGURED=true
elif usable_key "${OPENAI_API_KEY:-}"; then
    MODEL_CONFIGURED=true
elif usable_key "${ANTHROPIC_AUTH_TOKEN:-}" && [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
    MODEL_CONFIGURED=true
elif usable_key "${OPENAI_MAAS_API_KEY:-}" && [ -n "${OPENAI_MAAS_ENDPOINT:-}" ]; then
    MODEL_CONFIGURED=true
fi

# 模型 API Key 不再在终端里问，改为装完在浏览器里配。
#
# 为什么挪走：Web 端的「设置 → 模型配置」本来就更强（能拉取模型列表、做连通性
# 自测、保存后自动同步 openclaw 配置并重启网关），而终端向导只能盲填，还要求用户
# 在装机时就准备好 Key，否则这一步就卡住。顺带两个收益：
#   - API Key 不再经过 shell 变量和 `>> .env` 追加（重跑会写出重复键）；
#   - 安装过程变成全程非交互，CI 与自动化不需要再喂 stdin。
if [ "$MODEL_CONFIGURED" = false ]; then
    warn_collect '模型配置' '还没有可用的 API Key，对话功能尚不可用' \
        'easel web → 设置 → 模型配置 → 填 Key → 保存' high
fi

DEFAULT_PRIMARY_MODEL="anthropic/claude-sonnet-4-6"
STANDARD_LLM_CONFIGURED=false
# 仅当真正写了 anthropic provider 时，才补设它的 provider 级超时（见下方 timeoutSeconds）；
# 否则会给 OpenAI/MAAS 用户凭空造出一个只有 timeoutSeconds、缺 baseUrl/models 的残缺 anthropic provider。
ANTHROPIC_PROVIDER_SYNCED=false
# 下面 if 链里只要有一支写成了 provider 就算配好；仅 else（谁都没匹配上）会翻成 false。
AUTH_CONFIGURED=true
if usable_key "${ANTHROPIC_API_KEY:-}"; then
    STANDARD_LLM_CONFIGURED=true
elif usable_key "${EASEL_LLM_API_KEY:-}" && [ -n "${EASEL_LLM_BASE_URL:-}" ]; then
    STANDARD_LLM_CONFIGURED=true
elif usable_key "${OPENAI_API_KEY:-}"; then
    STANDARD_LLM_CONFIGURED=true
fi

# 「只配了 OpenAI」才走这支（Anthropic/EASEL_LLM 优先级更高）。判据必须是 usable_key
# 而非 -z，否则 .env.example 留下的占位符会一直把这支挡掉。
# EASEL_LLM 要连 BASE_URL 一起判：只填了 key 没填 URL 时它哪条分支都用不上，
# 不能让这种半拉配置把可用的 OPENAI 也一并挡死、最后落到「认证未配置」。
if usable_key "${OPENAI_API_KEY:-}" && ! usable_key "${ANTHROPIC_API_KEY:-}" \
   && ! { usable_key "${EASEL_LLM_API_KEY:-}" && [ -n "${EASEL_LLM_BASE_URL:-}" ]; }; then
    OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o}"
    # 未声明 maxTokens 时 OpenClaw 会自行推导，部分 OpenAI 兼容网关据此拒绝请求
    # （issue #26 P0-2）。默认值对齐默认模型 gpt-4o 的真实上限（128K 上下文 /
    # 16384 最大输出，OpenAI 官方文档），不是随手照抄 Gemini 分支的 65535 ——
    # 声称上限高于真实值，长输出请求照样会被下游网关拒；两个方向都可被 .env 覆盖。
    OPENAI_CONTEXT_WINDOW="${OPENAI_CONTEXT_WINDOW:-128000}"
    OPENAI_MAX_TOKENS="${OPENAI_MAX_TOKENS:-16384}"
    oc_set 'OpenAI provider' models.providers.openai.api "openai-completions"
    oc_set 'OpenAI provider' models.providers.openai.apiKey "$OPENAI_API_KEY"
    oc_set 'OpenAI provider' models.providers.openai.baseUrl "${OPENAI_BASE_URL:-https://api.openai.com/v1}"
    oc_set 'OpenAI provider' models.providers.openai.models \
        "[{\"id\":\"$OPENAI_MODEL\",\"name\":\"OpenAI model\",\"reasoning\":true,\"input\":[\"text\",\"image\"],\"contextWindow\":$OPENAI_CONTEXT_WINDOW,\"maxTokens\":$OPENAI_MAX_TOKENS}]" \
        --json
    DEFAULT_PRIMARY_MODEL="openai/$OPENAI_MODEL"
    CLAUDE_MODEL="$DEFAULT_PRIMARY_MODEL"
    ok "OpenAI 服务认证已同步"
elif [ "$STANDARD_LLM_CONFIGURED" = false ] && usable_key "${OPENAI_MAAS_API_KEY:-}"; then
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
    oc_set 'OpenAI-compatible 本地适配器' models.providers."$OPENAI_PROVIDER" \
        "$OPENAI_PROVIDER_CONFIG" --json
    DEFAULT_PRIMARY_MODEL="$OPENAI_PROVIDER/$OPENAI_MODEL"
    CLAUDE_MODEL="$DEFAULT_PRIMARY_MODEL"
    ok "OpenAI-compatible 服务已通过本地适配器同步"
elif [ "$STANDARD_LLM_CONFIGURED" = false ] && usable_key "${GEMINI_MAAS_API_KEY:-}"; then
    GEMINI_PROVIDER="rednote-gemini"
    GEMINI_MODEL="${GEMINI_MAAS_MODEL:-gemini-3.1-pro-preview}"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".baseUrl \
        "http://127.0.0.1:${GEMINI_ADAPTER_PORT:-18790}/v1"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".api "openai-completions"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".apiKey "local-adapter"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".models \
        "[{\"id\":\"$GEMINI_MODEL\",\"name\":\"Gemini-compatible model\",\"reasoning\":true,\"input\":[\"text\",\"image\"],\"contextWindow\":1048576,\"maxTokens\":65535}]" \
        --json
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".timeoutSeconds 600 --json
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".request.allowPrivateNetwork true --json
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.command "/usr/bin/python3"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.args \
        "[\"$PROJECT_ROOT/scripts/gemini_maas_adapter.py\",\"--port\",\"${GEMINI_ADAPTER_PORT:-18790}\"]" \
        --json
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.cwd "$PROJECT_ROOT"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.healthUrl \
        "http://127.0.0.1:${GEMINI_ADAPTER_PORT:-18790}/health"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.idleStopMs 0 --json
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_MAAS_API_KEY \
        "$GEMINI_MAAS_API_KEY"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_MAAS_ENDPOINT \
        "${GEMINI_MAAS_ENDPOINT:?GEMINI_MAAS_ENDPOINT is required}"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_MAAS_MODEL \
        "$GEMINI_MODEL"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_THINKING_LEVEL \
        "${GEMINI_THINKING_LEVEL:-HIGH}"
    oc_set 'Gemini 本地适配器' models.providers."$GEMINI_PROVIDER".localService.env.GEMINI_INCLUDE_THOUGHTS \
        "${GEMINI_INCLUDE_THOUGHTS:-true}"
    DEFAULT_PRIMARY_MODEL="$GEMINI_PROVIDER/$GEMINI_MODEL"
    CLAUDE_MODEL="$DEFAULT_PRIMARY_MODEL"
    ok "Gemini-compatible 服务已通过本地适配器同步"
elif usable_key "${EASEL_LLM_API_KEY:-}" && [ -n "${EASEL_LLM_BASE_URL:-}" ]; then
    # 原子写入整块 provider（含 header 与 anthropic-version）；整块替换会顺带清掉旧的 CodeWiz 专用 header。
    oc_write_anthropic "$EASEL_LLM_BASE_URL" "$EASEL_LLM_API_KEY" \
        "${EASEL_LLM_API_KEY_HEADER:-api-key}" "${EASEL_LLM_ANTHROPIC_VERSION:-2023-06-01}"
    ANTHROPIC_PROVIDER_SYNCED=true
    ok "自定义 Anthropic 兼容 MaaS 认证已同步"
elif usable_key "${ANTHROPIC_AUTH_TOKEN:-}" && [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
    oc_write_anthropic "$ANTHROPIC_BASE_URL" "$ANTHROPIC_AUTH_TOKEN"
    ANTHROPIC_PROVIDER_SYNCED=true
    ok "Anthropic 兼容服务认证已同步"
elif usable_key "${ANTHROPIC_API_KEY:-}"; then
    # 官方 ANTHROPIC_API_KEY 可搭配 ANTHROPIC_BASE_URL 指向自定义代理/网关；未指定时显式指向官方端点，
    # 否则请求会发往默认的 api.anthropic.com，代理网络下会直接超时。provider 由 oc_write_anthropic 原子写入。
    oc_write_anthropic "${ANTHROPIC_BASE_URL:-https://api.anthropic.com}" "$ANTHROPIC_API_KEY"
    ANTHROPIC_PROVIDER_SYNCED=true
    if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
        ok "API key + 自定义 Anthropic Base URL 已同步"
    else
        ok "API key 已同步"
    fi
else
    AUTH_CONFIGURED=false
    warn "认证未配置：.env 里没有可用的 API key（占位符 REPLACE_ME 不算）"
    warn "  编辑 $PROJECT_ROOT/.env 填入真实 key 后，重新运行 bash setup.sh"
fi

# ---- 10. OpenClaw agent 模型 + 超时 ----
# CLAUDE_MODEL 保留旧变量名以兼容现有环境，值必须是 OpenClaw 的 provider/model。
# 不要填内部 proxy 映射名（如 claude-4.6-opus-google），否则 OpenClaw 不认识。
if [ "$AUTH_CONFIGURED" = true ]; then
    oc_set '主模型路由' agents.defaults.model.primary \
        "${CLAUDE_MODEL:-$DEFAULT_PRIMARY_MODEL}" '' high
else
    # 上面一个 provider 都没写。这时还去写 primary 只会把 agent 指向一个不存在的
    # provider（CLAUDE_MODEL 直接来自 .env），对话时报 "No route-compatible
    # authentication source is configured for <provider>" —— 比「没配置」更难查。
    # 保持不动：既不造假配置，也不覆盖用户上一次跑成功时留下的可用 primary。
    warn "未写入 agents.defaults.model.primary；openclaw 中已有的模型设置保持不变"
fi
# 整个 agent run 的总时长上限。制作层任务（OpenClaw 自执行短剧/长稿/多镜）很久 → 给足。
oc_set 'agent 总超时' agents.defaults.timeoutSeconds 7200
# Easel 使用 profiles/<当前画像>/memory.md；关闭 OpenClaw 全局记忆索引，避免旧索引跨画像召回。
# Easel 使用 profiles/<当前画像>/memory.md；向量记忆必须使用单独的 embedding API。
# 否则 OpenClaw 会默认请求 text-embedding-3-small，很多聊天 MaaS 并不提供该模型。
EMBEDDING_API_KEY="${EASEL_EMBEDDING_API_KEY:-${EASEL_EMBEDDINGS_API_KEY:-${OPENAI_EMBEDDING_API_KEY:-${EMBEDDING_API_KEY:-${EMBEDDINGS_API_KEY:-}}}}}"
EMBEDDING_BASE_URL="${EASEL_EMBEDDING_BASE_URL:-${EASEL_EMBEDDINGS_BASE_URL:-${OPENAI_EMBEDDING_BASE_URL:-${EMBEDDING_BASE_URL:-${EMBEDDINGS_BASE_URL:-}}}}}"
EMBEDDING_MODEL="${EASEL_EMBEDDING_MODEL:-${EASEL_EMBEDDINGS_MODEL:-${OPENAI_EMBEDDING_MODEL:-${EMBEDDING_MODEL:-${EMBEDDINGS_MODEL:-}}}}}"
# 记忆检索配置的 schema 位置随 OpenClaw 版本变化：2026.9.x 起挪到顶层 memory.search.*，
# 之前（<=2026.6.x）在 agents.defaults.memorySearch.*。两者互斥（各自把对方的 key 判为 Unrecognized）。
# 用「先试新 key、失败再退老 key」自适应：第一条写入既是真实配置也是版本探测（失败输出静默）。
if [ -n "$EMBEDDING_API_KEY" ] && [ -n "$EMBEDDING_BASE_URL" ] && [ -n "$EMBEDDING_MODEL" ]; then
    # 先用 provider 这一条探出当前版本把记忆检索放在哪个前缀下，后续字段跟着它写。
    if oc_try memory.search.provider openai-compatible; then
        MEM_PREFIX="memory.search"                  # 新 schema（OpenClaw 2026.9.x+）
        oc_set '向量记忆' memory.search.enabled true --json
    elif oc_try agents.defaults.memorySearch.provider openai-compatible; then
        MEM_PREFIX="agents.defaults.memorySearch"   # 老 schema（<=2026.6.x）
    else
        MEM_PREFIX=""
        warn_collect '向量记忆' '当前 OpenClaw 不接受任何已知的 memory search 写法，已退回关键词检索'
    fi
    if [ -n "$MEM_PREFIX" ]; then
        oc_set '向量记忆' "$MEM_PREFIX.model" "$EMBEDDING_MODEL"
        oc_set '向量记忆' "$MEM_PREFIX.remote.baseUrl" "$EMBEDDING_BASE_URL"
        oc_set '向量记忆' "$MEM_PREFIX.remote.apiKey" "$EMBEDDING_API_KEY"
        ok "独立向量模型已配置（$MEM_PREFIX）：$EMBEDDING_MODEL"
    fi
else
    # Deliberate FTS-only mode: never fall back to the chat endpoint for embeddings.
    # 关闭向量检索的键随 OpenClaw 版本变过两次：2026.9.x+ 是 memory.search.enabled，
    # 更早是 agents.defaults.memorySearch.enabled。原来的 memorySearch.provider=none 在
    # 2026.2.x 上是无效枚举（只认 local/openai），报 Invalid input 并退出 1，配合
    # set -euo pipefail 会直接中断整个安装 —— 「关闭」不能用 provider 表达。
    # 末尾 || true 兜住未来再次变更 schema 的情况：关不掉也不该让安装失败。
    oc_set_first '关闭向量记忆' false --json \
        memory.search.enabled agents.defaults.memorySearch.enabled || true
    if [ -n "$EMBEDDING_API_KEY$EMBEDDING_BASE_URL$EMBEDDING_MODEL" ]; then
        warn "向量 API 配置不完整，已关闭向量检索；需要同时设置 EASEL_EMBEDDING_API_KEY、EASEL_EMBEDDING_BASE_URL、EASEL_EMBEDDING_MODEL"
    else
        info "未配置独立向量 API，使用关键词记忆检索（不会请求 text-embedding-3-small）"
    fi
fi
# 单次 LLM 请求的「空闲超时」（等模型开始/继续产出 token 的最长时间）。内部网关对大上下文/带思考的
# 请求首 token 可能较慢，不设会用默认较短值 → 报「model did not produce a response before the model
# idle timeout」而中断整个 run。与 agents.defaults.timeoutSeconds 是两回事，provider 超时不能延长整个 run。
# 尽力而为：老版本 OpenClaw（如 2026.3.x）的 provider schema 不认识 timeoutSeconds，会报 Unrecognized key
# 并拒绝该次写入。这里吞掉这条噪音、绝不让它中断安装（|| true）；新版本 OpenClaw 才会真正把它调到 600s。
# 想彻底拿到更长的 provider 超时，请 npm i -g openclaw@latest 升级到支持该字段的版本。
if [ "$ANTHROPIC_PROVIDER_SYNCED" = true ]; then
    # 老版本不认这个键属于预期内的降级，不值得记一条警告 —— 用 oc_try 静默尝试。
    oc_try models.providers.anthropic.timeoutSeconds 600 || true
fi
oc_set 'gateway 基本配置' gateway.mode local
oc_set 'gateway 基本配置' gateway.bind loopback
oc_set 'gateway 基本配置' gateway.auth.mode none
# 对话直连常驻网关（web/app.py 的 http 传输层）要用 OpenAI 兼容端点，而 openclaw 默认
# 不挂这条路由（chatCompletions.enabled 默认 false），不开的话 POST /v1/chat/completions
# 一律 404、只能退回每轮 spawn 客户端的老路径。端点只绑 loopback + auth.mode=none 的本机
# 网关，不额外扩暴露面。旧版本没这个键时会报 Unrecognized key，吞掉即可（照常走 cli）。
oc_try gateway.http.endpoints.chatCompletions.enabled true --json || true

# Refuse to start with a config rejected by the installed OpenClaw version.
# This catches schema changes early instead of producing opaque Gateway errors.
# `config validate` 直到 2026.3 才有；2026.2.x 只有 get/set/unset，直接调会报
# "too many arguments for 'config'" 并让安装在最后一步前功尽弃。老版本上跳过即可 ——
# 上面每个 config set 都会各自校验，schema 问题照样会当场暴露。
if oc config --help 2>&1 | grep -qE '^\s+validate\b'; then
    # 降级而非中断：上面每个 config set 都已各自校验过，整体 validate 失败通常是更早
    # 版本留下的陈旧键，属于可修而非致命 —— 让 doctor 去指引，别把安装卡死在这。
    if oc config validate; then
        ok "OpenClaw 配置校验通过"
    else
        warn_collect 'OpenClaw 配置校验' '整体校验未通过（多为旧版本遗留的配置键）' \
            "openclaw --profile $PROFILE doctor --fix" high
    fi
else
    warn "当前 OpenClaw（$("$OPENCLAW_BIN" --version 2>&1 | head -1)）不支持 config validate，跳过整体校验"
fi

# ---- 11. 启动 gateway ----
step "8/8" "启动并验证" "配置校验 · Chromium · Gateway health"
info "启动 Easel gateway..."
# 降级而非中断：gateway 随时可以重启，没理由让一次十几分钟的安装在这最后一步作废。
if ! run_step 'gateway start' bash "$PROJECT_ROOT/scripts/gateway.sh" start; then
    warn_collect 'Gateway' '启动失败' 'bash scripts/gateway.sh start（日志：/tmp/easel-gateway.log）' high
fi

# Playwright is a runtime dependency for browser login/publishing.
if [ "$SETUP_MODE" = check ]; then
    # check 模式跳过了 pip 安装，playwright 模块自然不在。这里不能当成失败，否则
    # check 模式必然在最后一步中断 —— 与上面 easel 命令那处同理。
    emit_action run_step 'playwright chromium' 'python3 -m playwright install chromium'
elif python3 -c 'import playwright' >/dev/null 2>&1; then
    # 降级而非中断：这是个 ~300MB 的下载，弱网下失败很常见，而它只影响浏览器登录/发布。
    CHROMIUM_OK=true
    run_step 'playwright chromium' python3 -m playwright install chromium || CHROMIUM_OK=false
    if [ "$CHROMIUM_OK" = true ] && [ "$SETUP_MODE" != check ]; then
        python3 -c 'from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); path=Path(p.chromium.executable_path); p.stop(); raise SystemExit(0 if path.is_file() else 1)' \
            || CHROMIUM_OK=false
    fi
    if [ "$CHROMIUM_OK" = true ]; then
        ok "Playwright Chromium 已就绪"
    else
        warn_collect 'Playwright Chromium' '下载或校验失败，浏览器登录/发布不可用' \
            'python3 -m playwright install chromium'
    fi
else
    # 这个仍然致命：playwright 模块缺失意味着 pip 安装没装全，不是网络抖动。
    fatal "未找到 Playwright 模块；Python 依赖安装不完整（重试：bash setup.sh）"
fi

write_install_report
print_summary
if [ "${MODEL_CONFIGURED:-false}" = false ]; then
    echo ""
    echo -e "  ${YELLOW}下一步：在浏览器里配置模型${NC}"
    if [ -x "$PROJECT_ROOT/.venv/bin/easel" ]; then
        echo -e "    1. ${CYAN}source .venv/bin/activate && easel web${NC}"
    else
        echo -e "    1. ${CYAN}easel web${NC}"
    fi
    echo -e "    2. 打开 ${CYAN}http://localhost:7860${NC}"
    echo -e "    3. 左下角${CYAN}设置${NC} → ${CYAN}模型配置${NC} → 填 API Key → 保存"
    echo -e "  ${DIM}保存后 Easel 会自动写好 openclaw 配置并重启网关，不用再跑 setup.sh。${NC}"
    echo -e "  ${DIM}也可以直接编辑 .env 填 key，然后运行 easel doctor 复检。${NC}"
fi
echo -e "\n  ${CYAN}开始使用：${NC}"
if [ -x "$PROJECT_ROOT/.venv/bin/easel" ]; then
    echo -e "    ${CYAN}source .venv/bin/activate${NC}    # 先激活虚拟环境，easel 命令才可用"
    echo -e "    ${DIM}# 新开终端都要先激活；或不激活直接用 .venv/bin/easel <命令>${NC}"
fi
echo "    easel web                    # 启动 Web 工作台"
echo "    easel chat                   # 终端对话"
echo "    easel doctor                 # 检查环境"
echo "    easel ping                   # Gateway 连通性"
echo -e "\n  ${DIM}Easel profile：~/.openclaw-${PROFILE}/${NC}"
echo -e "  ${DIM}项目目录：$PROJECT_ROOT${NC}\n"
