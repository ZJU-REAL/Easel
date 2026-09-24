#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$ROOT/runtime"

need_command() {
  local command="$1"
  local package="$2"
  if command -v "$command" >/dev/null 2>&1; then return; fi
  if ! command -v brew >/dev/null 2>&1; then
    echo "缺少 $command。请先安装 Homebrew，或手动安装 $package。" >&2
    exit 1
  fi
  HOMEBREW_NO_AUTO_UPDATE=1 brew install "$package"
}

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

resolve_python() {
  local candidate
  for candidate in \
    "$(command -v python3 || true)" \
    "/opt/homebrew/opt/python@3.12/bin/python3.12" \
    "/usr/local/opt/python@3.12/bin/python3.12"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && python_supported "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BOOTSTRAP="$(resolve_python || true)"
if [[ -z "$PYTHON_BOOTSTRAP" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "需要 Python 3.10 或更高版本。请先安装 Homebrew，或手动安装 Python 3.12。" >&2
    exit 1
  fi
  HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.12
  PYTHON_BOOTSTRAP="$(brew --prefix python@3.12)/bin/python3.12"
fi
if ! python_supported "$PYTHON_BOOTSTRAP"; then
  echo "Python 版本仍低于 3.10：$PYTHON_BOOTSTRAP" >&2
  exit 1
fi

need_command node node
need_command npm node
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if (( NODE_MAJOR < 22 )); then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Node.js 必须为 22 或更高版本，当前为 $(node --version)。" >&2
    exit 1
  fi
  HOMEBREW_NO_AUTO_UPDATE=1 brew upgrade node || HOMEBREW_NO_AUTO_UPDATE=1 brew install node
  hash -r
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  if (( NODE_MAJOR < 22 )); then
    echo "Node.js 升级后仍低于 22，当前为 $(node --version)。" >&2
    exit 1
  fi
fi

media_ready() {
  local media_bin="$1"
  [[ -x "$media_bin/ffmpeg" && -x "$media_bin/ffprobe" ]] || return 1
  "$media_bin/ffprobe" -version >/dev/null 2>&1 || return 1
  "$media_bin/ffmpeg" -hide_banner -filters 2>/dev/null | grep -q 'drawtext' || return 1
  "$media_bin/ffmpeg" -hide_banner -filters 2>/dev/null | grep -q 'subtitles'
}

MEDIA_BIN=""
if [[ -f "$RUNTIME/.seal-media-bin" ]]; then
  MEDIA_BIN="$(sed -n '1p' "$RUNTIME/.seal-media-bin")"
  if [[ "$MEDIA_BIN" != /* ]]; then MEDIA_BIN="$RUNTIME/$MEDIA_BIN"; fi
  if ! media_ready "$MEDIA_BIN"; then MEDIA_BIN=""; fi
fi
if [[ -z "$MEDIA_BIN" ]] && command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  SYSTEM_MEDIA_BIN="$(dirname "$(command -v ffmpeg)")"
  if media_ready "$SYSTEM_MEDIA_BIN"; then MEDIA_BIN="$SYSTEM_MEDIA_BIN"; fi
fi
if [[ -z "$MEDIA_BIN" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "需要带 drawtext/libass 的完整 FFmpeg；请先安装 Homebrew。" >&2
    exit 1
  fi
  if ! HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_DOWNLOAD_CONCURRENCY=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install ffmpeg-full; then
    echo "ffmpeg-full 下载失败。请确认当前网络可访问 ghcr.io 后重试本脚本；已下载的 Homebrew 缓存会被复用。" >&2
    exit 1
  fi
  MEDIA_BIN="$(brew --prefix ffmpeg-full)/bin"
  if [[ ! -x "$MEDIA_BIN/ffmpeg" ]] || ! "$MEDIA_BIN/ffmpeg" -hide_banner -filters 2>/dev/null | grep -q 'drawtext' || ! "$MEDIA_BIN/ffmpeg" -hide_banner -filters 2>/dev/null | grep -q 'subtitles'; then
    echo "ffmpeg-full 已安装，但未检测到 drawtext 与 subtitles/libass 过滤器。" >&2
    exit 1
  fi
  export PATH="$MEDIA_BIN:$PATH"
  printf '%s\n' "$MEDIA_BIN" > "$RUNTIME/.seal-media-bin"
fi
export PATH="$MEDIA_BIN:$PATH"

if ! command -v codex >/dev/null 2>&1 && [[ ! -x /Applications/ChatGPT.app/Contents/Resources/codex ]]; then
  npm install -g @openai/codex
fi
if ! command -v codex >/dev/null 2>&1 && [[ -x /Applications/ChatGPT.app/Contents/Resources/codex ]]; then
  export EASEL_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex
fi

"$PYTHON_BOOTSTRAP" -m venv "$RUNTIME/.venv"
PYTHON="$RUNTIME/.venv/bin/python"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -e "$RUNTIME[test]"
"$PYTHON" -m playwright install chromium
npm ci --ignore-scripts --prefix "$RUNTIME/tools"
node "$RUNTIME/tools/node_modules/bun/install.js"
"$PYTHON" "$ROOT/scripts/patch_redbook_runtime.py"

if [[ ! -f "$RUNTIME/web/frontend/dist/index.html" ]]; then
  npm ci --ignore-scripts --prefix "$RUNTIME/web/frontend"
  npm run build --prefix "$RUNTIME/web/frontend"
fi
"$PYTHON" "$ROOT/scripts/patch_redbook_runtime.py"
if [[ ! -f "$RUNTIME/.env" ]]; then
  if [[ -f "$RUNTIME/.env.example" ]]; then
    cp "$RUNTIME/.env.example" "$RUNTIME/.env"
  else
    : > "$RUNTIME/.env"
  fi
  chmod 600 "$RUNTIME/.env"
fi
"$PYTHON" "$ROOT/scripts/verify_install.py" --runtime
"$RUNTIME/.venv/bin/seal" doctor
echo "安装完成：$ROOT/scripts/start-macos.sh"
