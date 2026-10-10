[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingInvokeExpression', '',
    Justification = '测试探针需要按内容锚点把 setup.ps1 的容忍层切出来求值，这正是被测对象')]
param()

# CI 用：在真实的 Windows PowerShell 5.1 / pwsh 7 上验证 setup.ps1 的容忍层。
#
# 关键被测行为：openclaw 向 stderr 报错并退出 1 时，脚本必须存活并记一条警告。
# 这一条在 Linux 上验证不了 —— pwsh 7 不复现 5.1 把原生命令 stderr 包成 ErrorRecord
# 抛 NativeCommandError 的行为（实测把 ErrorActionPreference=Continue 去掉，pwsh 7
# 上照样通过）。所以 CI 的 windows-latest + shell: powershell 才是这条的真正把关点。
# 脚本本身写成跨平台的，便于在 Linux 上先用 pwsh 7 自检一遍探针逻辑。
$ErrorActionPreference = 'Stop'
function Fail($m) { Write-Host "FAIL: $m" -ForegroundColor Red; exit 1 }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }

$repo = Split-Path -Parent $PSScriptRoot
$src = Get-Content (Join-Path $repo 'setup.ps1') -Raw -Encoding UTF8
$i = $src.IndexOf('# ---- 失败收集')
$j = $src.IndexOf('# JSON 值的配置写入')
if ($i -lt 0 -or $j -lt 0) { Fail "切片锚点没找到（setup.ps1 结构变了？i=$i j=$j）" }
Invoke-Expression $src.Substring($i, $j - $i)

# 假 openclaw：对 $env:REJECT_KEY 指定的 key 退出 1 并**往 stderr 写**
$fakeDir = Join-Path ([System.IO.Path]::GetTempPath()) "easel-fake-oc-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $fakeDir | Out-Null
$isWin = ($env:OS -eq 'Windows_NT')
if ($isWin) {
    @'
@echo off
echo %* | findstr /C:"config set --help" >nul && (echo   --batch-file& echo   --replace& exit /b 0)
echo %* | findstr /C:"config --help" >nul && (echo   validate& exit /b 0)
if not "%REJECT_KEY%"=="" (
  echo %* | findstr /C:"%REJECT_KEY%" >nul && (
    echo Error: Config validation failed: %REJECT_KEY%: Unrecognized key 1>&2
    exit /b 1
  )
)
echo No change
exit /b 0
'@ | Set-Content (Join-Path $fakeDir 'openclaw.cmd') -Encoding ASCII
} else {
    $sh = Join-Path $fakeDir 'openclaw'
    @'
#!/usr/bin/env bash
args="$*"
case "$args" in
  *"config set --help"*) echo "  --batch-file"; echo "  --replace"; exit 0 ;;
  *"config --help"*)     echo "  validate"; exit 0 ;;
esac
if [ -n "${REJECT_KEY:-}" ]; then
  for a in "$@"; do
    if [ "$a" = "$REJECT_KEY" ]; then
      echo "Error: Config validation failed: $REJECT_KEY: Unrecognized key" >&2
      exit 1
    fi
  done
fi
echo "No change"
'@ -replace "`r`n", "`n" | Set-Content $sh -NoNewline
    & chmod +x $sh
}
$env:PATH = $fakeDir + [System.IO.Path]::PathSeparator + $env:PATH

$env:REJECT_KEY = 'gateway.mode'
Set-OpenClawConfig 'gateway.mode' 'local' -Label 'gateway 基本配置'
if ($script:Warnings.Count -ne 1) { Fail "期望记录 1 条警告，实际 $($script:Warnings.Count)" }
Ok "stderr + 非零退出未中断脚本"

$env:REJECT_KEY = 'memory.search.enabled'
Set-OpenClawFirst '关闭向量记忆' 'false' -Json -Keys @('memory.search.enabled','agents.defaults.memorySearch.enabled')
if ($script:Warnings.Count -ne 1) { Fail "退回第二套 schema 不该记警告，实际 $($script:Warnings.Count)" }
Ok "Set-OpenClawFirst 正确退到第二套 schema"

Remove-Item Env:REJECT_KEY -ErrorAction SilentlyContinue
if (-not (Test-OpenClawSupport @('config','set') '--replace')) { Fail '能力探测应当识别出 --replace' }
if (Test-OpenClawSupport @('config','set') '--nonexistent') { Fail '能力探测不该误报不存在的标志' }
Ok '能力探测正常'

Remove-Item $fakeDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "ALL PASS on PowerShell $($PSVersionTable.PSVersion)" -ForegroundColor Green
