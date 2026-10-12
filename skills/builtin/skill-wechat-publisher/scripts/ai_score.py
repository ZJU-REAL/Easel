#!/usr/bin/env python3
"""
AI 味检测器(反 AI 检测自检工具)

对一篇 Markdown 文章做启发式扫描,从以下维度给出"AI 味"评分(0-100),
越高越像 AI 生成,越低越像真人写作。

维度(与权重):
  1. burstiness(句长方差)   30%  —— 真人句长抖动大,AI 平滑
  2. phrase_hits(AI 套话)   30%  —— 命中 AI 高频句式 / 套话的次数
  3. vocab_hits(AI 词汇)    20%  —— 命中 AI 高频名词的次数
  4. structural_perfection  10%  —— 首先/其次/最后 等教科书结构
  5. punctuation_flatness   10%  —— 标点单调(几乎只有句号逗号)

用法:
    python3 ai_score.py article.md
    python3 ai_score.py article.md --json         # 输出 JSON
    python3 ai_score.py article.md --threshold 40 # 阈值,高于阈值 exit 1

返回:
    exit 0 通过(分数 < 阈值)
    exit 1 失败(分数 >= 阈值,建议重写)

注意:这只是启发式检测,不替代真实的第三方检测器(GPTZero / 朱雀 /
腾讯 AI 检测),但可以作为发布前的快速 gate 拦住最明显的 AI 味。
"""

import re
import sys
import json
import argparse
import statistics
from pathlib import Path

# 默认失败阈值：总分 >= 该值视为"AI 味过重"。
# check_ai_score()、CLI --threshold 默认值和 publish.py 均应引用此常量，保持一致。
DEFAULT_THRESHOLD: float = 45.0


# ---------- 黑名单 ----------

# AI 高频套话句式(正则)
AI_PHRASES = [
    r"首先[,，].{0,8}其次[,，].{0,10}最后",
    r"首先[,，].{0,8}其次[,，].{0,10}再次",
    r"不仅.{0,10}而且",
    r"一方面.{0,15}另一方面",
    r"值得一提的是",
    r"不可否认",
    r"毋庸置疑",
    r"综上所述",
    r"总而言之",
    r"总的来说",
    r"由此可见",
    r"众所周知",
    r"不难发现",
    r"显而易见",
    r"在.{1,15}的背景下",
    r"随着.{1,20}的发展",
    r"随着.{1,20}的不断",
    r"让我们一起来",
    r"让我们共同",
    r"归根结底",
    r"无论如何",
    r"从某种意义上(说|讲)",
    r"在当今社会",
    r"进入新时代",
    r"在.{1,10}时代",
    r"站在.{1,10}的角度",
    r"为.{1,10}提供了.{1,10}可能",
    r"打开了.{1,10}的大门",
    r"开启了.{1,10}的篇章",
    r"翻开了.{1,10}新的一页",
    r"具有(重要|深远|里程碑)的意义",
    r"产生了(深远|重大|巨大)的影响",
]

# AI 高频名词 / 形容词(整篇密集出现即扣分)
AI_VOCAB = [
    "赋能", "打造", "聚焦", "深度融合", "生态", "闭环", "链路", "抓手",
    "价值链", "护城河", "方法论", "底层逻辑", "生态位", "结构化思维",
    "提升效率", "助力", "全链路", "一站式", "端到端", "量变到质变",
    "引领", "颠覆", "革命性", "前所未有", "核心竞争力", "范式", "新范式",
    "降本增效", "数字化转型", "智能化", "生态体系", "产业升级",
    "破局", "出圈", "破圈", "沉淀", "赋予", "深耕", "蓝图", "新篇章",
]


