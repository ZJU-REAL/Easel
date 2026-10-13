"""知乎正文 Markdown → 富文本粘贴（paste_md 动作）的离线单元测试。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
import web_publisher  # noqa: E402


def test_actions_supports_paste_md():
    assert "paste_md" in web_publisher._ACTIONS
    # 原有动作不受影响
    assert {"type", "fill", "click"} <= web_publisher._ACTIONS


def test_zhihu_body_step_uses_paste_md():
    steps = web_publisher.PLATFORMS["zhihu"]["steps"]
    body = [s for s in steps if s.get("value") == "{desc}"]
    assert len(body) == 1
    assert body[0]["action"] == "paste_md"


def test_paste_md_js_sets_html_and_plain():
    js = web_publisher.PASTE_MD_JS
    assert "text/html" in js
    assert "text/plain" in js
    assert "ClipboardEvent" in js


def test_md_to_html_heading_levels():
    assert web_publisher._md_to_html("# 一级") == "<h2>一级</h2>"
    assert web_publisher._md_to_html("### 三级") == "<h3>三级</h3>"
    assert web_publisher._md_to_html("###### 六级") == "<h3>六级</h3>"


def test_md_to_html_inline_styles_and_escape():
    html = web_publisher._md_to_html("**加粗** 和 *斜体*")
    assert "<strong>加粗</strong>" in html
    assert "<em>斜体</em>" in html
    # HTML 特殊字符必须转义（防注入编辑器）
    assert "<script>" not in web_publisher._md_to_html("<script>x</script>")
    assert "&lt;script&gt;" in web_publisher._md_to_html("<script>x</script>")


def test_md_to_html_lists():
    html = web_publisher._md_to_html("1. 甲\n2. 乙\n\n- 丙\n- 丁")
    assert "<ol>" in html and "<li>甲</li>" in html and "</ol>" in html
    assert "<ul>" in html and "<li>丙</li>" in html and "</ul>" in html
    # 列表切换时先闭合旧列表
    assert html.index("</ol>") < html.index("<ul>")


def test_md_to_html_quote_and_hr_and_para():
    html = web_publisher._md_to_html("> 引用一句\n\n---\n\n第一段\n第二段")
    assert "<blockquote><p>引用一句</p></blockquote>" in html
    assert "<hr>" in html
    assert "<p>第一段<br>第二段</p>" in html


def test_md_to_plain_strips_marks():
    plain = web_publisher._md_to_plain("## 标题\n\n**粗** *斜*\n\n> 引\n\n1. 项")
    assert "#" not in plain
    assert "**" not in plain
    assert "标题" in plain and "粗 斜" in plain and "引" in plain and "项" in plain


def test_md_to_html_empty_and_blank_lines():
    assert web_publisher._md_to_html("") == ""
    assert web_publisher._md_to_html("\n\n\n") == ""
