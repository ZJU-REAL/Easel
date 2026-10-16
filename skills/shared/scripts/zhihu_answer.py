#!/usr/bin/env python3
"""zhihu_answer.py — 用已登录的 ZhihuProfile 对知乎问题发布回答。

用法（CWD=项目根）：
  # 预览（dry-run，不真正发布）：
  python skills/shared/scripts/zhihu_answer.py \
      --question https://www.zhihu.com/question/XXXXX \
      --content-file outputs/zhihu_answers/story1.md

  # 真正发布：
  python skills/shared/scripts/zhihu_answer.py \
      --question https://www.zhihu.com/question/XXXXX \
      --content-file outputs/zhihu_answers/story1.md \
      --exec

  # 有头模式（调试/首次校准）：
  python skills/shared/scripts/zhihu_answer.py \
      --question https://www.zhihu.com/question/XXXXX \
      --content-file outputs/zhihu_answers/story1.md \
      --exec --headed

依赖：playwright + chromium（与 web_publisher 共用 ZhihuProfile）
"""

from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import content_guard  # noqa: E402  出站内容安全闸门

# PROJECT_ROOT：优先 EASEL_ROOT env（gateway/CLI/web 注入），否则按 __file__ 上溯。
# ⚠️ 本脚本会被 sync.sh 拍平复制到 workspace/shared/scripts/，那里 parents[3] 会算错根，
# 相对 content-file 会解析到错误目录——故 env 兜底不可省（与 manifest.py 同款）。
PROJECT_ROOT = Path(os.environ.get("EASEL_ROOT") or Path(__file__).resolve().parents[3])
PROFILE_DIR = Path.home() / ".easel-browser-profiles" / "ZhihuProfile"

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--disable-extensions", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--mute-audio", "--no-first-run", "--no-default-browser-check",
]

EDITOR_CHECK = ".public-DraftEditor-content, .DraftEditor-editorContainer [contenteditable=true]"


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _click_write_answer_btn(page) -> bool:
    """三策略触发「写回答/编辑回答」编辑器出现，返回是否成功。"""
    # 先检查是否是"编辑回答"状态（已有草稿或已发布）
    already_answered = page.evaluate("""
        () => Array.from(document.querySelectorAll('button'))
                   .some(b => (b.innerText||'').trim() === '编辑回答')
    """)
    if already_answered:
        # 有草稿或已发布的回答，点击"编辑回答"进入编辑器
        clicked = page.evaluate("""
            () => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => (b.innerText||'').trim() === '编辑回答');
                if (btn) {
                    btn.scrollIntoView({block:'center'});
                    btn.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true,view:window}));
                    return true;
                }
                return false;
            }
        """)
        page.wait_for_timeout(3000)
        if page.query_selector(EDITOR_CHECK):
            print("[INFO] 编辑回答 点击 → 编辑器出现", file=sys.stderr)
            return True

    try:
        btn_loc = page.locator(".WriteAnswerButton").first
        btn_loc.wait_for(state="visible", timeout=8000)
    except Exception as e:
        print(f"[WARN] WriteAnswerButton 未出现: {e}", file=sys.stderr)
        return False

    # 策略1: dispatch_event（绕过 header 覆盖层）
    btn_loc.dispatch_event("click")
    page.wait_for_timeout(3000)
    if page.query_selector(EDITOR_CHECK):
        print("[INFO] 策略1 dispatch_event → 编辑器出现", file=sys.stderr)
        return True

    # 策略2: React 完整鼠标事件序列
    page.evaluate("""() => {
        const b = document.querySelector('.WriteAnswerButton');
        if (b) ['mousedown','mouseup','click'].forEach(t =>
            b.dispatchEvent(new MouseEvent(t, {bubbles:true,cancelable:true,view:window}))
        );
    }""")
    page.wait_for_timeout(3000)
    if page.query_selector(EDITOR_CHECK):
        print("[INFO] 策略2 React事件序列 → 编辑器出现", file=sys.stderr)
        return True

    # 策略3: focus + Enter 键（最可靠）
    try:
        btn_loc.focus()
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        if page.query_selector("[contenteditable=true]"):
            print("[INFO] 策略3 focus+Enter → 编辑器出现", file=sys.stderr)
            return True
    except Exception as e:
        print(f"[WARN] 策略3 失败: {e}", file=sys.stderr)

    print("[ERROR] 所有策略均未能打开编辑器", file=sys.stderr)
    return False


