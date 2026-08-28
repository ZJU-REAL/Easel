#!/usr/bin/env python3
"""
Markdown → 微信公众号 HTML 转换器

微信公众号编辑器的特殊限制:
- 不支持外部 CSS 和 JS 引用
- 不支持 class 和 id 属性(部分支持但不可靠)
- 所有样式必须使用内联 style
- 不支持 <style> 标签
- 不支持 position、float 等部分 CSS 属性
- 图片必须使用微信 CDN 的 URL

本转换器将 Markdown 转换为满足以上限制的 HTML,并应用精美的内联排版样式。

## 支持的 Markdown 扩展语法(排版增强标记)

除了标准 Markdown 之外,本转换器支持以下自定义行内标记,用来让段内
文字有更丰富的标色变化(字体颜色 + 背景高亮):

| 标记           | 含义          | 效果               |
|----------------|---------------|--------------------|
| `**文本**`     | 加粗(主强调)| 深色 + 黄色下划线  |
| `==文本==`     | 黄色高亮      | 荧光笔马克效果     |
| `++文本++`     | 蓝色高亮      | 冷色马克效果       |
| `%%文本%%`     | 粉色高亮      | 警示马克效果       |
| `&&文本&&`     | 绿色高亮      | 正向马克效果       |
| `!!文本!!`     | 红色强调      | 警告/反对/关键数字 |
| `@@文本@@`     | 蓝色强调      | 链接/术语/名词     |
| `^^文本^^`     | 橙色强调      | 温暖点缀           |
| `*文本*`       | 斜体          | 保留                |

写作时在同一篇文章里混用多种标记,避免"整篇只有一种加粗色"的
AI 号指纹。建议密度:每 500 字出现 3-5 处行内标记,但不要集中堆在
同一段里。

## 主题

样式从 assets/themes/<theme>.json 加载,默认 refined-blue。
每个主题包含 styles(标签样式)+ highlights(行内标记样式)+
section_divider_text(分节符字符)。
"""

import re
import json
import sys
import html
from pathlib import Path


# ============================================================
# 样式加载 / 主题解析
# ============================================================

DEFAULT_STYLES = {
    "body": "font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; font-size: 15.5px; color: #242832; line-height: 1.75; letter-spacing: 0.4px; word-spacing: 1.5px; padding: 12px 0;",
    "h1": "font-size: 22px; font-weight: 800; color: #0b1530; text-align: left; margin: 32px 0 20px; padding: 0 0 12px 0; border-bottom: 2px solid #0b1530; letter-spacing: 0.5px; line-height: 1.4;",
    "h2": "font-size: 18px; font-weight: 700; color: #0b1530; margin: 36px 0 16px; padding: 10px 0 10px 14px; border-left: 4px solid #2e5bff; background: linear-gradient(90deg, #eef2ff 0%, #ffffff 70%); border-radius: 0 6px 6px 0; line-height: 1.5; letter-spacing: 0.3px;",
    "h3": "font-size: 16px; font-weight: 700; color: #1a2240; margin: 26px 0 12px; padding: 0 0 6px 0; border-bottom: 1px dashed #c7d2fe; letter-spacing: 0.3px;",
    "p": "margin: 14px 0; text-indent: 0; text-align: justify; color: #242832; line-height: 1.85;",
    "blockquote": "margin: 22px 0; padding: 18px 22px; background: #f4f6fc; border-left: 3px solid #2e5bff; color: #3a4463; font-size: 14.5px; border-radius: 0 10px 10px 0; line-height: 1.85; letter-spacing: 0.4px;",
    "img": "max-width: 100%; height: auto; border-radius: 8px; margin: 22px auto; display: block; box-shadow: 0 6px 20px rgba(11,21,48,0.08); border: 1px solid #eef2ff;",
    "strong": "color: #0b1530; font-weight: 800; background: linear-gradient(180deg, transparent 62%, #fff18a 62%, #fff18a 95%, transparent 95%); padding: 0 2px;",
    "em": "font-style: italic; color: #5a6577;",
    "code_inline": "background: #eef2ff; color: #2e3a8a; padding: 2px 8px; border-radius: 4px; font-size: 13px; font-family: 'JetBrains Mono', 'Menlo', 'Consolas', 'SF Mono', monospace; border: 1px solid #dbe4ff;",
    "code_block": "background: #0f1729; color: #e1e7ff; padding: 20px 22px; border-radius: 10px; font-size: 13px; line-height: 1.7; font-family: 'JetBrains Mono', 'Menlo', 'Consolas', 'SF Mono', monospace; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; margin: 22px 0; border: 1px solid #1e2a4a;",
    "ul": "margin: 16px 0; padding-left: 4px; list-style-type: none;",
    "ol": "margin: 18px 0 18px 8px; padding-left: 28px; list-style-type: decimal; list-style-position: outside; color: #2e5bff; font-weight: 700;",
    "li": "margin: 10px 0; line-height: 1.8; padding-left: 8px; color: #242832; font-weight: 400; min-height: 22px;",
    "hr": "border: none; height: 1px; background: linear-gradient(to right, transparent, #c7d2fe, transparent); margin: 36px 0;",
    "a": "color: #2e5bff; text-decoration: none; border-bottom: 1px solid rgba(46,91,255,0.35); padding-bottom: 1px;",
    "table": "width: 100%; border-collapse: collapse; margin: 22px 0; font-size: 14px; border-radius: 8px; overflow: hidden; border: 1px solid #e8ecf7;",
    "th": "background: #0b1530; color: #ffffff; padding: 12px 14px; text-align: left; font-weight: 600; font-size: 13px; letter-spacing: 0.3px;",
    "td": "padding: 11px 14px; border-bottom: 1px solid #eef2ff; color: #242832;",
    "caption": "font-size: 12.5px; color: #8a93a8; text-align: center; margin-top: 10px; letter-spacing: 0.5px; font-style: italic;",
    "section_divider": "text-align: center; color: #c7d2fe; letter-spacing: 14px; font-size: 11px; margin: 36px 0 30px; user-select: none;",
}

