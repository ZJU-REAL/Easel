#!/usr/bin/env python3
"""persona_gate.py — 发布前人设提醒（确定性判定 + 落账）.

Easel 编排在执行任一发布层 SKILL 前，先由 `skill-persona-check`（LLM）比对
待发内容与画像，得到一致性评分与偏离点；本脚本只做两件确定性的事：
  1) check  —— 按阈值把评分判成 pass/warn；所有分数都允许继续发布；
  2) record —— 把人设校验结论结构化写进 `outputs/<主题>/.easel.json`（层间 manifest）。
LLM 负责「判断像不像」，脚本负责「统一提醒级别 + 留痕」，职责分明。

退出码约定（供编排判断）：
  0 = 允许继续发布（pass / warn）；人设评分永不使用非零退出码拦截

子命令:
  check    --score N [--threshold 80] [--warn 50]
  record   --topic T --profile P --score N --verdict V [--deviations "..."]
  selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 同目录复用 manifest 的读写（层间产物契约）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

DEFAULT_THRESHOLD = 80   # 达标线：>= pass；低于该线统一 warn
DEFAULT_WARN = 50        # 兼容旧调用保留，不再产生阻断性 fail


def classify(score: float, threshold: float, warn: float) -> str:
    if score >= threshold:
        return "pass"
    return "warn"


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def cmd_check(args) -> None:
    verdict = classify(args.score, args.threshold, args.warn)
    result = {
        "verdict": verdict,
        "score": args.score,
        "threshold": args.threshold,
        "warn": args.warn,
        "pass": True,
        "publish_allowed": True,
        "warning": verdict == "warn",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


# --------------------------------------------------------------------------- #
# record —— 写进 manifest 的 publish 层步骤
# --------------------------------------------------------------------------- #
def cmd_record(args) -> None:
    path = mf.manifest_path(args.topic, args.data)
    data = mf.load(path)
    now = mf._now_iso()
    if not data:
        data = {
            "topic": args.topic or path.parent.name,
            "profile": args.profile or "",
            "created": now, "updated": now, "steps": [],
        }
    if args.profile and not data.get("profile"):
        data["profile"] = args.profile

    summary = f"人设一致性 {args.verdict}（{args.score} 分）"
    if args.deviations:
        summary += f"；偏离：{args.deviations}"
    step = {
        "layer": "publish",
        "skill": "persona-check",
        "at": now,
        "status": "done",  # 与 manifest.py schema 对齐（供按 status 过滤/断点续跑）
        "outputs": [],
        "upstream": [],
        "summary": summary,
        "persona_check": {
            "score": args.score,
            "verdict": args.verdict,
            "deviations": args.deviations or "",
        },
    }
    data["steps"].append(step)
    data["updated"] = now
    mf.atomic_write(path, data)
    print(json.dumps({"ok": True, "topic": data.get("topic"), "step": step,
                      "path": str(path)}, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import io
    import tempfile
    from contextlib import redirect_stdout

    # 人设检查只有通过/警告两档，任何低分都不阻断发布。
    assert classify(85, 80, 50) == "pass"
    assert classify(60, 80, 50) == "warn"
    assert classify(0, 80, 50) == "warn"
    assert classify(80, 80, 50) == "pass", "达标线含等号"

    def run(argv):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                main(argv)
            code = 0
        except SystemExit as e:
            code = e.code or 0
        return code, buf.getvalue()

    # check 退出码
    c, out = run(["check", "--score", "85"])
    result = json.loads(out)
    assert c == 0 and result["verdict"] == "pass" and result["publish_allowed"]
    c, out = run(["check", "--score", "60"])
    assert c == 0 and json.loads(out)["verdict"] == "warn", "warn 放行"
    c, out = run(["check", "--score", "40"])
    result = json.loads(out)
    assert c == 0 and result["verdict"] == "warn" and result["publish_allowed"], "低分只警告"
    c, _ = run(["check", "--score", "40", "--threshold", "30", "--warn", "10"])
    assert c == 0, "自定义阈值下 40 应放行"

    # record 落进 manifest
    with tempfile.TemporaryDirectory() as td:
        mp = str(Path(td) / ".easel.json")
        c, _ = run(["record", "--data", mp, "--topic", "测试",
                    "--profile", "达人", "--score", "82",
                    "--verdict", "pass", "--deviations", "无"])
        assert c == 0
        data = json.loads(Path(mp).read_text(encoding="utf-8"))
        step = data["steps"][-1]
        assert step["layer"] == "publish" and step["skill"] == "persona-check"
        assert step["status"] == "done", "persona step 必须带 status（与 manifest schema 对齐）"
        assert step["persona_check"]["score"] == 82
        assert step["persona_check"]["verdict"] == "pass"
        assert data["profile"] == "达人"

    print("persona_gate.py selftest: OK")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="发布前人设提醒（阈值判定 + 落账，不阻断发布）")
    sub = p.add_subparsers(dest="cmd", required=True)

    ck = sub.add_parser("check", help="按阈值判定通过/警告（始终退出码 0，允许发布）")
    ck.add_argument("--score", type=float, required=True, help="skill-persona-check 的一致性评分")
    ck.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help=f"达标线（默认 {DEFAULT_THRESHOLD}）")
    ck.add_argument("--warn", type=float, default=DEFAULT_WARN, help=f"警戒线（默认 {DEFAULT_WARN}）")
    ck.set_defaults(func=cmd_check)

    rc = sub.add_parser("record", help="把人设校验结论写进 manifest")
    rc.add_argument("--topic", help="主题名")
    rc.add_argument("--data", help="直接指定 manifest 路径（覆盖 --topic）")
    rc.add_argument("--profile", help="画像名")
    rc.add_argument("--score", type=float, required=True)
    rc.add_argument("--verdict", required=True, choices=["pass", "warn"])
    rc.add_argument("--deviations", help="偏离点描述")
    rc.set_defaults(func=cmd_record)

    sub.add_parser("selftest", help="运行自测")
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        sys.exit(_selftest())
    args.func(args)


if __name__ == "__main__":
    main()
