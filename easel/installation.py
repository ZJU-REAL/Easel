"""Initialize optional harness selection without replacing user settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from easel.harnesses import store


def initialize_runtime(root: Path, default: str = "api") -> str:
    if default not in store.IDS:
        raise ValueError("未知默认执行引擎")
    config_path = root / "outputs" / "_harness" / "config.json"
    config = store.read_json(config_path)
    if "runtime" in config:
        return store.settings(root / "outputs", {})["runtime"]
    env_path = root / ".env"
    environment = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                environment[key.strip()] = value.strip().strip("\"'")
    environment.update(os.environ)
    if "EASEL_AGENT_RUNTIME" in environment:
        return store.settings(root / "outputs", environment)["runtime"]
    store.settings(root / "outputs", {"EASEL_AGENT_RUNTIME": default})
    store.write_json(config_path, {**config, "runtime": default})
    return default


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("用法：python -m easel.installation <Easel 目录> <默认执行引擎>")
    runtime = initialize_runtime(Path(sys.argv[1]), sys.argv[2])
    print(f"执行引擎设置已就绪：{runtime}；可进入 Web 设置选择已安装的底座")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
