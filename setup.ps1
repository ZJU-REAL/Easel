$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$env:PYTHONUTF8 = '1'

function Info($Message) { Write-Host "[easel] $Message" -ForegroundColor Cyan }
function Ok($Message) { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Fail($Message) { Write-Error $Message; exit 1 }
function Require-Command($Name, $Hint) { if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { Fail "$Name 未找到。$Hint" } }
function Read-EnvFile($Path) {
    $values = @{}
    if (Test-Path $Path) { Get-Content $Path | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $values[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'") } } }
    return $values
}
function Read-Secret($Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    return [System.Net.NetworkCredential]::new('', $secure).Password
}
function OpenClaw-Config($Key, $Value, [switch]$Json) {
    $arguments = @('--profile','easel','config','set',$Key,$Value)
    if ($Json) { $arguments += '--strict-json' }
    & openclaw @arguments 2>&1 | Where-Object { $_ -notmatch '^No change$' }
    if ($LASTEXITCODE -ne 0) { Fail "OpenClaw 配置失败：$Key" }
}

Write-Host "`nEasel · Windows 安装向导" -ForegroundColor Magenta
Info '检查系统环境...'
Require-Command 'git' '请安装 Git for Windows 后重试。'
Require-Command 'node' '请安装 Node.js 22.19+ 后重试。'
Require-Command 'npm' '请安装 Node.js 22.19+ 后重试。'
Require-Command 'python' '请安装 Python 3.10+ 并勾选 Add Python to PATH。'
Require-Command 'ffmpeg' '请安装 FFmpeg 并加入 PATH（推荐 winget install Gyan.FFmpeg）。'
$nodeVersion = (& node -p 'process.versions.node').Split('.')[0]
if ([int]$nodeVersion -lt 22) { Fail 'Node.js 22.19+ 是必需依赖。' }
if (-not (Test-Path $Venv)) { Info '创建 Python 虚拟环境...'; & python -m venv $Venv }
if (-not (Test-Path $Python)) { Fail 'Python venv 创建失败。' }
Ok '系统环境检查完成'

Info '安装 OpenClaw...'
if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) { & npm install -g openclaw@latest --loglevel warn }
Require-Command 'openclaw' '请确认 npm 全局 bin 已加入 PATH。'
Info '安装 Easel Python 依赖...'
& $Python -m pip install --upgrade pip --progress-bar on
& $Python -m pip install -e $Root --progress-bar on
Info '构建 Web 前端...'
$Frontend = Join-Path $Root 'web\frontend'
Push-Location $Frontend
try { & npm install; & npm run build } finally { Pop-Location }
Info '安装 Playwright Chromium...'
& $Python -m playwright install chromium

Info '准备 Easel OpenClaw profile...'
& openclaw --profile easel onboard --non-interactive --mode local --accept-risk --skip-health --skip-channels --skip-skills --skip-ui --skip-hooks --skip-search --skip-daemon 2>&1 | Where-Object { $_ -notmatch '^No change$' }
if ($LASTEXITCODE -ne 0) { & openclaw --profile easel onboard --non-interactive --mode local --accept-risk --skip-health }

Info '同步 skills 与 workspace...'
$workspace = Join-Path $HOME '.openclaw\workspace-easel'
$skills = Join-Path $workspace 'skills'
New-Item -ItemType Directory -Force -Path $skills | Out-Null
if (Test-Path (Join-Path $Root 'skills\openclaw')) { Copy-Item (Join-Path $Root 'skills\openclaw\*') $skills -Recurse -Force }
Copy-Item (Join-Path $Root 'openclaw\workspace\*.md') $workspace -Force -ErrorAction SilentlyContinue
$shared = Join-Path $workspace 'shared'
if (Test-Path $shared) { Remove-Item $shared -Recurse -Force }
if (Test-Path (Join-Path $Root 'skills\shared')) { Copy-Item (Join-Path $Root 'skills\shared') $shared -Recurse -Force }
$profilesLink = Join-Path $workspace 'easel-profiles'
if (-not (Test-Path $profilesLink)) { New-Item -ItemType Junction -Path $profilesLink -Target (Join-Path $Root 'profiles') | Out-Null }
$outputs = Join-Path $workspace 'outputs'
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'outputs') | Out-Null
if (-not (Test-Path $outputs)) { New-Item -ItemType Junction -Path $outputs -Target (Join-Path $Root 'outputs') | Out-Null }

$envPath = Join-Path $Root '.env'
if (-not (Test-Path $envPath)) { Copy-Item (Join-Path $Root '.env.example') $envPath }
$envValues = Read-EnvFile $envPath
function Is-UsableKey($Value) { return -not [string]::IsNullOrWhiteSpace($Value) -and $Value -notmatch 'REPLACE_ME|your[-_ ]?api[-_ ]?key' }
if (-not (Is-UsableKey $envValues['ANTHROPIC_API_KEY']) -and -not (Is-UsableKey $envValues['OPENAI_API_KEY'])) {
    $choice = Read-Host '模型服务：1 Anthropic / 2 OpenAI-compatible / 0 稍后配置 [1]'
    if ($choice -eq '2') { $key = Read-Secret 'OpenAI API Key（不会回显）'; $url = Read-Host 'Base URL [https://api.openai.com/v1]'; $model = Read-Host '模型 [gpt-4o]'; Add-Content $envPath "`nOPENAI_API_KEY=$key`nOPENAI_BASE_URL=$url`nOPENAI_MODEL=$model" }
    elseif ($choice -eq '1' -or [string]::IsNullOrWhiteSpace($choice)) { $key = Read-Secret 'Anthropic API Key（不会回显）'; $model = Read-Host '模型 [anthropic/claude-sonnet-4-6]'; Add-Content $envPath "`nANTHROPIC_API_KEY=$key`nCLAUDE_MODEL=$model" }
}
$envValues = Read-EnvFile $envPath
if (Is-UsableKey $envValues['OPENAI_API_KEY']) {
    $model = if ($envValues.ContainsKey('OPENAI_MODEL')) { $envValues['OPENAI_MODEL'] } else { 'gpt-4o' }
    OpenClaw-Config 'models.providers.openai.api' 'openai-completions'; OpenClaw-Config 'models.providers.openai.apiKey' $envValues['OPENAI_API_KEY']; OpenClaw-Config 'models.providers.openai.baseUrl' $(if ($envValues.ContainsKey('OPENAI_BASE_URL')) { $envValues['OPENAI_BASE_URL'] } else { 'https://api.openai.com/v1' }); OpenClaw-Config 'models.providers.openai.models' "[{\"id\":\"$model\",\"name\":\"OpenAI model\",\"reasoning\":true,\"input\":[\"text\",\"image\"]}]" -Json; OpenClaw-Config 'agents.defaults.model.primary' "openai/$model"
} elseif (Is-UsableKey $envValues['ANTHROPIC_API_KEY']) { OpenClaw-Config 'models.providers.anthropic.apiKey' $envValues['ANTHROPIC_API_KEY']; OpenClaw-Config 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' }) }
OpenClaw-Config 'agents.defaults.timeoutSeconds' '7200'; OpenClaw-Config 'gateway.mode' 'local'; OpenClaw-Config 'gateway.bind' 'loopback'; OpenClaw-Config 'gateway.auth.mode' 'none'
& $Python -m playwright install chromium
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\gateway.ps1') start
Ok 'Easel Windows 安装完成'
Write-Host "启动 Web：$Venv\Scripts\easel.exe web" -ForegroundColor Cyan
Write-Host "检查环境：$Venv\Scripts\easel.exe doctor" -ForegroundColor Cyan
