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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_PS1 = PROJECT_ROOT / "setup.ps1"
GATEWAY_PS1 = PROJECT_ROOT / "scripts" / "gateway.ps1"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


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
            code = line.split("#")[0]
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
