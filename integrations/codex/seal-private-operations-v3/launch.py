#!/usr/bin/env python3
"""启动 Seal 私人运营顾问 V3 独立工作台。

该入口只加载本 Skill 的 runtime，不读取或写入 V2。
默认监听 127.0.0.1:7862，可通过 SEAL_HOST/SEAL_PORT 覆盖。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

# 所有运行状态和浏览器登录目录均隔离在 V3 runtime 下。
os.environ.setdefault("SEAL_SKILL_ROOT", str(ROOT))
os.environ.setdefault("SEAL_RUNTIME_ROOT", str(RUNTIME))
os.environ.setdefault("SEAL_BUNDLED_SKILLS", str(ROOT / "bundled-skills"))
os.environ.setdefault("EASEL_BROWSER_PROFILES", str(ROOT / "runtime" / "browser-profiles"))
os.environ.setdefault("EASEL_XHS_PROXY_MODE", "direct")
os.environ.setdefault("REDBOOK_STATE_DIR", str(RUNTIME / "browser-profiles" / "redbook"))
os.environ.setdefault("REDBOOK_COOKIE_FILE", str(RUNTIME / "browser-profiles" / "redbook" / "cookies.json"))

# 让工作台及其启动的 Codex 子进程在两个系统上都优先使用 V3 自带的
# Python/Node 命令和安装时选定的 FFmpeg，不依赖调用终端是否激活虚拟环境。
from easel.paths import runtime_path_entries

os.environ["PATH"] = os.pathsep.join((*runtime_path_entries(), os.environ.get("PATH", "")))

try:
    import uvicorn
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少 uvicorn，请先运行本 Skill 对应平台的安装脚本") from exc

if __name__ == "__main__":
    host = os.getenv("SEAL_HOST", "127.0.0.1")
    port = int(os.getenv("SEAL_PORT", "7862"))
    uvicorn.run("web.app:app", host=host, port=port, reload=False, log_level="info")