def _strip_markdown(md_text: str) -> str:
    """去掉 markdown 语法,只保留正文文字,用于句子级分析。"""
    text = md_text
    # 代码块
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    # 行内代码
    text = re.sub(r"`[^`]+`", " ", text)
    # 图片 / 链接
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # 自定义行内标记(保留文字内容)
    text = re.sub(r"==([^=\n]+)==", r"\1", text)
    text = re.sub(r"\+\+([^+\n]+)\+\+", r"\1", text)
    text = re.sub(r"%%([^%\n]+)%%", r"\1", text)
    text = re.sub(r"&&([^&\n]+)&&", r"\1", text)
    text = re.sub(r"!!([^!\n]+)!!", r"\1", text)
    text = re.sub(r"@@([^@\n]+)@@", r"\1", text)
    text = re.sub(r"\^\^([^\^\n]+)\^\^", r"\1", text)
    # 加粗 / 斜体
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    # 标题符号 / 引用符号 / 列表符号
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # 表格
    text = re.sub(r"^\|.*\|$", " ", text, flags=re.MULTILINE)
    return text.strip()


def _split_sentences(text: str) -> list:
    """按中文/英文标点切句。"""
    parts = re.split(r"(?<=[。!?!?;;])", text)
    return [p.strip() for p in parts if p.strip()]


# ---------- 各维度打分 ----------

def score_burstiness(sentences: list) -> tuple:
    """
    真人写作句长分布有"突发性"(burstiness)。
    计算句长的变异系数(CV = stdev / mean),CV 越大越像真人。
    转换为 0-100 的 AI 味分数(CV 越小分越高)。
    """
    if len(sentences) < 5:
        return 50.0, {"cv": None, "reason": "too_few_sentences"}
    lengths = [len(s) for s in sentences]
    mean = statistics.mean(lengths)
    stdev = statistics.stdev(lengths) if len(lengths) > 1 else 0
    cv = stdev / mean if mean else 0
    # CV 0.3 以下 = 非常平滑(AI 味 90),CV 0.8 以上 = 抖动大(AI 味 10)
    if cv <= 0.3:
        ai = 90
    elif cv >= 0.8:
        ai = 10
    else:
        ai = 90 - (cv - 0.3) * (80 / 0.5)
    return round(ai, 1), {
        "sentence_count": len(sentences),
        "mean_length": round(mean, 1),
        "stdev": round(stdev, 1),
        "cv": round(cv, 3),
    }


def score_phrases(text: str) -> tuple:
    """AI 套话命中率(按 span 去重,避免同一段文本被多个重叠模式重复计数)。"""
    seen_spans = {}  # (start, end) -> matched text
    for pat in AI_PHRASES:
        for m in re.finditer(pat, text):
            span = (m.start(), m.end())
            # 只保留首次命中(不同 pattern 命中同一 span 算一次)
            if span not in seen_spans:
                seen_spans[span] = m.group(0)
    # 再做一轮重叠消除:若 span A 完全被 span B 包含,则丢弃 A
    spans = sorted(seen_spans.keys(), key=lambda s: (s[0], -s[1]))
    kept = []
    for span in spans:
        contained = any(
            other != span and other[0] <= span[0] and other[1] >= span[1]
            for other in seen_spans.keys()
        )
        if not contained:
            kept.append(span)
    hits = [seen_spans[s] for s in kept]
    # 每命中一次扣 15 分(从 0 起累加,上限 100)
    ai = min(100, len(hits) * 15)
    return round(float(ai), 1), {"hit_count": len(hits), "samples": hits[:8]}


def score_vocab(text: str) -> tuple:
    """AI 高频词密度。"""
    hits = {}
    for w in AI_VOCAB:
        c = text.count(w)
        if c > 0:
            hits[w] = c
    total = sum(hits.values())
    # 每 1000 字允许最多 2 个,再多按比例扣分
    char_count = max(1, len(text))
    density = total / (char_count / 1000)
    if density <= 2:
        ai = density * 15  # 0-30
    elif density <= 5:
        ai = 30 + (density - 2) * 15  # 30-75
    else:
        ai = min(100, 75 + (density - 5) * 5)
    return round(float(ai), 1), {
        "total_hits": total,
        "density_per_1k": round(density, 2),
        "top": sorted(hits.items(), key=lambda x: -x[1])[:10],
    }


def score_structural_perfection(text: str) -> tuple:
    """检测教科书式枚举结构。"""
    bad = [
        r"第一[,，、].{0,80}第二[,，、].{0,80}第三",
        r"一[是、][^。]{0,60}二[是、][^。]{0,60}三[是、]",
    ]
    hits = 0
    for pat in bad:
        hits += len(re.findall(pat, text))
    ai = min(100, hits * 35)
    return round(float(ai), 1), {"hit_count": hits}


