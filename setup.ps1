# 注意：本文件为 UTF-8 with BOM。Windows PowerShell 5.1 需 BOM 才能正确解析中文字符串（否则报「语法错误」）；请勿移除。
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$env:PYTHONUTF8 = '1'

function Info($Message) { Write-Host "[easel] $Message" -ForegroundColor Cyan }
function Ok($Message) { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Warn($Message) { Write-Host "  [!] $Message" -ForegroundColor Yellow }
# 用 [OK] / [!] 这种 ASCII 标记而不是 ✓ / ⚠：cmd.exe 与较老的终端代码页并不可靠地
# 支持 UTF-8，而本文件原有的 Ok() 已经是 [OK] 风格，不引入第二套符号。
function Step($Index, $Title, $Subtitle) {
    Write-Host ''
    Write-Host ('-' * 52) -ForegroundColor DarkBlue
    Write-Host "  [$Index] " -NoNewline -ForegroundColor Magenta
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "  $Subtitle" -ForegroundColor DarkGray
}

# 长耗时步骤转圈。注意三点：
#   1. 用 Start-Process -PassThru 轮询 HasExited，不要用 Start-Job —— job 跑在全新
#      runspace 里，拿不到 $Root / $Python / Install-RequiredCommand 改过的 PATH。
#   2. 非 TTY（CI、重定向）下不要转圈：1Hz 的 `r 会刷出几千行无用日志。
#   3. 失败时把日志尾部打出来，否则用户只看到一个 [FAIL] 不知道发生了什么。
function Invoke-WithProgress([string]$Label, [string]$Exe, [string[]]$Arguments, [string]$WorkDir = $null) {
    $log = Join-Path ([System.IO.Path]::GetTempPath()) "easel-install-$(Get-Random).log"
    $startArgs = @{ FilePath = $Exe; ArgumentList = $Arguments; PassThru = $true;
                    NoNewWindow = $true; RedirectStandardOutput = $log;
                    RedirectStandardError = "$log.err" }
    if ($WorkDir) { $startArgs['WorkingDirectory'] = $WorkDir }
    $proc = Start-Process @startArgs
    $quiet = [Console]::IsOutputRedirected
    if ($quiet) { Write-Host "  [....] $Label 开始（非交互终端，不显示进度）" }
    $frames = @('[>   ]', '[=>  ]', '[==> ]', '[===>]')
    $t0 = Get-Date
    $i = 0
    while (-not $proc.HasExited) {
        if (-not $quiet) {
            $el = [int]((Get-Date) - $t0).TotalSeconds
            Write-Host ("`r  {0} 进行中 {1} 已运行 {2}s" -f $frames[$i % 4], $Label, $el) -NoNewline
            $i++
        }
        Start-Sleep -Seconds 1
    }
    if (-not $quiet) { Write-Host "`r$(' ' * 60)`r" -NoNewline }
    if ($proc.ExitCode -eq 0) {
        Ok "$Label 完成"
        Remove-Item $log, "$log.err" -Force -ErrorAction SilentlyContinue
        return $true
    }
    Write-Host "  [FAIL] $Label 失败" -ForegroundColor Red
    foreach ($f in @($log, "$log.err")) {
        if (Test-Path $f) { Get-Content $f -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ } }
    }
    Remove-Item $log, "$log.err" -Force -ErrorAction SilentlyContinue
    return $false
}

# 结尾汇总。变宽内容不套框线：中文是双宽字符，按字符数 padding 的 ASCII 框一定错位。
function Show-Summary {
    $n = $script:Warnings.Count
    Write-Host ''
    if ($n -eq 0) { Write-Host '  [OK] Easel 安装完成' -ForegroundColor Green }
    else { Write-Host "  [OK] Easel 安装完成（有 $n 项降级）" -ForegroundColor Yellow }
    if ($n -gt 0) {
        Write-Host ''
        Write-Host "  需要处理（$n）：" -ForegroundColor Yellow
        foreach ($sev in @('high', 'low')) {
            foreach ($w in $script:Warnings) {
                if ($w.Severity -ne $sev) { continue }
                Write-Host "   [!] $($w.Label) - $($w.Detail)" -ForegroundColor Yellow
                if ($w.Fix) { Write-Host "       -> $($w.Fix)" -ForegroundColor DarkGray }
            }
        }
        Write-Host ''
        Write-Host '  以上均不影响已装好的部分；逐项修完可用 easel doctor 复检。' -ForegroundColor DarkGray
        Write-Host '  若希望这些问题直接让安装失败（CI/自动化场景）：$env:EASEL_SETUP_STRICT=1' -ForegroundColor DarkGray
    }
}

