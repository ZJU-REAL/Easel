#!/usr/bin/env python3
"""Render and audit paper-explainer slides from a constrained slide-plan JSON."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


THEMES: dict[str, dict[str, Any]] = {
    "editorial": {"bg": "#f3f0e8", "ink": "#11110f", "muted": "#68625a",
                  "accent": "#315d93", "accent2": "#9b5a2e", "line": "#d2ccc0",
                  "surface": "#ffffff", "panel": "#ebe7dc", "font": "serif",
                  "radius": 4, "heading_weight": 400, "texture": "paper"},
    "swiss": {"bg": "#fafaf8", "ink": "#0a0a0a", "muted": "#686868",
              "accent": "#002fa7", "accent2": "#ff6b35", "line": "#d8d8d4",
              "surface": "#ffffff", "panel": "#f0f0ed", "font": "sans",
              "radius": 0, "heading_weight": 300, "texture": "none"},
    "noir": {"bg": "#0e0d0c", "ink": "#ece2cf", "muted": "#9a8c75",
             "accent": "#d4a04a", "accent2": "#b95f55", "line": "#3a332b",
             "surface": "#171512", "panel": "#171512", "font": "serif",
             "radius": 2, "heading_weight": 300, "texture": "paper"},
    "chinese-ink": {"bg": "#f3efe4", "ink": "#1a1a1a", "muted": "#6b6357",
                    "accent": "#a8322d", "accent2": "#b08d57", "line": "#cfc5b5",
                    "surface": "#faf7ef", "panel": "#ebe4d7", "font": "serif",
                    "radius": 2, "heading_weight": 500, "texture": "paper"},
    "cream": {"bg": "#faf6ef", "ink": "#51463d", "muted": "#6f6054",
              "accent": "#8ca3ad", "accent2": "#c9a9a6", "line": "#ded3c5",
              "surface": "#fffdf9", "panel": "#ede4d3", "font": "sans",
              "radius": 24, "heading_weight": 600, "texture": "none"},
    "dopamine": {"bg": "#ffd500", "ink": "#0a0a0a", "muted": "#353535",
                 "accent": "#002fa7", "accent2": "#ff5ca8", "line": "#0a0a0a",
                 "surface": "#ffffff", "panel": "#c5e803", "font": "sans",
                 "radius": 8, "heading_weight": 900, "texture": "halftone"},
    "journal": {"bg": "#fbf7f0", "ink": "#332f2a", "muted": "#625b54",
                "accent": "#b77979", "accent2": "#6f9d87", "line": "#cfc3b5",
                "surface": "#fffdfa", "panel": "#f3d9a4", "font": "sans",
                "radius": 10, "heading_weight": 600, "texture": "grid"},
    "terminal": {"bg": "#0d1117", "ink": "#c9d1d9", "muted": "#7d8590",
                 "accent": "#3fb950", "accent2": "#e3b341", "line": "#30363d",
                 "surface": "#161b22", "panel": "#161b22", "font": "mono",
                 "radius": 6, "heading_weight": 600, "texture": "grid"},
    "botanical": {"bg": "#f6f4ee", "ink": "#2f3b2c", "muted": "#5d6858",
                  "accent": "#7d9b76", "accent2": "#c08457", "line": "#ccd4c8",
                  "surface": "#fcfbf7", "panel": "#e7ede3", "font": "serif",
                  "radius": 12, "heading_weight": 500, "texture": "paper"},
    "cute-anime": {"bg": "#fff8ef", "ink": "#25304b", "muted": "#626b83",
                   "accent": "#ff6f91", "accent2": "#669cf6", "line": "#384364",
                   "surface": "#ffffff", "panel": "#fff0f4", "font": "rounded",
                   "radius": 24, "heading_weight": 700, "texture": "sparkle"},
    "detective-comic": {"bg": "#f7fbff", "ink": "#101827", "muted": "#4f5b70",
                        "accent": "#1257b7", "accent2": "#e51b2b", "line": "#101827",
                        "surface": "#ffffff", "panel": "#fff0a8", "font": "sans",
                        "radius": 6, "heading_weight": 900, "texture": "halftone"},
}
BASE_STYLES = set(THEMES)
THEME_COLOR_KEYS = {"bg", "ink", "muted", "accent", "accent2", "line", "surface", "panel"}
THEME_KEYS = THEME_COLOR_KEYS | {"font", "radius", "heading_weight", "texture"}
FONT_FAMILIES = {"sans", "serif", "mono", "rounded"}
TEXTURES = {"none", "paper", "grid", "halftone", "sparkle"}
TREATMENTS = {"clean", "soft", "comic", "technical", "handmade"}
MOTIFS = {"auto", "none", "index", "brackets", "rings", "crosshair"}
CONTENT_DENSITIES = {"balanced", "visual"}
DEFAULT_TREATMENTS = {
    "cream": "soft", "cute-anime": "soft",
    "dopamine": "comic", "detective-comic": "comic",
    "terminal": "technical", "journal": "handmade",
}

MINIMUMS = {
    "point": 8,
    "step_body": 12,
    "metric_note": 6,
    "column_body": 24,
}
SLIDE_TYPES = {"cover", "statement", "evidence", "process", "metrics", "comparison", "takeaway"}
SIZES = {"1920x1080": (1920, 1080), "1080x1920": (1080, 1920)}
LIMITS = {
    "title": 28,
    "claim": 72,
    "point": 48,
    "source": 100,
    "step_title": 16,
    "step_body": 52,
    "metric_value": 14,
    "metric_label": 20,
    "metric_note": 40,
    "column_title": 20,
    "column_body": 90,
}


def _die(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def _read_plan(path: str) -> tuple[Path, dict[str, Any]]:
    plan_path = Path(path).expanduser().resolve()
    if not plan_path.is_file():
        _die(f"slide plan 不存在：{plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"slide plan 不是有效 JSON：{exc}")
    if not isinstance(plan, dict):
        _die("slide plan 顶层必须是 object")
    return plan_path, plan


def _text_len(value: Any) -> int:
    return len(str(value or "").strip())


def _hex_luminance(value: str) -> float:
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    first, second = _hex_luminance(foreground), _hex_luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _effective_theme(plan: dict[str, Any]) -> dict[str, Any]:
    custom = plan.get("theme") if isinstance(plan.get("theme"), dict) else {}
    return {**THEMES[_base_style(plan)], **custom}


def _theme_contrast_problems(plan: dict[str, Any]) -> list[str]:
    theme = _effective_theme(plan)
    problems = []
    for foreground in ("ink", "muted"):
        for background in ("bg", "surface", "panel"):
            ratio = _contrast_ratio(theme[foreground], theme[background])
            if ratio < 4.5:
                problems.append(
                    f"theme.{foreground} 与 theme.{background} 对比度 {ratio:.2f}:1 < 4.5:1"
                )
    return problems


def _readable_accent(accent: str, ink: str, background: str, minimum: float = 4.5) -> str:
    return accent if _contrast_ratio(accent, background) >= minimum else ink


def _on_accent_color(accent: str, ink: str, surface: str) -> str:
    return max((ink, surface), key=lambda candidate: _contrast_ratio(candidate, accent))


def _resolve_asset(plan_path: Path, raw: str) -> Path:
    source = Path(raw).expanduser()
    if source.is_absolute():
        return source.resolve()
    local = (plan_path.parent / source).resolve()
    if local.exists():
        return local
    return (Path.cwd() / source).resolve()


def _figure(slide: dict[str, Any]) -> dict[str, str] | None:
    raw = slide.get("figure")
    if not raw:
        return None
    if isinstance(raw, str):
        return {"path": raw, "caption": "", "fit": "contain"}
    if isinstance(raw, dict):
        return {
            "path": str(raw.get("path") or ""),
            "caption": str(raw.get("caption") or ""),
            "fit": str(raw.get("fit") or "contain"),
        }
    return {"path": "", "caption": "", "fit": "contain"}


def _theme_problems(theme: Any) -> list[str]:
    if theme is None:
        return []
    if not isinstance(theme, dict):
        return ["theme 必须是 object"]
    problems = []
    unknown = sorted(set(theme) - THEME_KEYS)
    if unknown:
        problems.append(f"theme 含不支持字段：{', '.join(unknown)}")
    for key in THEME_COLOR_KEYS & set(theme):
        if not isinstance(theme[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", theme[key]):
            problems.append(f"theme.{key} 必须是 #RRGGBB")
    if "font" in theme and theme["font"] not in FONT_FAMILIES:
        problems.append(f"theme.font 必须是 {', '.join(sorted(FONT_FAMILIES))}")
    if "texture" in theme and theme["texture"] not in TEXTURES:
        problems.append(f"theme.texture 必须是 {', '.join(sorted(TEXTURES))}")
    if "radius" in theme and (not isinstance(theme["radius"], int) or not 0 <= theme["radius"] <= 32):
        problems.append("theme.radius 必须是 0–32 的整数")
    if "heading_weight" in theme and (
        not isinstance(theme["heading_weight"], int) or theme["heading_weight"] not in range(100, 1000, 100)
    ):
        problems.append("theme.heading_weight 必须是 100–900、步长 100")
    return problems


def _base_style(plan: dict[str, Any]) -> str:
    requested = plan.get("base_style")
    if requested in BASE_STYLES:
        return str(requested)
    legacy = plan.get("style")
    return str(legacy) if legacy in BASE_STYLES else "editorial"


def _treatment(plan: dict[str, Any]) -> str:
    requested = plan.get("treatment")
    if requested in TREATMENTS:
        return str(requested)
    return DEFAULT_TREATMENTS.get(_base_style(plan), "clean")


def _motif(plan: dict[str, Any], slide: dict[str, Any]) -> str:
    requested = slide.get("motif", plan.get("motif", "auto"))
    if requested != "auto":
        return str(requested)
    return {
        "soft": "rings", "comic": "index", "technical": "crosshair",
        "handmade": "brackets", "clean": "brackets",
    }[_treatment(plan)]


def validate_plan(plan_path: Path, plan: dict[str, Any], *, check_assets: bool = True) -> list[str]:
    problems: list[str] = []
    if plan.get("version") != 1:
        problems.append("version 必须为 1")
    style = plan.get("style")
    if not isinstance(style, str) or not style.strip() or len(style.strip()) > 60:
        problems.append("style 必须是 1–60 字符的风格意图")
    base_style = plan.get("base_style")
    if base_style is not None and base_style not in BASE_STYLES:
        problems.append(f"base_style 必须是 {', '.join(sorted(BASE_STYLES))}")
    if isinstance(style, str) and style not in BASE_STYLES and base_style is None:
        problems.append("自定义 style 必须指定 base_style，用于稳定渲染")
    if plan.get("treatment") is not None and plan.get("treatment") not in TREATMENTS:
        problems.append(f"treatment 必须是 {', '.join(sorted(TREATMENTS))}")
    if plan.get("motif") is not None and plan.get("motif") not in MOTIFS:
        problems.append(f"motif 必须是 {', '.join(sorted(MOTIFS))}")
    theme_problems = _theme_problems(plan.get("theme"))
    problems.extend(theme_problems)
    if not theme_problems:
        problems.extend(_theme_contrast_problems(plan))
    if plan.get("density") is not None and plan.get("density") not in CONTENT_DENSITIES:
        problems.append(f"density 必须是 {', '.join(sorted(CONTENT_DENSITIES))}")
    if plan.get("size") not in SIZES:
        problems.append("size 仅支持 1920x1080 或 1080x1920")
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        problems.append("slides 必须是非空数组")
        return problems
    if len(slides) > 24:
        problems.append("slides 最多 24 页；更长内容请拆集")

    last_type = ""
    repeated = 0
    for index, slide in enumerate(slides, 1):
        prefix = f"slide {index}"
        if not isinstance(slide, dict):
            problems.append(f"{prefix}: 必须是 object")
            continue
        slide_type = slide.get("type")
        if slide_type not in SLIDE_TYPES:
            problems.append(f"{prefix}: type 不支持：{slide_type}")
            continue
        repeated = repeated + 1 if slide_type == last_type else 1
        last_type = slide_type
        if repeated > 2:
            problems.append(f"{prefix}: 连续超过两页使用 {slide_type}，需要切换视觉节奏")
        if slide.get("motif") is not None and slide.get("motif") not in MOTIFS:
            problems.append(f"{prefix}: motif 必须是 {', '.join(sorted(MOTIFS))}")
        density = slide.get("density", plan.get("density", "balanced"))
        if density not in CONTENT_DENSITIES:
            problems.append(f"{prefix}: density 必须是 {', '.join(sorted(CONTENT_DENSITIES))}")
            density = "balanced"

        title = str(slide.get("title") or "").strip()
        claim = str(slide.get("claim") or "").strip()
        if not title:
            problems.append(f"{prefix}: 缺 title")
        if _text_len(title) > LIMITS["title"]:
            problems.append(f"{prefix}: title {_text_len(title)} 字符 > {LIMITS['title']}")
        if _text_len(claim) > LIMITS["claim"]:
            problems.append(f"{prefix}: claim {_text_len(claim)} 字符 > {LIMITS['claim']}")
        if slide_type in {"cover", "statement", "evidence", "metrics", "takeaway"} and not claim:
            problems.append(f"{prefix}: {slide_type} 缺 claim")

        points = slide.get("points") or []
        if not isinstance(points, list):
            problems.append(f"{prefix}: points 必须是数组")
            points = []
        if len(points) > 5:
            problems.append(f"{prefix}: points 最多 5 条")
        for point_index, point in enumerate(points, 1):
            if _text_len(point) > LIMITS["point"]:
                problems.append(
                    f"{prefix}: point {point_index} {_text_len(point)} 字符 > {LIMITS['point']}"
                )

        fig = _figure(slide)
        if slide_type == "evidence" and not fig:
            problems.append(f"{prefix}: evidence 必须提供 figure")
        if fig:
            if not fig["path"]:
                problems.append(f"{prefix}: figure.path 不能为空")
            elif check_assets and not _resolve_asset(plan_path, fig["path"]).is_file():
                problems.append(f"{prefix}: figure 不存在：{fig['path']}")
            if fig["fit"] not in {"contain", "cover"}:
                problems.append(f"{prefix}: figure.fit 仅支持 contain/cover")
        if density == "visual" and not fig:
            problems.append(f"{prefix}: density=visual 必须提供承载主要信息的 figure")

        if density == "balanced":
            if slide_type in {"statement", "takeaway"} and not fig and len(points) < 2:
                problems.append(f"{prefix}: {slide_type} 无 figure 时至少需要 2 条解释/启示 points")
            if slide_type == "evidence" and len(points) < 2:
                problems.append(f"{prefix}: evidence 至少需要 2 条读图线索 points；纯视觉页请显式用 density=visual")
            for point_index, point in enumerate(points, 1):
                if _text_len(point) < MINIMUMS["point"]:
                    problems.append(
                        f"{prefix}: point {point_index} 只有 {_text_len(point)} 字符，需写成可独立理解的解释"
                    )

        steps = slide.get("steps") or []
        if slide_type == "process" and not (isinstance(steps, list) and 2 <= len(steps) <= 4):
            problems.append(f"{prefix}: process 需要 2–4 个 steps")
        if isinstance(steps, list):
            for step_index, step in enumerate(steps, 1):
                if not isinstance(step, dict):
                    problems.append(f"{prefix}: step {step_index} 必须是 object")
                    continue
                if _text_len(step.get("title")) > LIMITS["step_title"]:
                    problems.append(f"{prefix}: step {step_index} title 过长")
                if _text_len(step.get("body")) > LIMITS["step_body"]:
                    problems.append(f"{prefix}: step {step_index} body 过长")
                if density == "balanced" and _text_len(step.get("body")) < MINIMUMS["step_body"]:
                    problems.append(f"{prefix}: step {step_index} body 信息不足，需说明动作或因果")

        metrics = slide.get("metrics") or []
        if slide_type == "metrics" and not (isinstance(metrics, list) and 1 <= len(metrics) <= 3):
            problems.append(f"{prefix}: metrics 需要 1–3 个指标")
        if isinstance(metrics, list):
            for metric_index, metric in enumerate(metrics, 1):
                if not isinstance(metric, dict):
                    problems.append(f"{prefix}: metric {metric_index} 必须是 object")
                    continue
                for field, limit_key in (("value", "metric_value"), ("label", "metric_label"),
                                         ("note", "metric_note")):
                    if _text_len(metric.get(field)) > LIMITS[limit_key]:
                        problems.append(f"{prefix}: metric {metric_index} {field} 过长")
                if density == "balanced" and _text_len(metric.get("note")) < MINIMUMS["metric_note"]:
                    problems.append(f"{prefix}: metric {metric_index} note 信息不足，需解释数字口径或意义")

        columns = slide.get("columns") or []
        if slide_type == "comparison" and not (isinstance(columns, list) and len(columns) == 2):
            problems.append(f"{prefix}: comparison 需要恰好 2 个 columns")
        if isinstance(columns, list):
            for column_index, column in enumerate(columns, 1):
                if not isinstance(column, dict):
                    problems.append(f"{prefix}: column {column_index} 必须是 object")
                    continue
                if _text_len(column.get("title")) > LIMITS["column_title"]:
                    problems.append(f"{prefix}: column {column_index} title 过长")
                if _text_len(column.get("body")) > LIMITS["column_body"]:
                    problems.append(f"{prefix}: column {column_index} body 过长")
                if density == "balanced" and _text_len(column.get("body")) < MINIMUMS["column_body"]:
                    problems.append(f"{prefix}: column {column_index} body 信息不足，需形成完整对比依据")

        if _text_len(slide.get("source") or plan.get("source")) > LIMITS["source"]:
            problems.append(f"{prefix}: source 过长")
    return problems


def _esc(value: Any) -> str:
    return html.escape(str(value or "").strip())


def _figure_html(plan_path: Path, slide: dict[str, Any]) -> str:
    fig = _figure(slide)
    if not fig:
        return ""
    path = _resolve_asset(plan_path, fig["path"])
    caption = f'<div class="figure-caption" data-fit>{_esc(fig["caption"])}</div>' if fig["caption"] else ""
    return (
        '<figure class="figure-shell" data-layout-box>'
        f'<img src="{path.as_uri()}" class="figure-img fit-{fig["fit"]}" alt="">'
        f"{caption}</figure>"
    )


def _points_html(points: Any) -> str:
    if not isinstance(points, list) or not points:
        return ""
    items = "".join(
        f'<li><span class="point-no">{index:02d}</span><span data-fit>{_esc(point)}</span></li>'
        for index, point in enumerate(points, 1)
    )
    return f'<ol class="points">{items}</ol>'


def _slide_body(plan_path: Path, slide: dict[str, Any]) -> str:
    slide_type = slide["type"]
    claim = f'<div class="claim" data-fit>{_esc(slide.get("claim"))}</div>' if slide.get("claim") else ""
    points = _points_html(slide.get("points"))
    figure = _figure_html(plan_path, slide)
    if slide_type == "cover":
        return f'<div class="cover-copy" data-layout-box>{claim}{points}</div>{figure}'
    if slide_type in {"statement", "takeaway"}:
        return f'<div class="statement-copy" data-layout-box>{claim}{points}</div>{figure}'
    if slide_type == "evidence":
        return f'<div class="evidence-grid" data-layout-box data-align-group>{figure}<div class="evidence-copy" data-layout-box>{claim}{points}</div></div>'
    if slide_type == "process":
        step_items = slide.get("steps") or []
        steps = "".join(
            '<div class="step" data-layout-box>'
            f'<div class="step-no">{index:02d}</div>'
            f'<h3 data-fit>{_esc(step.get("title"))}</h3>'
            f'<p data-fit>{_esc(step.get("body"))}</p>'
            '</div>'
            for index, step in enumerate(step_items, 1)
        )
        return f'<div class="process count-{len(step_items)}" data-layout-box data-align-group>{steps}</div>{claim}'
    if slide_type == "metrics":
        metric_items = slide.get("metrics") or []
        metrics = "".join(
            '<div class="metric" data-layout-box>'
            f'<div class="metric-value" data-fit>{_esc(metric.get("value"))}</div>'
            f'<div class="metric-label" data-fit>{_esc(metric.get("label"))}</div>'
            f'<div class="metric-note" data-fit>{_esc(metric.get("note"))}</div>'
            '</div>'
            for metric in metric_items
        )
        return f'<div class="metrics count-{len(metric_items)}" data-layout-box data-align-group>{metrics}</div>{claim}{points}'
    if slide_type == "comparison":
        columns = "".join(
            '<div class="compare-column" data-layout-box>'
            f'<div class="compare-label">{index:02d}</div>'
            f'<h3 data-fit>{_esc(column.get("title"))}</h3>'
            f'<p data-fit>{_esc(column.get("body"))}</p>'
            '</div>'
            for index, column in enumerate(slide.get("columns") or [], 1)
        )
        return f'<div class="comparison" data-layout-box data-align-group>{columns}</div>{claim}'
    return ""


def build_html(plan_path: Path, plan: dict[str, Any]) -> str:
    width, height = SIZES[plan["size"]]
    portrait = height > width
    base_style = _base_style(plan)
    treatment = _treatment(plan)
    slides_html = []
    total = len(plan["slides"])
    for index, slide in enumerate(plan["slides"], 1):
        source = slide.get("source") or plan.get("source") or ""
        kicker = slide.get("kicker") or f"PAPER EXPLAINED · {index:02d}"
        figure_class = "has-figure" if _figure(slide) else "no-figure"
        motif = _motif(plan, slide)
        slides_html.append(
            f'<section class="slide base-{base_style} treatment-{treatment} '
            f'motif-{motif} {"portrait" if portrait else "landscape"} '
            f'type-{slide["type"]} {figure_class}">'
            f'<div class="slide-motif" aria-hidden="true"><span>{index:02d}</span></div>'
            '<header class="slide-header">'
            f'<div class="kicker" data-fit>{_esc(kicker)}</div>'
            f'<div class="folio">{index:02d} / {total:02d}</div>'
            '</header>'
            f'<h1 data-fit>{_esc(slide.get("title"))}</h1>'
            f'<main>{_slide_body(plan_path, slide)}</main>'
            '<footer>'
            f'<span class="source" data-fit>{_esc(source)}</span>'
            f'<span class="deck-title" data-fit>{_esc(plan.get("title"))}</span>'
            '</footer></section>'
        )
    css = _css(width, height, base_style, portrait, plan.get("theme"))
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width={width},initial-scale=1"><style>{css}</style></head>'
        f'<body><div class="deck">{"".join(slides_html)}</div></body></html>'
    )


def _css(width: int, height: int, style: str, portrait: bool,
         custom_theme: dict[str, Any] | None = None) -> str:
    theme = {**THEMES[style], **(custom_theme or {})}
    bg, ink, muted = theme["bg"], theme["ink"], theme["muted"]
    accent, accent2, line = theme["accent"], theme["accent2"], theme["line"]
    surface, panel = theme["surface"], theme["panel"]
    accent_text_bg = _readable_accent(accent, ink, bg)
    accent_text_panel = _readable_accent(accent, ink, panel)
    accent2_text_panel = _readable_accent(accent2, ink, panel)
    accent_large_bg = _readable_accent(accent, ink, bg, minimum=3.0)
    on_accent = _on_accent_color(accent, ink, surface)
    font = {
        "serif": '"Noto Serif CJK SC","Source Han Serif SC",Georgia,serif',
        "sans": '"Noto Sans CJK SC","Source Han Sans SC",Helvetica,sans-serif',
        "mono": '"Noto Sans Mono CJK SC","JetBrains Mono",monospace',
        "rounded": '"Noto Sans CJK SC","Source Han Sans SC",sans-serif',
    }[theme["font"]]
    radius = f'{theme["radius"]}px'
    heading_weight = theme["heading_weight"]
    texture = {
        "none": "none",
        "paper": f"radial-gradient({ink} 0.65px,transparent .8px)",
        "grid": f"linear-gradient({line}55 1px,transparent 1px),linear-gradient(90deg,{line}55 1px,transparent 1px)",
        "halftone": f"radial-gradient({ink} 1.2px,transparent 1.5px)",
        "sparkle": f"radial-gradient(circle,{accent} 0 2px,transparent 2.5px),radial-gradient(circle,{accent2} 0 1.5px,transparent 2px)",
    }[theme["texture"]]
    texture_size = {"none": "auto", "paper": "9px 9px", "grid": "48px 48px",
                    "halftone": "16px 16px", "sparkle": "72px 72px,72px 72px"}[theme["texture"]]
    pad_x, pad_y = ((76, 82) if portrait else (92, 62))
    title_size = 66 if portrait else 60
    claim_size = 60 if portrait else 52
    body_size = 34 if portrait else 31
    return f"""
