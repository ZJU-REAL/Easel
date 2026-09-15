$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root 'runtime\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw 'Seal V3 尚未安装，请先运行 scripts\install-windows.ps1'
}
& $Python (Join-Path $Root 'launch.py') @args
exit $LASTEXITCODE