# 致命退出前也要把汇总打出来：第 8 步挂掉时，用户仍然需要知道第 4~7 步降级了什么。
function Fail($Message) {
    if ($script:Warnings) { Show-Summary }
    Write-Host ''
    Write-Host "  [X] 安装中止：$Message" -ForegroundColor Red
    exit 1
}
function Assert-Command($Name, $Hint) { if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { Fail "$Name 未找到。$Hint" } }
function Install-RequiredCommand($Name, $PackageId, $Hint) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Fail "$Name 未找到。$Hint`n也可以先安装 Windows App Installer（winget）后重试。" }
    Info "未找到 $Name，使用 winget 安装 $PackageId..."
    & winget install --id $PackageId --exact --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Fail "$Name 自动安装失败。$Hint" }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    Assert-Command $Name $Hint
}
function Read-EnvFile($Path) {
    $values = @{}
    # 显式 -Encoding UTF8：PS 5.1 的 Get-Content 默认按系统 ANSI 代码页解码，
    # 而 .env 由 UTF-8 的 .env.example 复制而来，中文系统上会解出乱码。
    if (Test-Path $Path) { Get-Content $Path -Encoding UTF8 | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $values[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'") } } }
    return $values
}
function Read-Secret($Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    return [System.Net.NetworkCredential]::new('', $secure).Password
}
# 所有 openclaw 调用的唯一出口。
#
# 这里局部把 $ErrorActionPreference 降到 Continue 是**必须的**，不是保险起见：
# 文件开头是 'Stop'，而 Windows PowerShell 5.1 在 Stop 下会把原生命令 stderr 的每一行
# 包成 ErrorRecord 抛出 NativeCommandError —— 脚本级终止，根本轮不到读 $LASTEXITCODE。
# 本文件下方 147 行附近的注释早就写明了这个坑，但 Set-OpenClawConfigQuiet 自己就踩了进去：
# 它做 `2>&1 | Out-Null`，于是这个「探测失败不该中断」的函数，恰恰会在它唯一该发挥
# 作用的场景（openclaw 打印 Unrecognized key 到 stderr）把整个安装打断。
# ---- 失败收集（与 setup.sh 的 warn_collect 对等）----
# 非致命问题不再中断安装，收集起来在结尾汇总。即时打印也要有：用户盯着十几分钟的
# 安装，问题发生时就该看见，而不是只在最后的汇总里（还可能被滚屏冲掉）。
$script:Warnings = New-Object System.Collections.ArrayList
function Add-Warning([string]$Label, [string]$Detail, [string]$Fix = '', [string]$Severity = 'low') {
    [void]$script:Warnings.Add([pscustomobject]@{
        Label = $Label; Detail = $Detail; Fix = $Fix; Severity = $Severity })
    Write-Host "  [!] $Label : $Detail" -ForegroundColor Yellow
    if ($Fix) { Write-Host "      -> $Fix" -ForegroundColor DarkGray }
    if ($env:EASEL_SETUP_STRICT) {
        Fail "$Label : $Detail（EASEL_SETUP_STRICT 下警告视为致命）"
    }
}

# 任何对原生命令做 stderr 重定向的地方都必须走这里（原因见上）。
function Invoke-NativeCapture([string]$Exe, [string[]]$Arguments) {
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

function Invoke-OpenClawRaw([string[]]$Arguments) {
    return (Invoke-NativeCapture 'openclaw' $Arguments)
}

# 能力探测（带记忆）：读 --help 判断某个子命令/标志在当前版本上存在不存在。
# 比「先调用、失败再回退」可靠 —— 后者分不清「不支持该功能」与「这次配置真的写错了」，
# 本文件的 Set-OpenClawConfigBatch 正是因此把 2026.9.x 的拒绝写入误报成
# 「当前 OpenClaw 不支持 --batch-file」。
$script:OcCaps = @{}
function Test-OpenClawSupport([string[]]$SubCommand, [string]$Needle) {
    $cacheKey = ($SubCommand -join ' ') + '|' + $Needle
    if (-not $script:OcCaps.ContainsKey($cacheKey)) {
        $r = Invoke-OpenClawRaw (@('--profile','easel') + $SubCommand + @('--help'))
        $script:OcCaps[$cacheKey] = ($r.Output -match [regex]::Escape($Needle))
    }
    return $script:OcCaps[$cacheKey]
}

# 尽力而为的写入：失败只记一条警告，绝不中断安装。
function Set-OpenClawConfig([string]$Key, $Value, [switch]$Json, [string]$Label, [string]$Severity = 'low') {
    $arguments = @('--profile','easel','config','set',$Key,$Value)
    if ($Json) { $arguments += '--strict-json' }
    $r = Invoke-OpenClawRaw $arguments
    if ($r.Ok) {
        ($r.Output -split "`n") | Where-Object { $_ -and $_ -notmatch '^No change$' } |
            ForEach-Object { Write-Host $_ }
        return
    }
    $first = (($r.Output -split "`n") | Where-Object { $_ } | Select-Object -First 1)
    # 不要用三元运算符 `? :` —— 那是 PowerShell 7+ 语法，Windows 自带的 5.1 会直接
     # 报语法错误，而 5.1 才是绝大多数用户实际跑的版本。
     $shown = $Key
     if ($Label) { $shown = $Label }
     Add-Warning $shown "openclaw 不接受 $Key（$first）" '' $Severity
}

# 静默尝试，只返回成败。用于探测哪套 schema 被接受。
function Set-OpenClawConfigQuiet([string]$Key, $Value, [switch]$Json) {
    $arguments = @('--profile','easel','config','set',$Key,$Value)
    if ($Json) { $arguments += '--strict-json' }
    return (Invoke-OpenClawRaw $arguments).Ok
}

# 依次尝试多套候选 key，第一个成功即止；全失败只报一条警告（按意图而非按 key 计数）。
# 用于那些「配置项位置随 OpenClaw 版本搬过家」的场景。
function Set-OpenClawFirst([string]$Label, $Value, [switch]$Json, [string[]]$Keys) {
    foreach ($k in $Keys) {
        if (Set-OpenClawConfigQuiet $k $Value -Json:$Json) { return }
    }
    Add-Warning $Label "当前 OpenClaw 不接受任何已知写法（已试 $($Keys -join '、')）"
}
# JSON 值的配置写入。Windows PowerShell 5.1（系统自带版本）向原生程序传参时会剥掉字符串里的
# 双引号：任何含 JSON 的 config set 都会变成裸键值、--strict-json 解析失败（见 issue #41）。
# 这里改走 --batch-file：argv 里只出现临时文件路径（无引号字符），JSON 从文件读，5.1/7 行为一致。
function Set-OpenClawConfigBatch($Operations, [string]$Label = 'OpenClaw 配置') {
    $batchPath = Join-Path ([System.IO.Path]::GetTempPath()) "easel-config-set-$(Get-Random).json"
    try {
        [System.IO.File]::WriteAllText($batchPath, (ConvertTo-Json -InputObject $Operations -Depth 40 -Compress))
        # 「支持不支持 --batch-file」必须由能力探测回答，不能拿退出码去推断：
        # 非零退出同样可能是「这次配置真的被拒了」（2026.9.x 对会删掉 provider 下已存在
        # 子键的整块写入一律拒绝）。原来按退出码回退，于是把真实的配置错误报成了
        # 「当前 OpenClaw 不支持 --batch-file」—— 排查时被这条错信息直接带偏。
        if (Test-OpenClawSupport @('config','set') '--batch-file') {
            $arguments = @('--profile','easel','config','set','--batch-file',$batchPath)
            # --replace 明确声明「有意整块替换」。不声明时 2026.9.x 会拒绝任何会删掉既有
            # 子键的写入，让重复安装失败。老版本没这个标志，所以先探测。
            if (Test-OpenClawSupport @('config','set') '--replace') { $arguments += '--replace' }
            $r = Invoke-OpenClawRaw $arguments
            if ($r.Ok) {
                ($r.Output -split "`n") | Where-Object { $_ -and $_ -notmatch '^No change$' } |
                    ForEach-Object { Write-Host $_ }
                return
            }
            $first = (($r.Output -split "`n") | Where-Object { $_ } | Select-Object -First 1)
            Add-Warning $Label "openclaw 拒绝了这批配置（$first）" '' 'high'
            return
        }
        # 当前版本确实没有 --batch-file：退回逐条写入。
        foreach ($op in $Operations) {
            Set-OpenClawConfig $op.path (ConvertTo-Json -InputObject $op.value -Depth 40 -Compress) -Json -Label $Label
        }
    } finally { Remove-Item $batchPath -Force -ErrorAction SilentlyContinue }
}
# 原子写入 anthropic provider。部分 OpenClaw 版本（如 2026.3.x）的 schema 要求 provider 一次性带齐
# baseUrl + models，逐字段 config set 会因中间态缺字段而整体校验失败（baseUrl/models: received undefined）。
# 用 venv Python 生成 JSON，避开 ConvertTo-Json 对空数组的序列化坑；整块替换也会顺带清掉旧的残留 header。
function Write-AnthropicProvider($BaseUrl, $ApiKey, $ApiKeyHeader, $AnthropicVersion) {
    $env:A_BASE_URL = $BaseUrl
    $env:A_API_KEY = $ApiKey
    $env:A_HDR = $ApiKeyHeader
    $env:A_VER = $AnthropicVersion
    $seed = @'
import json, os
# api 必须显式写死：不写时 OpenClaw 2026.2.x 会把这个 provider 当成 openai-responses，
# 请求打到 /responses，上游报错被 gateway 当正常回复塞进 choices[0].message.content
# → Web 对话静默显示「（无输出）」。与 setup.sh 的 oc_write_anthropic 对齐。
#
# timeoutSeconds 也一并写进来，而不是事后单独 config set 一次：2026.9.x 对「整块写入
# 会删掉已存在子键」的操作一律拒绝，而事后设的 timeoutSeconds 恰好就是那个子键 ——
# 于是首次安装能过、第二次重跑必失败（不可重入）。折进种子后这个问题从根上消失。
p = {"baseUrl": os.environ["A_BASE_URL"], "apiKey": os.environ["A_API_KEY"],
     "api": "anthropic-messages", "timeoutSeconds": 600, "models": []}
hdr = os.environ.get("A_HDR"); ver = os.environ.get("A_VER")
if hdr or ver:
    h = {}
    if hdr: h[hdr] = os.environ["A_API_KEY"]
    if ver: h["anthropic-version"] = ver
    p["headers"] = h
print(json.dumps(p))
'@ | & $Python -
    Remove-Item Env:A_BASE_URL, Env:A_API_KEY, Env:A_HDR, Env:A_VER -ErrorAction SilentlyContinue
    Set-OpenClawConfigBatch @(@{ path = 'models.providers.anthropic'; value = ($seed | ConvertFrom-Json) })
}

Write-Host "`nEasel · Windows 安装向导" -ForegroundColor Magenta
Step '1/8' '检查系统环境' 'Python · Node.js · Git · FFmpeg'
Info '检查系统环境...'
Install-RequiredCommand 'git' 'Git.Git' '请安装 Git for Windows 并加入 PATH。'
Install-RequiredCommand 'node' 'OpenJS.NodeJS.LTS' '请安装 Node.js 24.16+ 并加入 PATH。'
Install-RequiredCommand 'npm' 'OpenJS.NodeJS.LTS' '请安装 Node.js 24.16+ 并加入 PATH。'
if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) { Install-RequiredCommand 'python' 'Python.Python.3.12' '请安装 Python 3.10+ 并勾选 Add Python to PATH。' }
Install-RequiredCommand 'ffmpeg' 'Gyan.FFmpeg' '请安装 FFmpeg 并加入 PATH。'
# 跟随 openclaw@latest 的引擎要求（当前 2026.9.x 需要 Node >=24.16.0 <25 || >=26.1.0，25.x/26.0 被排除）。
$nodeParts = (& node -p 'process.versions.node').Split('.') | ForEach-Object { [int]$_ }
$nodeOk = ($nodeParts[0] -eq 24 -and $nodeParts[1] -ge 16) -or ($nodeParts[0] -eq 26 -and $nodeParts[1] -ge 1) -or ($nodeParts[0] -ge 27)
if (-not $nodeOk) { Fail 'Node.js 24.16+（24.x）或 26.1+ 是必需依赖（openclaw@latest 要求）；winget 的 LTS 若仍是 22.x，请手动安装 Node 24。' }
$pythonCommand = (Get-Command python -ErrorAction SilentlyContinue).Source
# 这是一次可用性探测：python 存在但跑不起来（典型是 Windows 应用商店的占位 python.exe）
# 时要安静地换下一个候选，不能让它抛 NativeCommandError 把安装打断。
if ($pythonCommand -and -not (Invoke-NativeCapture $pythonCommand @('--version')).Ok) { $pythonCommand = $null }
if (-not $pythonCommand -and (Get-Command py -ErrorAction SilentlyContinue)) { $pythonCommand = (Get-Command py).Source; $pythonArgs = @('-3') } else { $pythonArgs = @() }
if (-not $pythonCommand) { Fail '未找到可运行的 Python 3；请安装 Python 3.10+。' }
& $pythonCommand @pythonArgs -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { Fail 'Python 3.10+ 是必需依赖。' }
if (-not (Test-Path $Venv)) { Info '创建 Python 虚拟环境...'; & $pythonCommand @pythonArgs -m venv $Venv }
if (-not (Test-Path $Python)) { Fail 'Python venv 创建失败。' }
Ok '系统环境检查完成'

Step '2/8' '检测 OpenClaw' '已有安装将直接复用'
Info '安装 OpenClaw...'
if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) { & npm install -g openclaw@latest --loglevel warn; if ($LASTEXITCODE -ne 0) { Fail 'OpenClaw 安装失败。' } }
Assert-Command 'openclaw' '请确认 npm 全局 bin 已加入 PATH。'
Step '3/8' '安装 Easel 运行依赖' 'Web · 媒体 · 浏览器发布'
Info '安装 Easel Python 依赖...'
& $Python -m pip install --upgrade pip --progress-bar on
if ($LASTEXITCODE -ne 0) { Fail 'pip 升级失败。' }
& $Python -m pip install -e $Root --prefer-binary --progress-bar on
if ($LASTEXITCODE -ne 0) { Fail 'Easel Python 依赖安装失败。' }
Step '4/8' '构建 Web 工作台' 'React production bundle'
Info '构建 Web 前端...'
$Frontend = Join-Path $Root 'web\frontend'
Push-Location $Frontend
try {
    & npm install
    if ($LASTEXITCODE -ne 0) { Fail 'Web 前端依赖安装失败。' }
    & npm run build
    if ($LASTEXITCODE -ne 0) { Fail 'Web 前端构建失败。' }
} finally { Pop-Location }
Step '5/8' '安装 Playwright Chromium' '浏览器登录与发布'
Info '安装 Playwright Chromium...'
# 降级而非中断：这是个 ~300MB 的下载，弱网下失败很常见，且只影响浏览器登录/发布。
if (-not (Invoke-WithProgress 'Playwright Chromium' $Python @('-m','playwright','install','chromium'))) {
    Add-Warning 'Playwright Chromium' '下载失败，浏览器登录/发布不可用' `
        "$Python -m playwright install chromium"
}

Step '6/8' '初始化 Easel profile' '独立配置、独立 workspace、独立 Gateway'
Info '准备 Easel OpenClaw profile...'
$onboardHelp = (Invoke-NativeCapture 'openclaw' @('onboard','--help')).Output
$onboardArgs = @('--profile','easel','onboard','--non-interactive','--mode','local','--accept-risk')
foreach ($flag in @('--skip-health','--skip-channels','--skip-skills','--skip-ui','--skip-hooks','--skip-search','--skip-daemon')) {
    if ($onboardHelp -match [regex]::Escape($flag)) { $onboardArgs += $flag }
}
if ($onboardHelp -match '--no-install-daemon' -and $onboardHelp -notmatch '--skip-daemon') { $onboardArgs += '--no-install-daemon' }
$onboard = Invoke-NativeCapture 'openclaw' $onboardArgs
($onboard.Output -split "`n") | Where-Object { $_ -and $_ -notmatch '^No change$' } |
    ForEach-Object { Write-Host $_ }
# onboard 失败且 profile 配置确实不存在才算致命：没有 profile 后面每一条 config set
# 都会失败，没有可以 fail-soft 进去的东西。
if (-not $onboard.Ok -and -not (Test-Path (Join-Path $env:USERPROFILE '.openclaw-easel\openclaw.json'))) {
    Fail 'OpenClaw profile 初始化失败，请检查上方输出。'
} elseif (-not $onboard.Ok) {
    Add-Warning 'OpenClaw profile 初始化' 'onboard 返回非零，但已有 profile 配置，继续安装' '' 'high'
}

Step '7/8' '同步 skills 与配置' 'workspace · OpenClaw 认证'
Info '同步 skills 与 workspace...'
# workspace 目标不能写死：OpenClaw 的默认布局变过（2026.6.x 是 ~\.openclaw\workspace-easel，
# 2026.9.x 起是 ~\.openclaw-easel\workspace）。写死其一就会在另一个版本上装到 agent 不读的
# 目录里，而这里和 doctor 都照样报成功（issue #19）。统一问 easel\openclaw_workspace.py。
#
# 这段有两个 Windows 专属的坑，改动前请先看明白：
#   1. 顶上是 $ErrorActionPreference='Stop'。此时只要对原生命令做任何 stderr 重定向
#      （2>$null / 2>&1 / *>），PowerShell 5.1 会把 stderr 的每一行包成 ErrorRecord 抛出
#      NativeCommandError —— 脚本级终止，下面的回退分支根本轮不到。所以这里**不重定向**，
#      让 Python 的报错原样显示给用户，只用 $LASTEXITCODE 判成败。
#   2. PS 5.1 按 [Console]::OutputEncoding（中文系统是 OEM 936）解码原生命令的 stdout，
#      而 Python 那边输出的是 UTF-8（开头设了 PYTHONUTF8=1，模块里也显式 reconfigure）。
#      路径含中文时两边对不上就是乱码。把 OutputEncoding 临时钉成 UTF-8，用完还原。
$workspace = ''
$prevOutEnc = [Console]::OutputEncoding
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $wsOut = & $Python (Join-Path $Root 'easel\openclaw_workspace.py')
    if ($LASTEXITCODE -eq 0) { $workspace = ($wsOut | Select-Object -Last 1) }
} catch {
    Write-Warning "解析 workspace 时出错：$($_.Exception.Message)"
} finally {
    [Console]::OutputEncoding = $prevOutEnc
}
$workspace = "$workspace".Trim()
if ([string]::IsNullOrWhiteSpace($workspace)) {
    # 走到这里说明 Python 压根没跑起来（解析器内部的逐级退化没机会执行）。先认用户的显式覆盖。
    if ($env:EASEL_OPENCLAW_WORKSPACE) {
        $workspace = $env:EASEL_OPENCLAW_WORKSPACE
    } else {
        $workspace = Join-Path $HOME '.openclaw-easel\workspace'
    }
    Write-Warning "无法向 openclaw 问出 workspace，回退到 $workspace；若 agent 读不到技能，请设 EASEL_OPENCLAW_WORKSPACE 后重跑。"
}
Info "  workspace → $workspace"
$skills = Join-Path $workspace 'skills'
New-Item -ItemType Directory -Force -Path $skills | Out-Null
if (Test-Path (Join-Path $Root 'skills\openclaw')) { Copy-Item (Join-Path $Root 'skills\openclaw\*') $skills -Recurse -Force }
Copy-Item (Join-Path $Root 'openclaw\workspace\*.md') $workspace -Force -ErrorAction SilentlyContinue
$context = Join-Path $workspace 'CONTEXT.md'
@"
# Easel 项目路径

项目根目录：$Root
产物输出到：$(Join-Path $Root 'outputs')
用户素材在：$(Join-Path $Root 'assets')
用户画像在：$(Join-Path $Root 'profiles')
"@ | Set-Content -Path $context -Encoding UTF8
$shared = Join-Path $workspace 'shared'
if (Test-Path $shared) { Remove-Item $shared -Recurse -Force }
if (Test-Path (Join-Path $Root 'skills\shared')) { Copy-Item (Join-Path $Root 'skills\shared') $shared -Recurse -Force }
$profilesLink = Join-Path $workspace 'easel-profiles'
if (Test-Path $profilesLink) {
    $profileItem = Get-Item $profilesLink -Force
    if ($profileItem.LinkType -ne 'Junction') { Fail "$profilesLink 已存在但不是项目 profiles Junction，请移走后重试。" }
} else { New-Item -ItemType Junction -Path $profilesLink -Target (Join-Path $Root 'profiles') | Out-Null }
$outputs = Join-Path $workspace 'outputs'
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'outputs') | Out-Null
if (Test-Path $outputs) {
    $outputsItem = Get-Item $outputs -Force
    if ($outputsItem.LinkType -ne 'Junction') { Fail "$outputs 已存在但不是项目 outputs Junction，请移走后重试。" }
} else { New-Item -ItemType Junction -Path $outputs -Target (Join-Path $Root 'outputs') | Out-Null }

