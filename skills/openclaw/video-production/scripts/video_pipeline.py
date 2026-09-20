#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频产线 · Easel 薄壳（只转发，不做业务逻辑）

把宿主（Easel）与视频产线 SDK（独立接口）焊在一起的最小转发器：
- 调用 SDK 的 pipeline/run.py（唯一入口，契约见 SDK 的 INTERFACE.md）
- 运行态统一放 <base>/<时间戳>/（默认 <工作区>/outputs/视频产线）
- 退出码透传：0 完成 ｜ 2 门失败 ｜ 3 待作答/待审批 ｜ 1 异常
- 每个命令末行打印 `STATE: ...`（agent 用这一行判断下一步）

红线：本文件不复制任何 SDK 逻辑；SDK 升级不需要改这里。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STATE = {0: "done", 2: "gate-failed", 3: "awaiting-answer", 1: "error"}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def find_sdk(args) -> Path:
    cands = []
    if args.sdk:
        cands.append(args.sdk)
    if os.environ.get("VIDEO_PIPELINE_SDK"):
        cands.append(os.environ["VIDEO_PIPELINE_SDK"])
    # 内置 SDK（随 Easel 进仓，默认自包含）：本脚本在 .../video-production/scripts/，
    # SDK 在 .../video-production/vendor/video-pipeline-sdk/。作 --sdk/env 之后的首选。
    cands.append(str(Path(__file__).resolve().parent.parent / "vendor" / "video-pipeline-sdk"))
    cands += [
        str(Path.cwd() / "video-pipeline-sdk"),
        str(Path.home() / "video-pipeline-sdk"),
        str(Path.home() / "video-pipeline" / "video-pipeline-sdk"),
    ]
    for c in cands:
        if c and (Path(c) / "pipeline" / "run.py").is_file():
            return Path(c)
    print("找不到视频产线 SDK。请设环境变量 VIDEO_PIPELINE_SDK 或用 --sdk 指定。", file=sys.stderr)
    print("试过：" + " ｜ ".join(map(str, cands)), file=sys.stderr)
    sys.exit(1)


def find_base(args) -> Path:
    if args.base:
        base = Path(args.base)
    elif os.environ.get("EASEL_OPENCLAW_WORKSPACE"):
        base = Path(os.environ["EASEL_OPENCLAW_WORKSPACE"]) / "outputs" / "视频产线"
    else:
        base = Path.home() / ".openclaw" / "workspace-easel" / "outputs" / "视频产线"
    base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_run(args, base: Path) -> Path:
    if getattr(args, "run_dir", None):
        rd = Path(args.run_dir)
        if (rd / "run-state.json").is_file():
            return rd
        print(f"run-dir 无运行态：{rd}", file=sys.stderr)
        sys.exit(1)
    cur = base / "current.txt"
    if cur.is_file():
        rd = Path(cur.read_text(encoding="utf-8").strip())
        if (rd / "run-state.json").is_file():
            return rd
    print("没有找到进行中的运行（先 start，或用 --run-dir 指定）", file=sys.stderr)
    sys.exit(1)


def cexec(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).rstrip()


def rcmd(sdk: Path, args):
    return [sys.executable, str(sdk / "pipeline" / "run.py")] + args


def show_questions(sdk: Path, rd: Path):
    code, out = cexec(rcmd(sdk, ["ask", "--emit", "--run-dir", str(rd)]))
    if out:
        print(out)
    qf = rd / "questions.json"
    if qf.is_file():
        data = json.loads(qf.read_text(encoding="utf-8"))
        qs = data.get("questions", [])
        if qs:
            print("")
            print("── 待作答的问题（用 ask_user 转问用户；作答后走 answer + resume）──")
            print(json.dumps(qs, ensure_ascii=False, indent=2))


def finish(code: int, extra_state: str | None = None):
    print("")
    print(f"STATE: {extra_state or STATE.get(code, 'error')}")
    return code


