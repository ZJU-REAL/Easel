#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wordcount.py — 社媒文案字数统计与目标字数校验（纯标准库）。

text-condenser 的 strict 模式靠 LLM 自数字数不可靠，本脚本负责"判定"：
LLM 负责改写，脚本给出权威字数与是否达标。

用法：
    # 统计字数（从文件）
    python3 wordcount.py count -f draft.txt
    # 统计字数（从 stdin）
    echo "文本内容" | python3 wordcount.py count
    # 校验是否命中目标字数（默认 ±5% 容差）
    python3 wordcount.py check --target 140 -f draft.txt
    python3 wordcount.py check --target 140 --tolerance 0.1 < draft.txt

口径说明：社媒（微博/小红书/Twitter 等）主要看"计数字符数"，
即中文字符 + 英文单词（每个英文词计 1）+ 数字串（每串计 1），
这也是微博等平台的常见计法。同时给出多个口径供参考。
"""

import argparse
import json
import re
import sys

# 中文/日文/韩文等 CJK 表意字符区间（含扩展 A、兼容表意）
_CJK = (
    r"㐀-䶿"      # CJK 扩展 A
    r"一-鿿"      # CJK 基本
    r"豈-﫿"      # CJK 兼容表意
    r"\U00020000-\U0002ffff"  # CJK 扩展 B+（需 wide build，py3.11 默认支持）
)
_CJK_RE = re.compile(f"[{_CJK}]")
# 英文/拉丁单词（连字符、撇号视作词内字符）
_WORD_RE = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")
# 数字串（含小数点、千分位逗号）
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
# 标点/符号（非空白、非 CJK、非字母数字）
_PUNCT_RE = re.compile(
    f"[^\\s0-9A-Za-z{_CJK}]"
)


def count(text: str) -> dict:
    """统计文本各口径字数。"""
    cjk = len(_CJK_RE.findall(text))
    en_words = len(_WORD_RE.findall(text))
    num_groups = len(_NUM_RE.findall(text))
    punct = len(_PUNCT_RE.findall(text))
    total_chars = len(text)
    no_space_chars = len(re.sub(r"\s", "", text))

    # 社媒计数口径：中文字符 + 英文单词 + 数字串（标点/emoji 也计入 1，贴近微博计法）
    social = cjk + en_words + num_groups + punct

    return {
        "cjk_chars": cjk,             # 中文（CJK）字符数 —— 社媒主看
        "en_words": en_words,         # 英文单词数
        "num_groups": num_groups,     # 数字串个数
        "punct": punct,               # 标点/符号数（不含空白）
        "total_chars": total_chars,   # 总字符数（含空白，len 计）
        "no_space_chars": no_space_chars,  # 去空白字符数
        "social_count": social,       # 社媒计数口径（推荐用于字数限制判定）
    }


def check(text: str, target: int, tolerance: float, metric: str) -> dict:
    """校验文本是否命中目标字数 ±tolerance。

    metric 决定按哪个口径判定，默认 social_count（社媒计数）。
    """
    stats = count(text)
    actual = stats[metric]
    margin = round(target * tolerance)
    low = target - margin
    high = target + margin

    if actual < low:
        status = "under"
        diff = low - actual           # 至少还需增加多少
        advice = f"少了，至少再补 {diff} 字（当前 {actual}，下限 {low}）"
    elif actual > high:
        status = "over"
        diff = actual - high          # 至少还需删减多少
        advice = f"超了，至少再删 {diff} 字（当前 {actual}，上限 {high}）"
    else:
        status = "ok"
        diff = 0
        advice = f"达标（{low} ≤ {actual} ≤ {high}）"

    return {
        "pass": status == "ok",
        "status": status,             # ok / under / over
        "metric": metric,
        "target": target,
        "tolerance": tolerance,
        "range": [low, high],
        "actual": actual,
        "adjust": diff,               # 需要增/删的字数（0 表示达标）
        "advice": advice,
        "stats": stats,
    }


def _read_input(path: str | None) -> str:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    data = sys.stdin.read()
    if not data:
        sys.exit("错误：没有输入。用 -f 指定文件，或通过 stdin 传入文本。")
    return data


def _print(obj: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        for k, v in obj.items():
            if isinstance(v, dict):
                print(f"{k}:")
                for kk, vv in v.items():
                    print(f"  {kk}: {vv}")
            else:
                print(f"{k}: {v}")


def _selftest() -> int:
    cases = []
    s = count("你好世界")
    cases.append(("cjk 4", s["cjk_chars"] == 4 and s["social_count"] == 4))
    s = count("Hello world")
    cases.append(("en 2 words", s["en_words"] == 2 and s["social_count"] == 2))
    s = count("我有 3 只猫 and 2 dogs")
    # 中文4 + 数字2串 + 英文2词 = 8
    cases.append(("mixed", s["cjk_chars"] == 4 and s["en_words"] == 2
                  and s["num_groups"] == 2 and s["social_count"] == 8))
    s = count("价格是 1,299.99 元")
    cases.append(("num group", s["num_groups"] == 1 and s["cjk_chars"] == 4))
    r = check("一二三四五六七八九十", 10, 0.05, "social_count")
    cases.append(("check ok", r["pass"] and r["status"] == "ok"))
    r = check("一二三", 10, 0.05, "social_count")
    cases.append(("check under", r["status"] == "under" and r["adjust"] > 0))
    r = check("一二三四五六七八九十一二三四五", 10, 0.05, "social_count")
    cases.append(("check over", r["status"] == "over" and r["adjust"] > 0))
    r = check("", 0, 0.05, "social_count")
    cases.append(("empty target 0", r["pass"]))

    ok = True
    for name, passed in cases:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    return 0 if ok else 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="社媒文案字数统计与目标字数校验（纯标准库）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("count", help="统计文本字数（多口径）")
    pc.add_argument("-f", "--file", help="从文件读入（默认 stdin）")
    pc.add_argument("--json", action="store_true", help="JSON 输出")

    pk = sub.add_parser("check", help="校验是否命中目标字数 ±容差")
    pk.add_argument("--target", type=int, required=True, help="目标字数")
    pk.add_argument("--tolerance", type=float, default=0.05,
                    help="容差比例，默认 0.05（±5%%）")
    pk.add_argument("--metric", default="social_count",
                    choices=["social_count", "cjk_chars", "no_space_chars",
                             "total_chars"],
                    help="判定口径，默认 social_count（社媒计数）")
    pk.add_argument("-f", "--file", help="从文件读入（默认 stdin）")
    pk.add_argument("--json", action="store_true", help="JSON 输出")

    sub.add_parser("selftest", help="运行自测")

    args = p.parse_args()

    if args.cmd == "selftest":
        sys.exit(_selftest())

    text = _read_input(args.file)
    if args.cmd == "count":
        _print(count(text), args.json)
    elif args.cmd == "check":
        result = check(text, args.target, args.tolerance, args.metric)
        _print(result, args.json)
        sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
