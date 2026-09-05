$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$env:PYTHONUTF8 = '1'

function Info($Message) { Write-Host "[easel] $Message" -ForegroundColor Cyan }
function Ok($Message) { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Fail($Message) { Write-Error $Message; exit 1 }
function Require-Command($Name, $Hint) { if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { Fail "$Name 未找到。$Hint" } }
function Ensure-Command($Name, $PackageId, $Hint) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Fail "$Name 未找到。$Hint`n也可以先安装 Windows App Installer（winget）后重试。" }
    Info "未找到 $Name，使用 winget 安装 $PackageId..."
    & winget install --id $PackageId --exact --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Fail "$Name 自动安装失败。$Hint" }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    Require-Command $Name $Hint
}
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
Ensure-Command 'git' 'Git.Git' '请安装 Git for Windows 并加入 PATH。'
Ensure-Command 'node' 'OpenJS.NodeJS.LTS' '请安装 Node.js 22.19+ 并加入 PATH。'
Ensure-Command 'npm' 'OpenJS.NodeJS.LTS' '请安装 Node.js 22.19+ 并加入 PATH。'
Ensure-Command 'python' 'Python.Python.3.12' '请安装 Python 3.10+ 并勾选 Add Python to PATH。'
Ensure-Command 'ffmpeg' 'Gyan.FFmpeg' '请安装 FFmpeg 并加入 PATH。'
$nodeParts = (& node -p 'process.versions.node').Split('.') | ForEach-Object { [int]$_ }
if ($nodeParts[0] -lt 22 -or ($nodeParts[0] -eq 22 -and $nodeParts[1] -lt 19)) { Fail 'Node.js 22.19+ 是必需依赖。' }
if (-not (Test-Path $Venv)) { Info '创建 Python 虚拟环境...'; & python -m venv $Venv }
if (-not (Test-Path $Python)) { Fail 'Python venv 创建失败。' }
Ok '系统环境检查完成'

Info '安装 OpenClaw...'
if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) { & npm install -g openclaw@latest --loglevel warn; if ($LASTEXITCODE -ne 0) { Fail 'OpenClaw 安装失败。' } }
Require-Command 'openclaw' '请确认 npm 全局 bin 已加入 PATH。'
Info '安装 Easel Python 依赖...'
& $Python -m pip install --upgrade pip --progress-bar on
if ($LASTEXITCODE -ne 0) { Fail 'pip 升级失败。' }
& $Python -m pip install -e $Root --progress-bar on
if ($LASTEXITCODE -ne 0) { Fail 'Easel Python 依赖安装失败。' }
Info '构建 Web 前端...'
$Frontend = Join-Path $Root 'web\frontend'
Push-Location $Frontend
try {
    & npm install
    if ($LASTEXITCODE -ne 0) { Fail 'Web 前端依赖安装失败。' }
    & npm run build
    if ($LASTEXITCODE -ne 0) { Fail 'Web 前端构建失败。' }
} finally { Pop-Location }
Info '安装 Playwright Chromium...'
& $Python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Fail 'Playwright Chromium 安装失败。' }