def _find_editor(page):
    """找到可见的回答编辑器元素。"""
    selectors = [
        ".DraftEditor-editorContainer [contenteditable=true]",
        "[contenteditable=true][data-contents]",
        ".public-DraftEditor-content",
        ".AnswerForm [contenteditable=true]",
        "[contenteditable=true]",
    ]
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=5000)
            el = page.query_selector(sel)
            if el and el.is_visible():
                print(f"[INFO] 找到编辑器: {sel}", file=sys.stderr)
                return el
        except Exception:
            pass
    return None


def type_into_editor(page, text: str) -> bool:
    """点击「写回答/编辑回答」并写入内容（先清空已有草稿）。"""
    if not _click_write_answer_btn(page):
        print("[WARN] 写回答按钮未能打开编辑器，尝试直接查找", file=sys.stderr)

    editor = _find_editor(page)
    if not editor:
        print("[ERROR] 未找到回答编辑器", file=sys.stderr)
        return False

    # 激活编辑器
    page.evaluate("el => el.click()", editor)
    page.wait_for_timeout(500)

    # 清空已有草稿内容（全选删除）
    page.keyboard.press("Control+A")
    page.wait_for_timeout(300)
    page.keyboard.press("Backspace")
    page.wait_for_timeout(500)
    print("[INFO] 已清空编辑器草稿", file=sys.stderr)

    # 按段落输入（保留换行）
    paragraphs = text.split('\n')
    for i, para in enumerate(paragraphs):
        if para.strip():
            page.keyboard.type(para, delay=10)
        if i < len(paragraphs) - 1:
            page.keyboard.press("Enter")

    page.wait_for_timeout(1500)
    return True


