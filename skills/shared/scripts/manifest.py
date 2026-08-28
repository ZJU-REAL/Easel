#!/usr/bin/env python3
"""manifest.py — 层间产物契约（确定性读写）.

Easel 纵向编排（发现/策划/制作/发布/归因）跨层时，上游产物路径与关键结论
过去只靠 agent「凝练」口传，无结构化传递。本脚本把每层步骤登记到
`outputs/<主题>/.easel.json`，让下游用 `latest` 直接取上游结论/产物，
不必重新推导。契约见 docs/SKILL-SPEC.md。

Schema:
  {
    "topic":   "主题名",
    "profile": "画像名 或 ''",
    "created": ISO8601(CST),
    "updated": ISO8601(CST),

    # —— 展示头（供前端「内容库」富展示；均可选，缺省有兜底）——
    "title":        "人类可读标题（缺省=topic）",
    "summary":      "一句话摘要",
    "platform":     "目标平台（小红书/知乎/抖音/…）",
    "kind":         "产物体裁：article|xhs-note|video|cards|poster|audio|other",
    "status":       "生命周期：draft|ready|published",
    "tags":         ["标签1", "标签2"],
    "cover":        "封面文件名（项目根相对；缺省=首张成品媒体）",
    "deliverables": ["最终成品文件名（区别于 assets/ 中间件）"],

    "steps": [
      {"layer": "plan", "skill": "video-script", "at": ISO8601, "status": "done",
       "outputs": ["script.md"], "upstream": [], "summary": "一句话结论"}
    ]
  }

`status` 取 done|failed（默认 done）。失败步登记 failed，供将来断点续跑判断
「从哪层接着跑」——已 done 的层产物在 outputs/ 里，可直接复用，不必重跑。

**目录布局规约**：一个内容项目 = `outputs/<主题>/` 一个目录；成品（用户要发/读的
最终文件）放项目根，中间件（frames/clips/构建脚本/原始素材/草稿/重复文件）进
`assets/` 子目录；`.easel.json` 是本项目唯一元数据（隐藏）。系统状态一律
`_` 前缀目录（_login/_publish/_analytics/_scratch…）。

子命令:
  record   追加一步（新主题自动初始化；--status failed 记失败步）
  meta     upsert 展示头（title/platform/kind/status/tags/cover/deliverables）
  read     打印整份 manifest
  latest   取最近一步（可按 --layer 过滤），供下游读上游

数据文件默认 <项目根>/outputs/<主题>/.easel.json，可用 --data 覆盖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# PROJECT_ROOT：优先 EASEL_ROOT env（gateway/CLI 注入），否则按 __file__ 上溯。
# ⚠️ 本脚本会被 sync.sh 拍平复制到 workspace/shared/scripts/，那里 __file__ 上溯会
# 算成 ~/.openclaw（少一层 skills/），产物会写错地方——故 env 兜底不可省。
PROJECT_ROOT = Path(os.environ.get("EASEL_ROOT") or Path(__file__).resolve().parents[3])
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
MANIFEST_NAME = ".easel.json"
CST = timezone(timedelta(hours=8))
LAYERS = ("discover", "plan", "produce", "publish", "attribute", "general")
STATUSES = ("done", "failed")
# 展示头取值域（前端富展示用；kind 决定内容库卡片图标/分组，proj_status 决定生命周期 chip）
KINDS = ("article", "xhs-note", "video", "cards", "poster", "audio", "other")
PROJECT_STATUSES = ("draft", "ready", "published")
# 展示头可 upsert 的标量字段（列表字段 tags/deliverables 单独处理）
META_SCALAR_FIELDS = ("title", "summary", "platform", "kind", "status", "cover")


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(CST).replace(microsecond=0).isoformat()


def manifest_path(topic: str | None, data_override: str | None) -> Path:
    """--data 优先；否则按主题落到 outputs/<主题>/.easel.json。"""
    if data_override:
        return Path(data_override)
    if not topic:
        sys.exit("错误：需要 --topic 或 --data 之一")
    return OUTPUTS_DIR / topic / MANIFEST_NAME


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        sys.exit(f"错误：无法读取 {path}：{e}")
    if not raw:
        return {}  # 空文件视作未初始化（agent 可能先建了空占位）
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"错误：manifest 非合法 JSON {path}：{e}")
    data.setdefault("steps", [])
    return data


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _csv(s: str | None) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #
def cmd_record(args) -> None:
    path = manifest_path(args.topic, args.data)
    data = load(path)
    now = _now_iso()

    if not data:
        data = {
            "topic": args.topic or path.parent.name,
            "profile": args.profile or "",
            "created": now,
            "updated": now,
            "steps": [],
        }
    # 后续步骤补登画像（首次登记时未带 profile 的情况）
    if args.profile and not data.get("profile"):
        data["profile"] = args.profile

    step = {
        "layer": args.layer,
        "skill": args.skill,
        "at": now,
        "status": args.status,
        "outputs": _csv(args.outputs),
        "upstream": _csv(args.upstream),
        "summary": args.summary or "",
    }
    data["steps"].append(step)
    data["updated"] = now
    atomic_write(path, data)
    print(json.dumps({"ok": True, "topic": data.get("topic"),
                      "step_index": len(data["steps"]) - 1, "step": step,
                      "path": str(path)},
                     ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# meta（upsert 展示头）
# --------------------------------------------------------------------------- #
def cmd_meta(args) -> None:
    path = manifest_path(args.topic, args.data)
    data = load(path)
    now = _now_iso()

    if not data:
        data = {
            "topic": args.topic or path.parent.name,
            "profile": args.profile or "",
            "created": now,
            "updated": now,
            "steps": [],
        }
    if args.profile and not data.get("profile"):
        data["profile"] = args.profile

    # 校验取值域（给错就报，避免前端拿到脏值）
    if args.kind and args.kind not in KINDS:
        sys.exit(f"错误：--kind 需为 {'/'.join(KINDS)}，收到 {args.kind!r}")
    if args.status and args.status not in PROJECT_STATUSES:
        sys.exit(f"错误：--status 需为 {'/'.join(PROJECT_STATUSES)}，收到 {args.status!r}")

    # 标量字段：仅合并本次传入的（None=不动，保留旧值）
    for field in META_SCALAR_FIELDS:
        val = getattr(args, field, None)
        if val is not None:
            data[field] = val
    # 列表字段：给了就整体替换（含空串=清空）
    if args.tags is not None:
        data["tags"] = _csv(args.tags)
    if args.deliverables is not None:
        data["deliverables"] = _csv(args.deliverables)

    data["updated"] = now
    atomic_write(path, data)
    header = {k: data.get(k) for k in
              ("title", "summary", "platform", "kind", "status", "tags", "cover", "deliverables")
              if k in data}
    print(json.dumps({"ok": True, "topic": data.get("topic"), "meta": header,
                      "path": str(path)}, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# read / latest
# --------------------------------------------------------------------------- #
def cmd_read(args) -> None:
    path = manifest_path(args.topic, args.data)
    data = load(path)
    if not data:
        sys.exit(f"错误：manifest 不存在：{path}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_latest(args) -> None:
    path = manifest_path(args.topic, args.data)
    data = load(path)
    steps = data.get("steps", [])
    if args.layer:
        steps = [s for s in steps if s.get("layer") == args.layer]
    if not steps:
        print(json.dumps({"found": False, "layer": args.layer}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"found": True, "topic": data.get("topic"),
                      "profile": data.get("profile", ""), "step": steps[-1]},
                     ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import io
    from contextlib import redirect_stdout

    with tempfile.TemporaryDirectory() as td:
        mp = str(Path(td) / ".easel.json")

        def run(argv):
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    main(argv)
                code = 0
            except SystemExit as e:
                code = e.code or 0
            return code, buf.getvalue()

        # 1) plan 层登记
        c, _ = run(["record", "--data", mp, "--topic", "测试主题",
                    "--layer", "plan", "--skill", "video-script",
                    "--profile", "达人", "--outputs", "script.md",
                    "--summary", "3 幕结构"])
        assert c == 0, "record plan 应成功"

        # 2) produce 层登记，带 upstream
        c, _ = run(["record", "--data", mp, "--topic", "测试主题",
                    "--layer", "produce", "--skill", "auto-short-video",
                    "--outputs", "final.mp4", "--upstream", "script.md",
                    "--summary", "已出片 45s"])
        assert c == 0, "record produce 应成功"

        # 3) read 校验
        c, out = run(["read", "--data", mp])
        assert c == 0
        data = json.loads(out)
        assert data["topic"] == "测试主题", "topic 应保留"
        assert data["profile"] == "达人", "profile 应保留"
        assert len(data["steps"]) == 2, "应有 2 步"
        assert data["steps"][0]["layer"] == "plan"
        assert data["steps"][0]["status"] == "done", "未指定 status 应默认 done"
        assert data["created"] and data["updated"], "时间戳应存在"

        # 4) latest 取整体最近一步
        c, out = run(["latest", "--data", mp])
        assert c == 0
        assert json.loads(out)["step"]["skill"] == "auto-short-video"

        # 5) latest 按层过滤
        c, out = run(["latest", "--data", mp, "--layer", "plan"])
        assert c == 0
        step = json.loads(out)["step"]
        assert step["skill"] == "video-script"
        assert step["outputs"] == ["script.md"]

        # 6) latest 未命中层 → 退出码 1
        c, _ = run(["latest", "--data", mp, "--layer", "publish"])
        assert c == 1, "未命中应退出码 1"

        # 7) 登记失败步（断点续跑：publish 失败可查）
        c, _ = run(["record", "--data", mp, "--topic", "测试主题",
                    "--layer", "publish", "--skill", "skill-xhs-publisher",
                    "--status", "failed", "--upstream", "final.mp4",
                    "--summary", "IP 风控，未发出"])
        assert c == 0, "record failed 应成功"
        c, out = run(["latest", "--data", mp, "--layer", "publish"])
        assert c == 0
        assert json.loads(out)["step"]["status"] == "failed", "失败步应记 failed"

        # 8) meta upsert：写展示头，read 回验
        c, out = run(["meta", "--data", mp, "--topic", "测试主题",
                      "--title", "标题党", "--platform", "小红书", "--kind", "cards",
                      "--status", "draft", "--tags", "标签A,标签B",
                      "--cover", "cover.png", "--deliverables", "card_1.png,card_2.png"])
        assert c == 0, "meta 应成功"
        c, out = run(["read", "--data", mp])
        data = json.loads(out)
        assert data["title"] == "标题党"
        assert data["kind"] == "cards" and data["status"] == "draft"
        assert data["tags"] == ["标签A", "标签B"]
        assert data["deliverables"] == ["card_1.png", "card_2.png"]
        assert len(data["steps"]) == 3, "meta 不应动 steps"

        # 9) meta 二次 upsert：只改传入字段，其余保留
        c, _ = run(["meta", "--data", mp, "--topic", "测试主题", "--status", "published"])
        assert c == 0
        data = json.loads(run(["read", "--data", mp])[1])
        assert data["status"] == "published", "status 应更新"
        assert data["title"] == "标题党", "未传的 title 应保留"

        # 10) meta 非法取值域 → 报错退出
        c, _ = run(["meta", "--data", mp, "--topic", "测试主题", "--kind", "不存在"])
        assert c != 0, "非法 kind 应报错（argparse choices 拦）"

        # 11) meta 可先于 record 建新主题（自动初始化）
        mp2 = str(Path(td) / "sub" / ".easel.json")
        c, _ = run(["meta", "--data", mp2, "--topic", "新主题", "--title", "T"])
        assert c == 0, "meta 应能初始化新主题"
        assert json.loads(run(["read", "--data", mp2])[1])["title"] == "T"

    print("manifest.py selftest: OK")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="层间产物契约（确定性读写）")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="追加一步")
    r.add_argument("--topic", help="主题名（决定落盘目录）")
    r.add_argument("--data", help="直接指定 manifest 路径（覆盖 --topic）")
    r.add_argument("--layer", required=True, choices=LAYERS)
    r.add_argument("--skill", required=True, help="执行的 SKILL 名")
    r.add_argument("--status", choices=STATUSES, default="done",
                   help="本步结果，默认 done；失败记 failed（供断点续跑）")
    r.add_argument("--profile", help="画像名")
    r.add_argument("--outputs", help="产物文件名，逗号分隔")
    r.add_argument("--upstream", help="消费的上游产物，逗号分隔")
    r.add_argument("--summary", help="一句话关键结论")
    r.set_defaults(func=cmd_record)

    m = sub.add_parser("meta", help="upsert 展示头（前端富展示用）")
    m.add_argument("--topic", help="主题名（决定落盘目录）")
    m.add_argument("--data", help="直接指定 manifest 路径（覆盖 --topic）")
    m.add_argument("--profile", help="画像名（首次登记时可带）")
    m.add_argument("--title", help="人类可读标题")
    m.add_argument("--summary", help="一句话摘要")
    m.add_argument("--platform", help="目标平台")
    m.add_argument("--kind", choices=KINDS, help="产物体裁")
    m.add_argument("--status", choices=PROJECT_STATUSES, help="生命周期")
    m.add_argument("--tags", help="标签，逗号分隔（给了即整体替换）")
    m.add_argument("--cover", help="封面文件名（项目根相对）")
    m.add_argument("--deliverables", help="最终成品文件名，逗号分隔（给了即整体替换）")
    m.set_defaults(func=cmd_meta)

    rd = sub.add_parser("read", help="打印整份 manifest")
    rd.add_argument("--topic")
    rd.add_argument("--data")
    rd.set_defaults(func=cmd_read)

    lt = sub.add_parser("latest", help="取最近一步（可按层过滤）")
    lt.add_argument("--topic")
    lt.add_argument("--data")
    lt.add_argument("--layer", choices=LAYERS, help="只看某层的最近一步")
    lt.set_defaults(func=cmd_latest)

    sub.add_parser("selftest", help="运行自测")
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        sys.exit(_selftest())
    args.func(args)


if __name__ == "__main__":
    main()
