#!/usr/bin/env python3
"""
贴图(图片消息 / newspic)拆卡 + 出图计划生成器

输入: 一个 brief.md,含 YAML frontmatter + 要点列表 + (可选)短文本
输出: 一份 card_plan.json,列出每张卡的主副文字 + 生图 prompt + 目标文件名

本脚本**不直接生成图片**。生图由主流程 Claude 调项目内置 `scripts/generate_image.py`
按 card_plan.json 的 prompts 批量执行,保存到 `<slug>/images/`。

典型流程:
    # 1. 人类写 brief.md(话题+要点+短文本)
    # 2. 拆卡 + 生成 prompts + 短文本
    python3 newspic_build.py brief.md
    # 3. Claude 按 card_plan.json 逐张生图,保存到 images/01.png 起
    # 4. Claude 跑 AI 味检测(newspic 模式)
    python3 ai_score.py article.md --mode newspic
    # 5. 发布
    python3 publish.py --account main --type newspic --brief brief.md

brief.md 格式示例:

    ---
    topic: "Claude Code /rewind 命令"
    image_style: marker-lime    # 可选,不写就用账号默认或 hand-drawn-blue
    card_count: 6                  # 可选,不写就跟要点数走
    title: "Claude Code 里,最有用的命令之一"
    account: main
    ---

    # 要点

    1. /rewind 厉害的地方不是"撤销一下",而是给你一个更对的工作流
    2. 你可以输入 /rewind,也可以连续按两次 Esc,快速回滚代码
    3. AI 解决不好问题,常常不是因为它不够会写,而是你不敢让它放手试
    4. /rewind 的价值,就是把"试错"这件事真正变得可控

    # 短文本

    (可选,不写由 Claude 根据"要点"生成 100-300 字的短描述)

-------

prompt 模板中可用的变量占位符(由 build_card_plan 替换):
    {topic}         — brief.md 的 topic 字段
    {card_main}     — 当前卡片主文字(要点首段)
    {card_sub}      — 当前卡片副文字(要点后段,可能为空)
    {point_full}    — 完整原始要点(未切分),信息图类模板用它拿到更多上下文
    {card_index}    — 当前卡片序号,两位数字如 "01"
    {card_total}    — 卡片总数,两位数字如 "06"
    {image_subject} — "topic - card_main" 拼接,兼容老风格

marker-* / data-chart 等风格只用 card_main/card_sub,
infographic-blue / -warm / -dark / -mint 新风格用 point_full + card_index 做高密度信息图。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

try:
    import yaml
except ImportError as exc:
    raise ImportError(
        "缺少 pyyaml 依赖。请执行: pip install pyyaml --break-system-packages"
    ) from exc

from config import (
    ConfigError,
    DEFAULT_IMAGE_STYLE,
    get_image_style,
    resolve_image_style,
)


# ============================================================
# brief.md 解析
# ============================================================

FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_brief(md_text: str) -> Dict[str, Any]:
    """
    把 brief.md 拆成:
        {
          "frontmatter": dict,
          "sections": {"要点": [str, ...], "短文本": str, ...}
        }
    """
    m = FRONTMATTER_RE.match(md_text)
    if not m:
        raise ValueError(
            "brief.md 必须以 YAML frontmatter 开头(--- ... --- 包围),请补上"
        )
    try:
        frontmatter = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"brief.md frontmatter 解析失败: {e}") from e

    body = md_text[m.end():]

    # 按一级标题切分 body,收集每个 section 的文字
    sections: Dict[str, str] = {}
    current_name: Optional[str] = None
    buf: List[str] = []
    for line in body.splitlines():
        h1 = re.match(r"^#\s+(.+?)\s*$", line)
        if h1:
            if current_name is not None:
                sections[current_name] = "\n".join(buf).strip()
            current_name = h1.group(1).strip()
            buf = []
        else:
            if current_name is not None:
                buf.append(line)
    if current_name is not None:
        sections[current_name] = "\n".join(buf).strip()

    return {"frontmatter": frontmatter, "sections": sections}


def extract_bullet_points(section_text: str) -> List[str]:
    """从一个 section 里提取列表项。支持 `1.` / `-` / `*` / `+` 三种。"""
    points: List[str] = []
    for line in section_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?:\d+[.、)]|[-*+])\s+(.+)$", line)
        if m:
            points.append(m.group(1).strip())
    return points


# ============================================================
# 拆卡
# ============================================================

_VERSION_TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[-\.][A-Za-z0-9]+)+"
)


def _protect_version_tokens(text: str) -> Tuple[str, Dict[str, str]]:
    """把 GPT-5.5 / V4-Pro / 2026-04-25 / API价$5/M 这样的 token 用占位符替换,
    避免被英文句点/连字符误切。返回 (替换后文本, 占位符到原文 map)。"""
    mapping: Dict[str, str] = {}

    def repl(m: re.Match) -> str:
        key = f"\x01TOK{len(mapping):03d}\x01"
        mapping[key] = m.group(0)
        return key

    return _VERSION_TOKEN_RE.sub(repl, text), mapping


def _restore_tokens(text: str, mapping: Dict[str, str]) -> str:
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text


def _split_card_text(point: str, max_main: int = 18) -> Tuple[str, str]:
    """
    把一条"要点"拆成卡片主文字 + 副文字。

    策略:
      - 短于 max_main 直接当主文字,副文字空
      - **先保护版本号 token** ("GPT-5.5" / "V4-Pro" / "2026-04-25") 不被切开
      - 找中文句号/逗号/分号/冒号/破折号,在合理位置切
      - 实在没自然断点才硬切
    """
    point = point.strip()
    if len(point) <= max_main:
        return point, ""

    protected, tokens = _protect_version_tokens(point)
    # 占位符长度不同,简单用字符级 index 工作即可

    # pattern 1: 中文/英文断句标点
    safe_splits = re.compile(r"——|[,。;：:,；！？!?]")
    for m in safe_splits.finditer(protected):
        if 3 <= m.start() <= max_main + 8:
            main = _restore_tokens(protected[: m.start()], tokens).strip()
            sub = _restore_tokens(protected[m.end():], tokens).strip()
            if main and sub and len(main) >= 3:
                return main, sub

    # pattern 2: 单独的 `-`(保护过版本号后的安全连字符),两侧至少一侧是中文才切
    for m in re.finditer(r"-", protected):
        i = m.start()
        if not (3 <= i <= max_main + 8):
            continue
        left = protected[i - 1] if i > 0 else ""
        right = protected[i + 1] if i + 1 < len(protected) else ""
        if re.match(r"[一-鿿]", left) or re.match(r"[一-鿿]", right):
            main = _restore_tokens(protected[:i], tokens).strip()
            sub = _restore_tokens(protected[i + 1:], tokens).strip()
            if main and sub:
                return main, sub

    # 硬切(在原始 point 上,但避开占位符)
    restored = _restore_tokens(protected, tokens)
    return restored[:max_main].strip(), restored[max_main:].strip()


def build_card_plan(
    parsed: Dict[str, Any],
    image_style: Optional[str] = None,
    card_count_override: Optional[int] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    把解析好的 brief 拍平成可执行的 card_plan。

    每张卡输出:
        {
          "index": 1,
          "card_main": str,
          "card_sub":  str,
          "prompt":    str,          # 填好 placeholder 的完整 Gemini prompt
          "target_file": str,        # 相对 output_dir 的目标文件名,如 images/01.png
          "aspect":    str,
          "size":      str,
        }
    """
    fm = parsed["frontmatter"] or {}
    sections = parsed["sections"]

    # 风格解析: CLI > frontmatter > 账号默认 > newspic 兜底(infographic-warm)
    # 贴图模式走 mode="newspic",让兜底用高密度手绘水彩信息图,而不是文章模式
    # 的线条手绘(hand-drawn-blue)
    style_name = image_style or fm.get("image_style")
    account = fm.get("account")
    style = resolve_image_style(
        cli_value=image_style,
        frontmatter_value=fm.get("image_style"),
        account_name=account,
        mode="newspic",
    )

    # 提取要点
    points_text = sections.get("要点") or sections.get("要点列表") or sections.get("卡片要点") or ""
    points = extract_bullet_points(points_text)
    if not points:
        raise ValueError(
            "brief.md 里找不到『# 要点』小节,或要点列表是空的。\n"
            "格式: # 要点 下面 1. xxx / - xxx / * xxx 每行一个"
        )

    target_count = card_count_override or fm.get("card_count") or len(points)
    if not 1 <= target_count <= 20:
        raise ValueError(f"card_count 必须在 1-20 之间,当前 {target_count}")
    if target_count > len(points):
        raise ValueError(
            f"card_count={target_count} > 要点数({len(points)})。"
            f"请补要点或调小 card_count。"
        )
    points = points[:target_count]

    # 构造每张卡
    topic = fm.get("topic", "")
    tmpl = style.get("prompt_template", {})
    newspic_prompt = tmpl.get("newspic_card") or tmpl.get("article_inline", "")
    if not newspic_prompt:
        raise ValueError(
            f"风格 '{style['style_name']}' 缺少 prompt_template.newspic_card,"
            "无法用于贴图。改用 newspic_ready=true 的风格。"
        )

    canvas = style.get("canvas", {})
    aspect = canvas.get("newspic_aspect", "1:1")
    size = canvas.get("newspic_size", "1080x1080")

    total = len(points)
    cards: List[Dict[str, Any]] = []
    for i, point in enumerate(points, start=1):
        main, sub = _split_card_text(point)
        prompt = (
            newspic_prompt
            .replace("{topic}", topic)
            .replace("{card_main}", main)
            .replace("{card_sub}", sub or main)  # 副文字空就复用主文字
            .replace("{point_full}", point)  # 原始完整要点,给 AI 更多上下文渲染信息图
            .replace("{card_index}", f"{i:02d}")
            .replace("{card_total}", f"{total:02d}")
            .replace("{image_subject}", f"{topic} - {main}")
        )
        cards.append({
            "index": i,
            "card_main": main,
            "card_sub": sub,
            "point_full": point,
            "prompt": prompt,
            "target_file": f"images/{i:02d}.png",
            "aspect": aspect,
            "size": size,
        })

    short_text = sections.get("短文本") or sections.get("短描述") or ""

    plan = {
        "topic": topic,
        "title": fm.get("title", ""),
        "account": account,
        "image_style": style["style_name"],
        "image_style_display": style.get("display_name", style["style_name"]),
        "card_count": len(cards),
        "cards": cards,
        "short_text": short_text,
        "short_text_target_chars": [100, 300],
        "output_dir": str(output_dir) if output_dir else None,
    }
    return plan


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="贴图拆卡 + 出图计划生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("brief", help="brief.md 路径")
    parser.add_argument("-o", "--output", help="card_plan.json 输出路径(默认 <brief_dir>/card_plan.json)")
    parser.add_argument("--image-style", help="覆盖 frontmatter 的 image_style")
    parser.add_argument("--card-count", type=int, help="覆盖 frontmatter 的 card_count")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印,不写文件")
    args = parser.parse_args()

    brief_path = Path(args.brief)
    if not brief_path.exists():
        print(f"[错误] brief.md 不存在: {brief_path}", file=sys.stderr)
        sys.exit(1)

    md_text = brief_path.read_text(encoding="utf-8")
    try:
        parsed = parse_brief(md_text)
        plan = build_card_plan(
            parsed,
            image_style=args.image_style,
            card_count_override=args.card_count,
            output_dir=brief_path.parent,
        )
    except (ValueError, ConfigError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    # 控制台人类友好摘要
    print(f"话题: {plan['topic']}")
    print(f"风格: {plan['image_style']} ({plan['image_style_display']})")
    print(f"卡数: {plan['card_count']}")
    print(f"标题: {plan['title'] or '(未填,发布时可用 --title 指定)'}")
    print(f"短文本: {'(已填)' if plan['short_text'] else '(未填,需 Claude 根据要点生成)'}")
    print("-" * 60)
    for c in plan["cards"]:
        print(f"  卡 {c['index']:2d}: {c['card_main']}")
        if c["card_sub"]:
            print(f"         └─ {c['card_sub']}")
        print(f"         → {c['target_file']}  ({c['aspect']} {c['size']})")
    print("-" * 60)

    if args.dry_run:
        print("[dry-run] 不写文件")
        return

    out_path = Path(args.output) if args.output else brief_path.parent / "card_plan.json"
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"card_plan.json 已写入: {out_path}")
    print("\n下一步:")
    print("  1. Claude 按 card_plan.json 里每张卡的 prompt 调 scripts/generate_image.py 生图")
    print(f"     目标路径: {brief_path.parent}/images/01.png, 02.png, ...")
    print("  2. 如短文本未填,Claude 根据要点撰写 100-300 字短描述写入 brief.md '# 短文本' 小节")
    print("  3. python3 ai_score.py <brief.md 里的短文本> --mode newspic --threshold 45")
    print(f"  4. python3 publish.py --account <main|tech> --type newspic --brief {brief_path}")


if __name__ == "__main__":
    main()
