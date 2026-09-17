#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频产线 SDK · 单入口（接口契约 v0.2）

run.py 是产线的唯一机器入口：stage 机 + 两道确认门 + 退出码。
宿主（Easel 等）只经本文件与 questions/answers 协议调用，不碰 SDK 内部件。

退出码：0 完成 ｜ 1 异常 ｜ 2 门失败 ｜ 3 待审批/待作答（附 questions/*.json）

用法：
  python pipeline/run.py doctor                                  # 环境自检
  python pipeline/run.py init --source S --out O [--brief B] [--transcript T] [--scenes C] [--config F] [--run-dir R]
  python pipeline/run.py stage <name> [--run-dir R]              # 单步执行
  python pipeline/run.py run [--through STAGE] [--run-dir R]     # 连跑；遇问题/审批停
  python pipeline/run.py resume [--approve design-table|preview] [--note "..."] [--run-dir R]
  python pipeline/run.py gates [--run-dir R]                     # 七件门聚合
  python pipeline/run.py ask --emit|--serve [--port 8898] [--run-dir R]
  python pipeline/run.py status [--run-dir R]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.3.3"

EXIT_OK, EXIT_ERR, EXIT_GATE, EXIT_AWAIT = 0, 1, 2, 3

STAGES = ["ingest", "transcribe", "scenes", "design-table", "scaffold",
          "build", "verify", "preview", "render", "deliver"]
CHECKPOINTS = {"design-table": "checkpoint-1", "preview": "checkpoint-2"}
# 需要执行者产出、机器只校验在档的步骤
EXECUTOR_ARTIFACTS = {
    "scenes": ("artifacts/scenes.json", "分场结构 JSON（scenes）。可先在 RUNBOOK Step 4 起草后拷入。"),
    "design-table": ("artifacts/design-table.md", "设计表（design-table.md）。模板见 pipeline/RUNBOOK.md Step 5。"),
    "build": (None, "写码产物。执行者完成后 `touch workdir/.build-ok` 标记（或配置 stages.build.cmd）。"),
    "render": (None, "渲染产物 final.mp4。配置 stages.render.cmd 后由机器执行；或执行者手动渲染后拷入 workdir/out/final.mp4。"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[run] {msg}", flush=True)


def die(msg: str, code: int = EXIT_ERR):
    print(f"[run][error] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ---------------------------------------------------------------- state ----

def state_path(rd: Path) -> Path:
    return rd / "run-state.json"


def load_state(rd: Path) -> dict:
    if not state_path(rd).is_file():
        die(f"找不到运行态：{state_path(rd)}（先跑 init）")
    return json.loads(state_path(rd).read_text(encoding="utf-8"))


def save_state(rd: Path, st: dict) -> None:
    st["updated"] = now_iso()
    state_path(rd).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------- question ----

def emit_question(rd: Path, q: dict) -> Path:
    """写一道待作答问题（协议见 design §4.1）。"""
    q.setdefault("allow_notes", True)
    q["emitted_at"] = now_iso()
    p = rd / "questions" / f"{q['id']}.json"
    p.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"待作答：{q['id']}（{q.get('type')}）→ {p}")
    return p


def read_answer(rd: Path, qid: str) -> dict | None:
    p = rd / "answers" / f"{qid}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def pending_questions(rd: Path) -> list[dict]:
    out = []
    for p in sorted((rd / "questions").glob("*.json")):
        if read_answer(rd, p.stem) is None and load_json_quiet(p):
            out.append(load_json_quiet(p))
    return out


def load_json_quiet(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ------------------------------------------------------------------ util ----

def _shell_cmd(cmd: str) -> list:
    """字符串命令显式走宿主 shell：Windows 用 cmd.exe（COMSPEC 未必可靠），其余 /bin/sh。"""
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC", "")
        if "cmd.exe" not in comspec.lower():
            comspec = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
        return [comspec, "/c", cmd]
    return ["/bin/sh", "-c", cmd]


def passthrough(cmd: list) -> int:
    """直通执行（stdout/stderr 不捕获，给 doctor/gates/ask 这类交互输出用）。"""
    return subprocess.call(cmd)


def run_cmd(cmd, cwd=None, log_path: Path | None = None, timeout: int | None = None) -> tuple[int, str]:
    """执行命令，返回 (exit_code, 合并输出)。stdout+stderr 一并捕获；log_path 存在则落盘。"""
    if isinstance(cmd, str):
        cmd = _shell_cmd(cmd)
    env = dict(os.environ)
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        code = r.returncode
    except FileNotFoundError as e:
        return 127, f"命令不存在：{e}"
    except subprocess.TimeoutExpired:
        return 124, f"命令超时（{timeout}s）"
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n$ {' '.join(cmd) if isinstance(cmd, list) else cmd}\n{out}\n[exit {code}]\n")
    return code, out


def stage_cfg(state: dict, name: str) -> dict:
    return ((state.get("config") or {}).get("stages") or {}).get(name) or {}


# ---------------------------------------------------------------- stages ----

def st_ingest(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    src = st["source"]
    art = rd / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    code, out = run_cmd(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", src],
                        log_path=rd / "logs" / "ingest.log")
    if code != 0:
        return "error", f"ffprobe 失败：{out[:300]}"
    probe = json.loads(out)
    (art / "probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
    dur = float(probe.get("format", {}).get("duration") or 0)
    v = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    fps = v.get("r_frame_rate", "0/1")
    try:
        n, d = fps.split("/"); fps_f = float(n) / float(d or 1)
    except Exception:
        fps_f = 0.0
    frames_dir = art / "frames"
    frames_dir.mkdir(exist_ok=True)
    ts = sorted({round(max(0.05, dur * 0.05), 2), round(dur * 0.5, 2), round(max(0.1, dur * 0.95), 2)})
    for t in ts:
        run_cmd(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", str(frames_dir / f"f{t:.2f}.png")],
                log_path=rd / "logs" / "ingest.log")
    proxy = None
    if (st.get("config") or {}).get("proxy", True) and dur > 1:
        pp = art / "proxy.mp4"
        if not pp.exists():
            code, out = run_cmd(["ffmpeg", "-y", "-i", src, "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "veryfast",
                                 "-crf", "24", "-c:a", "aac", "-b:a", "160k", str(pp)],
                                log_path=rd / "logs" / "ingest.log")
            if code != 0:
                return "error", f"代理转码失败：{out[:300]}"
        proxy = "artifacts/proxy.mp4"
    (art / "ingest.json").write_text(json.dumps({
        "source": src, "duration": dur, "fps": fps_f, "width": v.get("width"), "height": v.get("height"),
        "codec": v.get("codec_name"), "frames": [f"artifacts/frames/{p.name}" for p in sorted(frames_dir.glob("*.png"))],
        "proxy": proxy, "at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return "done", f"摸底完成 {dur:.2f}s · {v.get('width')}x{v.get('height')} @{fps_f:.2f}fps"


def st_transcribe(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    art = rd / "artifacts"; art.mkdir(exist_ok=True)
    tgt = art / "transcript.json"
    prov = (st.get("config") or {}).get("transcript")
    if prov:
        p = Path(prov)
        if not p.is_file():
            return "error", f"转录稿不存在：{p}"
        if p.suffix.lower() == ".json":
            shutil.copy(p, tgt)
        else:
            tgt.write_text(json.dumps({"text": p.read_text(encoding="utf-8"), "source": str(p)},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
        return "done", f"转录稿就位：{tgt.name}"
    src = str(rd / "artifacts" / "proxy.mp4") if (rd / "artifacts" / "proxy.mp4").exists() else st["source"]
    code, out = run_cmd([sys.executable, str(SDK_ROOT / "tools" / "transcribe.py"),
                         "--src", src, "--out", str(tgt)],
                        log_path=rd / "logs" / "transcribe.log")
    if code != 0:
        return "error", f"转录失败（需 faster-whisper + 模型；或 init 时给 --transcript）：{out[-300:]}"
    return "done", "转录完成"


def st_scenes(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    art = rd / "artifacts"; art.mkdir(exist_ok=True)
    tgt = art / "scenes.json"
    if tgt.exists():
        (rd / "questions" / "need-scenes.json").unlink(missing_ok=True)
        return "done", "分场结构在档"
    prov = (st.get("config") or {}).get("scenes")
    if prov and Path(prov).is_file():
        shutil.copy(prov, tgt)
        return "done", "分场结构就位（来自 --scenes）"
    emit_question(rd, {
        "id": "need-scenes", "type": "free-text", "gate": None,
        "title": "需要分场结构（scenes.json）",
        "description": EXECUTOR_ARTIFACTS["scenes"][1] + f"\n产出后放入：{tgt}",
    })
    return "await", "待执行者提供分场结构"


def st_design_table(ctx: dict) -> tuple[str, str]:
    rd = ctx["rd"]
    art = rd / "artifacts"
    tgt = art / "design-table.md"
    if tgt.exists():
        (rd / "questions" / "need-design-table.json").unlink(missing_ok=True)
    if not tgt.exists():
        emit_question(rd, {
            "id": "need-design-table", "type": "free-text", "gate": None,
            "title": "需要设计表（design-table.md）",
            "description": EXECUTOR_ARTIFACTS["design-table"][1] + f"\n产出后放入：{tgt}",
        })
        return "await", "待执行者提供设计表"
    ans = read_answer(rd, "checkpoint-1")
    if ans is None:
        emit_question(rd, {
            "id": "checkpoint-1", "type": "approval", "gate": "checkpoint-1",
            "title": "设计表确认（铁律门）", "allow_notes": True,
            "description": "看完设计表再放行；有意见写进备注，machine 会带回下一轮。",
            "options": [
                {"value": "approve", "label": "通过，按设计表开工"},
                {"value": "revise", "label": "带意见修改"},
                {"value": "reject", "label": "打回重做"},
            ],
        })
        return "await", "等待设计表确认（checkpoint-1）"
    vals = ans.get("values") or []
    (rd / "checkpoints" / "checkpoint-1.json").write_text(json.dumps(ans, ensure_ascii=False, indent=2), encoding="utf-8")
    if "approve" in vals:
        return "done", "设计表已确认"
    # revise / reject：记录意见并重新出题
    (rd / "questions" / "checkpoint-1.json").unlink(missing_ok=True)
    emit_question(rd, {
        "id": "checkpoint-1", "type": "approval", "gate": "checkpoint-1",
        "title": "设计表确认（第 2 轮）", "allow_notes": True,
        "description": f"上轮意见：{ans.get('notes') or '（无备注）'}",
        "options": [
            {"value": "approve", "label": "通过，按设计表开工"},
            {"value": "revise", "label": "带意见修改"},
            {"value": "reject", "label": "打回重做"},
        ],
    })
    return "await", "设计表未过，意见已带回（重新出题）"


def st_scaffold(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    wd = rd / "workdir"
    (wd / "src").mkdir(parents=True, exist_ok=True)
    (wd / "public").mkdir(parents=True, exist_ok=True)
    deps = SDK_ROOT / "deps" / "remotion"
    for f in ("package.json", "package-lock.json"):
        if (deps / f).is_file() and not (wd / f).exists():
            shutil.copy(deps / f, wd / f)
    if (st.get("config") or {}).get("scaffold_install"):
        code, out = run_cmd(["npm", "install"], cwd=wd, log_path=rd / "logs" / "scaffold.log")
        if code != 0:
            return "error", f"npm install 失败：{out[-300:]}"
    (rd / "artifacts" / "scaffold.json").write_text(json.dumps(
        {"workdir": str(wd), "deps": "deps/remotion", "install": bool((st.get("config") or {}).get("scaffold_install")),
         "at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return "done", f"workdir 就绪：{wd}"


def st_build(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    wd = rd / "workdir"
    cfg = stage_cfg(st, "build")
    if cfg.get("cmd"):
        code, out = run_cmd(cfg["cmd"], cwd=wd, log_path=rd / "logs" / "build.log", timeout=cfg.get("timeout"))
        if code != 0:
            return "error", f"build 命令失败：{out[-300:]}"
        (wd / ".build-ok").touch()
        return "done", "build 命令通过"
    if (wd / ".build-ok").exists():
        return "done", "build 标记在档"
    emit_question(rd, {
        "id": "need-build", "type": "free-text", "gate": None,
        "title": "等待写码与编译",
        "description": EXECUTOR_ARTIFACTS["build"][1] + f"\n或在 config.stages.build.cmd 配置编译命令。workdir：{wd}",
    })
    return "await", "待执行者写码/编译"


def _gate_fails(rd: Path, phase: str) -> list:
    rep_p = rd / "gate-report.json"
    if not rep_p.is_file():
        return None
    rep = json.loads(rep_p.read_text(encoding="utf-8"))
    return [g for g in rep.get("gates", []) if g.get("phase", "verify") == phase and g.get("status") == "FAIL"]


def st_verify(ctx: dict) -> tuple[str, str]:
    rd = ctx["rd"]
    code, out = run_cmd([sys.executable, str(SDK_ROOT / "gates" / "aggregate.py"), "--run-dir", str(rd), "--phase", "verify"],
                        log_path=rd / "logs" / "verify.log")
    fails = _gate_fails(rd, "verify")
    if fails is None:
        return "error", f"门聚合未产出报告（exit {code}）：{out[-300:]}"
    if not fails and not (rd / "gates.json").is_file():
        return "error", "未配置质量门（gates.json 缺失）——门不过不交付"
    if fails:
        return "gatefail", f"门失败：{', '.join(g.get('id', '?') for g in fails)}（报告：{rd / 'gate-report.md'}）"
    rep = json.loads((rd / "gate-report.json").read_text(encoding="utf-8"))
    n = sum(1 for g in rep.get("gates", []) if g.get("phase", "verify") == "verify")
    return "done", f"验证层门全过（{n} 项）"


def st_preview(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    cfg = stage_cfg(st, "preview")
    if cfg.get("cmd"):
        code, out = run_cmd(cfg["cmd"], cwd=rd / "workdir", log_path=rd / "logs" / "preview.log", timeout=cfg.get("timeout"))
        if code != 0:
            return "error", f"预览命令失败：{out[-300:]}"
    elif cfg.get("project") and cfg.get("comp"):
        (rd / "preview").mkdir(exist_ok=True)
        for fr in cfg.get("frames", [60, 300]):
            code, out = run_cmd(["npx", "remotion", "still", "src/index.ts", cfg["comp"],
                                 str(rd / "preview" / f"f{fr}.png"), f"--frame={fr}", "--gl=angle"],
                                cwd=cfg["project"], log_path=rd / "logs" / "preview.log")
            if code != 0:
                return "error", f"stills 抽取失败：{out[-300:]}"
    ans = read_answer(rd, "checkpoint-2")
    if ans is None:
        previews = [f"preview/{p.name}" for p in sorted((rd / "preview").glob("*.png"))]
        emit_question(rd, {
            "id": "checkpoint-2", "type": "approval", "gate": "checkpoint-2",
            "title": "预览确认（点头门）", "allow_notes": True,
            "description": "预览在 preview/ 目录（或本地 Studio）。点头继续全片渲染。",
            "previews": previews,
            "options": [
                {"value": "approve", "label": "通过，渲全片"},
                {"value": "revise", "label": "有场次要改"},
            ],
        })
        return "await", "等待预览确认（checkpoint-2）"
    vals = ans.get("values") or []
    (rd / "checkpoints" / "checkpoint-2.json").write_text(json.dumps(ans, ensure_ascii=False, indent=2), encoding="utf-8")
    if "approve" in vals:
        return "done", "预览已确认"
    (rd / "questions" / "checkpoint-2.json").unlink(missing_ok=True)
    emit_question(rd, {
        "id": "checkpoint-2", "type": "approval", "gate": "checkpoint-2",
        "title": "预览确认（第 2 轮）", "allow_notes": True,
        "description": f"上轮意见：{ans.get('notes') or '（无备注）'}",
        "options": [
            {"value": "approve", "label": "通过，渲全片"},
            {"value": "revise", "label": "有场次要改"},
        ],
    })
    return "await", "预览未过，意见已带回（重新出题）"


def st_render(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    cfg = stage_cfg(st, "render")
    out_mp4 = rd / "workdir" / "out" / "final.mp4"
    if cfg.get("cmd"):
        code, out = run_cmd(cfg["cmd"], cwd=rd / "workdir", log_path=rd / "logs" / "render.log", timeout=cfg.get("timeout"))
        if code != 0:
            return "error", f"渲染命令失败：{out[-300:]}"
    elif not out_mp4.exists():
        emit_question(rd, {
            "id": "need-render", "type": "free-text", "gate": None,
            "title": "等待全片渲染",
            "description": EXECUTOR_ARTIFACTS["render"][1] + f"\n期望位置：{out_mp4}",
        })
        return "await", "待渲染"
    # 渲染后门（响度 / 同步等）
    run_cmd([sys.executable, str(SDK_ROOT / "gates" / "aggregate.py"), "--run-dir", str(rd), "--phase", "render"],
            log_path=rd / "logs" / "render-gates.log")
    fails = _gate_fails(rd, "render") or []
    if fails:
        return "gatefail", f"渲染后门失败：{', '.join(g.get('id', '?') for g in fails)}"
    return "done", "渲染完成（渲染后门通过）"


def st_deliver(ctx: dict) -> tuple[str, str]:
    rd, st = ctx["rd"], ctx["state"]
    out = Path(st["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    art = rd / "artifacts"
    copied, missing = [], []

    def want(src_p: Path, name: str, required: bool = False):
        if src_p.exists():
            shutil.copy(src_p, out / name)
            copied.append(name)
        elif required:
            missing.append(name)
        else:
            missing.append(name)

    final = rd / "workdir" / "out" / "final.mp4"
    want(final, "final.mp4", required=True)
    want(art / "design-table.md", "design-table.md")
    want(art / "asset-match.md", "asset-match.md")
    want(rd / "gate-report.md", "gate-report.md")
    want(rd / "gate-report.json", "gate-report.json")
    want(art / "sources.json", "sources.json")
    if "final.mp4" in missing:
        return "gatefail", f"缺 final.mp4（{final}）；其余在档：{copied}"
    # 人审包：每场定格帧 + 核对表（无视觉执行者的人眼兜底）
    try:
        rp_tool = SDK_ROOT / "tools" / "make_review_pack.py"
        if rp_tool.is_file():
            run_cmd([sys.executable, str(rp_tool), "--run-dir", str(rd)], log_path=rd / "logs" / "review-pack.log")
            rp_md = rd / "review" / "review-pack.md"
            if rp_md.is_file():
                dst_dir = out / "review-pack"
                dst_dir.mkdir(exist_ok=True)
                shutil.copy(rp_md, dst_dir / "review-pack.md")
                for png in sorted((rd / "review").glob("*.png")):
                    shutil.copy(png, dst_dir / png.name)
                copied.append("review-pack/")
    except Exception as e:  # noqa: BLE001
        print(f"（提示）人审包跳过：{e}")
    files = []
    for f in sorted(out.glob("*")):
        if f.is_file():
            files.append({"name": f.name, "bytes": f.stat().st_size, "sha256": sha256_file(f)[:16]})
    manifest = {
        "sdk_version": VERSION, "run_id": st.get("run_id"), "source": st["source"],
        "out_dir": str(out), "created": st.get("created"), "delivered_at": now_iso(),
        "files": files, "missing_optional": [m for m in missing],
        # 交付物自述：manifest 生成于 deliver 完成时刻，本阶段状态回写为 done
        "stages": {**{k: v.get("status") for k, v in st["stages"].items()}, "deliver": "done"},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return "done", f"交付完成：{len(files) + 1} 件（含 manifest）"


HANDLERS = {
    "ingest": st_ingest, "transcribe": st_transcribe, "scenes": st_scenes,
    "design-table": st_design_table, "scaffold": st_scaffold, "build": st_build,
    "verify": st_verify, "preview": st_preview, "render": st_render, "deliver": st_deliver,
}


def run_stage(rd: Path, name: str) -> tuple[str, str]:
    st = load_state(rd)
    rec = st["stages"].setdefault(name, {"status": "pending"})
    if rec.get("status") == "done":
        return "done", "已完成（跳过）"
    rec.update({"status": "running", "start": now_iso()})
    save_state(rd, st)
    try:
        result, msg = HANDLERS[name]({"rd": rd, "state": st, "name": name})
    except Exception as e:
        import traceback as tb
        result, msg = "error", f"{e}\n{tb.format_exc()[-500:]}"
    st = load_state(rd)
    rec = st["stages"].setdefault(name, {})
    status = {"done": "done", "await": "awaiting", "gatefail": "failed", "error": "failed"}[result]
    rec.update({"status": status, "end": now_iso(), "note": msg})
    save_state(rd, st)
    # 阶段完成后清掉对应的「待产出」问题（产物已在档，问题不该再挂着）
    if result == "done":
        (rd / "questions" / f"need-{name}.json").unlink(missing_ok=True)
    log(f"{name}: [{result}] {msg}")
    return result, msg


def cmd_run(rd: Path, through: str | None = None) -> int:
    st = load_state(rd)
    names = STAGES[: STAGES.index(through) + 1] if through else STAGES
    for name in names:
        rec = st["stages"].get(name, {})
        if rec.get("status") == "done":
            continue
        result, _ = run_stage(rd, name)
        if result == "done":
            st = load_state(rd)
            continue
        return {"await": EXIT_AWAIT, "gatefail": EXIT_GATE, "error": EXIT_ERR}[result]
    log("全部阶段完成 ✓")
    return EXIT_OK


# ------------------------------------------------------------------- CLI ----

def cmd_init(args) -> int:
    src = Path(args.source).resolve()
    if not src.is_file():
        die(f"源片不存在：{src}")
    out = Path(args.out).resolve()
    rd = Path(args.run_dir).resolve() if args.run_dir else out / ".pipeline-run"
    for sub in ("questions", "answers", "checkpoints", "logs", "artifacts"):
        (rd / sub).mkdir(parents=True, exist_ok=True)
    cfg: dict = {"proxy": True}
    if args.brief:
        cfg["brief"] = args.brief
    if args.transcript:
        cfg["transcript"] = str(Path(args.transcript).resolve())
    if args.scenes:
        cfg["scenes"] = str(Path(args.scenes).resolve())
    if args.config:
        extra = json.loads(Path(args.config).read_text(encoding="utf-8"))
        cfg.update(extra)
    st = {
        "version": VERSION, "run_id": time.strftime("%Y%m%d-%H%M%S"), "source": str(src),
        "out_dir": str(out), "brief": args.brief or "", "created": now_iso(), "updated": now_iso(),
        "stages": {name: {"status": "pending"} for name in STAGES}, "config": cfg,
    }
    save_state(rd, st)
    log(f"init 完成 · run-dir：{rd}")
    log(f"下一步：python pipeline/run.py run --run-dir \"{rd}\"")
    return EXIT_OK


def cmd_resume(args) -> int:
    rd = Path(args.run_dir).resolve()
    st = load_state(rd)
    if args.approve:
        m = {"design-table": "checkpoint-1", "preview": "checkpoint-2",
             "checkpoint-1": "checkpoint-1", "checkpoint-2": "checkpoint-2"}
        qid = m.get(args.approve)
        if not qid:
            die(f"--approve 只认 design-table / preview（收到 {args.approve}）")
        (rd / "answers" / f"{qid}.json").write_text(json.dumps({
            "id": qid, "values": ["approve"], "notes": args.note or "",
            "answered_by": "cli", "answered_at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"已写入审批：{qid} = approve")
    return cmd_run(rd, through=None)


def cmd_status(args) -> int:
    rd = Path(args.run_dir).resolve()
    st = load_state(rd)
    print(f"run-dir : {rd}")
    print(f"source  : {st['source']}")
    print(f"brief   : {st.get('brief') or '（无）'}")
    print(f"stages  :")
    for name in STAGES:
        rec = st["stages"].get(name, {})
        s = rec.get("status", "pending")
        mark = {"done": "✓", "awaiting": "⏸", "failed": "✗", "running": "…", "pending": "·"}.get(s, "·")
        note = rec.get("note", "")
        print(f"  {mark} {name:<12} {s:<9} {note[:80]}")
    pend = pending_questions(rd)
    if pend:
        print("待作答 :")
        for q in pend:
            print(f"  - {q.get('id')}（{q.get('type')}）：{q.get('title')}")
    print(f"下一动作：python pipeline/run.py run --run-dir \"{rd}\"")
    return EXIT_OK


def main() -> None:
    ap = argparse.ArgumentParser(description="视频产线 SDK · 单入口")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor"); p.set_defaults(fn="doctor")
    p = sub.add_parser("init")
    p.add_argument("--source", required=True); p.add_argument("--out", required=True)
    p.add_argument("--brief"); p.add_argument("--transcript"); p.add_argument("--scenes")
    p.add_argument("--config"); p.add_argument("--run-dir"); p.set_defaults(fn="init")
    p = sub.add_parser("stage"); p.add_argument("name"); p.add_argument("--run-dir", required=True); p.set_defaults(fn="stage")
    p = sub.add_parser("run"); p.add_argument("--through"); p.add_argument("--run-dir", required=True); p.set_defaults(fn="run")
    p = sub.add_parser("resume"); p.add_argument("--approve"); p.add_argument("--note")
    p.add_argument("--run-dir", required=True); p.set_defaults(fn="resume")
    p = sub.add_parser("gates"); p.add_argument("--run-dir", required=True); p.set_defaults(fn="gates")
    p = sub.add_parser("ask"); p.add_argument("--emit", action="store_true"); p.add_argument("--serve", action="store_true")
    p.add_argument("--port", type=int, default=8898); p.add_argument("--run-dir", required=True); p.set_defaults(fn="ask")
    p = sub.add_parser("status"); p.add_argument("--run-dir", required=True); p.set_defaults(fn="status")

    args = ap.parse_args()

    if args.fn == "doctor":
        sys.exit(passthrough([sys.executable, str(SDK_ROOT / "pipeline" / "doctor.py")]))
    if args.fn == "init":
        sys.exit(cmd_init(args))
    if args.fn == "stage":
        rd = Path(args.run_dir).resolve()
        result, _ = run_stage(rd, args.name)
        sys.exit({"done": EXIT_OK, "await": EXIT_AWAIT, "gatefail": EXIT_GATE, "error": EXIT_ERR}[result])
    if args.fn == "run":
        sys.exit(cmd_run(Path(args.run_dir).resolve(), args.through))
    if args.fn == "resume":
        sys.exit(cmd_resume(args))
    if args.fn == "gates":
        sys.exit(passthrough([sys.executable, str(SDK_ROOT / "gates" / "aggregate.py"), "--run-dir", str(Path(args.run_dir).resolve())]))
    if args.fn == "ask":
        ask = [sys.executable, str(SDK_ROOT / "pipeline" / "ask.py"), "--run-dir", str(Path(args.run_dir).resolve())]
        if args.serve:
            ask += ["--serve", "--port", str(args.port)]
        else:
            ask += ["--emit"]
        sys.exit(passthrough(ask))
    if args.fn == "status":
        sys.exit(cmd_status(args))


if __name__ == "__main__":
    main()
