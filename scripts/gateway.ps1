$ErrorActionPreference = 'Stop'
# 不要用 $Profile：它是 PowerShell 的自动变量（当前用户的配置脚本路径），
# 覆写它会遮蔽自动变量，PSScriptAnalyzer 也会直接报警。
$ProfileName = 'easel'
$Root = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $env:TEMP 'easel-gateway.log'
$ErrorLogFile = Join-Path $env:TEMP 'easel-gateway.error.log'
$ConfigDir = Join-Path $HOME ".openclaw-$ProfileName"

# 对原生命令做 stderr 重定向必须先把 ErrorActionPreference 降到 Continue：
# 本文件顶部是 'Stop'，而 PS 5.1 在 Stop 下会把原生命令 stderr 的每一行包成
# ErrorRecord 抛出 NativeCommandError —— 脚本级终止，轮不到读 $LASTEXITCODE。
function Invoke-NativeCapturePS([string]$Exe, [string[]]$Arguments) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = (& $Exe @Arguments 2>&1 | Out-String)
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ Ok = ($code -eq 0); Output = $out; Code = $code }
}

# ---- gateway 端口：问 Easel 的解析器，不要在这里再抄一份 ----------------------
# 这里曾经用 PowerShell 重新实现过一遍 OpenClaw 的 resolveGatewayPort（FNV-1a 哈希、
# 配置文件读取、环境变量优先级）。那样一来同一个端口就有三份独立实现：这里、
# easel/gateway_endpoint.py、以及 OpenClaw 自己。三份只要有一份跟不上版本变化就错配，
# 而下面的 start 带 --force —— 错配的后果不是探不通，而是**杀掉占用那个端口的别人家
# gateway**（Linux 侧实测发生过：老版 OpenClaw 不认 profile 哈希端口、照旧绑 18789，
# --force 就把默认 profile 的健康进程干掉了）。单一真相源在 Python 那边，这里只负责问。
function Get-EaselPython {
    # 优先用项目内 venv：gateway.ps1 可能被 easel CLI 以外的方式调起，此时 PATH 上
    # 未必有正确的 python。回退链与 openclaw/sync.sh 一致。
    $venv = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return @($venv, @()) }
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($py) { return @($py, @()) }
    $pyLauncher = (Get-Command py -ErrorAction SilentlyContinue).Source
    if ($pyLauncher) { return @($pyLauncher, @('-3')) }
    return @($null, @())
}

$pyExe, $pyPre = Get-EaselPython
if (-not $pyExe) {
    Write-Error '[easel] 找不到 Python，无法解析 gateway 端口；请先运行 setup.ps1。'
    exit 1
}
# PS 5.1 按 [Console]::OutputEncoding 解码原生命令 stdout（中文系统是 OEM 936），
# 而 Python 输出 UTF-8；这里只取一个数字，仍统一设好编码以免将来扩展时踩坑。
$prevEnc = [Console]::OutputEncoding
$prevPyPath = $env:PYTHONPATH
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $env:PYTHONPATH = $Root
    $probe = Invoke-NativeCapturePS $pyExe ($pyPre + @('-c',
        'from easel.gateway_endpoint import resolve_gateway_port as p; print(p())'))
} finally {
    [Console]::OutputEncoding = $prevEnc
    $env:PYTHONPATH = $prevPyPath
}
$Port = 0
if ($probe.Ok) { [void][int]::TryParse(($probe.Output -split "`n" | Where-Object { $_ } | Select-Object -Last 1).Trim(), [ref]$Port) }
# 解析不出来就明着失败，而不是退到一个猜的端口 —— 「悄悄探错端口」正是要根治的病。
if ($Port -le 0) {
    Write-Error "[easel] 无法解析 gateway 端口（需要能 import easel）。手动查：`n" +
                "        `$env:PYTHONPATH='$Root'; $pyExe -c ""from easel.gateway_endpoint import describe; print(describe())"""
    exit 1
}
# 把解析结果**无条件**钉给 OpenClaw：gateway 进程只认 OPENCLAW_GATEWAY_PORT。
# 以前只在 EASEL_GATEWAY_PORT 显式设置时才透传，于是平时探测端口与实际绑定端口是
# 两份独立推导。无条件透传后两边同源，--force 最多只会动我们自己这个端口。
$env:OPENCLAW_GATEWAY_PORT = "$Port"

function Test-Gateway {
    try { Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

function Get-GatewayProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
        Where-Object { $_.CommandLine -match "openclaw.*--profile\s+$ProfileName.*gateway" } |
        Select-Object -First 1
}

function Stop-Gateway {
    $process = Get-GatewayProcess
    if ($process) { Stop-Process -Id $process.ProcessId -Force; Write-Host '[easel] Gateway stopped' }
    else { Write-Host '[easel] Gateway was not running' }
}

switch ($args[0]) {
    'start' {
        if (Test-Gateway) { Write-Host '[easel] Gateway already running'; break }
        New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
        Write-Host "[easel] Starting Easel gateway (profile: $ProfileName, port: $Port)..."
        $command = "openclaw --profile $ProfileName gateway run --force --allow-unconfigured --bind loopback"
        Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command', $command `
            -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $ErrorLogFile -WindowStyle Hidden | Out-Null
        $ready = $false
        1..20 | ForEach-Object {
            if (-not $ready) {
                if (Test-Gateway) { $ready = $true }
                else { Start-Sleep -Seconds 1 }
            }
        }
        if ($ready) { Write-Host '[easel] Gateway started' }
        else { Write-Error "Gateway 启动失败；请检查 $LogFile 和 $ErrorLogFile"; exit 1 }
    }
    'stop' { Stop-Gateway }
    'restart' { Stop-Gateway; Start-Sleep -Seconds 2; & $PSCommandPath start }
    'status' {
        if (Test-Gateway) { Write-Host "[easel] Gateway running (profile: $ProfileName, port: $Port)" }
        else { Write-Host "[easel] Gateway not running (profile: $ProfileName, port: $Port)" }
    }
    'logs' { Get-Content $LogFile -Wait }
    default { Write-Host 'Usage: gateway.ps1 {start|stop|restart|status|logs}'; exit 1 }
}
