"""setup.sh 国内镜像加速的回归测试。

覆盖：
  ① npmjs.org 连不通时自动回落 npmmirror，且安装命令带 --registry；
  ② EASEL_NPM_REGISTRY / EASEL_PIP_INDEX 显式指定时优先使用；
  ③ 不再 `npm config set registry` 写用户全局 npm 配置；
  ④ pypi.org 连不通时 pip 自动带清华镜像 -i。

按内容锚点切出 setup.sh 真实片段在沙箱里跑（与 test_setup_issue26 同模式）。
"""
from __future__ import annotations

import subprocess
import os
import shlex
import signal
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = PROJECT_ROOT / "setup.sh"


def _bash_works() -> bool:
    try:
        p = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True,
                           timeout=30, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip() == "ok"


needs_bash = pytest.mark.skipif(os.name == 'nt' or not _bash_works(), reason="需要非 Windows 的 bash 环境")


def _slice(text: str, start: str, end: str) -> str:
    lines = text.splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith(start))
    j = next(n for n, line in enumerate(lines) if n > i and line.startswith(end))
    return "\n".join(lines[i:j])


def _stub_tools(tmp_path: Path, npm_ping_ok: bool, pypi_ok: bool,
                log: Path) -> str:
    """假 npm / python3：记录调用，按场景决定 ping/urlopen 结果。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    npm = bin_dir / "npm"
    ping = "0" if npm_ping_ok else "7"
    npm.write_text(f"""#!/bin/bash
echo "npm $*" >> {shlex.quote(str(log))}
exit {ping}
""", encoding="utf-8")
    # 真实流程里 npm ping 失败不 abort，但裸 ping 退出码 7 会让 set -e 里的
    # if 条件正常走 false 分支 —— 退出码非零即可。
    py = bin_dir / "python3"
    py.write_text(f"""#!/bin/bash
case "$*" in
  *--version*) echo 'Python 3.11.0'; exit 0 ;;
  *urlopen*) exit {0 if pypi_ok else 1} ;;