def post_deliver(base: Path, rd: Path):
    """交付后收尾（宿主专属）：抽封面帧 + 更新内容库项目卡 .easel.json。"""
    try:
        st = json.loads((rd / "run-state.json").read_text(encoding="utf-8"))
        outd = Path(st.get("out_dir") or "")
        final = outd / "final.mp4"
        if not final.is_file():
            return
        stamp = rd.parent.name
        cover = outd / "cover.png"
        if not cover.is_file():
            cexec(["ffmpeg", "-y", "-ss", "2", "-i", str(final), "-frames:v", "1", str(cover)])
        meta_p = base / ".easel.json"
        meta = {}
        if meta_p.is_file():
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = {}
        deliv = list(meta.get("deliverables") or [])
        for rel in (f"{stamp}/out/final.mp4", f"{stamp}/out/gate-report.md",
                    f"{stamp}/out/gate-report.json", f"{stamp}/out/design-table.md",
                    f"{stamp}/out/manifest.json", f"{stamp}/out/cover.png"):
            if (base / rel).is_file() and rel not in deliv:
                deliv.append(rel)
        meta.update({
            "title": "视频产线",
            "kind": "video",
            "status": "已完成",
            "summary": (st.get("brief") or "口播整片（原片 → 包装级成片；门全过才交付）"),
            "cover": f"{stamp}/out/cover.png",
            "deliverables": deliv[-30:],
        })
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"内容库卡片已更新：{meta_p}")
    except Exception as e:  # noqa: BLE001
        print(f"（提示）封面/卡片更新跳过：{e}")


# ---------------------------------------------------------------- commands --

def report_transcription_tiers(sdk: Path) -> None:
    """打印三级转录策略可用性（Easel 内置改造）。"""
    print("转录三级策略（优先级从上到下）：")
    print("  tier1 现成稿  ：start 时给 --transcript（.srt/.vtt 自动转段级，.json 直接用）— 有则最省")
    key_on = bool(os.environ.get("SILICONFLOW_API_KEY", "").strip())
    model = os.environ.get("SILICONFLOW_ASR_MODEL", "XingChenAGI/XingChenGSR-V1.0")
    print(f"  tier2 云端API ：SILICONFLOW_API_KEY {'已配置 ✓' if key_on else '未配置（export 后启用）'}"
          f" · model={model}")
    try:
        import faster_whisper  # noqa: F401
        fw = "已装 ✓"
    except ImportError:
        fw = "未装"
    print(f"  tier3 本地whisper：faster-whisper {fw}（兜底，首次需下 large-v3 约 3GB）")


def cmd_doctor(args) -> int:
    sdk = find_sdk(args)
    base = find_base(args)
    ver = "?"
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', (sdk / "pipeline" / "run.py").read_text(encoding="utf-8"))
    if m:
        ver = m.group(1)
    print(f"SDK：{sdk}（{ver}）")
    print(f"运行态根：{base}")
    print("")
    report_transcription_tiers(sdk)
    print("")
    code, out = cexec(rcmd(sdk, ["doctor"]))
    print(out)
    return finish(code, "ok" if code == 0 else "doctor-failed")


def cmd_start(args) -> int:
    sdk = find_sdk(args)
    base = find_base(args)
    src = Path(args.source)
    if not src.is_file():
        print(f"源片不存在：{src}", file=sys.stderr)
        return finish(1)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = base / stamp
    rd, outd = root / "run", root / "out"
    init_args = ["init", "--source", str(src), "--out", str(outd), "--run-dir", str(rd)]
    for flag, val in (("--brief", args.brief), ("--transcript", args.transcript),
                      ("--scenes", args.scenes), ("--config", args.config)):
        if val:
            init_args += [flag, str(val)]
    code, out = cexec(rcmd(sdk, init_args))
    print(out)
    if code != 0:
        return finish(code)
    if args.design_table:
        dt = Path(args.design_table)
        if dt.is_file():
            (rd / "artifacts").mkdir(parents=True, exist_ok=True)
            shutil.copy(dt, rd / "artifacts" / "design-table.md")
            print(f"设计表就位：{dt}")
        else:
            print(f"提示：设计表不存在（{dt}），流程会停在需要设计表处", file=sys.stderr)
    if args.gates:
        gp = Path(args.gates)
        if gp.is_file():
            text = gp.read_text(encoding="utf-8")
            posix = lambda v: str(v).replace("\\", "/")  # noqa: E731 —— JSON 里路径必须正斜杠
            text = text.replace("{run_dir}", posix(rd)).replace("{out_dir}", posix(outd))
            (rd / "gates.json").write_text(text, encoding="utf-8")
            print(f"质量门配置就位：{gp}")
        else:
            print(f"提示：gates 配置不存在（{gp}）", file=sys.stderr)
    code, out = cexec(rcmd(sdk, ["run", "--run-dir", str(rd)]))
    print(out)
    (base / "current.txt").write_text(str(rd), encoding="utf-8")
    print("")
    print(f"运行态：{rd}")
    print(f"交付目录：{outd}")
    if code == 3:
        show_questions(sdk, rd)
    if code == 0:
        for f in sorted(outd.glob("*")):
            print(f"  - {f.name}（{f.stat().st_size} B）")
        post_deliver(base, rd)
    return finish(code)