Info '准备 Easel OpenClaw profile...'
$onboardHelp = (& openclaw onboard --help 2>&1 | Out-String)
$onboardArgs = @('--profile','easel','onboard','--non-interactive','--mode','local','--accept-risk')
foreach ($flag in @('--skip-health','--skip-channels','--skip-skills','--skip-ui','--skip-hooks','--skip-search','--skip-daemon')) {
    if ($onboardHelp -match [regex]::Escape($flag)) { $onboardArgs += $flag }
}
if ($onboardHelp -match '--no-install-daemon' -and $onboardHelp -notmatch '--skip-daemon') { $onboardArgs += '--no-install-daemon' }
& openclaw @onboardArgs 2>&1 | Where-Object { $_ -notmatch '^No change$' }
if ($LASTEXITCODE -ne 0) { Fail 'OpenClaw profile 初始化失败，请检查上方输出。' }

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
if (-not (Is-UsableKey $envValues['ANTHROPIC_API_KEY']) -and -not (Is-UsableKey $envValues['OPENAI_API_KEY']) -and -not (Is-UsableKey $envValues['ANTHROPIC_AUTH_TOKEN']) -and -not (Is-UsableKey $envValues['EASEL_LLM_API_KEY']) -and -not (Is-UsableKey $envValues['OPENAI_MAAS_API_KEY'])) {
    $choice = Read-Host '模型服务：1 Anthropic / 2 OpenAI-compatible / 0 稍后配置 [1]'
    if ($choice -eq '2') { $key = Read-Secret 'OpenAI API Key（不会回显）'; $url = Read-Host 'Base URL [https://api.openai.com/v1]'; $model = Read-Host '模型 [gpt-4o]'; Add-Content $envPath "`nOPENAI_API_KEY=$key`nOPENAI_BASE_URL=$url`nOPENAI_MODEL=$model" }
    elseif ($choice -eq '1' -or [string]::IsNullOrWhiteSpace($choice)) { $key = Read-Secret 'Anthropic API Key（不会回显）'; $model = Read-Host '模型 [anthropic/claude-sonnet-4-6]'; Add-Content $envPath "`nANTHROPIC_API_KEY=$key`nCLAUDE_MODEL=$model" }
}
$envValues = Read-EnvFile $envPath
if (Is-UsableKey $envValues['OPENAI_MAAS_API_KEY'] -and $envValues.ContainsKey('OPENAI_MAAS_ENDPOINT')) {
    $model = if ($envValues.ContainsKey('OPENAI_MAAS_MODEL')) { $envValues['OPENAI_MAAS_MODEL'] } else { 'gpt-5.5' }
    $port = if ($envValues.ContainsKey('OPENAI_MAAS_ADAPTER_PORT')) { $envValues['OPENAI_MAAS_ADAPTER_PORT'] } else { '18791' }
    $adapter = Join-Path $Root 'scripts\openai_maas_adapter.py'
    $provider = @{ baseUrl = "http://127.0.0.1:$port/v1"; api = 'openai-completions'; apiKey = 'local-adapter'; timeoutSeconds = 600; request = @{ allowPrivateNetwork = $true }; models = @(@{ id = $model; name = 'OpenAI-compatible model'; reasoning = $true; input = @('text') }); localService = @{ command = $Python; args = @($adapter, '--port', $port); cwd = $Root; healthUrl = "http://127.0.0.1:$port/health"; idleStopMs = 0; env = @{ OPENAI_MAAS_API_KEY = $envValues['OPENAI_MAAS_API_KEY']; OPENAI_MAAS_ENDPOINT = $envValues['OPENAI_MAAS_ENDPOINT']; OPENAI_MAAS_MODEL = $model; OPENAI_MAAS_API_KEY_HEADER = if ($envValues.ContainsKey('OPENAI_MAAS_API_KEY_HEADER')) { $envValues['OPENAI_MAAS_API_KEY_HEADER'] } else { 'Authorization' } } } }
    OpenClaw-Config 'models.providers.rednote-openai' ($provider | ConvertTo-Json -Compress -Depth 10) -Json
    OpenClaw-Config 'agents.defaults.model.primary' "rednote-openai/$model"
} elseif (Is-UsableKey $envValues['OPENAI_API_KEY']) {
    $model = if ($envValues.ContainsKey('OPENAI_MODEL')) { $envValues['OPENAI_MODEL'] } else { 'gpt-4o' }
    OpenClaw-Config 'models.providers.openai.api' 'openai-completions'; OpenClaw-Config 'models.providers.openai.apiKey' $envValues['OPENAI_API_KEY']; OpenClaw-Config 'models.providers.openai.baseUrl' $(if ($envValues.ContainsKey('OPENAI_BASE_URL')) { $envValues['OPENAI_BASE_URL'] } else { 'https://api.openai.com/v1' }); OpenClaw-Config 'models.providers.openai.models' "[{\"id\":\"$model\",\"name\":\"OpenAI model\",\"reasoning\":true,\"input\":[\"text\",\"image\"]}]" -Json; OpenClaw-Config 'agents.defaults.model.primary' "openai/$model"
} elseif (Is-UsableKey $envValues['EASEL_LLM_API_KEY'] -and $envValues.ContainsKey('EASEL_LLM_BASE_URL')) {
    OpenClaw-Config 'models.providers.anthropic.apiKey' $envValues['EASEL_LLM_API_KEY']; OpenClaw-Config 'models.providers.anthropic.baseUrl' $envValues['EASEL_LLM_BASE_URL']; OpenClaw-Config 'models.providers.anthropic.headers.api-key' $envValues['EASEL_LLM_API_KEY']; OpenClaw-Config 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' })
} elseif (Is-UsableKey $envValues['ANTHROPIC_AUTH_TOKEN'] -and $envValues.ContainsKey('ANTHROPIC_BASE_URL')) {
    OpenClaw-Config 'models.providers.anthropic.apiKey' $envValues['ANTHROPIC_AUTH_TOKEN']; OpenClaw-Config 'models.providers.anthropic.baseUrl' $envValues['ANTHROPIC_BASE_URL']; OpenClaw-Config 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' })
} elseif (Is-UsableKey $envValues['ANTHROPIC_API_KEY']) { OpenClaw-Config 'models.providers.anthropic.apiKey' $envValues['ANTHROPIC_API_KEY']; OpenClaw-Config 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' }) }
OpenClaw-Config 'agents.defaults.timeoutSeconds' '7200'; OpenClaw-Config 'gateway.mode' 'local'; OpenClaw-Config 'gateway.bind' 'loopback'; OpenClaw-Config 'gateway.auth.mode' 'none'
& openclaw --profile easel config validate
if ($LASTEXITCODE -ne 0) { Fail 'OpenClaw 配置校验失败。' }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\gateway.ps1') start
if ($LASTEXITCODE -ne 0) { Fail 'Easel Gateway 启动失败。' }
Ok 'Easel Windows 安装完成'
Write-Host "启动 Web：$Venv\Scripts\easel.exe web" -ForegroundColor Cyan
Write-Host "检查环境：$Venv\Scripts\easel.exe doctor" -ForegroundColor Cyan