def score_punctuation_flatness(text: str) -> tuple:
    """检测标点单调度(真人会用破折号、问号、省略号、感叹号)。"""
    chars = len(text)
    flavor = 0
    flavor += text.count("——") * 3
    flavor += text.count("…") * 2
    flavor += text.count("?") + text.count("？")
    flavor += (text.count("!") + text.count("！")) // 2  # 感叹号加分但上限低
    flavor += text.count("(") + text.count("（") + text.count(")") + text.count("）")
    # 每 1000 字期望出现 5 次以上"人味标点";短文本用 200 字做下限避免过度敏感
    expected = max(chars, 200) / 1000 * 5
    ratio = flavor / expected if expected else 0
    if ratio >= 1:
        ai = 10
    elif ratio >= 0.5:
        ai = 30
    elif ratio >= 0.2:
        ai = 60
    else:
        ai = 85
    return round(float(ai), 1), {
        "flavor_points": flavor,
        "expected": round(expected, 1),
        "ratio": round(ratio, 2),
    }


# ---------- 总评 ----------

# 长文(news)用的完整 5 维权重
WEIGHTS_NEWS = {
    "burstiness": 0.30,
    "phrases": 0.30,
    "vocab": 0.20,
    "structural": 0.10,
    "punctuation": 0.10,
}

# 短文(newspic 贴图)用的精简权重
# - 短文本里 burstiness 和 structural 都不稳定(句子/枚举少),权重归 0
# - phrases 和 vocab 是 AI 味主要来源
# - punctuation 保留兜底(整篇只有句号也是 AI 信号)
WEIGHTS_NEWSPIC = {
    "burstiness": 0.0,
    "phrases": 0.55,
    "vocab": 0.35,
    "structural": 0.0,
    "punctuation": 0.10,
}

# 向后兼容:现有代码从本模块 `from ai_score import WEIGHTS` 的地方仍然能读到长文权重
WEIGHTS = WEIGHTS_NEWS


def _weights_for(mode: str) -> dict:
    if mode == "newspic":
        return WEIGHTS_NEWSPIC
    return WEIGHTS_NEWS


def analyze(md_text: str, mode: str = "news") -> dict:
    """
    对一段 Markdown(或纯文本)做 AI 味打分。

    Args:
        md_text: 原文
        mode:  "news"(默认,长文 5 维)或 "newspic"(贴图短文本,phrases + vocab + punctuation)
    """
    plain = _strip_markdown(md_text)
    sentences = _split_sentences(plain)

    b_score, b_det = score_burstiness(sentences)
    p_score, p_det = score_phrases(plain)
    v_score, v_det = score_vocab(plain)
    s_score, s_det = score_structural_perfection(plain)
    pu_score, pu_det = score_punctuation_flatness(plain)

    weights = _weights_for(mode)
    total = (
        b_score * weights["burstiness"]
        + p_score * weights["phrases"]
        + v_score * weights["vocab"]
        + s_score * weights["structural"]
        + pu_score * weights["punctuation"]
    )

    verdict = (
        "🟢 PASS (真人味)"
        if total < 35
        else ("🟡 WARN (有 AI 味,建议改)" if total < 55 else "🔴 FAIL (AI 味太重,必须重写)")
    )

    return {
        "total_ai_score": round(total, 1),
        "verdict": verdict,
        "mode": mode,
        "char_count": len(plain),
        "sentence_count": len(sentences),
        "dimensions": {
            "burstiness":   {"score": b_score,  "detail": b_det},
            "phrases":      {"score": p_score,  "detail": p_det},
            "vocab":        {"score": v_score,  "detail": v_det},
            "structural":   {"score": s_score,  "detail": s_det},
            "punctuation":  {"score": pu_score, "detail": pu_det},
        },
        "weights": weights,
    }