*{{box-sizing:border-box}} html,body{{margin:0;background:#d9d9d9;color:{ink};font-family:{font}}}
.deck{{display:flex;flex-direction:column;gap:28px;padding:28px}} .slide{{width:{width}px;height:{height}px;
position:relative;overflow:hidden;background:{bg};padding:{pad_y}px {pad_x}px;display:grid;
grid-template-rows:auto auto 1fr auto;gap:{24 if portrait else 18}px}}
.slide:before{{content:"";position:absolute;inset:0;pointer-events:none;opacity:.06;
background-image:{texture};background-size:{texture_size}}}
.slide>*{{position:relative;z-index:1}} .slide-motif{{position:absolute;z-index:0;pointer-events:none}}
.slide-header,footer{{display:flex;align-items:center;justify-content:space-between;
border-bottom:1px solid {line};padding-bottom:14px}} .kicker,.folio,.source,.deck-title{{font-family:ui-monospace,
"Noto Sans Mono CJK SC",monospace;text-transform:uppercase;letter-spacing:.16em;font-size:{22 if portrait else 19}px;
line-height:1.25;color:{muted};white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.kicker{{color:{accent_text_bg};font-weight:700}} h1{{margin:0;max-width:94%;font-size:{title_size}px;line-height:1.13;
letter-spacing:-.035em;font-weight:{heading_weight};text-wrap:balance}}
main{{min-width:0;min-height:0;display:flex;flex-direction:column;justify-content:center;align-items:stretch}} footer{{border-bottom:0;border-top:1px solid {line};
padding:13px 0 0;gap:32px}} .source{{max-width:68%}} .deck-title{{max-width:28%;text-align:right}}
.claim{{font-size:{claim_size}px;line-height:1.28;letter-spacing:-.025em;font-weight:{heading_weight};
text-wrap:balance}} .points{{list-style:none;padding:0;margin:28px 0 0;display:grid;gap:17px}}
.points li{{display:grid;grid-template-columns:54px 1fr;align-items:start;border-top:1px solid {line};padding-top:14px;
font-size:{body_size}px;line-height:1.45}} .point-no{{font:600 18px ui-monospace,monospace;color:{accent_text_bg};padding-top:8px}}
.figure-shell{{margin:0;min-width:0;min-height:0;border:1px solid {line};border-radius:{radius};padding:16px;
display:grid;grid-template-rows:1fr auto;background:{surface};overflow:hidden}}
.figure-img{{width:100%;height:100%;min-height:0;display:block}} .fit-contain{{object-fit:contain}} .fit-cover{{object-fit:cover}}
.figure-caption{{font:500 {22 if portrait else 19}px/1.3 ui-monospace,monospace;color:{muted};padding-top:10px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.cover-copy,.statement-copy{{width:100%;max-width:{'100%' if portrait else '760px'};display:flex;flex-direction:column;justify-content:center}}
.type-cover main,.type-statement main,.type-takeaway main{{display:grid;grid-template-columns:{'1fr' if portrait else '1.2fr .8fr'};
gap:50px;align-items:stretch}} .type-cover.no-figure main,.type-statement.no-figure main,.type-takeaway.no-figure main{{grid-template-columns:1fr}}
.type-cover.no-figure .cover-copy,.type-statement.no-figure .statement-copy,.type-takeaway.no-figure .statement-copy{{max-width:{'100%' if portrait else '1120px'}}}
.type-cover .figure-shell,.type-statement .figure-shell,.type-takeaway .figure-shell{{height:100%;max-height:620px}}
.evidence-grid{{height:100%;display:grid;grid-template-columns:{'1fr' if portrait else '1.35fr .65fr'};grid-template-rows:{'1.15fr .85fr' if portrait else '1fr'};
gap:{34 if portrait else 48}px;min-height:0}} .evidence-copy{{display:flex;flex-direction:column;justify-content:center;min-height:0}}
.type-evidence .claim{{font-size:{49 if portrait else 42}px}} .type-evidence .figure-shell{{min-height:0}}
.process{{display:grid;grid-template-columns:{'1fr' if portrait else 'repeat(4,minmax(0,1fr))'};gap:18px;align-items:stretch;min-height:{420 if portrait else 330}px}}
.process.count-2{{grid-template-columns:repeat(2,minmax(0,1fr))}} .process.count-3{{grid-template-columns:repeat({2 if portrait else 3},minmax(0,1fr))}}
.process.count-4{{grid-template-columns:repeat({2 if portrait else 4},minmax(0,1fr))}}
{'.process.count-3 .step:last-child{grid-column:1/-1}' if portrait else ''}
.step{{border-top:5px solid {accent};padding:22px 20px 18px;background:{panel};
border-radius:{radius};min-width:0;display:flex;flex-direction:column;align-items:flex-start}} .step-no,.compare-label{{font:600 18px ui-monospace,monospace;color:{accent_text_panel};letter-spacing:.12em}}
.step h3,.compare-column h3{{font-size:{35 if portrait else 31}px;line-height:1.2;margin:16px 0 12px;font-weight:600}}
.step p,.compare-column p{{font-size:{30 if portrait else 27}px;line-height:1.5;margin:0;color:{muted}}}
.type-process .claim,.type-comparison .claim{{font-size:{38 if portrait else 34}px;margin-top:30px;border-left:5px solid {accent};padding-left:22px}}
.metrics{{display:grid;grid-template-columns:{'1fr' if portrait else 'repeat(3,minmax(0,1fr))'};gap:22px;margin-bottom:34px;align-items:stretch}}
.metrics.count-1{{grid-template-columns:1fr}} .metrics.count-2{{grid-template-columns:repeat({1 if portrait else 2},minmax(0,1fr))}}
.metrics.count-3{{grid-template-columns:repeat({1 if portrait else 3},minmax(0,1fr))}}
.metric{{border-top:1px solid {line};padding:20px 18px 18px;min-width:0;display:flex;flex-direction:column;align-items:flex-start}} .metric-value{{font:300 {106 if portrait else 92}px/1 {font};
color:{accent_large_bg};letter-spacing:-.055em}} .metric-label{{font-size:{32 if portrait else 29}px;font-weight:600;margin-top:10px}}
.metric-note{{font-size:{27 if portrait else 24}px;line-height:1.45;color:{muted};margin-top:9px}}
.type-metrics .claim{{font-size:{44 if portrait else 39}px;border-top:1px solid {line};padding-top:24px}}
.comparison{{display:grid;grid-template-columns:{'1fr' if portrait else 'repeat(2,minmax(0,1fr))'};gap:26px;align-items:stretch}}
.compare-column{{min-width:0;min-height:{330 if portrait else 360}px;padding:30px;border:1px solid {line};border-radius:{radius};background:{panel};display:flex;flex-direction:column;align-items:flex-start}}
.motif-none .slide-motif{{display:none}} .motif-index .slide-motif{{right:{80 if portrait else 110}px;bottom:{155 if portrait else 120}px;
font:300 {230 if portrait else 190}px/1 {font};color:{accent};opacity:.10;letter-spacing:-.08em}}
.motif-brackets .slide-motif{{right:{76 if portrait else 104}px;top:{250 if portrait else 230}px;width:{300 if portrait else 390}px;height:{430 if portrait else 390}px;
border:2px solid {accent};border-left-width:22px;opacity:.16}}
.motif-brackets .slide-motif span{{position:absolute;right:34px;bottom:22px;font:300 {118 if portrait else 132}px/1 {font};letter-spacing:-.07em;color:{accent}}}
.motif-rings .slide-motif{{right:{45 if portrait else 100}px;top:{300 if portrait else 280}px;width:{390 if portrait else 430}px;height:{390 if portrait else 430}px;
border:3px solid {accent};border-radius:50%;box-shadow:34px 26px 0 {panel},38px 30px 0 {accent2};opacity:.22}}
.motif-rings .slide-motif span{{display:none}} .motif-crosshair .slide-motif{{right:{65 if portrait else 125}px;top:{310 if portrait else 300}px;
width:{330 if portrait else 390}px;height:{330 if portrait else 390}px;border:2px solid {line};border-radius:50%;opacity:.28}}
.motif-crosshair .slide-motif:before,.motif-crosshair .slide-motif:after{{content:"";position:absolute;background:{accent}}}
.motif-crosshair .slide-motif:before{{left:50%;top:-45px;width:2px;height:calc(100% + 90px)}}
.motif-crosshair .slide-motif:after{{top:50%;left:-45px;height:2px;width:calc(100% + 90px)}} .motif-crosshair .slide-motif span{{display:none}}
.has-figure .slide-motif,.type-evidence .slide-motif,.type-process .slide-motif,
.type-metrics .slide-motif,.type-comparison .slide-motif{{display:none}}
.treatment-soft:before{{opacity:.16}} .treatment-soft h1{{text-shadow:3px 3px 0 {surface}}}
.treatment-soft .step,.treatment-soft .compare-column,.treatment-soft .metric{{border:3px solid {line};
box-shadow:8px 8px 0 {accent2}}} .treatment-soft .metric{{padding:22px}}
.treatment-soft .point-no{{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:{accent};
color:{on_accent};padding:0}} .treatment-soft .figure-shell{{border-width:3px;box-shadow:9px 9px 0 {accent}}}
.treatment-soft.type-cover.no-figure.landscape:after{{content:"01";position:absolute;z-index:0;right:145px;top:305px;
width:470px;height:470px;border:4px solid {line};border-radius:50%;display:grid;place-items:center;
font:900 150px/1 {font};letter-spacing:-.08em;color:{surface};transform:rotate(6deg);
background:radial-gradient(circle at 31% 28%,{surface} 0 7%,transparent 7.5%),
linear-gradient(135deg,{accent} 0 49%,{accent2} 49% 100%);box-shadow:18px 18px 0 {panel},22px 22px 0 {line}}}
.treatment-comic:before{{opacity:.10}}
.treatment-comic .step,.treatment-comic .compare-column,.treatment-comic .metric{{border:4px solid {line};box-shadow:8px 8px 0 {line}}}
.treatment-comic h1{{text-shadow:4px 4px 0 {accent2}}}
.treatment-handmade .step:nth-child(even),.treatment-handmade .compare-column:nth-child(2){{background:{surface};transform:rotate(.35deg)}}
.treatment-technical h1:before{{content:"> ";color:{accent_text_bg}}} .treatment-technical .step-no,.treatment-technical .compare-label{{color:{accent2_text_panel}}}
@media (orientation:portrait){{.type-cover main,.type-statement main,.type-takeaway main{{grid-template-columns:1fr;grid-template-rows:auto 1fr}}
.cover-copy,.statement-copy{{max-width:100%}} .process{{grid-template-columns:1fr 1fr}} .comparison{{grid-template-columns:1fr}}
.metrics{{grid-template-columns:1fr}} .metric-value{{font-size:92px}}}}
"""


async def render(plan_path: Path, plan: dict[str, Any], out_dir: Path, html_path: Path) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        _die("未安装 playwright；运行 pip install playwright && playwright install chromium", 3)

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(plan_path, plan), encoding="utf-8")
    width, height = SIZES[plan["size"]]
    report: dict[str, Any] = {"plan": str(plan_path), "size": plan["size"], "slides": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"])
        page = await browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        await page.goto(html_path.as_uri(), wait_until="load", timeout=20000)
        try:
            await page.evaluate("document.fonts && document.fonts.ready")
        except Exception:
            pass
        elements = await page.query_selector_all(".slide")
        for index, element in enumerate(elements, 1):
            overflows = await element.eval_on_selector_all(
                "[data-fit]",
                "els => els.map((e,i) => { const r=e.getBoundingClientRect(); let p=e.parentElement; let outside=false; "
                "while(p && !p.classList.contains('slide')) { const q=p.getBoundingClientRect(); "
                "if(r.left<q.left-3 || r.right>q.right+3 || r.top<q.top-3 || r.bottom>q.bottom+3) outside=true; p=p.parentElement; } "
                "const nowrap=getComputedStyle(e).whiteSpace==='nowrap'; return {i,text:(e.textContent||'').trim(), "
                "scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,scrollWidth:e.scrollWidth,clientWidth:e.clientWidth, "
                "overflow:outside || (nowrap && e.scrollWidth>e.clientWidth+3)}; }).filter(x => x.overflow)",
            )
            if overflows:
                await browser.close()
                details = "; ".join(
                    f"{item['text'][:36]} ({item['scrollWidth']}x{item['scrollHeight']} > "
                    f"{item['clientWidth']}x{item['clientHeight']})" for item in overflows
                )
                _die(f"slide {index} 文本溢出：{details}；请删字或拆页")
            layout = await element.evaluate(
                """slide => {
                  const rect = el => { const r=el.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}; };
                  const outside = (inner, outer, pad=3) => inner.left < outer.left-pad || inner.right > outer.right+pad || inner.top < outer.top-pad || inner.bottom > outer.bottom+pad;
                  const violations=[]; const slideRect=rect(slide); const main=slide.querySelector('main'); const mainRect=rect(main);
                  slide.querySelectorAll('[data-layout-box]').forEach((box,i) => {
                    const r=rect(box); let parent=box.parentElement.closest('[data-layout-box],main');
                    const p=rect(parent || main);
                    if (outside(r,p)) violations.push(`box ${i+1} 超出父容器边界`);
                    if (outside(r,slideRect)) violations.push(`box ${i+1} 超出 slide 边界`);
                  });
                  slide.querySelectorAll('[data-align-group]').forEach((group,gi) => {
                    const children=[...group.children].filter(x => x.matches('[data-layout-box]'));
                    const rs=children.map(rect);
                    if (rs.length > 1) {
                      const tops=rs.map(r=>r.top), bottoms=rs.map(r=>r.bottom);
                      if (Math.max(...tops)-Math.min(...tops)>5 || Math.max(...bottoms)-Math.min(...bottoms)>5)
                        violations.push(`group ${gi+1} 顶/底边未对齐`);
                      for(let a=0;a<rs.length;a++) for(let b=a+1;b<rs.length;b++) {
                        const x=Math.min(rs[a].right,rs[b].right)-Math.max(rs[a].left,rs[b].left);
                        const y=Math.min(rs[a].bottom,rs[b].bottom)-Math.max(rs[a].top,rs[b].top);
                        if(x>3 && y>3) violations.push(`group ${gi+1} 子元素重叠`);
                      }
                    }
                  });
                  slide.querySelectorAll('.step,.metric,.compare-column,.evidence-copy').forEach((box,bi) => {
                    const children=[...box.children].filter(x => (x.textContent||'').trim() && getComputedStyle(x).position!=='absolute');
                    const lefts=children.map(x=>rect(x).left);
                    if(lefts.length>1 && Math.max(...lefts)-Math.min(...lefts)>5) violations.push(`text group ${bi+1} 左边未对齐`);
                  });
                  const major=[...main.children].filter(x => getComputedStyle(x).display!=='none').map(rect);
                  let occupancy={width:0,height:0};
                  if(major.length){ const union={left:Math.min(...major.map(r=>r.left)),right:Math.max(...major.map(r=>r.right)),top:Math.min(...major.map(r=>r.top)),bottom:Math.max(...major.map(r=>r.bottom))}; occupancy={width:union.right-union.left,height:union.bottom-union.top}; }
                  const structured=slide.matches('.type-process,.type-metrics,.type-comparison,.type-evidence');
                  if(structured && occupancy.width < mainRect.width*.62) violations.push('主内容横向跨度不足 62%');
                  if(structured && occupancy.height < mainRect.height*.38) violations.push('主内容纵向跨度不足 38%');
                  return {violations:[...new Set(violations)], main:{width:Math.round(mainRect.width),height:Math.round(mainRect.height)}, occupancy:{width:Math.round(occupancy.width),height:Math.round(occupancy.height)}};
                }"""
            )
            if layout["violations"]:
                await browser.close()
                _die(f"slide {index} 版式审计失败：{' ; '.join(layout['violations'])}")
            out_path = out_dir / f"slide_{index:02d}.png"
            await element.screenshot(path=str(out_path), type="png")
            report["slides"].append({"index": index, "file": str(out_path), "overflow": False,
                                     "layout": layout})
        await browser.close()
    report_path = out_dir / "render-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def audit(plan_path: Path, plan: dict[str, Any], slides_dir: Path, contact_sheet: Path | None) -> dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageStat
    except ImportError:
        _die("audit 需要 Pillow", 3)
    problems = validate_plan(plan_path, plan, check_assets=True)
    width, height = SIZES.get(plan.get("size"), (0, 0))
    files = sorted(slides_dir.glob("slide_*.png"))
    if len(files) != len(plan.get("slides") or []):
        problems.append(f"成图数量 {len(files)} 与计划 {len(plan.get('slides') or [])} 不一致")
    checked = []
    images = []
    for index, file in enumerate(files, 1):
        try:
            image = Image.open(file).convert("RGB")
        except Exception as exc:
            problems.append(f"{file.name}: 无法读取：{exc}")
            continue
        if image.size != (width, height):
            problems.append(f"{file.name}: 尺寸 {image.size} != {(width, height)}")
        stat = ImageStat.Stat(image.resize((160, 90)))
        contrast = sum(stat.stddev) / 3
        if contrast < 6:
            problems.append(f"{file.name}: 画面近乎空白（contrast={contrast:.1f}）")
        checked.append({"file": str(file), "size": f"{image.width}x{image.height}",
                        "contrast": round(contrast, 2)})
        images.append((file.name, image))

    render_report = slides_dir / "render-report.json"
    if not render_report.is_file():
        problems.append("缺 render-report.json；必须通过 render 子命令生成，不能手工截图冒充")
    else:
        try:
            rendered = json.loads(render_report.read_text(encoding="utf-8"))
            layout_rows = [row.get("layout") for row in rendered.get("slides", [])]
            if len(layout_rows) != len(plan.get("slides") or []) or any(not row for row in layout_rows):
                problems.append("render-report 缺少完整版式审计；请用当前 render 重渲")
            for index, row in enumerate(layout_rows, 1):
                if row and row.get("violations"):
                    problems.append(f"slide {index}: render-report 存在版式违规")
        except (OSError, json.JSONDecodeError, AttributeError):
            problems.append("render-report.json 无法解析；请重新 render")

    if contact_sheet and images:
        thumb_w = 480 if width >= height else 270
        thumb_h = round(thumb_w * height / width)
        cols = 3 if width >= height else 4
        rows = (len(images) + cols - 1) // cols
        label_h = 38
        sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "#dedede")
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 22)
        except OSError:
            font = ImageFont.load_default()
        for index, (name, image) in enumerate(images):
            x = (index % cols) * thumb_w
            y = (index // cols) * (thumb_h + label_h)
            thumb = image.copy()
            thumb.thumbnail((thumb_w, thumb_h))
            sheet.paste(thumb, (x, y + label_h))
            draw.text((x + 10, y + 7), name, fill="#222", font=font)
        contact_sheet.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(contact_sheet, quality=91)

    result = {"pass": not problems, "problems": problems, "slides": checked,
              "contact_sheet": str(contact_sheet) if contact_sheet else None}
    (slides_dir / "slide-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def _sample_plan() -> dict[str, Any]:
    return {
        "version": 1,
        "title": "Paper Slides Selftest",
        "style": "editorial",
        "size": "1920x1080",
        "source": "Easel selftest",
        "slides": [
            {"type": "cover", "title": "论文解读不该只是把文字塞进卡片",
             "claim": "先确定一页的中心结论，再让版式服务证据。"},
            {"type": "process", "title": "稳定页面只需要三步",
             "steps": [{"title": "提炼", "body": "从论文证据中选一个中心结论"},
                       {"title": "分页", "body": "把口播和屏幕文字分开，各自承担信息"},
                       {"title": "审计", "body": "溢出、尺寸和节奏不过就返工"}]},
            {"type": "metrics", "title": "质量门必须可测",
             "claim": "脚本负责守住底线，当前 Agent 再肉眼判断审美。",
             "metrics": [{"value": "0", "label": "允许溢出", "note": "任何文字越界都失败"},
                         {"value": "1", "label": "每页观点", "note": "不把 narration 搬上屏"}]},
        ],
    }


async def _selftest() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        plan_path = root / "slide-plan.json"
        plan = _sample_plan()
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        problems = validate_plan(plan_path, plan)
        if problems:
            print("[FAIL] sample validate: " + "; ".join(problems), file=sys.stderr)
            return 1
        report = await render(plan_path, plan, root / "slides", root / "slides.html")
        result = audit(plan_path, plan, root / "slides", root / "contact-sheet.jpg")
        ok = len(report["slides"]) == 3 and result["pass"] and (root / "contact-sheet.jpg").is_file()
        print("[PASS] validate + render + overflow gate + audit + contact sheet" if ok else "[FAIL] selftest")
        return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="论文 slide-plan 校验、稳定渲染与成图审计")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_cmd = sub.add_parser("validate", help="校验 slide-plan 和引用素材")
    validate_cmd.add_argument("--plan", required=True)
    render_cmd = sub.add_parser("render", help="渲染 slide-plan；任何 DOM 溢出直接失败")
    render_cmd.add_argument("--plan", required=True)
    render_cmd.add_argument("--out-dir", required=True)
    render_cmd.add_argument("--html", help="保存生成的 HTML；默认写到 out-dir/slides.html")
    audit_cmd = sub.add_parser("audit", help="检查成图并生成 contact sheet")
    audit_cmd.add_argument("--plan", required=True)
    audit_cmd.add_argument("--slides-dir", required=True)
    audit_cmd.add_argument("--contact-sheet")
    sub.add_parser("selftest", help="临时目录端到端自检")
    args = parser.parse_args()

    if args.command == "selftest":
        return asyncio.run(_selftest())
    plan_path, plan = _read_plan(args.plan)
    problems = validate_plan(plan_path, plan, check_assets=True)
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(f"ERROR: slide-plan 校验失败（{len(problems)} 项）", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(f"OK: {len(plan['slides'])} slides · {plan['style']} · {plan['size']}")
        return 0
    if args.command == "render":
        out_dir = Path(args.out_dir).expanduser().resolve()
        html_path = Path(args.html).expanduser().resolve() if args.html else out_dir / "slides.html"
        report = asyncio.run(render(plan_path, plan, out_dir, html_path))
        print(f"OK: rendered {len(report['slides'])} slides -> {out_dir}")
        return 0
    slides_dir = Path(args.slides_dir).expanduser().resolve()
    contact = Path(args.contact_sheet).expanduser().resolve() if args.contact_sheet else None
    result = audit(plan_path, plan, slides_dir, contact)
    if not result["pass"]:
        for problem in result["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        print(f"ERROR: slide audit failed ({len(result['problems'])} problems)", file=sys.stderr)
        return 2
    print(f"OK: audited {len(result['slides'])} slides" + (f" · {contact}" if contact else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
