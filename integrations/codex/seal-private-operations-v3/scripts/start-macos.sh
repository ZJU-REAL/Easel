#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/runtime/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Seal V3 尚未安装，请先运行 scripts/install-macos.sh" >&2
  exit 1
fi
if [[ -f "$ROOT/runtime/.seal-media-bin" ]]; then
  MEDIA_BIN="$(sed -n '1p' "$ROOT/runtime/.seal-media-bin")"
  if [[ "$MEDIA_BIN" != /* ]]; then
    MEDIA_BIN="$ROOT/runtime/$MEDIA_BIN"
  fi
  export PATH="$MEDIA_BIN:$PATH"
fi
exec "$PYTHON" "$ROOT/launch.py" "$@"
