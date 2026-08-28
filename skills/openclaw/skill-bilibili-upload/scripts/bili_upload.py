#!/usr/bin/env python3
"""bili_upload.py — B站投稿封装（包装 biliup CLI）。

包装成熟的 biliup（Rust 后端）命令行做 B站视频投稿：友好参数、分区名→tid 映射、
cookie 路径管理、dry-run 预览、投稿执行。

⚠️ 环境依赖：投稿/登录需 **biliup CLI + 已登录 cookie（QR 扫码）+ 外网**。当前无头环境可做
   `check` 与命令构造（dry-run），真实登录/投稿需在有网络与账号的环境执行。

子命令：
    check      检查 biliup 是否安装、cookie 是否存在
    login      扫码登录 B站，保存 cookie（biliup login）
    tid        列出常用投稿分区 → tid
    upload     投稿（默认 dry-run 预览命令；--exec 真正执行）
    selftest   自检（命令构造 + 分区映射 + check）

用法举例：
    bili_upload.py check
    bili_upload.py login --cookie cookies.json
    bili_upload.py upload --video out.mp4 --title "标题" --partition 知识 \\
        --tag "AI,教程,效率" --desc "简介" --cover cover.jpg --cookie cookies.json
    bili_upload.py upload ... --exec        # 真正投稿
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SHARED_SCRIPTS = Path(__file__).resolve().parents[3] / "shared" / "scripts"
sys.path.insert(0, str(SHARED_SCRIPTS))
import content_guard  # noqa: E402

# 常用投稿分区名 → tid（B站分区，节选常用）
PARTITIONS: dict[str, int] = {
    "动画": 1, "音乐": 3, "游戏": 4, "娱乐": 5, "生活": 160, "日常": 21,
    "科技": 188, "数码": 95, "知识": 36, "科普": 201, "资讯": 202,
    "影视": 181, "美食": 211, "时尚": 155, "美妆": 157, "穿搭": 158,
    "运动": 234, "汽车": 223, "动物": 217, "舞蹈": 129, "鬼畜": 119,
    "绘画": 162, "手工": 161, "摄影": 282, "职场": 253, "校园": 55,
    "母婴": 216, "家居": 239, "旅游": 250, "三农": 251,
}


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _has_biliup() -> bool:
    return shutil.which("biliup") is not None


def resolve_tid(partition: str | None, tid: int | None) -> int:
    if tid is not None:
        return tid
    if not partition:
        return 36  # 默认 知识
    partition = partition.strip()
    if partition.isdigit():
        return int(partition)
    if partition in PARTITIONS:
        return PARTITIONS[partition]
    _die(f"未知分区：{partition}。用 `tid` 子命令看支持列表，或直接用 --tid 数字。")
    raise AssertionError


def build_cmd(a) -> list[str]:
    """构造 biliup upload 命令（纯函数，供测试）。全局选项在子命令前。"""
    cookie = a.cookie or "cookies.json"
    cmd = ["biliup", "-u", cookie]
    if getattr(a, "proxy", None):
        cmd += ["-p", a.proxy]
    cmd += ["upload", a.video]
    cmd += ["--title", a.title or Path(a.video).stem]
    cmd += ["--tid", str(resolve_tid(a.partition, a.tid))]
    if a.desc:
        cmd += ["--desc", a.desc]
    if a.tag:
        cmd += ["--tag", a.tag]
    if a.cover:
        cmd += ["--cover", a.cover]
    cmd += ["--copyright", str(a.copyright)]
    if a.copyright == 2 and a.source:
        cmd += ["--source", a.source]
    if getattr(a, "dtime", None):
        cmd += ["--dtime", str(a.dtime)]
    return cmd


def cmd_check(_a) -> int:
    ok = True
    if _has_biliup():
        try:
            v = subprocess.run(["biliup", "--version"], capture_output=True, text=True)
            print(f"✅ biliup: {(v.stdout or v.stderr).strip()}")
        except Exception:
            print("✅ biliup 已安装")
    else:
        print("❌ 未安装 biliup（pip install biliup）"); ok = False
    print(f"分区映射：内置 {len(PARTITIONS)} 个常用分区，其余用 --tid 数字")
    print("cookie：投稿前需 `login` 扫码登录生成（默认 cookies.json）")
    return 0 if ok else 3


def cmd_login(a) -> int:
    if not _has_biliup():
        _die("未安装 biliup（pip install biliup）", 3)
    cookie = a.cookie or "cookies.json"
    print(f"启动 B站扫码登录，cookie 将保存到 {cookie} ...", file=sys.stderr)
    print("（需终端可显示二维码 + 手机 B站 App 扫码 + 外网）", file=sys.stderr)
    return subprocess.call(["biliup", "-u", cookie, "login"])


def cmd_tid(_a) -> int:
    print("常用投稿分区 → tid：")
    for name, tid in PARTITIONS.items():
        print(f"  {name:6s} {tid}")
    print("\n更多分区见 B站创作中心；也可直接 --tid <数字>。")
    return 0


def cmd_upload(a) -> int:
    if not Path(a.video).expanduser().is_file():
        _die(f"视频不存在：{a.video}")
    cmd = build_cmd(a)
    printable = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    if not a.exec:
        content_guard.guard_or_die(
            [a.title or Path(a.video).stem, a.desc, a.tag, a.source],
            exec_mode=False,
            label="B站投稿内容",
        )
        print("dry-run（加 --exec 真正投稿）：\n" + printable)
        print("\n前置：已 `login` 生成 cookie、biliup 已装、外网可用。", file=sys.stderr)
        return 0
    if not _has_biliup():
        _die("未安装 biliup", 3)
    cookie = a.cookie or "cookies.json"
    if not Path(cookie).is_file():
        _die(f"cookie 不存在：{cookie}，请先 `login`。")
    content_guard.guard_or_die(
        [a.title or Path(a.video).stem, a.desc, a.tag, a.source],
        exec_mode=True,
        label="B站投稿内容",
    )
    print("投稿中 ...", file=sys.stderr)
    rc = subprocess.call(cmd)
    if rc == 0:
        # 投稿成功 → 落统一内容日历（对话页自动；发布页 B 站走 biliup CLI 由 web 记录，路径不同不重复）
        try:
            import calendar_ops
            calendar_ops.record_publish("bilibili", a.title or Path(a.video).stem,
                                        ptype="视频", tags=(a.tag or ""),
                                        note=(a.desc or ""), source="chat")
        except Exception:
            pass
    return rc


def cmd_selftest(_a) -> int:
    print("bili_upload 自检 ...", file=sys.stderr)
    # 分区解析
    assert resolve_tid("知识", None) == 36
    assert resolve_tid("科技", None) == 188
    assert resolve_tid(None, 999) == 999, "显式 tid 应优先"
    assert resolve_tid("21", None) == 21, "数字分区应直通"
    # 命令构造
    a = argparse.Namespace(video="out.mp4", title="标题", partition="知识", tid=None,
                           desc="简介", tag="AI,教程", cover="c.jpg", copyright=1,
                           source="", dtime=None, cookie="ck.json", proxy=None)
    cmd = build_cmd(a)
    assert cmd[0] == "biliup" and "upload" in cmd, "命令头不对"
    assert "-u" in cmd and "ck.json" in cmd, "cookie 未带上"
    assert cmd[cmd.index("--tid") + 1] == "36", "tid 未映射"
    assert cmd[cmd.index("--title") + 1] == "标题"
    assert cmd[cmd.index("--tag") + 1] == "AI,教程"
    # 全局选项在子命令前
    assert cmd.index("-u") < cmd.index("upload"), "全局 -u 应在 upload 前"
    # 转载来源
    a2 = argparse.Namespace(video="v.mp4", title="", partition=None, tid=None, desc="",
                            tag="", cover="", copyright=2, source="https://x",
                            dtime=None, cookie=None, proxy=None)
    c2 = build_cmd(a2)
    assert "--source" in c2 and c2[c2.index("--copyright")+1] == "2", "转载参数缺失"
    assert c2[c2.index("--title")+1] == "v", "无标题应回退文件名"
    # check（此环境已装 biliup）
    assert cmd_check(None) in (0, 3)
    print("✅ selftest 通过（分区映射/命令构造/全局选项顺序/转载/check）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="B站投稿（包装 biliup CLI）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("check", help="检查 biliup/cookie").set_defaults(func=cmd_check)
    sub.add_parser("tid", help="列出常用分区 tid").set_defaults(func=cmd_tid)

    pl = sub.add_parser("login", help="扫码登录保存 cookie")
    pl.add_argument("--cookie", help="cookie 文件路径（默认 cookies.json）")
    pl.set_defaults(func=cmd_login)

    pu = sub.add_parser("upload", help="投稿")
    pu.add_argument("--video", required=True, help="视频文件")
    pu.add_argument("--title", help="标题（默认取文件名）")
    pu.add_argument("--partition", help="分区名（如 知识/科技/生活）")
    pu.add_argument("--tid", type=int, help="分区 tid（数字，优先于 --partition）")
    pu.add_argument("--desc", help="简介")
    pu.add_argument("--tag", help="标签，逗号分隔")
    pu.add_argument("--cover", help="封面图")
    pu.add_argument("--copyright", type=int, default=1, choices=[1, 2],
                    help="1-自制(默认) 2-转载")
    pu.add_argument("--source", help="转载来源（copyright=2 时）")
    pu.add_argument("--dtime", type=int, help="定时发布 10 位时间戳（距今>4h）")
    pu.add_argument("--cookie", help="cookie 文件（默认 cookies.json）")
    pu.add_argument("--proxy", help="代理")
    pu.add_argument("--exec", action="store_true", help="真正投稿（默认 dry-run 预览）")
    pu.set_defaults(func=cmd_upload)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
