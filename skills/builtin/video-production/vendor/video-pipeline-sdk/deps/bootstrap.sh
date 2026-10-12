#!/usr/bin/env bash
# 视频产线 SDK · 依赖自检与安装（Linux · Easel 内置版）
# 用法: bash deps/bootstrap.sh
# 说明: 只装渲染引擎依赖（Remotion node_modules）；转录默认走三级策略
#       （SRT → 硅基流动 API → 本地 whisper），本地 whisper 模型仅在兜底时才需下载。
set -uo pipefail

echo "=========================================="
echo " 视频产线 SDK · bootstrap (linux)"
echo "=========================================="

sdk_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
proj="$sdk_root/deps/remotion"

echo
echo "== 1. Node.js =="
if command -v node >/dev/null 2>&1; then
  node -v
  major="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
  [ "$major" -lt 20 ] && echo "!! Node 偏旧（建议 24.x；<20 Remotion 4 可能不稳）"
else
  echo "!! 缺 Node.js（建议 24.x）——装完重跑"
fi

echo
echo "== 2. ffmpeg =="
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -version 2>/dev/null | head -1
  for f in lut3d nlmeans loudnorm; do
    ffmpeg -hide_banner -filters 2>/dev/null | grep -qw "$f" || echo "!! ffmpeg 缺滤镜 $f（需 full build）"
  done
else
  echo "!! 缺 ffmpeg（需 full build，含 lut3d/nlmeans/loudnorm 等滤镜）"
fi

echo
echo "== 3. Python =="
python3 --version 2>/dev/null || echo "!! 缺 python3（需 >=3.10）"

echo
echo "== 4. Python 依赖（faster-whisper，仅本地转录兜底才需要）=="
python3 -c "import faster_whisper; print('faster-whisper OK')" 2>/dev/null \
  || echo "(可选) 缺 faster-whisper：仅 tier3 本地转录需要；pip install faster-whisper"

echo
echo "== 5. Remotion 工程依赖还原（--ignore-scripts，安全）=="
if [ -d "$proj/node_modules" ]; then
  echo "node_modules 已存在，跳过（要重装：删除后重跑）"
else
  ( cd "$proj" && npm ci --ignore-scripts --no-audit --no-fund )
  echo "npm ci exit=$?"
fi

echo
echo "== 6. Remotion 自检 =="
( cd "$proj" && npx --no-install remotion versions 2>/dev/null | head -6 ) || echo "(跳过 remotion 自检)"

echo
echo "== 完成。下一步：按 pipeline/RUNBOOK.md 走九步，或用 Easel video-production 技能 =="