def _click_publish_btn(page) -> bool:
    """点击「发布回答/提交修改」按钮 — JS遍历全部button，不依赖视口内可见。"""
    # 候选按钮文本（发布回答 和 提交修改 均可）
    PUBLISH_TEXTS = ['发布回答', '提交修改']

    # 策略1: JS遍历所有button，找含候选文本的，scrollIntoView再click
    clicked = page.evaluate("""
        () => {
            const texts = ['发布回答', '提交修改'];
            const btns = Array.from(document.querySelectorAll('button'));
            const pub = btns.find(b => texts.some(t => (b.innerText || '').trim().includes(t)));
            if (pub) {
                pub.scrollIntoView({behavior:'instant', block:'center'});
                pub.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true,view:window}));
                return pub.innerText.trim();
            }
            return '';
        }
    """)
    if clicked:
        page.wait_for_timeout(4000)
        print(f"[INFO] 发布按钮 [{clicked}] JS遍历点击 OK", file=sys.stderr)
        return True

    print("[WARN] JS遍历未找到发布按钮，尝试 locator attached", file=sys.stderr)

    # 策略2: locator state=attached（不要求在视口内），两种文本都试
    for btn_text in PUBLISH_TEXTS:
        try:
            pub_loc = page.locator(f"button:has-text('{btn_text}')").first
            pub_loc.wait_for(state="attached", timeout=5000)
            pub_loc.scroll_into_view_if_needed()
            pub_loc.dispatch_event("click")
            page.wait_for_timeout(4000)
            print(f"[INFO] 发布按钮 [{btn_text}] locator+attached OK", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[WARN] 发布按钮 [{btn_text}] locator 失败: {e}", file=sys.stderr)

    return False


def classify_publish_outcome(question_url: str, final_url: str) -> dict:
    """判定发布结果。只解析 URL 的路径部分，不做整串子串匹配。

    返回 {"outcome": ..., "success": bool, "detail": str}，其中
    outcome ∈ {"verified", "login_required", "unverified"}。

    - verified：落在同一问题 id 下的回答地址，且回答 id 不是输入地址里原有的。
    - login_required：发布后跳到登录页（可能未登录或登录态失效）。
    - unverified：仍在问题页或其他情况，需手动检查账号回答列表确认。
    """
    q_path = urlparse(question_url).path
    f_path = urlparse(final_url).path

    if re.search(r"(signin|login)", f_path, re.IGNORECASE):
        return {"outcome": "login_required", "success": False,
                "detail": "发布后跳到登录页，可能未登录或登录态失效"}

    m_q = re.search(r"/question/(\d+)", q_path)
    qid = m_q.group(1) if m_q else None

    m_a = re.search(r"/question/(\d+)/answer/(\d+)", f_path)
    if m_a and qid and m_a.group(1) == qid:
        # 输入地址本身可能是某个回答链接：回答 id 与输入一致则不是本次新发布
        m_input = re.search(r"/answer/(\d+)", q_path)
        if m_input and m_input.group(1) == m_a.group(2):
            return {"outcome": "unverified", "success": False,
                    "detail": "地址中的回答 id 与输入地址一致，非本次新发布"}
        return {"outcome": "verified", "success": True,
                "detail": f"新回答地址 /question/{qid}/answer/{m_a.group(2)}"}

    return {"outcome": "unverified", "success": False,
            "detail": "发布后未落到新回答地址，请手动检查账号回答列表确认"}


def publish_answer(question_url: str, content: str, headed: bool = False, dry_run: bool = True) -> dict:
    from playwright.sync_api import sync_playwright

    result = {"success": False, "url": "", "error": ""}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=not headed,
            args=LAUNCH_ARGS,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        # 1. 打开问题页
        print(f"[INFO] 访问问题页: {question_url}", file=sys.stderr)
        page.goto(question_url, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(2000)

        # 检查登录态
        if page.query_selector(".SignContainer, .Login-content"):
            result["error"] = "未登录知乎，请先在「账号」页扫码登录"
            ctx.close()
            return result

        # 获取问题标题
        title = ""
        for sel in ["h1.QuestionHeader-title", "h1"]:
            el = page.query_selector(sel)
            if el:
                title = el.inner_text().strip()[:60]
                break
        print(f"[INFO] 问题标题: {title}", file=sys.stderr)

        if dry_run:
            print(f"[DRY-RUN] 将回答问题：{title}", file=sys.stderr)
            print(f"[DRY-RUN] 回答字数：{len(content)} 字", file=sys.stderr)
            print(f"[DRY-RUN] 内容预览（前100字）：{content[:100]}...", file=sys.stderr)
            result["success"] = True
            result["url"] = question_url
            result["dry_run"] = True
            ctx.close()
            return result

        # 2. 写入回答内容
        ok = type_into_editor(page, content)
        if not ok:
            result["error"] = "无法写入编辑器"
            ctx.close()
            return result

        page.wait_for_timeout(1500)

        # 3. 发布
        published = _click_publish_btn(page)
        if not published:
            result["error"] = "未找到或无法点击发布回答按钮"
            ctx.close()
            return result

        # 4. 验证：只解析 URL 路径部分判定，不做整串子串匹配（issue #113）
        current_url = page.url
        print(f"[INFO] 当前页面 URL: {current_url}", file=sys.stderr)
        outcome = classify_publish_outcome(question_url, current_url)
        result["success"] = outcome["success"]
        result["outcome"] = outcome["outcome"]
        result["url"] = current_url
        if outcome["success"]:
            print(f"[INFO] 发布已验证: {outcome['detail']}", file=sys.stderr)
        else:
            result["error"] = outcome["detail"]

        ctx.close()
        return result


def _selftest() -> int:
    """轻量自测（不启浏览器）：校验选择器常量、内容读取与相对路径解析逻辑。"""
    import tempfile
    assert EDITOR_CHECK and "contenteditable" in EDITOR_CHECK, "编辑器选择器不应为空"
    assert LAUNCH_ARGS and "--disable-blink-features=AutomationControlled" in LAUNCH_ARGS, "反检测参数缺失"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "a.md"
        f.write_text("回答正文\n\n第二段", encoding="utf-8")
        assert f.read_text(encoding="utf-8").strip() == "回答正文\n\n第二段"
    # 相对 content-file 应挂到 PROJECT_ROOT 下
    rel = Path("outputs/x/answer.md")
    assert (PROJECT_ROOT / rel).is_absolute()
    # issue #113：发布结果判定（离线，不启浏览器）
    outcome_cases = [
        # (question_url, final_url, 期望 outcome, 期望 success)
        ("https://www.zhihu.com/question/12345",
         "https://www.zhihu.com/question/12345",
         "unverified", False),  # 仍在问题页：发布被拒/风控/验证
        ("https://www.zhihu.com/question/12345",
         "https://www.zhihu.com/question/12345/answer/67890",
         "verified", True),  # 新回答地址
        ("https://www.zhihu.com/question/12345",
         "https://www.zhihu.com/signin?next=%2Fquestion%2F12345",
         "login_required", False),  # 跳登录页（回跳参数含 question 也不能误判）
        ("https://www.zhihu.com/question/12345/answer/11111",
         "https://www.zhihu.com/question/12345/answer/11111",
         "unverified", False),  # 输入的是别人回答链接
        ("https://www.zhihu.com/question/12345",
         "https://www.zhihu.com/question/99999/answer/67890",
         "unverified", False),  # 落到其他问题下
    ]
    for q, f, exp_outcome, exp_success in outcome_cases:
        r = classify_publish_outcome(q, f)
        assert r["outcome"] == exp_outcome, f"{f}: 期望 {exp_outcome}，实际 {r['outcome']}"
        assert r["success"] is exp_success, f"{f}: success 应为 {exp_success}"
    try:
        import playwright  # noqa: F401
        pw = "yes"
    except Exception:
        pw = "MISSING（需 pip install playwright && playwright install chromium）"
    print(f"zhihu_answer.py selftest: OK (playwright={pw})")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    parser = argparse.ArgumentParser(description="知乎问题回答发布工具")
    parser.add_argument("--selftest", action="store_true", help="离线自检")
    parser.add_argument("--question", required=True, help="知乎问题 URL")
    parser.add_argument("--content-file", required=True, help="回答内容文件路径")
    parser.add_argument("--exec", action="store_true", dest="execute", help="真正发布（默认 dry-run）")
    parser.add_argument("--allow-unsafe", action="store_true",
                        help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    parser.add_argument("--headed", action="store_true", help="有头浏览器模式（调试用）")
    args = parser.parse_args()

    content_path = Path(args.content_file)
    if not content_path.is_absolute():
        content_path = PROJECT_ROOT / content_path
    if not content_path.exists():
        die(f"内容文件不存在：{content_path}")

    content = content_path.read_text(encoding="utf-8").strip()
    if not content:
        die("内容文件为空")

    dry_run = not args.execute
    # 出站内容安全闸门：真发前扫描回答正文，检出内部设置泄露即阻止发布（dry-run 只告警）。
    content_guard.guard_or_die([content], exec_mode=not dry_run,
                               allow_unsafe=args.allow_unsafe, label="知乎回答内容")
    mode_label = "DRY-RUN" if dry_run else "EXEC"
    print(f"[{mode_label}] 知乎问题回答发布", file=sys.stderr)
    print(f"  问题: {args.question}", file=sys.stderr)
    print(f"  内容: {content_path} ({len(content)} 字)", file=sys.stderr)

    result = publish_answer(
        question_url=args.question,
        content=content,
        headed=args.headed,
        dry_run=dry_run,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