$envPath = Join-Path $Root '.env'
if (-not (Test-Path $envPath)) { Copy-Item (Join-Path $Root '.env.example') $envPath }
$envValues = Read-EnvFile $envPath
function Test-UsableKey($Value) { return -not [string]::IsNullOrWhiteSpace($Value) -and $Value -notmatch 'REPLACE_ME|your[-_ ]?api[-_ ]?key' }
if (-not (Test-UsableKey $envValues['ANTHROPIC_API_KEY']) -and -not (Test-UsableKey $envValues['OPENAI_API_KEY']) -and -not (Test-UsableKey $envValues['ANTHROPIC_AUTH_TOKEN']) -and -not (Test-UsableKey $envValues['EASEL_LLM_API_KEY']) -and -not (Test-UsableKey $envValues['OPENAI_MAAS_API_KEY'])) {
    $choice = Read-Host '模型服务：1 Anthropic / 2 OpenAI-compatible / 0 稍后配置 [1]'
    if ($choice -eq '2') { $key = Read-Secret 'OpenAI API Key（不会回显）'; $url = Read-Host 'Base URL [https://api.openai.com/v1]'; $model = Read-Host '模型 [gpt-4o]'; Add-Content $envPath "`nOPENAI_API_KEY=$key`nOPENAI_BASE_URL=$url`nOPENAI_MODEL=$model" }
    elseif ($choice -eq '1' -or [string]::IsNullOrWhiteSpace($choice)) { $key = Read-Secret 'Anthropic API Key（不会回显）'; $model = Read-Host '模型 [anthropic/claude-sonnet-4-6]'; Add-Content $envPath "`nANTHROPIC_API_KEY=$key`nCLAUDE_MODEL=$model" }
}
$envValues = Read-EnvFile $envPath

