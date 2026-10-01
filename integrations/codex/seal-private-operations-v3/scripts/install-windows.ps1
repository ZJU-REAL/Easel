$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root 'runtime'

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Ensure-WingetPackage([string]$Command, [string]$PackageId) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "缺少 $Command，且系统没有 winget。请手动安装 $PackageId 后重试。"
    }
    & winget install --id $PackageId --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "安装 $PackageId 失败。" }
    Refresh-Path
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$PackageId 已安装但当前终端仍找不到 $Command，请重新打开 PowerShell 后重试。"
    }
}

function Test-PythonExe([string]$Candidate) {
    if (-not $Candidate) { return $false }
    try {
        & $Candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Resolve-PythonExe {
    $candidates = @(
        (Join-Path $env:LocalAppData 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe')
    )
    foreach ($name in @('python', 'python3')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ((Test-Path $candidate) -and (Test-PythonExe $candidate)) { return $candidate }
    }
    return $null
}

$PythonBootstrap = Resolve-PythonExe
if (-not $PythonBootstrap) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw '需要 Python 3.10 或更高版本，且系统没有 winget。请手动安装 Python 3.12 后重试。'
    }
    & winget install --id 'Python.Python.3.12' --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 安装失败。' }
    Refresh-Path
    $PythonBootstrap = Resolve-PythonExe
}
if (-not $PythonBootstrap) { throw 'Python 3.12 已安装，但当前 PowerShell 无法定位 python.exe。请重新打开 PowerShell 后重试。' }

Ensure-WingetPackage 'node' 'OpenJS.NodeJS.LTS'
Ensure-WingetPackage 'npm' 'OpenJS.NodeJS.LTS'

$nodeMajor = [int]((& node -p 'process.versions.node.split(".")[0]').Trim())
if ($nodeMajor -lt 22) {
    & winget upgrade --id 'OpenJS.NodeJS.LTS' --exact --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $nodeMajor = [int]((& node -p 'process.versions.node.split(".")[0]').Trim())
    if ($nodeMajor -lt 22) { throw "Node.js 必须为 22 或更高版本，当前为 $(& node --version)。" }
}

function Test-FfmpegFull([string]$Candidate) {
    if (-not (Test-Path $Candidate)) { return $false }
    try {
        $filters = (& $Candidate -hide_banner -filters 2>&1 | Out-String)
        return ($LASTEXITCODE -eq 0 -and $filters -match 'drawtext' -and $filters -match 'subtitles')
    } catch { return $false }
}

function Resolve-FfmpegBin {
    $candidates = @()
    foreach ($command in Get-Command ffmpeg -All -ErrorAction SilentlyContinue) {
        $candidates += $command.Source
    }
    $wingetRoot = Join-Path $env:LocalAppData 'Microsoft\WinGet\Packages'
    if (Test-Path $wingetRoot) {
        $candidates += Get-ChildItem $wingetRoot -Filter 'ffmpeg.exe' -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object FullName
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-FfmpegFull $candidate) {
            $bin = Split-Path -Parent $candidate
            if (Test-Path (Join-Path $bin 'ffprobe.exe')) { return $bin }
        }
    }
    return $null
}

$MediaBin = Resolve-FfmpegBin
if (-not $MediaBin) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw '需要包含 drawtext、subtitles/libass 与 FFprobe 的完整 FFmpeg，且系统没有 winget。'
    }
    & winget install --id 'Gyan.FFmpeg' --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Gyan.FFmpeg full build 安装失败。' }
    Refresh-Path
    $MediaBin = Resolve-FfmpegBin
}
if (-not $MediaBin) { throw '未找到同时包含 drawtext、subtitles/libass 与 FFprobe 的完整 FFmpeg。' }
$env:Path = "$MediaBin;$env:Path"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $Runtime '.seal-media-bin'), $MediaBin, $utf8NoBom)

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    & npm install -g '@openai/codex'
    if ($LASTEXITCODE -ne 0) { throw 'Codex CLI 安装失败。' }
    Refresh-Path
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw '找不到 Codex CLI。请将 codex 加入 PATH，或设置 EASEL_CODEX_BIN。'
}

& $PythonBootstrap -m venv (Join-Path $Runtime '.venv')
if ($LASTEXITCODE -ne 0) { throw '创建 V3 Python 虚拟环境失败。' }
$Python = Join-Path $Runtime '.venv\Scripts\python.exe'
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw '升级 pip 失败。' }
& $Python -m pip install -e "$Runtime[test]"
if ($LASTEXITCODE -ne 0) { throw '安装 V3 Python 依赖失败。' }
& $Python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw '安装 Playwright Chromium 失败。' }
& npm ci --ignore-scripts --prefix (Join-Path $Runtime 'tools')
if ($LASTEXITCODE -ne 0) { throw '安装 V3 Node.js 依赖失败。' }
& node (Join-Path $Runtime 'tools\node_modules\bun\install.js')
if ($LASTEXITCODE -ne 0) { throw 'V3 内置 Bun 安装失败。' }
& $Python (Join-Path $Root 'scripts\patch_redbook_runtime.py')
if ($LASTEXITCODE -ne 0) { throw '应用 Redbook 跨平台补丁失败。' }

$Frontend = Join-Path $Runtime 'web\frontend'
if (-not (Test-Path (Join-Path $Frontend 'dist\index.html'))) {
    & npm ci --ignore-scripts --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw '安装 V3 前端依赖失败。' }
    & npm run build --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw '构建 V3 前端失败。' }
}
& $Python (Join-Path $Root 'scripts\patch_redbook_runtime.py')
if ($LASTEXITCODE -ne 0) { throw '复验 Redbook 跨平台补丁失败。' }
$EnvFile = Join-Path $Runtime '.env'
if (-not (Test-Path $EnvFile)) {
    $EnvTemplate = Join-Path $Runtime '.env.example'
    if (Test-Path $EnvTemplate) {
        Copy-Item $EnvTemplate $EnvFile
    }
    else {
        [System.IO.File]::WriteAllText($EnvFile, '', $utf8NoBom)
    }
}
& $Python (Join-Path $Root 'scripts\verify_install.py') --runtime
if ($LASTEXITCODE -ne 0) { throw 'Seal V3 完整性校验失败。' }
& (Join-Path $Runtime '.venv\Scripts\seal.exe') doctor
if ($LASTEXITCODE -ne 0) { throw 'Seal V3 运行环境检查失败。' }
Write-Host "安装完成：powershell -ExecutionPolicy Bypass -File `"$Root\scripts\start-windows.ps1`""
