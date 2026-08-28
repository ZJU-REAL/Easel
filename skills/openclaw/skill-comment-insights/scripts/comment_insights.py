#!/usr/bin/env python3
"""comment_insights.py — 评论区量化分析（情感 + 高频词 + 需求/吐槽挖掘）。

对一批评论做确定性量化分析，为内容复盘与选题反哺提供数据：
    情感分析   SnowNLP 基线 + 社媒情感词典修正 → 正/中/负分布 + 代表评论
    高频词/短语 jieba 分词 + 词性过滤 + 停用词 → Top 词与 2-gram 短语
    诉求挖掘   规则识别 需求/疑问/吐槽/求购 → 计数 + 例子（喂给选题）

与 skill-community-ops 的边界：community-ops 是"怎么回评论 + 危机应对"（运营动作）；
本 SKILL 是"评论区说了什么"（量化洞察）。与 xhs-analyzer：那个负责抓评论，本脚本负责分析。

依赖：jieba + snownlp（`pip install jieba snownlp`）。

子命令：
    analyze    分析评论（txt 每行一条 / json 数组 / csv 指定列）
    selftest   自检

用法举例：
    comment_insights.py analyze -i comments.txt
    comment_insights.py analyze -i comments.csv --column content --top 20 -o report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── 社媒情感词典（对 SnowNLP 基线做修正，覆盖网络用语） ──────────────
_POS_WORDS = set("""
好 喜欢 爱了 绝了 绝绝子 yyds 神器 推荐 种草 好用 值 值得 赞 棒 太棒 厉害 优秀 完美
香 真香 可爱 好看 划算 满意 惊喜 惊艳 治愈 舒服 期待 支持 感谢 谢谢 强 强推 爱 心动
喜欢 好评 靠谱 良心 实用 干货 收藏 有用 nice 顶 牛 赞美 温柔 好吃 美 帅 甜 稳
""".split())
_NEG_WORDS = set("""
差 垃圾 退 退货 坑 避雷 踩雷 翻车 失望 难用 难看 贵 死贵 骗 骗人 假 假货 烂 无语 恶心
后悔 浪费 拉胯 雷 别买 劝退 敷衍 套路 难吃 尬 水 割韭菜 智商税 差评 一般 一般般 糊弄
坑爹 恶臭 反感 讨厌 崩 卡 bug 退款 客服 态度差 不值 踩坑 慎买 难受 恶评 抵制
""".split())

# ── 停用词（高频功能词 / 语气词，分词后剔除） ─────────────────────────
_STOPWORDS = set("""
的 了 是 我 你 他 她 它 们 这 那 有 和 就 都 而 及 与 或 一个 一 也 在 不 得 着 过 呢 吧
啊 呀 吗 嘛 哦 哈 嗯 呵 么 啦 嘞 咯 唉 哎 但 但是 因为 所以 如果 虽然 然后 还 还是 很
太 挺 非常 真的 真 好 感觉 觉得 自己 什么 怎么 这个 那个 这样 那样 一下 一点 有点 就是
可以 没有 不是 这么 那么 现在 已经 应该 可能 大家 我们 你们 他们 东西 时候 之后 之前
知道 看到 觉得 一直 直接 完全 而且 只是 这种 那种 不会 会 让 被 把 给 对 从 向 到 用
""".split())

_KEEP_FLAGS = ("n", "nr", "ns", "nt", "nz", "vn", "v", "a", "an", "l", "i")  # 名/动/形/成语等
_DEMAND_RE = re.compile(r"(求|想要|想买|在哪买|哪里买|求链接|链接|多少钱|价格|怎么买|"
                        r"能不能|可不可以|会不会|求教程|出个|教程|怎么做|求推荐|求同款)")
_COMPLAINT_RE = re.compile(r"(差|垃圾|退|坑|避雷|踩雷|翻车|失望|难用|贵|骗|假|烂|后悔|"
                           r"浪费|拉胯|劝退|套路|智商税|差评|慎买|退款|态度差)")
_QUESTION_RE = re.compile(r"[?？]")


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_comments(path: str, column: str | None) -> list[str]:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"评论文件不存在：{p}")
    suf = p.suffix.lower()
    raw = p.read_text(encoding="utf-8-sig", errors="replace")
    out: list[str] = []
    if suf == ".json":
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("comments", data.get("data", []))
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                out.append(str(item.get(column or "content")
                               or item.get("text") or item.get("comment") or ""))
    elif suf == ".csv":
        import csv
        import io
        reader = csv.DictReader(io.StringIO(raw))
        col = column or "content"
        if reader.fieldnames and col not in reader.fieldnames:
            col = reader.fieldnames[0]
        for r in reader:
            out.append((r.get(col) or "").strip())
    else:  # txt：每行一条
        out = [ln.strip() for ln in raw.splitlines()]
    out = [c for c in (x.strip() for x in out) if c]
    if not out:
        _die("未读到任何评论。")
    return out


def _sentiment(text: str) -> float:
    """SnowNLP 基线 + 词典修正，返回 [0,1]。"""
    from snownlp import SnowNLP
    try:
        base = SnowNLP(text).sentiments
    except Exception:
        base = 0.5
    pos = sum(1 for w in _POS_WORDS if w in text)
    neg = sum(1 for w in _NEG_WORDS if w in text)
    score = base + (pos - neg) * 0.15
    return max(0.0, min(1.0, score))


def _classify(score: float) -> str:
    if score >= 0.6:
        return "positive"
    if score <= 0.4:
        return "negative"
    return "neutral"


def _keywords(comments: list[str], top: int) -> tuple[list, list]:
    import jieba.posseg as pseg
    word_freq: dict[str, int] = {}
    phrase_freq: dict[str, int] = {}
    for c in comments:
        kept = []
        for w, flag in pseg.cut(c):
            w = w.strip()
            if (len(w) >= 2 and w not in _STOPWORDS
                    and any(flag.startswith(f) for f in _KEEP_FLAGS)
                    and not w.isdigit()):
                word_freq[w] = word_freq.get(w, 0) + 1
                kept.append(w)
        for i in range(len(kept) - 1):  # 相邻 2-gram 短语
            ph = kept[i] + kept[i + 1]
            phrase_freq[ph] = phrase_freq.get(ph, 0) + 1
    words = sorted(word_freq.items(), key=lambda x: -x[1])[:top]
    phrases = [(p, n) for p, n in sorted(phrase_freq.items(), key=lambda x: -x[1])
               if n >= 2][:max(5, top // 2)]
    return words, phrases


def cmd_analyze(a) -> int:
    comments = _load_comments(a.input, a.column)
    n = len(comments)

    # 情感
    buckets = {"positive": [], "neutral": [], "negative": []}
    scored = []
    for c in comments:
        s = _sentiment(c)
        lab = _classify(s)
        buckets[lab].append((c, s))
        scored.append((c, s, lab))
    dist = {k: len(v) for k, v in buckets.items()}

    def _reps(label, k=3, reverse=True):
        items = sorted(buckets[label], key=lambda x: x[1], reverse=reverse)
        return [c for c, _ in items[:k]]

    # 高频词
    words, phrases = _keywords(comments, a.top)

    # 诉求挖掘
    demands = [c for c in comments if _DEMAND_RE.search(c)]
    complaints = [c for c in comments if _COMPLAINT_RE.search(c)]
    questions = [c for c in comments if _QUESTION_RE.search(c)]

    report = {
        "total": n,
        "sentiment": {
            "distribution": dist,
            "ratio": {k: round(v / n, 3) for k, v in dist.items()},
            "positive_examples": _reps("positive"),
            "negative_examples": _reps("negative", reverse=False),
        },
        "keywords": [{"word": w, "count": c} for w, c in words],
        "phrases": [{"phrase": p, "count": c} for p, c in phrases],
        "demands": {"count": len(demands), "examples": demands[:5]},
        "complaints": {"count": len(complaints), "examples": complaints[:5]},
        "questions": {"count": len(questions), "examples": questions[:5]},
    }

    if a.output:
        out = Path(a.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 报告 → {out}")
    # 可读摘要
    r = report["sentiment"]["ratio"]
    print(f"\n评论分析（共 {n} 条）")
    print(f"  情感：😊正 {r['positive']:.0%} · 😐中 {r['neutral']:.0%} · 😠负 {r['negative']:.0%}")
    print(f"  高频词：{'、'.join(w['word'] for w in report['keywords'][:10])}")
    if report["phrases"]:
        print(f"  高频短语：{'、'.join(p['phrase'] for p in report['phrases'][:5])}")
    print(f"  诉求 {report['demands']['count']} · 吐槽 {report['complaints']['count']} · "
          f"提问 {report['questions']['count']}")
    if not a.output:
        print("\n" + json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_a) -> int:
    print("comment_insights 自检 ...", file=sys.stderr)
    import tempfile
    sample = [
        "这个真的绝绝子！强烈推荐，太好用了", "yyds 爱了爱了，好看又划算",
        "质量太差了，完全是智商税，退货！", "避雷！用了翻车，浪费钱后悔",
        "还行吧，中规中矩", "请问在哪买？求链接", "能不能出个教程？想学",
        "客服态度差，退款都不给", "包装一般，东西还可以", "求同款！多少钱",
    ]
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "c.txt"
        f.write_text("\n".join(sample), encoding="utf-8")
        comments = _load_comments(str(f), None)
        assert len(comments) == 10, "读取条数不对"

        # 情感方向
        assert _classify(_sentiment("绝绝子！强烈推荐太好用了")) == "positive"
        assert _classify(_sentiment("太差了智商税退货避雷")) == "negative"

        # 关键词提取（应含内容词，不含停用词）
        words, phrases = _keywords(comments, 20)
        wset = {w for w, _ in words}
        assert wset, "未提取到关键词"
        assert "的" not in wset and "了" not in wset, "停用词未过滤"

        # 诉求 / 吐槽识别
        demands = [c for c in comments if _DEMAND_RE.search(c)]
        complaints = [c for c in comments if _COMPLAINT_RE.search(c)]
        assert len(demands) >= 3, f"需求识别偏少：{demands}"
        assert len(complaints) >= 2, f"吐槽识别偏少：{complaints}"

        # 端到端 analyze（写文件）
        outp = Path(td) / "r.json"
        cmd_analyze(argparse.Namespace(input=str(f), column=None, top=15, output=str(outp)))
        rep = json.loads(outp.read_text(encoding="utf-8"))
        assert rep["total"] == 10
        assert sum(rep["sentiment"]["distribution"].values()) == 10, "情感分布和≠总数"
        assert rep["demands"]["count"] >= 3 and rep["complaints"]["count"] >= 2
    print("✅ selftest 通过（读取/情感方向/关键词过滤/诉求识别/端到端）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="评论区量化分析（情感 + 高频词 + 诉求挖掘）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("analyze", help="分析评论")
    p.add_argument("-i", "--input", required=True, help="txt(每行一条)/json/csv")
    p.add_argument("--column", help="csv/json 的评论字段名（默认 content）")
    p.add_argument("--top", type=int, default=20, help="高频词 Top N（默认 20）")
    p.add_argument("-o", "--output", help="报告 JSON 输出路径")
    p.set_defaults(func=cmd_analyze)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
