# 视频产线 SDK · 依赖自检与安装（Windows）
# 用法: powershell -ExecutionPolicy Bypass -File deps/bootstrap.ps1
$ErrorActionPreference = "Continue"
Write-Output "=========================================="
Write-Output " 视频产线 SDK · bootstrap"
Write-Output "=========================================="

Write-Output "`n== 1. Node.js =="
node -v 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output "!! 缺 Node.js（建议 24 LTS）——装完重跑本脚本" }

Write-Output "`n== 2. ffmpeg =="
$ff = (ffmpeg -version 2>$null | Select-Object -First 1)
Write-Output $ff
if (-not $ff) { Write-Output "!! 缺 ffmpeg（需 full build，含 lut3d/nlmeans 等滤镜）" }

Write-Output "`n== 3. Python =="
python --version 2>$null

Write-Output "`n== 4. Python 依赖（faster-whisper）=="
python -c "import faster_whisper; print('faster-whisper OK')" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output "!! 缺 faster-whisper：pip install faster-whisper" }

Write-Output "`n== 5. rm（Remotion）工程依赖还原 =="
$sdkRoot = Split-Path -Parent $PSScriptRoot
$proj = Join-Path $sdkRoot "deps\remotion"
if (Test-Path (Join-Path $proj "node_modules")) {
  Write-Output "node_modules 已存在，跳过（要重装：删除后重跑）"
} else {
  Set-Location $proj
  npm ci --registry=https://registry.npmmirror.com
  Write-Output "npm ci exit=$LASTEXITCODE"
}

Write-Output "`n== 6. Remotion 自检 =="
Set-Location $proj
npx remotion versions 2>$null | Select-Object -First 6

Write-Output "`n== 完成。下一步：按 pipeline/RUNBOOK.md 走九步 =="