DEFAULT_HIGHLIGHTS = {
    "hl_yellow": "background: linear-gradient(180deg, transparent 55%, #fff18a 55%); color: #242832; padding: 0 3px; font-weight: 600;",
    "hl_blue":   "background: #dbe4ff; color: #1e2a8a; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
    "hl_pink":   "background: #ffe0ec; color: #a6115a; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
    "hl_green":  "background: #d7f5e2; color: #167a44; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
    "em_red":    "color: #c43a30; font-weight: 700;",
    "em_blue":   "color: #2e5bff; font-weight: 700;",
    "em_orange": "color: #ea7c1c; font-weight: 700;",
}

DEFAULT_SECTION_DIVIDER_TEXT = "● ● ●"

# 默认 list_style:让旧主题(没写 list_style 的)也能用统一的渲染逻辑。
# 渲染器会先把数字/项目符号包成 <span>,样式跟着主题走;旧主题的 ol/ul/li
# 还在,只是多出来一个 prefix span,视觉影响极小。
DEFAULT_LIST_STYLE = {
    "num_container": "color: #4a6cf7; font-weight: 700; margin-right: 8px;",
    "num_prefix": "",
    "num_suffix": ".",
    "num_formatter": "decimal",
    "bullet_container": "color: #4a6cf7; margin-right: 8px;",
    "bullet_char": "●",
}


def _themes_dir():
    return Path(__file__).parent.parent / "assets" / "themes"


def list_themes():
    """列出可用主题名称"""
    d = _themes_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_theme(theme_name=None, style_path=None):
    """
    加载一个完整主题(styles + highlights + section_divider_text + list_style)。

    参数优先级:
      1. style_path(显式指定 JSON 文件)
      2. theme_name(查 assets/themes/<name>.json)
      3. 内置 DEFAULT_STYLES / DEFAULT_HIGHLIGHTS / DEFAULT_LIST_STYLE

    返回:
        (styles: dict, highlights: dict, divider_text: str, list_style: dict)

    注:为向后兼容,如果调用方按 3 元组解包(styles, highlights, divider),
    多出来的 list_style 会被忽略。convert_markdown_to_wechat_html 自身
    会从默认值兜底,没传 list_style 不会出问题。
    """
    styles = DEFAULT_STYLES.copy()
    highlights = DEFAULT_HIGHLIGHTS.copy()
    divider_text = DEFAULT_SECTION_DIVIDER_TEXT
    list_style = DEFAULT_LIST_STYLE.copy()

    candidates = []
    if style_path:
        candidates.append(Path(style_path))
    if theme_name:
        candidates.append(_themes_dir() / f"{theme_name}.json")

    for path in candidates:
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                styles.update(data.get("styles", {}))
                highlights.update(data.get("highlights", {}))
                if data.get("section_divider_text"):
                    divider_text = data["section_divider_text"]
                if data.get("list_style"):
                    list_style.update(data["list_style"])
                break
            except (json.JSONDecodeError, KeyError):
                continue

    return styles, highlights, divider_text, list_style


