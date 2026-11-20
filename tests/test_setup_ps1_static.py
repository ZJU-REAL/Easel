"""setup.ps1 / gateway.ps1 的静态断言 —— 在 Linux 上守住 Windows 专属的几类缺陷。

本仓库作者的开发机是 Linux，改 PowerShell 没法本地跑真实安装。pwsh 7 虽然能装在
Linux 上做解析和 PSScriptAnalyzer，但**复现不了 Windows PowerShell 5.1 的关键行为**
（实测：去掉 Invoke-OpenClawRaw 里的 ErrorActionPreference=Continue，在 pwsh 7 上
测试照样通过）。而 5.1 才是 Windows 自带、绝大多数用户实际跑的版本。

所以凡是能表达成「源码里必须/不许出现某种写法」的，都在这里钉住，把 Windows 盲区
压到最小；剩下必须真跑的部分交给 CI 上 windows-latest 的双 shell 任务。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_PS1 = PROJECT_ROOT / "setup.ps1"
GATEWAY_PS1 = PROJECT_ROOT / "scripts" / "gateway.ps1"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def test_windows_optional_openclaw_is_an_explicit_install_choice() -> None:
    text = _read(SETUP_PS1)
    before = text[:text.index("$ErrorActionPreference")]
    assert "[switch]$SkipOpenClaw" in before
    assert "[switch]$OpenClaw" in before
    assert "[switch]$NonInteractive" in before
    assert "[switch]$Plain" in before
    assert "if (-not $SkipOpenClaw) {\nStep '2/8'" in text
    assert "if ($SkipOpenClaw) {\n    Step '6/8'" in text
    assert "& $Python -m easel.installation $Root api" in text
    assert "[Console]::IsInputRedirected" in text
    assert text.index("Step '5/8'") < text.index("$envPath = Join-Path $Root '.env'")


def test_dependency_install_preserves_process_path() -> None:
    text = _read(SETUP_PS1)
    start = text.index("function Install-RequiredCommand")
    body = text[start:text.index("function Read-EnvFile", start)]
    assert re.search(r"\$env:Path\s*=\s*\$env:Path\s*\+", body)
    assert "GetEnvironmentVariable('Path', 'Machine')" in body
    assert "GetEnvironmentVariable('Path', 'User')" in body


@pytest.mark.parametrize("shell_name", ["powershell", "pwsh"])
def test_dependency_install_path_in_powershell(shell_name: str, tmp_path: Path) -> None:
    executable = shutil.which(shell_name)
    if not executable:
        pytest.skip(f"{shell_name} is unavailable")
    text = _read(SETUP_PS1)
    start = text.index("function Assert-Command")
    functions = text[start:text.index("function Read-EnvFile", start)]
    script = tmp_path / "path-probe.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        + functions
        + r"""
function Info($Message) {}
function Fail($Message) { throw $Message }
$script:Installed = $false
function Get-Command($Name, $ErrorAction) {
    if ($Name -eq 'winget' -or $script:Installed) {
        return [pscustomobject]@{ Name = $Name }
    }
}
function winget {
    $script:Installed = $true
    $global:LASTEXITCODE = 0
}
$originalPath = 'C:\easel probe\node;C:\easel probe\python'
$env:Path = $originalPath
Install-RequiredCommand 'easel-path-probe' 'Easel.Test' 'mock dependency'
if (-not $script:Installed) { throw 'Mock dependency was not installed' }
$expectedPath = $originalPath + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if ($env:Path -ne $expectedPath) { throw 'Process PATH was lost or registry PATH was not refreshed' }
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_non_ascii_ps1_files_keep_bom() -> None:
    """含非 ASCII 字符的 .ps1 必须带 UTF-8 BOM。

    PS 5.1 没有 BOM 时按系统 ANSI 代码页解析，中文字符串会乱码甚至报语法错误。
    本仓库每个 .ps1 都带中文注释，所以这条对全部文件生效 —— 新增 ps_tolerance_probe.ps1
    时就漏了 BOM，而它恰恰要在 CI 的 5.1 下运行，是 PSScriptAnalyzer 替我抓到的。
    """
    import subprocess

    out = subprocess.run(["git", "ls-files", "*.ps1"], cwd=PROJECT_ROOT,
                         capture_output=True, text=True, timeout=60).stdout
    checked = 0
    for rel in out.split():
        if "vendor/" in rel:
            continue
        data = (PROJECT_ROOT / rel).read_bytes()
        try:
            data.decode("ascii")
            continue        # 纯 ASCII 文件不需要 BOM
        except UnicodeDecodeError:
            pass
        assert data[:3] == b"\xef\xbb\xbf", f"{rel} 含非 ASCII 字符，必须带 UTF-8 BOM"
        checked += 1
    assert checked >= 2, f"只检查到 {checked} 个文件，git ls-files 可能失效了"