esac
exit 0
""", encoding="utf-8")
    for f in (npm, py):
        f.chmod(0o755)
    return str(tmp_path / "bin")


def _run(block: str, tmp_path: Path, bin_dir: str, extra_env: str = "", timeout: float = 60) -> subprocess.CompletedProcess:
    script = textwrap.dedent(f"""
        set -uo pipefail
        export PATH="{bin_dir}:$PATH"
        {extra_env}
        ok()   {{ echo "OK|$*"; }}
        warn() {{ echo "WARN|$*"; }}
        step() {{ echo "STEP|$*"; }}
    """) + block + textwrap.dedent(f"""
        echo "RESULT_REGISTRY=${{NPM_REGISTRY:-unset}}"
        echo "RESULT_NPM_ARGS=${{NPM_REGISTRY_ARGS[*]:-unset}}"
        echo "RESULT_PIP_ARGS=${{PIP_ARGS[*]:-unset}}"
    """)
    process = subprocess.Popen(["bash", "-c", script], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, errors="replace", start_new_session=True, cwd=tmp_path)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


@needs_bash
def test_npm_falls_back_to_npmmirror_when_official_unreachable(tmp_path: Path) -> None:
    """npmjs 连不通 → 自动回落 npmmirror，安装命令带 --registry。"""
    log = tmp_path / "calls.log"
    bin_dir = _stub_tools(tmp_path, npm_ping_ok=False, pypi_ok=True, log=log)
    text = SETUP_SH.read_text(encoding="utf-8")
    block = _slice(text, "# ---- 2. npm 源 ----", "# ---- 3. 检测/安装 OpenClaw")

    r = _run(block, tmp_path, bin_dir)
    assert r.returncode == 0, r.stderr
    assert "RESULT_REGISTRY=https://registry.npmmirror.com" in r.stdout
    assert "WARN" in r.stdout, "应给出 warn 说明已切换镜像"
    # 安装参数数组要带上 --registry，让后续 npm install 真正走镜像
    assert "RESULT_NPM_ARGS=--registry https://registry.npmmirror.com" in r.stdout


@needs_bash
def test_npm_keeps_official_when_reachable(tmp_path: Path) -> None:
    """官方源连通 → 保持 npmjs.org，不出 warn。"""
    log = tmp_path / "calls.log"
    bin_dir = _stub_tools(tmp_path, npm_ping_ok=True, pypi_ok=True, log=log)
    text = SETUP_SH.read_text(encoding="utf-8")
    block = _slice(text, "# ---- 2. npm 源 ----", "# ---- 3. 检测/安装 OpenClaw")

    r = _run(block, tmp_path, bin_dir)
    assert r.returncode == 0, r.stderr
    assert "RESULT_REGISTRY=https://registry.npmjs.org" in r.stdout
    assert "RESULT_NPM_ARGS=--registry https://registry.npmjs.org" in r.stdout


@needs_bash
def test_easel_npm_registry_override_wins(tmp_path: Path) -> None:
    """EASEL_NPM_REGISTRY 显式指定 → 直接用，不做探测。"""
    log = tmp_path / "calls.log"
    bin_dir = _stub_tools(tmp_path, npm_ping_ok=False, pypi_ok=True, log=log)
    text = SETUP_SH.read_text(encoding="utf-8")
    block = _slice(text, "# ---- 2. npm 源 ----", "# ---- 3. 检测/安装 OpenClaw")

    r = _run(block, tmp_path, bin_dir,
             extra_env='EASEL_NPM_REGISTRY="https://my-mirror.example.com"')
    assert r.returncode == 0, r.stderr
    assert "RESULT_REGISTRY=https://my-mirror.example.com" in r.stdout
    assert "RESULT_NPM_ARGS=--registry https://my-mirror.example.com" in r.stdout


@needs_bash
def test_pip_falls_back_to_tuna_when_official_unreachable(tmp_path: Path) -> None:
    """pypi.org 连不通 → PIP_ARGS 自动带清华镜像 -i。"""
    log = tmp_path / "calls.log"
    bin_dir = _stub_tools(tmp_path, npm_ping_ok=True, pypi_ok=False, log=log)
    text = SETUP_SH.read_text(encoding="utf-8")
    block = _slice(text, "# pip 镜像：", "if [ \"$(id -u)\" -eq 0 ]; then")
    block = 'PROJECT_ROOT="."\n' + block

    r = _run(block, tmp_path, bin_dir)
    assert r.returncode == 0, r.stderr
    assert "RESULT_PIP_ARGS=" in r.stdout
    pip_args = next(l for l in r.stdout.splitlines() if l.startswith("RESULT_PIP_ARGS="))
    assert "pypi.tuna.tsinghua.edu.cn" in pip_args, pip_args


@needs_bash
def test_setup_no_longer_touches_global_npm_config(tmp_path: Path) -> None:
    """setup.sh 不得再写用户全局 npm 配置（npm config set registry 已移除）。"""
    src = SETUP_SH.read_text(encoding="utf-8")
    # 只匹配实际执行行（排除注释里的提及）
    offenders = [line for line in src.splitlines()
                 if "npm config set registry" in line and not line.strip().startswith("#")]
    assert not offenders, f"setup.sh 不应修改用户全局 npm 配置：{offenders}"


@needs_bash
def test_all_npm_installs_carry_registry_flag(tmp_path: Path) -> None:
    """setup.sh 里所有 npm install/ci 都必须挂镜像参数数组（防新增安装点漏挂）。"""
    src = SETUP_SH.read_text(encoding="utf-8")
    offenders = [line.strip() for line in src.splitlines()
                 if ("npm install" in line or "npm ci" in line)
                 and "NPM_REGISTRY_ARGS" not in line
                 and not line.strip().startswith("#")
                 and "echo" not in line]
    assert not offenders, f"以下 npm 安装命令未挂 NPM_REGISTRY_ARGS：{offenders}"


@needs_bash
def test_npm_ping_has_short_timeout(tmp_path: Path) -> None:
    """连通性探测必须带短超时：npm 默认 fetch-timeout 是 300s，
    国内网络下裸 ping 最坏会把用户卡在 step 2 五分钟，比原来更糟。
    """
    src = SETUP_SH.read_text(encoding="utf-8")
    # 命令可能跨多行（续行符），把整段 step2 拼起来再断言
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines) if "npm ping" in l)
    seg = []
    for l in lines[start:start + 5]:
        seg.append(l)
        if not l.rstrip().endswith("\\"):
            break
    joined = "\n".join(seg)
    assert "--fetch-timeout" in joined, "npm ping 必须显式限制超时"
    assert "--fetch-retries=0" in joined, "探测不应重试（重试会把等待乘几倍）"


@needs_bash
def test_pypi_probe_guarded_by_timeout_command(tmp_path: Path) -> None:
    """pip 探测在系统有 timeout(1) 时应被它兜底（urlopen 的 timeout 不含 DNS 卡死）。"""
    src = SETUP_SH.read_text(encoding="utf-8")
    assert "timeout 8 python3 -c" in src, "pypi 探测缺少 timeout 命令兜底"
