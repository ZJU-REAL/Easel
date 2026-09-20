# 视频产线 SDK · 自检（非渲染级八件门全数演练：正例过、反例被逮）
# 用法: powershell -ExecutionPolicy Bypass -File gates/selftest.ps1
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$sdk = Split-Path -Parent $PSScriptRoot
Set-Location $sdk
$f = "gates\fixtures"
Write-Output "=========================================="
Write-Output " SDK 自检 @ $sdk"
Write-Output "=========================================="

Write-Output "`n== 门⑥ 排版（正例 → 期望 0）=="
python gates/check_layout.py --elements "$f/layout_ok.json"
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门⑥ 排版（反例 → 期望 1）=="
python gates/check_layout.py --elements "$f/layout_bad.json"
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门③ 查重（正例 → 期望 0）=="
python gates/check_dup.py --scenes "$f/scenes_clean.json" --ref "$f/ref.json" --table "$env:TEMP\sdk_table.md"
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门③ 查重（反例 → 期望 1）=="
python gates/check_dup.py --scenes "$f/scenes_bad.json"
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门⑧ 时间轴（正例 → 期望 0）=="
python gates/check_timeline.py --scenes "$f/timeline_ok.json"
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门⑧ 时间轴（反例 → 期望 1）=="
python gates/check_timeline.py --scenes "$f/timeline_bad.json"
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门⑤ 五件套（自包含夹具 → 期望 0）=="
python gates/check_meta.py --project "$f/proj.json" --root $sdk
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门④ 对位（需本机示例素材目录；无则跳过）=="
if ($env:REMOTION_PROJECT -and (Test-Path "$env:REMOTION_PROJECT\public\stock")) {
  python gates/check_match.py --scenes "$f/match.json" --clipsdir "$env:REMOTION_PROJECT\public\stock" --out "$env:TEMP\sdk_match.md"
  Write-Output "  exit=$LASTEXITCODE"
} else {
  Write-Output "  skip（未设 REMOTION_PROJECT 或无 public/stock）"
}

Write-Output "`n== 门⑦ 音频响度（合成测试音 → 期望 0）=="
$tone = "$env:TEMP\sdk_tone.wav"
ffmpeg -y -v error -f lavfi -i "aevalsrc=0.9*sin(440*2*PI*t):d=1" $tone
python gates/check_audio.py $tone
Write-Output "  exit=$LASTEXITCODE"

Write-Output "`n== 门①/② 为渲染级（需 Remotion 工程），见 pipeline/RUNBOOK.md Step 7 =="
Write-Output "== 自检结束 =="