def test_native_stderr_redirect_only_inside_continue_scope() -> None:
    """对原生命令做 stderr 重定向，必须在一个先把 ErrorActionPreference 降为 Continue 的函数里。

    文件顶部是 $ErrorActionPreference='Stop'。此时 PS 5.1 会把原生命令 stderr 的每一行
    包成 ErrorRecord 抛出 NativeCommandError —— 脚本级终止，根本轮不到读 $LASTEXITCODE。
    历史上 Try-OpenClawConfig 就是这么写的：一个「探测失败不该中断」的函数，偏偏会在
    它唯一该发挥作用的场景把整个安装打断。
    """
    text = _read(SETUP_PS1)
    lines = text.splitlines()

    # 找出所有把 ErrorActionPreference 降级的函数的行号区间
    safe_ranges: list[tuple[int, int]] = []
    fn_start = None
    depth = 0
    has_continue = False
    for n, line in enumerate(lines):
        if re.match(r"^\s*function\s+[\w-]+", line):
            fn_start, depth, has_continue = n, 0, False
        if fn_start is not None:
            depth += line.count("{") - line.count("}")
            if re.search(r"\$ErrorActionPreference\s*=\s*'Continue'", line):
                has_continue = True
            if depth <= 0 and n > fn_start:
                if has_continue:
                    safe_ranges.append((fn_start, n))
                fn_start = None

    offenders = []
    for n, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        # 只看对原生命令（& openclaw / & node ...）的重定向
        if not re.search(r"2>&1|2>\$null|\*>", line):
            continue
        if "&" not in line and "openclaw" not in line:
            continue
        if any(a <= n <= b for a, b in safe_ranges):
            continue
        offenders.append(f"{n + 1}: {line.strip()}")

    assert not offenders, (
        "以下 stderr 重定向不在 ErrorActionPreference=Continue 的作用域内，"
        "PS 5.1 会抛 NativeCommandError 中断安装：\n" + "\n".join(offenders)
    )


def test_anthropic_provider_seed_declares_api() -> None:
    """provider 种子必须写 api=anthropic-messages，否则 2026.2.x 会打到 /responses。"""
    text = _read(SETUP_PS1)
    i = text.index("function Write-AnthropicProvider")
    seed = text[i: text.index("\n}", i)]
    assert "anthropic-messages" in seed, "种子 JSON 必须声明 api"
    assert "timeoutSeconds" in seed, (
        "timeoutSeconds 要折进种子，而不是事后单独 config set —— "
        "那会让 2026.9.x 在重装时拒绝整块替换"
    )


def test_no_memorysearch_provider_none() -> None:
    """'关闭' 不能用 provider 枚举表达：2026.2.x 只认 local/openai，写 none 会中断安装。"""
    text = _read(SETUP_PS1)
    bad = [f"{n}: {l.strip()}" for n, l in enumerate(text.splitlines(), 1)
           if "memorySearch.provider" in l and "none" in l and not l.lstrip().startswith("#")]
    assert not bad, "不许再用 memorySearch.provider='none' 关闭向量检索：\n" + "\n".join(bad)


def test_config_validate_is_capability_probed() -> None:
    """config validate 直到 2026.3 才有，必须先探测再调用。"""
    text = _read(SETUP_PS1)
    assert "Test-OpenClawSupport @('config') 'validate'" in text, \
        "调用 config validate 之前必须先做能力探测"


def test_batch_fallback_is_not_exit_code_driven() -> None:
    """--batch-file 的回退判据必须是能力探测，不能是退出码。

    非零退出同样可能是「这次配置真的被拒了」。按退出码回退会把真实的配置错误报成
    「当前 OpenClaw 不支持 --batch-file」，排查时被这条错信息直接带偏。
    """
    text = _read(SETUP_PS1)
    i = text.index("function Set-OpenClawConfigBatch")
    body = text[i: text.index("\n}\n", i)]
    assert "Test-OpenClawSupport" in body, "回退必须由能力探测决定"
    assert "不支持 --batch-file" not in body or "Test-OpenClawSupport" in body