def check_ai_score(
    md_content: str,
    threshold: float = DEFAULT_THRESHOLD,
    mode: str = "news",
) -> tuple:
    """
    库入口:对 md 内容做 AI 味检测。

    Args:
        md_content: Markdown 原文
        threshold: 失败阈值(total_score >= threshold 视为失败)
        mode: "news"(长文)或 "newspic"(贴图短文本,只看 phrases/vocab/punctuation)

    Returns:
        (passed, report)
          passed: bool,total_score < threshold 时为 True
          report: dict,包含:
            - total_score: float  总分 0-100
            - mode: str
            - dimensions: dict    各维度原始分(未加权)
                - burstiness / phrases / vocab / structural / punctuation
            - hit_phrases: list[str]  命中的 AI 套话样本
            - hit_vocab:   list[str]  命中的 AI 词汇样本
            - threshold:   float
    """
    full = analyze(md_content, mode=mode)
    dims = full["dimensions"]
    hit_phrases = list(dims["phrases"]["detail"].get("samples", []))
    hit_vocab = [w for w, _ in dims["vocab"]["detail"].get("top", [])]

    report = {
        "total_score": full["total_ai_score"],
        "mode": full.get("mode", mode),
        "dimensions": {
            "burstiness":  dims["burstiness"]["score"],
            "phrases":     dims["phrases"]["score"],
            "vocab":       dims["vocab"]["score"],
            "structural":  dims["structural"]["score"],
            "punctuation": dims["punctuation"]["score"],
        },
        "hit_phrases": hit_phrases,
        "hit_vocab":   hit_vocab,
        "threshold":   float(threshold),
    }
    passed = report["total_score"] < threshold
    return passed, report


def _pretty_print(report: dict):
    print("=" * 60)
    print(f" AI 味检测报告  —— {report['verdict']}")
    print("=" * 60)
    mode = report.get("mode", "news")
    print(f"模式: {mode}  (news=长文, newspic=贴图短文)")
    print(f"总分: {report['total_ai_score']} / 100  (0 = 纯真人, 100 = 纯 AI)")
    print(f"字数: {report['char_count']}  句数: {report['sentence_count']}")
    print("-" * 60)
    weights = report.get("weights", WEIGHTS)
    for name, d in report["dimensions"].items():
        w = weights.get(name, 0)
        suffix = "  [跳过]" if w == 0 else ""
        print(f"  [{name:13s}] 分数={d['score']:>5}  权重={int(w*100)}%{suffix}")
        det = d["detail"]
        if name == "phrases" and det.get("hit_count"):
            print(f"      命中 {det['hit_count']} 次 AI 套话:")
            for s in det.get("samples", []):
                print(f"        · {s}")
        elif name == "vocab" and det.get("total_hits"):
            top = det.get("top", [])
            if top:
                top_str = ", ".join(f"{w}×{c}" for w, c in top)
                print(f"      AI 词密度 {det['density_per_1k']}/千字: {top_str}")
        elif name == "burstiness" and det.get("cv") is not None:
            print(f"      句长均值 {det['mean_length']} 字,CV={det['cv']}")
        elif name == "punctuation":
            print(f"      人味标点 {det.get('flavor_points', 0)} 次,期望 {det.get('expected', 0)}")
        elif name == "structural" and det.get("hit_count"):
            print(f"      教科书枚举命中 {det['hit_count']} 次")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="AI 味检测器")
    parser.add_argument("input", help="Markdown 文件路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"失败阈值(默认 {DEFAULT_THRESHOLD})。总分 >= 阈值则 exit 1",
    )
    parser.add_argument(
        "--mode",
        choices=["news", "newspic"],
        default="news",
        help="检测模式: news(长文,默认)/ newspic(贴图短文本,只看 phrases+vocab+punctuation)",
    )
    args = parser.parse_args()

    md = Path(args.input).read_text(encoding="utf-8")
    # 走和库 API 相同的 check_ai_score 路径,保证 CLI/库行为一致。
    passed, _ = check_ai_score(md, threshold=args.threshold, mode=args.mode)
    full = analyze(md, mode=args.mode)  # 用于详细打印(库 API 只返回简表)

    if args.json:
        print(json.dumps(full, ensure_ascii=False, indent=2))
    else:
        _pretty_print(full)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
