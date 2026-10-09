"""Resolve how to invoke the openclaw CLI as an argv prefix.

Windows pitfall this solves: `openclaw` on PATH is a `.cmd` shim. Python's
CreateProcess cannot run it directly, and wrapping in cmd.exe /c breaks
messages containing newlines (cmd treats the rest of the line as a separate
command -> "your message got cut off" / silently truncated input). Running
`node openclaw.mjs` directly avoids both problems.

On Linux/macOS `openclaw` on PATH is a real executable (a symlink to
`openclaw.mjs` with a `#!/usr/bin/env node` shebang), so running it directly
is fine. The resolution below therefore prefers `node + openclaw.mjs` when it
can locate the script (robust everywhere, mandatory on Windows), and falls
back to the PATH `openclaw` executable rather than hard-failing.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path


def _npmrc_prefix(path: Path) -> Path | None:
    """从 .npmrc 读 prefix=（支持 #/; 注释与尾随空白）；文件不存在或未配置返回 None。"""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith(("prefix=", "prefix =")):
                val = s.split("=", 1)[1].strip().strip('"')
                if val:
                    p = Path(val).expanduser()
                    return p.resolve() if p.is_absolute() else p
    except OSError:
        pass
    return None


@lru_cache(maxsize=1)
def openclaw_base_cmd() -> list[str]:
    """Return the argv prefix for invoking openclaw.

    Prefers ``[node, /path/to/openclaw.mjs]``; falls back to ``[openclaw]`` on
    PATH. Raises FileNotFoundError only when openclaw cannot be located at all.
    """
    node = shutil.which("node")
    oc = shutil.which("openclaw")

    # 1) PATH `openclaw` that resolves to the .mjs (Unix symlink, or a direct
    #    .mjs on PATH): run it through node explicitly.
    if oc and node:
        resolved = Path(oc).resolve()
        if resolved.suffix == ".mjs" and resolved.is_file():
            return [node, str(resolved)]

    # 1.5) PATH `openclaw` is a Windows npm .cmd shim: the shim sits next to
    #      node.exe + node_modules/openclaw/openclaw.mjs (standard npm global
    #      layout — see the shim body). Running the shim routes the argv through
    #      cmd.exe, which truncates a multiline `--message` at the first newline
    #      ("消息只剩第一行/画像前缀" 的根因，实测于 PATH 里 nvm node 在前的机器)。
    #      这里解析出 shim 同目录的真实 node + .mjs，完全绕开 cmd.exe。
    if oc:
        shim = Path(oc).resolve()
        if shim.suffix.lower() in (".cmd", ".bat"):
            shim_dir = shim.parent
            mjs = shim_dir / "node_modules" / "openclaw" / "openclaw.mjs"
            node_exe = shim_dir / "node.exe"
            if mjs.is_file() and node_exe.is_file():
                return [str(node_exe), str(mjs)]

    # 2) Hunt for openclaw.mjs under the known npm global layouts.
    if node:
        node_dir = Path(node).resolve().parent
        candidates = [
            # Unix standard: <prefix>/bin/node -> <prefix>/lib/node_modules/...
            node_dir.parent / "lib" / "node_modules" / "openclaw" / "openclaw.mjs",
            # npm global prefix == node dir (zip / some nvm-style installs)
            node_dir / "node_modules" / "openclaw" / "openclaw.mjs",
            # Windows standard: npm global prefix == %APPDATA%/npm
            Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "openclaw" / "openclaw.mjs",
        ]
        for cand in candidates:
            if cand.is_file():
                return [node, str(cand)]

        # npm 自定义全局前缀（官方推荐的免 sudo 装法 `npm config set prefix
        # ~/.npm-global`）：此时 node 在系统路径、openclaw 在用户前缀下 ——
        # 上面的 node 相对布局全部落空。按可靠性逐级探测：
        # 显式环境变量 > .npmrc 的 prefix 键（项目级覆盖用户级，与 npm 同序）
        # > npm_config_prefix 环境变量（仅在 npm 脚本环境导出）> ~/.npm-global 约定。
        prefix_roots: list[Path] = []
        explicit = os.environ.get("EASEL_NPM_GLOBAL_PREFIX", "").strip()
        if explicit:
            prefix_roots.append(Path(explicit))
        npm_cfg = os.environ.get("npm_config_prefix", "").strip()
        if npm_cfg:
            prefix_roots.append(Path(npm_cfg))
        for npmrc in (Path(".npmrc"), Path.home() / ".npmrc"):
            val = _npmrc_prefix(npmrc)
            if val:
                prefix_roots.append(val)
        prefix_roots.append(Path.home() / ".npm-global")
        for root in prefix_roots:
            for cand in (
                root / "lib" / "node_modules" / "openclaw" / "openclaw.mjs",
                root / "node_modules" / "openclaw" / "openclaw.mjs",
            ):
                if cand.is_file():
                    return [node, str(cand)]

    # 3) Fallback: run the PATH `openclaw` directly. On Unix this is a real
    #    executable and works. On Windows this is the `.cmd` shim (only reached
    #    when the .mjs truly can't be found) — still better than hard-failing.
    if oc:
        return [oc]

    raise FileNotFoundError(
        "openclaw CLI not found: no 'node'+openclaw.mjs and no 'openclaw' on PATH。"
        "请先安装：npm i -g openclaw（若用自定义全局前缀，可设 EASEL_NPM_GLOBAL_PREFIX 指向该前缀）"
    )