def test_env_file_read_as_utf8() -> None:
    """PS 5.1 的 Get-Content 默认按系统 ANSI 解码，而 .env 是 UTF-8。"""
    text = _read(SETUP_PS1)
    i = text.index("function Read-EnvFile")
    body = text[i: text.index("\n}", i)]
    assert "-Encoding UTF8" in body, "Read-EnvFile 必须显式指定 UTF8"


def test_no_powershell7_only_syntax() -> None:
    """不许用 PS7-only 语法：Windows 自带的是 5.1，会直接语法错误。

    三元运算符 `? :`、null 合并 `??`、管道链 `&&`/`||` 都是 7.0 才有的。
    这一条是实打实踩过的：本次改动初稿里就用了三元运算符，pwsh 7 解析得过。
    """
    for p in (SETUP_PS1, GATEWAY_PS1):
        for n, line in enumerate(_read(p).splitlines(), 1):
            # Ignore quoted data: the ASCII Easel logo legitimately contains ``||``.
            code = re.sub(r"'(?:''|[^'])*'", "''", line.split("#")[0])
            assert "??" not in code, f"{p.name}:{n} 用了 PS7 的 ?? 运算符"
            assert not re.search(r"\)\s*\?\s|\s\?\s.*\s:\s", code), \
                f"{p.name}:{n} 疑似用了 PS7 的三元运算符：{line.strip()}"
            assert not re.search(r"(?<![|&])&&(?![&])|(?<![|&])\|\|(?![|])", code), \
                f"{p.name}:{n} 用了 PS7 的管道链运算符"


# ── gateway.ps1：端口必须问单一真相源 ───────────────────────────────

def test_gateway_ps1_has_no_own_port_math() -> None:
    """gateway.ps1 不许自己再实现一遍端口推导。

    曾经同一个端口有三份独立实现（这里、easel/gateway_endpoint.py、OpenClaw 自己）。
    三份只要有一份跟不上版本变化就错配，而 start 带 --force —— 错配的后果不是探不通，
    而是杀掉占用那个端口的别人家 gateway。
    """
    text = _read(GATEWAY_PS1)
    for const in ("2166136261", "16777619", "40000"):
        assert const not in text, f"gateway.ps1 里不该再出现 FNV/端口空间常量 {const}"
    assert "gateway_endpoint" in text, "必须调用 easel/gateway_endpoint.py 解析端口"


def test_gateway_ps1_exports_port_unconditionally() -> None:
    """解析出的端口必须无条件钉给 OpenClaw，不能只在用户显式设了环境变量时才透传。"""
    text = _read(GATEWAY_PS1)
    assert '$env:OPENCLAW_GATEWAY_PORT = "$Port"' in text, \
        "必须无条件 export，否则探测端口与实际绑定端口是两份独立推导"
    bad = [l.strip() for l in text.splitlines()
           if "OPENCLAW_GATEWAY_PORT" in l and "if (" in l and not l.lstrip().startswith("#")]
    assert not bad, f"不该再有条件透传：{bad}"


def test_gateway_ps1_does_not_shadow_automatic_variable() -> None:
    """$Profile 是 PowerShell 的自动变量（当前用户的配置脚本路径），不该被覆写。"""
    text = _read(GATEWAY_PS1)
    bad = [f"{n}: {l.strip()}" for n, l in enumerate(text.splitlines(), 1)
           if re.search(r"^\s*\$Profile\s*=", l)]
    assert not bad, "不许给自动变量 $Profile 赋值：\n" + "\n".join(bad)


def test_gateway_ps1_has_configurable_bounded_start_timeout() -> None:
    """Gateway 冷启动等待必须有默认值，并允许受限的环境变量覆盖。

    回归背景：旧实现固定只等 20 秒，Windows 首次加载插件和 agent 状态时可能
    还没有完成 healthz，导致 setup 把正常启动误报成失败。这里同时锁住默认值、
    环境变量入口和 15--600 秒边界，避免后续改回硬编码或接受不受控的等待时间。
    """
    text = _read(GATEWAY_PS1)
    assert "$GatewayStartTimeoutSec = 120" in text
    assert re.search(
        r"\[int\]::TryParse\(\$env:EASEL_GATEWAY_START_TIMEOUT_SEC,\s*"
        r"\[ref\]\$configuredTimeout\)",
        text,
    ), "必须从 EASEL_GATEWAY_START_TIMEOUT_SEC 读取可选覆盖值"
    assert "$configuredTimeout -ge 15" in text
    assert "$configuredTimeout -le 600" in text
    assert "$GatewayStartTimeoutSec = $configuredTimeout" in text