# 部分 OpenClaw 版本执行 config unset 后会把字段留成 null 而非真正删除该键，
# 一旦落盘就再也无法通过 config set/doctor --fix 修复（每次校验都先失败）。
# 这里在写入任何配置前，先把 models.providers.* 下残留的 null 叶子节点原地清空。
$openclawJson = Join-Path $HOME '.openclaw-easel\openclaw.json'
if (Test-Path $openclawJson) {
    @'
import json, sys

path = sys.argv[1]
with open(path) as f:
    config = json.load(f)


def strip_nulls(node):
    if isinstance(node, dict):
        changed = False
        for key in list(node.keys()):
            value = node[key]
            if value is None:
                del node[key]
                changed = True
            elif strip_nulls(value):
                changed = True
        return changed
    return False


providers = config.get("models", {}).get("providers", {})
if strip_nulls(providers):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
'@ | & $Python - $openclawJson
}

# 仅当真正写了 anthropic provider 时，才补设它的 provider 级超时（见文末 timeoutSeconds）；
# 否则会给 OpenAI/MAAS 用户凭空造出一个只有 timeoutSeconds、缺 baseUrl/models 的残缺 anthropic provider。
# 注意函数调用外面这对括号不能省：`if (Test-UsableKey $x -and $y)` 会让解析器进入命令模式，
# 把 `-and` 当成 Test-UsableKey 的参数名（简单函数会把它静默吞进 $args），
# 于是 ContainsKey 那半边守卫被丢掉且不报错。加括号才让 -and 回到运算符语义。
if ((Test-UsableKey $envValues['OPENAI_MAAS_API_KEY']) -and $envValues.ContainsKey('OPENAI_MAAS_ENDPOINT')) {
    $model = if ($envValues.ContainsKey('OPENAI_MAAS_MODEL')) { $envValues['OPENAI_MAAS_MODEL'] } else { 'gpt-5.5' }
    $port = if ($envValues.ContainsKey('OPENAI_MAAS_ADAPTER_PORT')) { $envValues['OPENAI_MAAS_ADAPTER_PORT'] } else { '18791' }
    $adapter = Join-Path $Root 'scripts\openai_maas_adapter.py'
    $provider = @{ baseUrl = "http://127.0.0.1:$port/v1"; api = 'openai-completions'; apiKey = 'local-adapter'; timeoutSeconds = 600; request = @{ allowPrivateNetwork = $true }; models = @(@{ id = $model; name = 'OpenAI-compatible model'; reasoning = $true; input = @('text') }); localService = @{ command = $Python; args = @($adapter, '--port', $port); cwd = $Root; healthUrl = "http://127.0.0.1:$port/health"; idleStopMs = 0; env = @{ OPENAI_MAAS_API_KEY = $envValues['OPENAI_MAAS_API_KEY']; OPENAI_MAAS_ENDPOINT = $envValues['OPENAI_MAAS_ENDPOINT']; OPENAI_MAAS_MODEL = $model; OPENAI_MAAS_API_KEY_HEADER = if ($envValues.ContainsKey('OPENAI_MAAS_API_KEY_HEADER')) { $envValues['OPENAI_MAAS_API_KEY_HEADER'] } else { 'Authorization' } } } }
    Set-OpenClawConfigBatch @(@{ path = 'models.providers.rednote-openai'; value = $provider })
    Set-OpenClawConfig 'agents.defaults.model.primary' "rednote-openai/$model"
} elseif (Test-UsableKey $envValues['OPENAI_API_KEY']) {
    $model = if ($envValues.ContainsKey('OPENAI_MODEL')) { $envValues['OPENAI_MODEL'] } else { 'gpt-4o' }
    Set-OpenClawConfigBatch @(
        @{ path = 'models.providers.openai.api'; value = 'openai-completions' },
        @{ path = 'models.providers.openai.apiKey'; value = $envValues['OPENAI_API_KEY'] },
        @{ path = 'models.providers.openai.baseUrl'; value = $(if ($envValues.ContainsKey('OPENAI_BASE_URL')) { $envValues['OPENAI_BASE_URL'] } else { 'https://api.openai.com/v1' }) },
        @{ path = 'models.providers.openai.models'; value = @(@{ id = $model; name = 'OpenAI model'; reasoning = $true; input = @('text', 'image') }) },
        @{ path = 'agents.defaults.model.primary'; value = "openai/$model" }
    )
} elseif ((Test-UsableKey $envValues['EASEL_LLM_API_KEY']) -and $envValues.ContainsKey('EASEL_LLM_BASE_URL')) {
    # 原子写入整块 provider（含 header 与 anthropic-version）；整块替换会顺带清掉旧的专用 header。
    $hdr = if ($envValues.ContainsKey('EASEL_LLM_API_KEY_HEADER')) { $envValues['EASEL_LLM_API_KEY_HEADER'] } else { 'api-key' }
    $ver = if ($envValues.ContainsKey('EASEL_LLM_ANTHROPIC_VERSION')) { $envValues['EASEL_LLM_ANTHROPIC_VERSION'] } else { '2023-06-01' }
    Write-AnthropicProvider $envValues['EASEL_LLM_BASE_URL'] $envValues['EASEL_LLM_API_KEY'] $hdr $ver
    Set-OpenClawConfig 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' })
} elseif ((Test-UsableKey $envValues['ANTHROPIC_AUTH_TOKEN']) -and $envValues.ContainsKey('ANTHROPIC_BASE_URL')) {
    Write-AnthropicProvider $envValues['ANTHROPIC_BASE_URL'] $envValues['ANTHROPIC_AUTH_TOKEN'] '' ''
    Set-OpenClawConfig 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' })
} elseif (Test-UsableKey $envValues['ANTHROPIC_API_KEY']) {
    # 官方 ANTHROPIC_API_KEY 可搭配 ANTHROPIC_BASE_URL 指向自定义代理/网关；未指定时显式指向官方端点，
    # 否则请求会发往默认的 api.anthropic.com，代理网络下会直接超时。provider 由 Write-AnthropicProvider 原子写入，
    # 避免逐字段写入时 baseUrl/models 缺失导致 2026.3.x 报 expected string/array, received undefined。
    $baseUrl = if (-not [string]::IsNullOrWhiteSpace($envValues['ANTHROPIC_BASE_URL'])) { $envValues['ANTHROPIC_BASE_URL'] } else { 'https://api.anthropic.com' }
    Write-AnthropicProvider $baseUrl $envValues['ANTHROPIC_API_KEY'] '' ''
    Set-OpenClawConfig 'agents.defaults.model.primary' $(if ($envValues.ContainsKey('CLAUDE_MODEL')) { $envValues['CLAUDE_MODEL'] } else { 'anthropic/claude-sonnet-4-6' })
}
$embeddingKeyNames = @('EASEL_EMBEDDING_API_KEY', 'EASEL_EMBEDDINGS_API_KEY', 'OPENAI_EMBEDDING_API_KEY', 'EMBEDDING_API_KEY', 'EMBEDDINGS_API_KEY')
$embeddingUrlNames = @('EASEL_EMBEDDING_BASE_URL', 'EASEL_EMBEDDINGS_BASE_URL', 'OPENAI_EMBEDDING_BASE_URL', 'EMBEDDING_BASE_URL', 'EMBEDDINGS_BASE_URL')
$embeddingModelNames = @('EASEL_EMBEDDING_MODEL', 'EASEL_EMBEDDINGS_MODEL', 'OPENAI_EMBEDDING_MODEL', 'EMBEDDING_MODEL', 'EMBEDDINGS_MODEL')
$embeddingKey = $embeddingKeyNames | Where-Object { Test-UsableKey $envValues[$_] } | Select-Object -First 1
$embeddingUrl = $embeddingUrlNames | Where-Object { -not [string]::IsNullOrWhiteSpace($envValues[$_]) } | Select-Object -First 1
$embeddingModel = $embeddingModelNames | Where-Object { -not [string]::IsNullOrWhiteSpace($envValues[$_]) } | Select-Object -First 1
if ($embeddingKey -and $embeddingUrl -and $embeddingModel) {
    # 记忆检索 schema 位置随 OpenClaw 版本变化：2026.9.x 起在顶层 memory.search.*，之前在 agents.defaults.memorySearch.*。
    # 两者互斥，用「先试新 key、失败再退老 key」自适应：第一条写入既是真实配置也是版本探测。
    if (Set-OpenClawConfigQuiet 'memory.search.provider' 'openai-compatible') {
        Set-OpenClawConfig 'memory.search.enabled' 'true' -Json; Set-OpenClawConfig 'memory.search.model' $envValues[$embeddingModel]; Set-OpenClawConfig 'memory.search.remote.baseUrl' $envValues[$embeddingUrl]; Set-OpenClawConfig 'memory.search.remote.apiKey' $envValues[$embeddingKey]
        Ok "独立向量模型已配置（memory.search）：$($envValues[$embeddingModel])"
    } else {
        Set-OpenClawConfig 'agents.defaults.memorySearch.provider' 'openai-compatible'; Set-OpenClawConfig 'agents.defaults.memorySearch.model' $envValues[$embeddingModel]; Set-OpenClawConfig 'agents.defaults.memorySearch.remote.baseUrl' $envValues[$embeddingUrl]; Set-OpenClawConfig 'agents.defaults.memorySearch.remote.apiKey' $envValues[$embeddingKey]
        Ok "独立向量模型已配置（memorySearch）：$($envValues[$embeddingModel])"
    }
} else {
    # 新 schema 用 memory.search.enabled=false 关闭向量检索；老 schema 用 provider=none。
    # 关闭向量检索的键随版本搬过家：2026.9.x+ 是 memory.search.enabled，更早是
    # agents.defaults.memorySearch.enabled。原来写的 memorySearch.provider='none' 在
    # 2026.2.x 上是无效枚举（只认 local/openai），会退出 1 并把整个安装打断 ——
    # 「关闭」这个语义本来就不能用 provider 表达。
    Set-OpenClawFirst '关闭向量记忆' 'false' -Json `
        -Keys @('memory.search.enabled','agents.defaults.memorySearch.enabled')
    if (($embeddingKeyNames + $embeddingUrlNames + $embeddingModelNames | Where-Object { $envValues.ContainsKey($_) }).Count -gt 0) { Write-Warning '向量 API 配置不完整，已关闭向量检索；需要同时设置向量 API key、Base URL 和模型名' } else { Info '未配置独立向量 API，使用关键词记忆检索' }
}
Set-OpenClawConfig 'agents.defaults.timeoutSeconds' '7200'; Set-OpenClawConfig 'gateway.mode' 'local'; Set-OpenClawConfig 'gateway.bind' 'loopback'; Set-OpenClawConfig 'gateway.auth.mode' 'none'
# 对话直连常驻网关（web/app.py 的 http 传输层）要用 OpenAI 兼容端点，而 openclaw 默认不挂这条
# 路由（chatCompletions.enabled 默认 false），不开则 POST /v1/chat/completions 一律 404、只能
# 退回每轮 spawn 客户端的老路径。端点只绑 loopback + auth.mode=none 的本机网关，不扩暴露面。
# 走尽力而为版：老版本没这个 key 时只是拿不到提速，不该让整个安装失败。
if (-not (Set-OpenClawConfigQuiet 'gateway.http.endpoints.chatCompletions.enabled' 'true' -Json)) {
    Info '当前 OpenClaw 不支持 chatCompletions 端点，对话将走每轮启动客户端的兼容路径（可用，只是每轮慢几秒）'
}
# 单次 LLM 请求的「空闲超时」已经折进 Write-AnthropicProvider 的种子 JSON 里了，
# 这里不再事后单独写一次 —— 正是那一次事后写入让 provider 多出一个子键，继而使
# 2026.9.x 在重复安装时拒绝整块替换（见 Set-OpenClawConfigBatch 的注释）。
# config validate 直到 2026.3 才有；2026.2.x 只有 get/set/unset，直接调会报
# "too many arguments for 'config'" 并让安装在最后一步前功尽弃。
# 校验未通过也只降级：上面每条 config set 都已各自校验过，整体 validate 失败通常是
# 更早版本留下的陈旧键，属于可修而非致命 —— 交给 doctor 指引。
if (Test-OpenClawSupport @('config') 'validate') {
    $v = Invoke-OpenClawRaw @('--profile','easel','config','validate')
    if ($v.Ok) { Ok 'OpenClaw 配置校验通过' }
    else { Add-Warning 'OpenClaw 配置校验' '整体校验未通过（多为旧版本遗留的配置键）' 'openclaw --profile easel doctor --fix' 'high' }
} else {
    Add-Warning 'OpenClaw 配置校验' '当前 OpenClaw 不支持 config validate，已跳过整体校验'
}
Step '8/8' '启动并验证' '配置校验 · Gateway health'
$gw = Invoke-NativeCapture 'powershell' @('-NoProfile','-ExecutionPolicy','Bypass','-File',
    (Join-Path $Root 'scripts\gateway.ps1'), 'start')
($gw.Output -split "`n") | Where-Object { $_ } | ForEach-Object { Write-Host $_ }
# 降级而非中断：gateway 随时可以重启，没理由让一次十几分钟的安装在最后一步作废。
if (-not $gw.Ok) {
    Add-Warning 'Gateway' '启动失败' 'powershell -File scripts\gateway.ps1 start' 'high'
}

Show-Summary
if (-not (Test-UsableKey $envValues['ANTHROPIC_API_KEY']) -and
    -not (Test-UsableKey $envValues['OPENAI_API_KEY']) -and
    -not (Test-UsableKey $envValues['EASEL_LLM_API_KEY'])) {
    Write-Host ''
    Write-Host '  下一步：在浏览器里配置模型' -ForegroundColor Yellow
    Write-Host "    1. $Venv\Scripts\easel.exe web" -ForegroundColor Cyan
    Write-Host '    2. 打开 http://localhost:7860' -ForegroundColor Cyan
    Write-Host '    3. 左下角设置 -> 模型配置 -> 填 API Key -> 保存' -ForegroundColor Cyan
    Write-Host '  保存后 Easel 会自动写好 openclaw 配置并重启网关，不用再跑 setup.ps1。' -ForegroundColor DarkGray
}
Write-Host ''
Write-Host "  启动 Web：$Venv\Scripts\easel.exe web" -ForegroundColor Cyan
Write-Host "  检查环境：$Venv\Scripts\easel.exe doctor" -ForegroundColor Cyan