def load_styles(style_path=None):
    """向后兼容:老接口只返回 styles。"""
    styles, _, _, _ = load_theme(style_path=style_path)
    return styles


# ---------- 数字格式化(给 list_style.num_formatter 用) ----------
_CN = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
_ROMAN_U = ["", "Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]
_ROMAN_L = ["", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
_CIRCLED = ["", "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
_CIRCLED_FILLED = ["", "❶", "❷", "❸", "❹", "❺", "❻", "❼", "❽", "❾", "❿"]


def _format_num(n: int, fmt: str) -> str:
    if fmt == "padded":         return f"{n:02d}"
    if fmt == "decimal":        return str(n)
    if fmt == "chinese":        return _CN[n] if 0 < n < len(_CN) else str(n)
    if fmt == "roman_upper":    return _ROMAN_U[n] if 0 < n < len(_ROMAN_U) else str(n)
    if fmt == "roman_lower":    return _ROMAN_L[n] if 0 < n < len(_ROMAN_L) else str(n)
    if fmt == "circled":        return _CIRCLED[n] if 0 < n < len(_CIRCLED) else str(n)
    if fmt == "circled_filled": return _CIRCLED_FILLED[n] if 0 < n < len(_CIRCLED_FILLED) else str(n)
    return str(n)


# ============================================================
# Markdown 解析与转换
# ============================================================

# 行内扩展标记(有序,先处理长模式)
INLINE_MARKS = [
    # (正则, highlight_key)
    (r'==([^=\n]+)==',  "hl_yellow"),
    (r'\+\+([^+\n]+)\+\+', "hl_blue"),
    (r'%%([^%\n]+)%%',  "hl_pink"),
    (r'&&([^&\n]+)&&',  "hl_green"),
    (r'!!([^!\n]+)!!',  "em_red"),
    (r'@@([^@\n]+)@@',  "em_blue"),
    (r'\^\^([^\^\n]+)\^\^', "em_orange"),
]


def convert_markdown_to_wechat_html(
    markdown_text, styles=None, highlights=None, divider_text=None, list_style=None
):
    """
    将 Markdown 文本转换为微信公众号兼容的 HTML。

    Args:
        markdown_text: Markdown 格式的文章内容
        styles: 标签样式字典(默认使用内置)
        highlights: 行内标记样式字典(默认使用内置)
        divider_text: 分节符文本
        list_style: 主题的 list_style 块,控制 ol/ul 的序号 / 项目符号样式

    Returns:
        str: 微信兼容的 HTML 字符串
    """
    if styles is None:
        styles = DEFAULT_STYLES.copy()
    if highlights is None:
        highlights = DEFAULT_HIGHLIGHTS.copy()
    if divider_text is None:
        divider_text = DEFAULT_SECTION_DIVIDER_TEXT
    if list_style is None:
        list_style = DEFAULT_LIST_STYLE.copy()

    lines = markdown_text.split("\n")
    html_parts = []
    in_code_block = False
    code_block_content = []
    in_list = False
    list_type = None
    list_items = []
    in_blockquote = False
    blockquote_lines = []
    in_table = False
    table_rows = []
    h1_seen = False
    prev_was_h2 = False

    # ---- list_style 渲染辅助 ----
    def _num_token(n: int) -> str:
        prefix = list_style.get("num_prefix", "")
        suffix = list_style.get("num_suffix", "")
        fmt = list_style.get("num_formatter", "decimal")
        container = list_style.get("num_container", "")
        return f'<span style="{container}">{prefix}{_format_num(n, fmt)}{suffix}</span>'

    def _bullet_token() -> str:
        glyph = list_style.get("bullet_char", "•") or "&nbsp;"
        container = list_style.get("bullet_container", "")
        return f'<span style="{container}">{glyph}</span>'

    def flush_list():
        nonlocal in_list, list_items, list_type
        if in_list and list_items:
            tag = list_type or "ul"
            if tag == "ul":
                items_html = "\n".join(
                    f'<li style="{styles["li"]}">{_bullet_token()}{item}</li>'
                    for item in list_items
                )
            else:
                items_html = "\n".join(
                    f'<li style="{styles["li"]}">{_num_token(n)}{item}</li>'
                    for n, item in enumerate(list_items, 1)
                )
            html_parts.append(f'<{tag} style="{styles[tag]}">{items_html}</{tag}>')
            list_items = []
            in_list = False
            list_type = None

    def flush_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote and blockquote_lines:
            content = "<br>".join(blockquote_lines)
            html_parts.append(f'<blockquote style="{styles["blockquote"]}">{content}</blockquote>')
            blockquote_lines = []
            in_blockquote = False

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            rows_html = []
            for i, row in enumerate(table_rows):
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if i == 0:
                    cells_html = "".join(f'<th style="{styles["th"]}">{c}</th>' for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
                elif all(set(c.strip()) <= {"-", ":"} for c in cells):
                    continue
                else:
                    cells_html = "".join(f'<td style="{styles["td"]}">{c}</td>' for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
            html_parts.append(f'<table style="{styles["table"]}">{"".join(rows_html)}</table>')
            table_rows = []
            in_table = False

    def _escape_html(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def process_inline(text):
        """处理行内 Markdown 语法 + 扩展标记。

        安全处理:
        - 先转义 <,> 以阻止原始 HTML/JS (<script> 之类)透传
          (& 不在这一步转义,因为自定义标记 &&...&& 会被破坏;
          所有由我们自己生成的 style 属性都不含原始 &,所以无需
          整体转义,只在最后把游离的 & 转成 &amp;)
        - 链接 [text](url) 的 url 若以 javascript: / data: / vbscript: 开头
          (忽略大小写和前导空白),直接退化为纯文本
        - 图片 ![alt](url) 的 alt/url 经 html.escape(quote=True) 处理
        """
        # 1. 先把原始 <,> 转义掉 ── 禁止 <script> 透传
        text = text.replace("<", "&lt;").replace(">", "&gt;")

        # 2. 图片 ![alt](url) —— alt/url 完整转义,防止属性注入
        def _img_sub(m):
            alt = html.escape(m.group(1), quote=True)
            src = html.escape(m.group(2), quote=True)
            return f'<img src="{src}" alt="{alt}" style="{styles["img"]}"/>'
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _img_sub, text)

        # 3. 链接 [text](url) —— 拒绝危险协议
        _DANGEROUS_URL = re.compile(r'^\s*(javascript|data|vbscript)\s*:', re.IGNORECASE)
        def _link_sub(m):
            link_text = m.group(1)
            url = m.group(2).strip()
            if _DANGEROUS_URL.match(url):
                # 不生成 <a>,仅保留纯文本
                return link_text
            safe_url = html.escape(url, quote=True)
            return f'<a href="{safe_url}" style="{styles["a"]}">{link_text}</a>'
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _link_sub, text)

        # 4. 行内代码 `code`
        text = re.sub(
            r'`([^`]+)`',
            lambda m: f'<code style="{styles["code_inline"]}">{_escape_html(m.group(1))}</code>',
            text,
        )
        # 5. 扩展行内标记(==/++/%%/&&/!!/@@/^^)—— 要在 ** 之前处理
        for pattern, key in INLINE_MARKS:
            style_str = highlights.get(key, "")
            if not style_str:
                continue
            text = re.sub(
                pattern,
                lambda m, s=style_str: f'<span style="{s}">{m.group(1)}</span>',
                text,
            )
        # 6. 粗体 **text**
        text = re.sub(
            r'\*\*([^*\n]+)\*\*',
            lambda m: f'<strong style="{styles["strong"]}">{m.group(1)}</strong>',
            text,
        )
        # 7. 斜体 *text*
        text = re.sub(
            r'(?<!\*)\*([^*\n]+)\*(?!\*)',
            lambda m: f'<em style="{styles["em"]}">{m.group(1)}</em>',
            text,
        )
        # 8. 收尾:把游离的 & 转成 &amp;(不影响已生成的 &lt;/&gt;/&amp;/&#...)
        text = re.sub(r'&(?!(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});)', '&amp;', text)
        return text

    for line in lines:
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code_block:
                code_html = "\n".join(code_block_content)
                html_parts.append(f'<pre style="{styles["code_block"]}">{code_html}</pre>')
                code_block_content = []
                in_code_block = False
            else:
                flush_list()
                flush_blockquote()
                flush_table()
                in_code_block = True
            prev_was_h2 = False
            continue

        if in_code_block:
            code_block_content.append(_escape_html(line))
            continue

        # 表格
        if "|" in stripped and stripped.startswith("|"):
            flush_list()
            flush_blockquote()
            if not in_table:
                in_table = True
            table_rows.append(stripped)
            prev_was_h2 = False
            continue
        else:
            flush_table()

        # 引用块
        if stripped.startswith(">"):
            flush_list()
            if not in_blockquote:
                in_blockquote = True
            content = stripped.lstrip(">").strip()
            blockquote_lines.append(process_inline(content))
            prev_was_h2 = False
            continue
        else:
            flush_blockquote()

        # 自定义分节符: 单独一行的 `===` / `~~~` / `[SEC]`
        # `[SEC]` 是新主题包(2026)推荐写法,等价于旧的 `===`。
        if re.match(r'^(={3,}|~{3,})$', stripped) or stripped == "[SEC]":
            flush_list()
            html_parts.append(
                f'<p style="{styles.get("section_divider", "")}">{divider_text}</p>'
            )
            prev_was_h2 = False
            continue

        # 标题
        h_match = re.match(r'^(#{1,3})\s+(.+)$', stripped)
        if h_match:
            flush_list()
            level = len(h_match.group(1))
            text = process_inline(h_match.group(2))
            tag = f"h{level}"
            if level == 1 and not h1_seen:
                h1_seen = True
                prev_was_h2 = False
                continue
            # 如果两个 h2 之间已经有正文,在下一个 h2 前插一个分节符
            if level == 2 and html_parts and not prev_was_h2:
                html_parts.append(
                    f'<p style="{styles.get("section_divider", "")}">{divider_text}</p>'
                )
            html_parts.append(f'<{tag} style="{styles[tag]}">{text}</{tag}>')
            prev_was_h2 = (level == 2)
            continue

        # 分割线
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped):
            flush_list()
            html_parts.append(f'<hr style="{styles["hr"]}"/>')
            prev_was_h2 = False
            continue

        # 无序列表
        ul_match = re.match(r'^[-*+]\s+(.+)$', stripped)
        if ul_match:
            if not in_list or list_type != "ul":
                flush_list()
                in_list = True
                list_type = "ul"
            list_items.append(process_inline(ul_match.group(1)))
            prev_was_h2 = False
            continue

        # 有序列表
        ol_match = re.match(r'^\d+\.\s+(.+)$', stripped)
        if ol_match:
            if not in_list or list_type != "ol":
                flush_list()
                in_list = True
                list_type = "ol"
            list_items.append(process_inline(ol_match.group(1)))
            prev_was_h2 = False
            continue

        flush_list()

        if not stripped:
            continue

        # 纯图片行 —— alt/src 必须转义,避免 "><script> 这种属性注入
        img_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', stripped)
        if img_match:
            alt_raw = img_match.group(1)
            src_raw = img_match.group(2)
            alt = html.escape(alt_raw, quote=True)
            src = html.escape(src_raw, quote=True)
            html_parts.append(f'<p style="text-align:center;margin:16px 0;"><img src="{src}" alt="{alt}" style="{styles["img"]}"/></p>')
            if alt_raw:
                html_parts.append(f'<p style="{styles["caption"]}">{alt}</p>')
            prev_was_h2 = False
            continue

        # 普通段落
        text = process_inline(stripped)
        html_parts.append(f'<p style="{styles["p"]}">{text}</p>')
        prev_was_h2 = False

    flush_list()
    flush_blockquote()
    flush_table()

    # #23: 未闭合的代码块 —— 尽力把已积累的内容按代码块渲染,避免默默丢失内容
    if in_code_block and code_block_content:
        print("警告: 未闭合的 code block,已按代码块渲染", file=sys.stderr)
        code_html = "\n".join(code_block_content)
        html_parts.append(f'<pre style="{styles["code_block"]}">{code_html}</pre>')
        code_block_content = []
        in_code_block = False
    elif in_code_block:
        # 代码块开了但一行内容都没有 —— 也提醒一下
        print("警告: 未闭合的 code block,已按代码块渲染", file=sys.stderr)
        in_code_block = False

    body = "\n".join(html_parts)
    return f'<section style="{styles["body"]}">\n{body}\n</section>'


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Markdown → 微信公众号 HTML 转换器")
    parser.add_argument("input", help="Markdown 文件路径")
    parser.add_argument("-o", "--output", help="输出 HTML 文件路径(默认 stdout)")
    parser.add_argument("--theme", help=f"主题名,可选: {', '.join(list_themes()) or '无'}")
    parser.add_argument("--style", help="自定义样式 JSON 文件路径(覆盖 --theme)")
    parser.add_argument("--list-themes", action="store_true", help="列出所有可用主题")

    args = parser.parse_args()

    if args.list_themes:
        themes = list_themes()
        if not themes:
            print("未找到主题(assets/themes/ 为空)")
        else:
            for t in themes:
                print(t)
        sys.exit(0)

    with open(args.input, "r", encoding="utf-8") as f:
        md_text = f.read()

    styles, highlights, divider_text, list_style = load_theme(
        theme_name=args.theme, style_path=args.style
    )
    html = convert_markdown_to_wechat_html(
        md_text, styles, highlights, divider_text, list_style
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"转换完成: {args.output}")
    else:
        print(html)