def test_gateway_ps1_polls_healthz_until_ready_with_progress() -> None:
    """启动流程必须按可配置上限轮询 healthz，并在长启动时报告进度。"""
    text = _read(GATEWAY_PS1)
    start = text.index("    'start' {")
    body = text[start:text.index("    'stop' {", start)]

    assert "$polls = [int]($GatewayStartTimeoutSec * 2)" in body, \
        "等待上限应转换为 500ms 轮询次数"
    assert re.search(
        r"for \(\$i = 1; \$i -le \$polls -and -not \$ready; \$i\+\+\)",
        body,
    )
    assert "if (Test-Gateway) { $ready = $true; break }" in body
    assert "Start-Sleep -Milliseconds 500" in body
    assert "if (($i % 20) -eq 0)" in body
    assert "Gateway still starting..." in body


def test_setup_ps1_explains_gateway_wait_before_start() -> None:
    """setup.ps1 必须在调用 Gateway 前说明首次启动可能较慢。"""
    text = _read(SETUP_PS1)
    info = "Info '启动 Gateway；首次启动可能需要几分钟，正在等待 healthz...'"
    info_pos = text.index(info)
    start_pos = text.index("$gw = Invoke-NativeCapture", info_pos)
    assert info_pos < start_pos


def test_setup_ps1_normalizes_native_output_before_filtering_no_change() -> None:
    """PowerShell 5.1 的 CRLF 不应让 ``No change`` 穿透到终端。"""
    text = _read(SETUP_PS1)
    assert "function Get-NormalizedLines" in text
    assert "-split '\\r?\\n'" in text
    assert "if ($line -ne 'No change')" in text
    assert "Write-NativeOutput $r.Output" in text


def test_setup_ps1_quiets_dependency_commands_and_keeps_logs() -> None:
    """pip/npm 的常规噪声应进入安装日志，失败时才显示尾部。"""
    text = _read(SETUP_PS1)
    assert "--disable-pip-version-check" in text
    assert "--quiet" in text
    assert "--no-fund" in text
    assert "--no-audit" in text
    assert "$script:InstallLogDir" in text
    assert "1> $log 2> $errLog" in text
    assert "$LASTEXITCODE" in text
    progress = text[text.index("function Invoke-WithProgress"):text.index("# 结尾汇总", text.index("function Invoke-WithProgress"))]
    assert "New-Object System.Diagnostics.ProcessStartInfo" in progress, "TUI 长任务需要异步轮询以即时响应展开/收起按键"
    assert "$process.StartInfo = $startInfo" in progress
    assert "$exitCode = $process.ExitCode" in progress
    assert "function ConvertTo-ProcessArgument" in text
    assert "$startInfo.RedirectStandardOutput = $true" in progress
    assert "$startInfo.RedirectStandardError = $true" in progress
    assert "while (-not $process.HasExited)" in progress
    assert "Start-Sleep -Milliseconds 100" in progress
    assert "if (Update-TuiDetailsFromKeys) { Render-TuiProgress" in progress
    assert "Get-Content $f -Tail 40" in text
    assert "Remove-Item $log" not in text


def test_setup_ps1_writes_install_report_and_reloads_changed_gateway() -> None:
    """Windows 安装应持久化结果，并在配置写入后重启 Gateway。"""
    text = _read(SETUP_PS1)
    assert "outputs\\_install\\last-install.json" in text
    assert "function Write-InstallReport" in text
    assert "Write-InstallReport" in text[text.index("Step '8/8'"):]
    gateway = text[text.index("Step '8/8'"):]
    assert "$script:OpenClawConfigChanged" in gateway
    assert "$gatewayAction = 'restart'" in gateway
    assert "$gatewayAction = 'start'" in gateway


def test_setup_ps1_has_native_tui_with_plain_fallback() -> None:
    """交互终端使用原生方向键菜单，CI/重定向仍必须保持纯文本路径。"""
    text = _read(SETUP_PS1)
    assert "function Initialize-Tui" in text
    assert "[Console]::ReadKey($true)" in text
    assert "UpArrow" in text and "DownArrow" in text
    assert "[Console]::IsInputRedirected" in text
    assert "[Console]::IsOutputRedirected" in text
    assert "$NonInteractive" in text[text.index("function Initialize-Tui"):text.index("function Write-TuiHeader")]
    assert "if ($script:TuiEnabled)" in text[text.index("Write-Host \"`nEasel"):text.index("if ($SkipOpenClaw)")]