def cmd_pending(args) -> int:
    sdk = find_sdk(args)
    base = find_base(args)
    rd = resolve_run(args, base)
    show_questions(sdk, rd)
    qf = rd / "questions.json"
    has = bool(qf.is_file() and json.loads(qf.read_text(encoding="utf-8")).get("questions"))
    return finish(3 if has else 0, "awaiting-answer" if has else "ok")


def cmd_answer(args) -> int:
    sdk = find_sdk(args)
    base = find_base(args)
    rd = resolve_run(args, base)
    values = [v.strip() for v in (args.values or "").split(",") if v.strip()]
    if not args.id or not values:
        print("用法：answer --id <问题id> --values <value[,value]> [--notes ...]", file=sys.stderr)
        return finish(1)
    rec = {"id": args.id, "values": values, "notes": args.notes or "",
           "answered_by": "easel-agent", "answered_at": now_iso()}
    (rd / "answers").mkdir(exist_ok=True)
    (rd / "answers" / f"{args.id}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入作答：{args.id} = {values}")
    return finish(0, "ok")


def cmd_resume(args) -> int:
    sdk = find_sdk(args)
    base = find_base(args)
    rd = resolve_run(args, base)
    code, out = cexec(rcmd(sdk, ["resume", "--run-dir", str(rd)]))
    print(out)
    if code == 3:
        show_questions(sdk, rd)
    if code == 0:
        outd = None
        st = json.loads((rd / "run-state.json").read_text(encoding="utf-8"))
        outd = Path(st.get("out_dir", ""))
        if outd and outd.is_dir():
            print("")
            print(f"交付目录：{outd}")
            for f in sorted(outd.glob("*")):
                print(f"  - {f.name}（{f.stat().st_size} B）")
        post_deliver(base, rd)
    return finish(code)


def cmd_status(args) -> int:
    sdk = find_sdk(args)
    base = find_base(args)
    rd = resolve_run(args, base)
    code, out = cexec(rcmd(sdk, ["status", "--run-dir", str(rd)]))
    print(out)
    return finish(0, "ok")


def main() -> None:
    ap = argparse.ArgumentParser(description="视频产线 Easel 薄壳（转发 run.py）")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sdk", help="视频产线 SDK 路径")
    common.add_argument("--base", help="运行态根目录")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", parents=[common]); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("start", parents=[common])
    p.add_argument("--source", required=True); p.add_argument("--brief")
    p.add_argument("--transcript"); p.add_argument("--scenes"); p.add_argument("--config")
    p.add_argument("--gates"); p.add_argument("--design-table"); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("pending", parents=[common]); p.add_argument("--run-dir"); p.set_defaults(fn=cmd_pending)
    p = sub.add_parser("answer", parents=[common]); p.add_argument("--run-dir")
    p.add_argument("--id", required=True); p.add_argument("--values", required=True)
    p.add_argument("--notes"); p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("resume", parents=[common]); p.add_argument("--run-dir"); p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("status", parents=[common]); p.add_argument("--run-dir"); p.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
