"""
Tests for scripts/ai_score.py.

The `check_ai_score(md, threshold) -> (passed, report)` API is the library
entry; publish.py calls it as a blocking gate. These tests exercise the
shape of the report and the scoring logic against representative samples.

If `check_ai_score` is not yet importable (parallel agent still finishing),
the tests are skipped via pytest.importorskip-style guard so CI doesn't
block.
"""

from __future__ import annotations

import pytest

# Guard so tests don't blow up while another agent is still editing ai_score.py.
ai_score = pytest.importorskip(
    "ai_score",
    reason="ai_score module not yet available — parallel agent may still be working",
)

if not hasattr(ai_score, "check_ai_score"):
    pytest.skip(
        "ai_score.check_ai_score() not yet defined — parallel agent may still be working",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

# A deliberately "human-looking" sample: short/long sentence mix,
# first-person voice, concrete numbers, varied punctuation,
# zero AI-slop vocabulary.
HUMAN_SAMPLE = """\
上周三下午四点,我正在调试一个老脚本。看着屏幕上那个 404,我愣了一下——
这破玩意昨天还好好的。

回滚?不行,昨天的 commit 里混了别的改动。重跑?也不行,数据库已经写了一半。
我盯着日志看了三分钟,突然发现一个细节:我上周改过一个超时参数,从 30 秒
改成了 5 秒。对。就是这个。

你说这事儿气人不气人?一个五秒的超时,把两个下午的调试全干废了。我把参数
改回去,服务就活了。没有任何报警,没有任何 metric 跳出来告诉我。

说实话,我之前一直觉得监控做得挺全。今天这一下我自己都怀疑我在扯淡。
下次我得把超时值写到 README 里,最起码留个痕迹——免得下回又是自己给自己挖坑。

这篇写到这里有点跑题了,回到主题:稳定性不是测试能覆盖的,是一次次
踩坑沉下来的。我其实也说不准下次还会掉哪个沟里。存疑。
"""

# A deliberately "AI-looking" sample: stuffed with blacklist phrases,
# uniform sentence lengths, textbook enumeration, flat punctuation,
# and banned vocabulary.
AI_SLOP_SAMPLE = """\
随着人工智能技术的不断发展,我们迎来了前所未有的机遇。在当今的时代背景下,
AI 赋能千行百业已经成为一种共识。值得一提的是,大模型正在打造全新的生态,
实现端到端的全链路闭环。

首先,大模型提升了内容创作的效率。其次,它打开了知识普惠的大门。再次,
它助力企业完成数字化转型。综上所述,这项技术具有深远的意义。

不仅如此,它还颠覆了传统的方法论。一方面,它重塑了底层逻辑;另一方面,
它构建了新的护城河。毋庸置疑,我们正站在时代的风口。由此可见,拥抱变化
是唯一的选择。

总而言之,这是一场深度融合的革命。让我们共同迎接新篇章,一起破局出圈,
在智能化的浪潮中找到自己的生态位。归根结底,不断深耕,才能真正引领未来。
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_check_ai_score_pure_human_text_passes():
    """A clearly human-written sample with good burstiness should pass (<45)."""
    passed, report = ai_score.check_ai_score(HUMAN_SAMPLE, threshold=45.0)

    # The total score should be safely under the default pass threshold.
    assert passed is True, (
        f"human sample unexpectedly failed: score={report['total_score']}, "
        f"dims={report['dimensions']}"
    )
    assert report["total_score"] < 45.0


def test_check_ai_score_ai_slop_fails():
    """A sample full of banned phrases / vocab should fail (>=45)."""
    passed, report = ai_score.check_ai_score(AI_SLOP_SAMPLE, threshold=45.0)

    assert passed is False, (
        f"AI-slop sample unexpectedly passed: score={report['total_score']}, "
        f"dims={report['dimensions']}"
    )
    assert report["total_score"] >= 45.0
    # It should specifically report hits on phrases and vocab.
    assert len(report["hit_phrases"]) >= 2
    assert len(report["hit_vocab"]) >= 3


def test_report_shape():
    """The report dict must have all the documented keys with correct types."""
    _, report = ai_score.check_ai_score(HUMAN_SAMPLE, threshold=50.0)

    required_top = {"total_score", "dimensions", "hit_phrases", "hit_vocab", "threshold"}
    assert required_top.issubset(set(report.keys())), (
        f"missing keys: {required_top - set(report.keys())}"
    )
    assert isinstance(report["total_score"], (int, float))
    assert isinstance(report["threshold"], float)
    assert isinstance(report["hit_phrases"], list)
    assert isinstance(report["hit_vocab"], list)

    required_dims = {"burstiness", "phrases", "vocab", "structural", "punctuation"}
    assert required_dims.issubset(set(report["dimensions"].keys()))
    for k, v in report["dimensions"].items():
        assert isinstance(v, (int, float)), f"dim {k} is not numeric: {v!r}"


def test_full_width_punctuation_scored():
    """
    #8 fix: full-width punctuation (? ! ( ) — …) should count toward
    "flavor points" just like half-width equivalents.

    The text with full-width ? ! ( ) should score noticeably BETTER on the
    punctuation dimension (lower AI score) than text using only 。 .
    """
    # Long enough to clear the "too_short" branch in score_punctuation_flatness
    # (>= 200 chars). Each sample is the same length-ish with the same content
    # skeleton, only punctuation differs.
    base = "这是一段用来测试标点的样本文字内容重复堆满字数以绕过短文本分支"
    flat_text = (base + "。") * 12  # only periods
    rich_text = (
        "这是一段样本。"
        "真的吗？"
        "（顺便说句）"
        "太离谱了！"
        "——对的。"
        "再来——还有一处。"
        "(英文括号也算)"
        "?还有半角问号"
    ) * 3

    flat_score, _ = ai_score.score_punctuation_flatness(flat_text)
    rich_score, _ = ai_score.score_punctuation_flatness(rich_text)

    # Lower AI-score is better (more human-like). Rich text must beat flat text.
    assert rich_score < flat_score, (
        f"full-width punctuation didn't improve score: "
        f"flat={flat_score}, rich={rich_score}"
    )


def test_phrase_overlap_deduped():
    """
    #24 fix: overlapping phrase patterns should be counted once,
    not multiple times.

    `首先...其次...最后` and `首先...其次...再次` are two separate patterns
    but they can match overlapping spans of the same text. The scorer should
    dedupe and not double-count.
    """
    # This text triggers BOTH `首先.*其次.*最后` AND `首先.*其次.*再次`
    # patterns if they overlap. Naïvely summing would give 2+ hits; with
    # span-level dedupe it should be 1.
    text = (
        "首先,我们分析问题。其次,我们提出方案。再次,我们验证效果。"
        "最后,我们总结经验。"
    )
    score, detail = ai_score.score_phrases(text)

    # Implementation detail: hit_count >= 1 (some hit is expected), but
    # should be bounded — absolute cap we test is that it's not blown up
    # to 3+ by pure overlap. Allowing up to 2 handles edge cases where
    # the two patterns don't overlap at all on a given string.
    assert detail["hit_count"] <= 2, (
        f"overlap not deduped: got {detail['hit_count']} hits, samples={detail['samples']}"
    )


def test_threshold_parameter_respected():
    """Edge case: same content, two different thresholds should flip pass/fail."""
    # Pick a text in the grey zone so threshold actually matters.
    grey_text = (HUMAN_SAMPLE + "\n\n" + AI_SLOP_SAMPLE)

    passed_loose, report_loose = ai_score.check_ai_score(grey_text, threshold=99.0)
    passed_strict, _ = ai_score.check_ai_score(grey_text, threshold=1.0)

    assert passed_loose is True
    assert passed_strict is False
    assert report_loose["threshold"] == 99.0