def test_setup_ps1_tui_covers_choices_recovery_and_progress() -> None:
    """TUI 必须覆盖安装模式、模型服务、失败恢复和阶段进度。"""
    text = _read(SETUP_PS1)
    assert "选择安装模式" in text
    assert "选择模型服务" in text
    assert "function Invoke-WithRecovery" in text
    assert "重试" in text and "中止安装" in text
    assert "跳过（继续安装）" in text
    assert "function Render-TuiProgress" in text
    assert "安装进度" in text
    assert "'complete'" in text and "'running'" in text and "'failed'" in text
    assert "安装进度：{0}/{1}" not in text
    assert "([string]$Text).ToCharArray()" in text
    assert "Invoke-WithRecovery 'pip 升级'" in text
    assert "Invoke-WithRecovery 'Web 前端构建'" in text
    assert "Invoke-WithRecovery 'Playwright Chromium'" in text


def test_setup_ps1_tui_progress_uses_unicode_completion_and_pending_markers() -> None:
    """TUI 进度页用绿色勾和白色空心圈，其他状态保持现有标识。"""
    text = _read(SETUP_PS1)
    progress = text[text.index("function Render-TuiProgress"):text.index("function Read-TuiMenu")]
    assert "'complete' { $mark = '✓   '; $color = 'Green' }" in progress
    assert "$mark = '○   '; $color = 'White'" in progress
    assert "'running' { $mark = '⠋   '; $color = 'Yellow' }" in progress
    assert "'skipped' { $mark = '[--]'; $color = 'DarkGray' }" in progress
    assert "'failed' { $mark = '[!!]'; $color = 'Red' }" in progress


def test_setup_ps1_tui_does_not_replace_noninteractive_flags() -> None:
    """原有显式安装参数仍然优先于 TUI。"""
    text = _read(SETUP_PS1)
    start = text.index("Initialize-Tui")
    mode = text[start:text.index("if ($SkipOpenClaw)", start)]
    assert "-not $SkipOpenClaw" in mode
    assert "-not $OpenClaw" in mode
    assert "-not $NonInteractive" in mode
    assert "$Plain" in text[text.index("function Initialize-Tui"):text.index("function Write-TuiHeader")]
    assert "[Console]::IsOutputRedirected" in mode
    assert "-SkipOpenClaw" not in mode or "param(" in text[:start]


def test_setup_ps1_tui_keeps_instructions_colors_and_messages_inside_frame() -> None:
    """每个交互页都要有操作提示，进度消息不能再跑到框外。"""
    text = _read(SETUP_PS1)
    assert "操作：按 ↓ 展开详细安装信息，按 ↑ 收起；按 Ctrl+C 放弃安装。" in text
    assert "操作：详细信息已展开；按 ↑ 收起，按 Ctrl+C 放弃安装。" in text
    assert "操作：↑/↓ 选择，Enter 确认，Esc 返回/放弃。" in text
    assert "操作：输入内容后按 Enter；Ctrl+C 放弃安装。" in text
    assert "function Split-TuiLine" in text
    assert "function Add-TuiMessage" in text
    assert "['BackgroundColor'] = 'DarkCyan'" in text
    assert "'放弃安装'" in text
    assert "Write-TuiFrame $lines" in text


def test_setup_ps1_progress_details_are_collapsed_by_default_and_toggle_with_arrows() -> None:
    """进度页默认只显示摘要，Down/Up 控制详细消息展开和收起。"""
    text = _read(SETUP_PS1)
    assert "$script:TuiDetailsExpanded = $false" in text
    assert "function Update-TuiDetailsFromKeys" in text
    assert "[ConsoleKey]::DownArrow" in text
    assert "[ConsoleKey]::UpArrow" in text
    progress = text[text.index("function Render-TuiProgress"):text.index("function Read-TuiMenu")]
    assert "if ($script:TuiDetailsExpanded -and $script:TuiMessages.Count -gt 0)" in progress
    assert "详细安装信息" in progress
    assert "if ($script:TuiDetailsExpanded)" in progress


