# Easel Web 启动器（本地回环）
# 用法：右键“使用 PowerShell 运行”，或 powershell -ExecutionPolicy Bypass -File run-easel.ps1
# 停止：关闭该窗口，或 Stop-Process -Id (Get-NetTCPConnection -LocalPort 7860).OwningProcess
param(
    [int]$Port = 7860
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:EASEL_WEB_HOST = '127.0.0.1'
$env:EASEL_AGENT_RUNTIME = 'acp'
$env:PYTHONUTF8 = '1'
Write-Host "[easel] http://127.0.0.1:$Port  (loopback only)" -ForegroundColor Cyan
& (Join-Path $Root '.venv\Scripts\easel.exe') web --port $Port
