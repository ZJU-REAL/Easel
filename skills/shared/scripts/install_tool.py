#!/usr/bin/env python3
"""install_tool.py — 环境工具一键安装器（检测 → 一键装 → 装后校验）。

「设置面板 · 环境安装」页、独立安装版（拷到任意机器）与各技能的共用引擎：
- 配方表：每个工具 = 怎么认（check）+ 怎么装（策略链，自动降级）+ 中文说明
- 策略链依次尝试（pip → winget → choco → 直接下载），装完重跑 check，认到才算成
- 0 提问；--json 全程可机读（面板 / agent 直接消费）

子命令：
    list                        配方总览（含本机状态）
    check [id ...]              体检（默认全量；--json 机读）
    install <id> [<id> ...]     一键安装（--dir 给「工程目录类」工具）
    selftest                    自检（离线，不装任何东西）

约束：仅标准库、Python 3.11 兼容、无交互。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# 工具配方
#   check[0] 为 "@pyfn:<名字>" 时走内置函数检查；否则按 argv 跑（占位符：
#   {python} = 解析出的目标解释器；{dir} = --dir 传入的工程目录，只能整元素
#   替换 —— 目录是外部输入，拼进 -c 源码文本会被引号逃逸成任意代码）
#   install = [(策略名, argv[, 超时秒]), ...] 依次尝试
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Tool:
    id: str
    name: str
    group: str          # rm（视频产线套件）| pub（发布链）| common（常用库）
    desc: str
    check: list[str]
    install: list[tuple]
    needs_dir: bool = False
    big: bool = False   # 大件（面板上标注体积/耗时）


def _pip_chain(*pkgs: str, timeout: int = 1200) -> list[tuple]:
    """pip 双策略：默认源（带重试）→ 清华镜像（国内断流保险）。"""
    base = ["{python}", "-m", "pip", "install", "--upgrade",
            "--timeout", "60", "--retries", "5", *pkgs]
    mirror = [*base, "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
    return [("pip 安装（默认源）", base, timeout),
            ("pip 安装（清华镜像）", mirror, timeout)]


WHISPER_MODEL_PY = (
    "import os;os.environ.setdefault('HF_ENDPOINT','https://hf-mirror.com');"
    "from huggingface_hub import snapshot_download;"
    "print(snapshot_download('Systran/faster-whisper-large-v3',"
    "local_dir=os.path.expanduser('~/models/whisper-large-v3')))"
)


def _pyfn_check_cft() -> tuple[bool, str]:
    import glob
    la = os.environ.get("LOCALAPPDATA", "")
    pf, pf86 = os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")
    cands: list[str] = []
    for base in (pf, pf86):
        if base:
            cands += glob.glob(os.path.join(base, "Google", "Chrome", "Application", "*", "chrome.exe"))
    if la:
        cands += glob.glob(os.path.join(la, "Google", "Chrome for Testing", "*", "chrome.exe"))
        cands += glob.glob(os.path.join(la, "ms-playwright", "chromium-*", "chrome-win64", "chrome.exe"))
    w = shutil.which("chrome")
    if w:
        cands.append(w)
    if cands:
        return True, Path(sorted(cands)[-1]).parent.parent.name or "已装"
    return False, ""


def _pyfn_check_model() -> tuple[bool, str]:
    d = Path(os.path.expanduser("~/models/whisper-large-v3"))
    if d.is_dir() and any(d.iterdir()):
        return True, "模型目录已就绪"
    return False, ""


_PYFN = {"cft": _pyfn_check_cft, "model": _pyfn_check_model}


TOOLS: list[Tool] = [
    # ── 视频产线套件（Remotion）──
    Tool("node", "Node.js", "rm", "rm 运行时 · 建议 24 LTS",
         ["node", "-v"],
         [("winget · OpenJS.NodeJS.LTS",
           ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
            "--accept-source-agreements", "--accept-package-agreements"], 900)]),
    Tool("ffmpeg", "ffmpeg", "rm", "full build · lut3d / nlmeans 等滤镜齐",
         ["ffmpeg", "-version"],
         [("winget · Gyan.FFmpeg",
           ["winget", "install", "-e", "--id", "Gyan.FFmpeg",
            "--accept-source-agreements", "--accept-package-agreements"], 900),
          ("choco · ffmpeg", ["choco", "install", "ffmpeg", "-y"], 900)]),
    Tool("python", "Python", "rm", "3.11+ · 工具与门脚本运行用",
         ["{python}", "--version"],
         [("winget · Python.Python.3.13",
           ["winget", "install", "-e", "--id", "Python.Python.3.13",
            "--accept-source-agreements", "--accept-package-agreements"], 900)]),
    Tool("fw", "faster-whisper", "rm", "GPU 转录（cu121）",
         ["{python}", "-c", "import faster_whisper as f;print(getattr(f,'__version__','ok'))"],
         _pip_chain("faster-whisper", timeout=1800)),
    Tool("model", "Whisper large-v3 模型", "rm", "约 3.1GB · hf-mirror 直拉 · 不入包",
         ["@pyfn:model"],
         _pip_chain("huggingface_hub", timeout=600)
         + [("hf-mirror 下载 large-v3", ["{python}", "-c", WHISPER_MODEL_PY], 7200)],
         big=True),
    Tool("rmdeps", "Remotion 工程依赖", "rm", "蓝本内置 · npm ci 还原（镜像加速）",
         ["{python}", "-c",
          "import os,sys;sys.exit(0 if os.path.isdir(os.path.join(sys.argv[1],'node_modules')) else 1)",
          "{dir}"],
         [("npm ci · npmmirror 镜像", ["npm", "ci", "--registry=https://registry.npmmirror.com"], 1800)],
         needs_dir=True),
    Tool("shell", "Chrome Headless Shell", "rm", "渲染用 · 随 Remotion 下载",
         ["@pyfn:shell"],
         [("npx remotion browser ensure", ["npx", "--yes", "remotion", "browser", "ensure"], 1800)],
         needs_dir=True),
    # ── 发布链 ──
    Tool("biliup", "biliup", "pub", "B站投稿 CLI · python 包装",
         ["biliup", "--version"],
         _pip_chain("biliup", timeout=1800)),
    Tool("pw", "Playwright Chromium", "pub", "小红书 / 快手 / 知乎 发布链浏览器",
         ["{python}", "-c", "import playwright;print('playwright ok')"],
         _pip_chain("playwright")
         + [("下载 Chromium", ["{python}", "-m", "playwright", "install", "chromium"], 1800)]),
    Tool("cft", "Chrome for Testing", "pub", "登录态浏览器 · 平台登录用",
         ["@pyfn:cft"],
         [("playwright 自带 Chromium", ["{python}", "-m", "playwright", "install", "chromium"], 1800)]),
    # ── 常用库 ──
    Tool("pylibs", "常用 Python 库", "common", "Pillow · edge-tts · pdfplumber · requests",
         ["{python}", "-c", "import PIL,edge_tts,pdfplumber,requests;print('4/4 ok')"],
         _pip_chain("Pillow", "edge-tts", "pdfplumber", "requests")),
]

GROUP_NAMES = {"rm": "视频产线套件（Remotion）", "pub": "发布链", "common": "常用库"}

# ═══════════════════════════════════════════════════════════════════════
# 解释器解析：优先「Scripts 目录已在 PATH 上」的（装完 CLI 直接可见）
# ═══════════════════════════════════════════════════════════════════════

_PY_LIST: list[str] | None = None


def _candidate_pythons() -> list[str]:
    out: list[str] = []
    py = shutil.which("py")
    if py:
        try:
            r = subprocess.run([py, "-0p"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=20)
            out += re.findall(r"([A-Za-z]:\\[^\r\n]*?python\.exe)", r.stdout)
        except Exception:  # noqa: BLE001
            pass
    for name in ("python", "python3"):
        p = shutil.which(name)
        if p:
            out.append(p)
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        out += [str(Path(la) / "Programs" / "Python" / f"Python3{v}" / "python.exe") for v in (13, 12, 11)]
    out += ["C:/Python314/python.exe", "C:/Python313/python.exe", "C:/Python312/python.exe"]
    seen, uniq = set(), []
    for p in out:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and os.path.isfile(p):
            seen.add(key)
            uniq.append(os.path.abspath(p))
    return uniq


def _scripts_dir(python: str) -> str:
    try:
        r = subprocess.run([python, "-c", "import sysconfig;print(sysconfig.get_path('scripts'))"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _python_version(python: str) -> tuple:
    try:
        r = subprocess.run([python, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return tuple(int(x) for x in r.stdout.strip().split("."))
    except Exception:  # noqa: BLE001
        return (0, 0)


def resolve_python() -> str:
    """选目标解释器；结果缓存。可选 --python 覆盖（见 main）。"""
    global _PY_LIST
    if _PY_LIST:
        return _PY_LIST[0]
    path_env = os.environ.get("PATH", "").lower()
    scored = []
    for p in _candidate_pythons():
        sd = _scripts_dir(p).lower()
        scored.append((bool(sd) and sd in path_env, _python_version(p), p))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    _PY_LIST = [t[2] for t in scored]
    if not _PY_LIST:
        _die("找不到任何可用的 Python 解释器", 3)
    return _PY_LIST[0]


# ═══════════════════════════════════════════════════════════════════════
# 执行
# ═══════════════════════════════════════════════════════════════════════


def _search_dirs(python: str) -> list[str]:
    """CLI 可能落地的目录：解释器 Scripts + 用户级 site Scripts（pip 用户装时落这）。"""
    dirs = []
    sd = _scripts_dir(python)
    if sd:
        dirs.append(sd)
    try:
        r = subprocess.run([python, "-m", "site", "--user-base"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        ub = r.stdout.strip()
        if ub:
            dirs.append(os.path.join(ub, "Scripts"))
            v = _python_version(python)
            if all(v):
                dirs.append(os.path.join(ub, f"Python{v[0]}{v[1]}", "Scripts"))
    except Exception:  # noqa: BLE001
        pass
    appdata = os.environ.get("APPDATA", "")
    v = _python_version(python)
    if appdata and all(v):
        dirs.append(os.path.join(appdata, "Python", f"Python{v[0]}{v[1]}", "Scripts"))
    return dirs


def _find_cli(name: str, python: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    for d in _search_dirs(python):
        for ext in (".exe", ".cmd", ".bat", ""):
            cand = os.path.join(d, name + ext)
            if os.path.isfile(cand):
                return cand
    return None


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _fill(argv: list[str], python: str, dir_: str | None) -> list[str]:
    """占位符替换。{dir} 只认「整个元素就是 {dir}」的写法，永远作为独立 argv
    元素落地 —— 拼进更大的串（尤其 -c 的源码文本）时目录里一个引号就能逃逸
    成可执行代码，故此处直接拒绝，属结构性保证而非约定。"""
    out = []
    for a in argv:
        a = a.replace("{python}", python)
        if "{dir}" in a:
            if a != "{dir}":
                raise ValueError(f"配方非法：{{dir}} 只能单独成一个参数，不可拼进 {a!r}")
            if not dir_:
                raise ValueError("需要 --dir")
            a = dir_
        out.append(a)
    return out


def _err_tail(proc) -> str:
    """从输出里挑「像错误的那一行」（跳过进度条碎片）。"""
    text = ((proc.stderr or "") + "\n" + (proc.stdout or "")).replace("\r", "\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    bad = [l for l in lines
           if re.search(r"error|失败|failed|could not|no matching|not found|traceback", l, re.I)]
    pick = bad[-1] if bad else (lines[-1] if lines else "")
    return pick[:140]


def _run(argv: list[str], *, cwd: str | None = None, timeout: int = 600):
    exe = shutil.which(argv[0]) or argv[0]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        # Windows 通病：CreateProcess 不认 .cmd shim（npm/npx 等），走 cmd /c
        # —— 仅限参数简单的工具；带换行/怪引号的命令不用此路径
        exe = [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe]
    else:
        exe = [exe]
    return subprocess.run([*exe, *argv[1:]], cwd=cwd, timeout=timeout,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def check_tool(tool: Tool, python: str, dir_: str | None = None) -> dict:
    """单个体检 → {"id","state","version","detail"}；state: ok | missing | no_dir"""
    if tool.needs_dir and not dir_:
        return {"id": tool.id, "state": "no_dir", "version": None, "detail": "需要 --dir（工程目录）"}
    try:
        if tool.check[0].startswith("@pyfn:"):
            name = tool.check[0].split(":", 1)[1]
            if name == "shell":  # 依赖工程目录（无 dir 已在前面返回 no_dir）
                import glob
                g = glob.glob(os.path.join(dir_, "node_modules", ".remotion", "**",
                                           "chrome-headless-shell*"), recursive=True)
                return {"id": tool.id, "state": "ok" if g else "missing",
                        "version": "已缓存" if g else None, "detail": None}
            ok, detail = _PYFN[name]()
            return {"id": tool.id, "state": "ok" if ok else "missing",
                    "version": detail if ok else None, "detail": None}
        argv = _fill(tool.check, python, dir_)
        if not os.path.isabs(argv[0]):
            found = _find_cli(argv[0], python)
            if found:
                argv[0] = found
        proc = _run(argv, timeout=120)
        if proc.returncode == 0:
            first = (proc.stdout or proc.stderr or "").strip().splitlines()
            return {"id": tool.id, "state": "ok",
                    "version": (first[0].strip()[:70] if first else "已装"), "detail": None}
        return {"id": tool.id, "state": "missing", "version": None, "detail": None}
    except FileNotFoundError:
        return {"id": tool.id, "state": "missing", "version": None, "detail": None}
    except Exception as e:  # noqa: BLE001
        return {"id": tool.id, "state": "missing", "version": None, "detail": f"{type(e).__name__}: {e}"}


def check_all(python: str, dir_: str | None = None, only: list[str] | None = None) -> list[dict]:
    """全量体检。每条结果带回元信息（name/group/group_name/desc/big），供面板与接口直接渲染。"""
    tools = [t for t in TOOLS if not only or t.id in only]
    out = []
    for t in tools:
        r = check_tool(t, python, dir_)
        r.update({"name": t.name, "group": t.group,
                  "group_name": GROUP_NAMES.get(t.group, t.group),
                  "desc": t.desc, "big": bool(t.big)})
        out.append(r)
    return out


# 读改写整个在一次 PowerShell 里做完：既避免读/写之间的竞态，也保证类型不被降级。
# 不能用 [Environment]::GetEnvironmentVariable('Path','User')：它读 REG_EXPAND_SZ 时会把
# %USERPROFILE% 这类引用**展开**成字面路径；而 SetEnvironmentVariable 写回是 REG_SZ。
# 两者一合，用户 PATH 里原有的间接引用就被永久压平、值类型也降级了（换机器/漫游配置即失效）。
# 这里用 DoNotExpandEnvironmentNames 取原值，写回时沿用原来的 ValueKind。
# 代价：不再广播 WM_SETTINGCHANGE，已开着的 Explorer/终端看不到更新 —— 与调用方
# 「新进程生效」的提示一致，新开的终端启动时直接读注册表，不受影响。
_PS_APPEND_USER_PATH = r"""
$ErrorActionPreference = 'Stop'
$key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
if ($null -eq $key) { exit 2 }
try {
    if ($key.GetValueNames() -contains 'Path') {
        $raw  = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $kind = $key.GetValueKind('Path')
    } else {
        $raw  = ''
        $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    }
    $want = $env:EASEL_NEW_DIR.TrimEnd('\', '/')
    foreach ($p in ($raw -split ';')) {
        if ($p -and $p.TrimEnd('\', '/') -eq $want) { exit 3 }
    }
    $sep = if ($raw -and -not $raw.EndsWith(';')) { ';' } else { '' }
    $key.SetValue('Path', ($raw + $sep + $env:EASEL_NEW_DIR), $kind)
    exit 0
} finally { $key.Close() }
"""


def _ensure_user_path(d: str) -> str:
    """把目录追加进用户 PATH（幂等）。返回 changed | present | fail | skip。

    只有 Windows 才有「用户级持久 PATH」这回事；别的平台直接 skip（不碰、也不
    往 detail 里塞失败串）。
    """
    if os.name != "nt":
        return "skip"
    ps = shutil.which("powershell") or "powershell"
    try:
        # 目录走子进程环境变量递过去，绝不拼进脚本串：PATH 里只要有一个单引号，
        # 拼串写法就会截断字面量、后半截被当 PowerShell 代码执行
        proc = subprocess.run(
            [ps, "-NoProfile", "-Command", _PS_APPEND_USER_PATH],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, env={**os.environ, "EASEL_NEW_DIR": d})
        return {0: "changed", 3: "present"}.get(proc.returncode, "fail")
    except Exception:  # noqa: BLE001
        return "fail"


def install_tool(tool: Tool, python: str, dir_: str | None = None) -> dict:
    """一键装：策略链依次尝试 → 装完重跑 check，认到才算成。"""
    if tool.needs_dir and not dir_:
        _die(f"{tool.id} 需要 --dir <工程目录>（{tool.desc}）", 3)
    if tool.needs_dir and not (Path(dir_) / "package.json").is_file():
        _die(f"{dir_} 里没有 package.json，不是 Remotion 工程目录", 3)

    pre = check_tool(tool, python, dir_)
    if pre["state"] == "ok":
        note = _ensure_cli_visible(tool, python)
        print(f"✓ {tool.name} 已装，跳过（{pre['version']}）{note}", file=sys.stderr)
        return {"id": tool.id, "state": "ok", "version": pre["version"],
                "strategy": "已装", "detail": note or None}

    print(f"▶ 安装 {tool.name}（{tool.desc}）", file=sys.stderr)
    last_err = ""
    for label, argv, *rest in tool.install:
        timeout = int(rest[0]) if rest else 600
        argv_f = _fill(argv, python, dir_)
        print(f"  → 策略：{label}", file=sys.stderr)
        try:
            proc = _run(argv_f, cwd=dir_ if tool.needs_dir else None, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last_err = f"{label}: {type(e).__name__}: {e}"
            print(f"    ✗ {last_err}", file=sys.stderr)
            continue
        if proc.returncode != 0:
            last_err = f"{label}: 退出码 {proc.returncode}" + (f" · {_err_tail(proc)}" if _err_tail(proc) else "")
            print(f"    ✗ {last_err}", file=sys.stderr)
            continue
        state = check_tool(tool, python, dir_)
        if state["state"] == "ok":
            note = _ensure_cli_visible(tool, python)
            print(f"    ✓ {label} 完成{note}", file=sys.stderr)
            return {"id": tool.id, "state": "ok", "version": state["version"],
                    "strategy": label, "detail": note or None}
        last_err = f"{label}: 装完校验未通过（{state['detail'] or 'check 未认到'}）"
        print(f"    ✗ {last_err}", file=sys.stderr)

    return {"id": tool.id, "state": "fail", "version": None,
            "strategy": None, "detail": last_err or "未知失败"}


def _ensure_cli_visible(tool: Tool, python: str) -> str:
    """CLI 类工具：装了但 PATH 上看不见时，把落地目录追加进用户 PATH（幂等）。"""
    if tool.check[0].startswith(("@", "{python}")):
        return ""
    found = shutil.which(tool.id) or _find_cli(tool.id, python)
    if not found:
        return ""
    d = os.path.dirname(found)
    r = _ensure_user_path(d)
    if r == "changed":
        return f"（已把 {d} 追加进用户 PATH，新进程生效）"
    if r == "fail":
        return f"（CLI 在 {found}，PATH 追加失败，请手动加 {d}）"
    return ""


# ═══════════════════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════════════════

_MARK = {"ok": "✓", "missing": "✗", "no_dir": "·", "fail": "✗"}


def print_table(results: list[dict], python: str) -> None:
    by_id = {t.id: t for t in TOOLS}
    print(f"══ 环境体检（目标解释器：{python}）══")
    cur_group = None
    for r in results:
        t = by_id[r["id"]]
        if t.group != cur_group:
            cur_group = t.group
            print(f"\n[{GROUP_NAMES.get(cur_group, cur_group)}]")
        ver = f" · {r['version']}" if r.get("version") else ""
        note = "" if r["state"] in ("ok", "missing") else f"（{r.get('detail') or ''}）"
        print(f"  {_MARK.get(r['state'], '?')} {t.id:<9} {t.name}{ver}{note}")
    ok = sum(1 for r in results if r["state"] == "ok")
    print(f"\n就绪 {ok} / {len(results)}")


# ═══════════════════════════════════════════════════════════════════════
# 命令
# ═══════════════════════════════════════════════════════════════════════


def cmd_list(a) -> int:
    python = a.python or resolve_python()
    if a.json:
        print(json.dumps({"tools": [t.__dict__ for t in TOOLS]}, ensure_ascii=False, default=str))
        return 0
    for gid, gname in GROUP_NAMES.items():
        print(f"[{gname}]")
        for t in TOOLS:
            if t.group == gid:
                big = "（大件）" if t.big else ""
                print(f"  {t.id:<9} {t.name:<22} {t.desc}{big}")
    return 0


def cmd_check(a) -> int:
    python = a.python or resolve_python()
    results = check_all(python, a.dir, a.ids or None)
    if a.json:
        print(json.dumps({"python": python, "tools": results}, ensure_ascii=False))
    else:
        print_table(results, python)
    return 0


def cmd_install(a) -> int:
    python = a.python or resolve_python()
    by_id = {t.id: t for t in TOOLS}
    bad = [i for i in a.ids if i not in by_id]
    if bad:
        _die(f"不认识的工具：{'、'.join(bad)}（可用：{'、'.join(by_id)}）", 3)
    results = []
    for tid in a.ids:
        results.append(install_tool(by_id[tid], python, a.dir))
    if a.json:
        print(json.dumps({"python": python, "results": results}, ensure_ascii=False))
    else:
        for r in results:
            ok = r["state"] == "ok"
            print(f"{'✅' if ok else '❌'} {r['id']}"
                  + (f" · {r['version']}" if ok and r.get('version') else "")
                  + ("" if ok else f" · {r.get('detail')}"), file=sys.stderr)
    return 0 if all(r["state"] == "ok" for r in results) else 1


def cmd_selftest(_a) -> int:
    print("install_tool 自检 ...", file=sys.stderr)
    ids = [t.id for t in TOOLS]
    assert len(ids) == len(set(ids)), "工具 id 重复"
    assert set(t.group for t in TOOLS) <= set(GROUP_NAMES), "未知分组"
    for t in TOOLS:
        assert t.check and (t.check[0].startswith("@pyfn:") or len(t.check) >= 1), f"{t.id} check 异常"
        assert t.install, f"{t.id} 无安装策略"
        if t.check[0].startswith("@pyfn:"):
            _cn = t.check[0].split(":", 1)[1]
            assert _cn in _PYFN or _cn == "shell", f"{t.id} 引用了不存在的检查函数"
    py = resolve_python()
    assert os.path.isfile(py), "解析出的解释器不存在"
    sd = _scripts_dir(py)
    assert sd, "拿不到 Scripts 目录"
    # 体检冒烟（其中一个必须可跑通流程，不装任何东西）
    r = check_tool(TOOLS[0], py)
    assert r["state"] in ("ok", "missing"), f"check 状态异常：{r}"
    print(f"✅ selftest 通过（{len(TOOLS)} 个配方 · 解释器 {py}）", file=sys.stderr)
    return 0


def main() -> int:
    # 输出里全是中文。Windows 上 stdout 一旦是管道（被面板/agent 捕获），Python 就按
    # 系统 locale 编码（cp936/cp1252）写，配方表里的中文直接 UnicodeEncodeError 崩掉，
    # stdout 一个字节都不出 —— 调用方拿到空串，只会以为「配方表是空的」。
    # 面板的安装接口就是这么被整条废掉的：id 白名单永远为空，装什么都报「无效的工具 id」。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # 被重定向成非 TextIOWrapper 时忽略
            pass

    ap = argparse.ArgumentParser(
        description="环境工具一键安装器（检测 → 一键装 → 装后校验）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", help="目标解释器路径（默认自动解析：优先 PATH 可见者）")
    ap.add_argument("--json", action="store_true", help="机读输出（stdout 一个 JSON）")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="配方总览").set_defaults(func=cmd_list)

    pc = sub.add_parser("check", help="体检")
    pc.add_argument("ids", nargs="*", help="工具 id（默认全量）")
    pc.add_argument("--dir", help="工程目录（rmdeps / shell 用）")
    pc.set_defaults(func=cmd_check)

    pi = sub.add_parser("install", help="一键安装")
    pi.add_argument("ids", nargs="+", help="工具 id")
    pi.add_argument("--dir", help="工程目录（rmdeps / shell 用）")
    pi.set_defaults(func=cmd_install)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    for _p in sub.choices.values():  # --json 放在子命令后也认
        _p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="机读输出（与全局 --json 等效）")

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
