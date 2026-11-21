"""Inspect a local Remotion project separately from Easel's bundled template."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from easel.timeouts import TIMEOUT_REMOTION_PROBE
from .harnesses.store import read_json, write_json

PACKAGES = ("remotion", "@remotion/cli", "@remotion/renderer", "react", "react-dom")


def project_info(directory: Path) -> dict:
    """Inspect manifests without running code from a candidate project."""
    root = directory.resolve()
    versions = {}
    missing = []
    stamp = hashlib.sha256(os.fsencode(root))
    for name in PACKAGES:
        manifest = root / "node_modules" / name / "package.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("name") != name or not isinstance(data.get("version"), str):
                raise ValueError()
            versions[name] = data["version"]
            stamp.update(str((name, data["version"], manifest.stat().st_mtime_ns)).encode())
        except (OSError, ValueError, AttributeError):
            missing.append(name)
    cli = root / "node_modules/@remotion/cli/remotion-cli.js"
    complete = not missing and cli.is_file() and (root / "package.json").is_file()
    if complete:
        for file in (root / "package.json", cli):
            stamp.update(str((file.stat().st_size, file.stat().st_mtime_ns)).encode())
    match = complete and len({versions[name] for name in PACKAGES[:3]}) == 1
    return {"path": str(root), "version": versions.get("remotion"), "ready": bool(match),
            "missing": missing, "fingerprint": stamp.hexdigest(),
            "detail": "" if match else ("缺少 " + "、".join(missing) if missing else
                                      "请检查工程清单、CLI 入口及 Remotion 组件版本是否一致")}


def discover(root: Path, env: dict[str, str]) -> dict:
    config = read_json(root / "outputs/_harness/remotion.json")
    candidates = [config.get("path"), env.get("REMOTION_PROJECT")]
    candidates.append(str(root / "skills/builtin/video-production/vendor/video-pipeline-sdk/deps/remotion"))
    for item in env.get("PATH", "").split(os.pathsep):
        directory = Path(item)
        if directory.name == ".bin" and directory.parent.name == "node_modules":
            candidates.append(str(directory.parent.parent))
    projects = []
    seen = set()
    for value in filter(None, candidates):
        candidate = Path(value)
        candidate = candidate.resolve()
        if candidate in seen or not (candidate / "node_modules/remotion/package.json").is_file():
            continue
        seen.add(candidate)
        projects.append(project_info(candidate))
    selected = str(Path(config["path"]).resolve()) if config.get("path") else ""
    current = next((item for item in projects if item["path"] == selected), None)
    if selected and current is None:
        current = project_info(Path(selected))
    verified = read_json(root / "outputs/_harness/remotion-probe.json")
    return {"projects": projects, "selected": current, "probe": verified if current and
            current["ready"] and verified.get("fingerprint") == current["fingerprint"] else None}


def environment(root: Path, env: dict[str, str]) -> dict[str, str]:
    config = read_json(root / "outputs/_harness/remotion.json")
    preference = config.get("path")
    if not preference:
        return env
    return {**env, "REMOTION_PROJECT": preference}


def render_frame(root: Path, env: dict[str, str]) -> dict:
    current = discover(root, env)["selected"]
    if not current or not current["ready"]:
        raise ValueError("先选择依赖齐全的本机 Remotion 工程")
    report_path = root / "outputs/_harness/remotion-probe.json"
    report_path.unlink(missing_ok=True)
    project = Path(current["path"])
    modules = project / "node_modules"
    node = shutil.which("node", path=env.get("PATH"))
    if not node:
        raise ValueError("找不到 Node.js 运行时")
    with tempfile.TemporaryDirectory(prefix="easel-frame-") as tmp:
        entry = Path(tmp) / "probe.jsx"
        # Resolve imports against the selected installation, keeping the test entry outside the project.
        entry.write_text("import React from " + json.dumps((modules / "react").as_posix()) +
                         ";\nimport {AbsoluteFill,Composition,registerRoot} from " +
                         json.dumps((modules / "remotion").as_posix()) +
                         ";\nconst Probe=()=> <AbsoluteFill style={{background:'#343e78'}}/>;\n"
                         "registerRoot(()=> <Composition id='EaselProbe' component={Probe} "
                         "durationInFrames={1} fps={24} width={160} height={90}/>);", encoding="utf-8")
        target = Path(tmp) / "frame.png"
        result = subprocess.run([node, str(modules / "@remotion/cli/remotion-cli.js"),
                                 "still", str(entry), "EaselProbe", str(target), "--frame=0", "--log=error"],
                                cwd=project, env=env, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=TIMEOUT_REMOTION_PROBE)
        if result.returncode or not target.is_file():
            lines = [s for s in (result.stderr or result.stdout or "").splitlines() if s.strip()]
            detail = next((s for s in lines if "error" in s.lower()), lines[0] if lines else "")
            raise ValueError("渲染失败。 " + detail[:250])
        from PIL import Image
        with Image.open(target) as frame:
            frame.load()
            if frame.format != "PNG" or frame.size != (160, 90):
                raise ValueError("渲染器未生成预期尺寸的 PNG")
    report = {"fingerprint": current["fingerprint"], "time": int(time.time()), "size": "160 × 90"}
    write_json(report_path, report)
    return report