def test_setup_ps1_native_capture_polls_keys_during_late_install_steps() -> None:
    """第 6 步后的 OpenClaw/Python 原生命令也必须支持即时展开收起。"""
    text = _read(SETUP_PS1)
    assert "function Invoke-TuiProcessCapture" in text
    native = text[text.index("function Invoke-NativeCapture"):text.index("function Invoke-OpenClawRaw")]
    assert "return Invoke-TuiProcessCapture $Exe $Arguments" in native
    python_capture = text[text.index("function Invoke-PythonStdinCapture"):text.index("function Invoke-OpenClawRaw")]
    assert "return Invoke-TuiProcessCapture $Python $Arguments $Code" in python_capture
    assert "if ((Update-TuiDetailsFromKeys) -and $script:CurrentStepIndex)" in text


def test_setup_ps1_tui_resolves_windows_command_shims_before_dotnet_start() -> None:
    """.NET Process 不能直接解析 openclaw 这类 PATHEXT 命令名，必须先解析 .cmd/.exe。"""
    text = _read(SETUP_PS1)
    assert "function Resolve-TuiExecutable" in text
    resolver = text[text.index("function Resolve-TuiExecutable"):text.index("function Start-TuiSpinner")]
    assert '"$Exe.cmd"' in resolver
    assert '"$Exe.exe"' in resolver
    process = text[text.index("function Invoke-TuiProcessCapture"):text.index("# 任何对原生命令")]
    assert "$resolvedExe = Resolve-TuiExecutable $Exe" in process
    assert "$startInfo.FileName = $resolvedExe" in process


def test_setup_ps1_retries_transient_openclaw_batch_read_failures() -> None:
    """批量配置遇到临时 config read 错误时等待并重试，避免把瞬时竞态暴露给用户。"""
    text = _read(SETUP_PS1)
    assert "function Wait-TuiRetryDelay" in text
    batch = text[text.index("function Set-OpenClawConfigBatch"):text.index("function Write-AnthropicProvider")]
    assert "$maxAttempts = 3" in batch
    assert "config could not be read" in batch
    assert "Wait-TuiRetryDelay 500" in batch
    assert "正在重试（$attempt/$maxAttempts）" in batch


def test_setup_ps1_tui_completion_visual_keeps_launch_commands() -> None:
    """完成页采用居中品牌和状态块，同时保留用户需要的两个启动提示。"""
    text = _read(SETUP_PS1)
    assert "$script:TuiLogo = @(" in text
    assert "'    _____    _    ____  _____ _'" in text
    assert "'   |_____/_/   \\_\\____/|_____|_____|'" in text
    assert "[ INSTALLATION COMPLETE ]" in text
    assert "Easel 已准备就绪。" in text
    assert "('[' + ('#' * 48) + '] 100%')" in text
    assert '启动 Web：$Venv\\Scripts\\easel.exe web' in text
    assert '检查环境：$Venv\\Scripts\\easel.exe doctor' in text
    assert 'easel --help' not in text[text.index('function Show-Summary'):text.index('function Write-InstallReport')]


def test_setup_ps1_running_step_uses_in_place_braille_spinner() -> None:
    """Running 只动态替换原标记，并用定时器写回固定光标位置。"""
    text = _read(SETUP_PS1)
    progress = text[text.index("function Render-TuiProgress"):text.index("function Read-TuiMenu")]
    assert '⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏' in text
    assert 'new Timer(Tick, null, 100, 100)' in text
    assert 'Console.SetCursorPosition(left, top)' in text
    assert 'Console.Write(Frames[frame])' in text
    assert '$totalRows = $renderedRows + 1' in text
    assert 'Top = ([Console]::CursorTop - ($totalRows - $spinnerRow))' in text
    assert "'running' { $mark = '⠋   '; $color = 'Yellow' }" in progress
    assert 'Stop-TuiSpinner' in progress
    assert 'if ($activeStep) { Start-TuiSpinner }' in progress


def test_setup_ps1_tui_uses_utf8_for_braille_spinner_and_restores_encoding() -> None:
    """Braille 动画应避免被 Windows 控制台代码页替换成问号。"""
    text = _read(SETUP_PS1)
    assert "$script:TuiPreviousOutputEncoding = [Console]::OutputEncoding" in text
    assert "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false" in text
    assert "function Restore-TuiConsoleEncoding" in text
    assert "Restore-TuiConsoleEncoding" in text[text.index("function Show-Summary"):text.index("function Write-InstallReport")]
