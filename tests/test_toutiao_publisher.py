"""今日头条（头条号）发布 SKILL 的契约单测。

覆盖：发布脚本离线自检、标题长度守卫、出站安全闸门、跨平台派发注册表、SKILL frontmatter 契约。
全部不启浏览器、不联网、不派生进程（直接调 main()，用 monkeypatch 顶掉浏览器阶段）。
运行：pytest tests/test_toutiao_publisher.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / "skills" / "builtin" / "skill-toutiao-publisher"
SKILL_MD = SKILL_DIR / "SKILL.md"

sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "builtin"
                       / "skill-cross-platform-publish" / "scripts"))

import toutiao_publish as tp  # noqa: E402
import publish_dispatch  # noqa: E402


@pytest.fixture
def article(tmp_path):
    path = tmp_path / "article.md"
    path.write_text("正文第一段\n\n正文第二段", encoding="utf-8")
    return path


def test_selftest_passes_offline(capsys):
    assert tp._selftest() == 0
    assert "selftest: OK" in capsys.readouterr().out


def test_title_over_limit_is_rejected(monkeypatch, article, capsys):
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--input", str(article), "--title", "标" * 40])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 1
    assert "上限 30 字" in capsys.readouterr().err


def test_sensitive_content_is_blocked_before_publishing(monkeypatch, tmp_path, capsys):
    """真发（--exec）命中密钥必须退出码 7 阻止，且发生在起浏览器之前。"""
    path = tmp_path / "article.md"
    path.write_text("正文里混进了 sk-ABCDEFGHIJKLMNOPQRSTUVWX", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--input", str(path), "--title", "标题", "--exec"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 7
    assert "阻止本次发布" in capsys.readouterr().err


def test_dry_run_fills_editor_without_publishing(monkeypatch, article, tmp_path):
    """默认 dry-run：把内容交给编辑器但不点发布，tags 正确拆分。"""
    captured: dict = {}

    def fake_publish(content, title, tags, cover, images, dry_run, headed, as_draft, timeout_ms):
        captured.update(content=content, title=title, tags=tags, cover=cover,
                        images=images, dry_run=dry_run, draft=as_draft)
        return {"platform": "toutiao", "dry_run": dry_run,
                "steps": {"title": True, "body": True}}

    monkeypatch.setattr(tp, "publish_article", fake_publish)
    monkeypatch.setattr(tp, "_write_record", lambda result: tmp_path / "record.json")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--input", str(article), "--title", "标题",
        "--tags", "AI, 效率工具 ,"])

    assert tp.main() == 0
    assert captured["dry_run"] is True
    assert captured["draft"] is False
    assert captured["tags"] == ["AI", "效率工具"]
    assert captured["title"] == "标题"
    assert captured["images"] == []


def test_publish_dispatch_routes_toutiao_to_this_skill():
    platform = publish_dispatch.PLATFORMS["toutiao"]

    assert platform["publisher"] == "skill-toutiao-publisher"
    assert platform["title"] == 30
    assert "article" in platform["types"]


def test_publish_dispatch_plan_covers_toutiao():
    plan = publish_dispatch._check_platform(
        "toutiao", {"title": "标题", "body": "正文", "tags": ["AI"], "media_type": "article"})

    assert plan["ok"] and not plan["warnings"]


def test_skill_frontmatter_contract():
    text = SKILL_MD.read_text(encoding="utf-8")
    head = text.split("---")[1]

    assert "name: skill-toutiao-publisher" in head
    assert "layer: publish" in head
    assert len(text.splitlines()) <= 200

@pytest.mark.parametrize("placeholder", [
    "mp.toutiao.com", "ToutiaoProfile", "outputs/_publish",
])
def test_skill_documents_key_entrypoints(placeholder):
    assert placeholder in SKILL_MD.read_text(encoding="utf-8")


def test_skill_documents_real_machine_calibrated_flows():
    """SKILL.md 必须写清真机校准出的三件事，否则使用者会按旧直觉踩坑。

    1) 头条没有「存草稿」按钮，草稿自动保存（dry-run 也会留草稿）
    2) 插图要靠「#占位符」决定位置
    3) 话题是编辑器内 # 联想
    """
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "自动保存" in text, "SKILL.md 应说明草稿是自动保存的"
    assert "dry-run" in text and "草稿箱" in text, "SKILL.md 应提醒 dry-run 也会留草稿"
    assert "--images" in text, "SKILL.md 应记录 --images 用法"
    assert "![](" in text, "SKILL.md 应说明正文里的图片占位符写法"
    assert "话题" in text and "#" in text, "SKILL.md 应说明话题是正文内 # 联想"


def test_publish_flow_doc_records_real_selectors():
    """references/publish-flow.md 是排障时的唯一依据，得记着实测选择器。"""
    ref = (SKILL_DIR / "references" / "publish-flow.md").read_text(encoding="utf-8")

    for needle in (".syl-toolbar-tool.image", ".forum-list-item-text",
                   "tteditor-forum", "草稿保存中", "「确定」"):
        assert needle in ref, f"publish-flow.md 缺真机校准结论：{needle}"


# ---------- Web 工作台接入契约（login / whoami / --content） ----------
# 这三样是 web/app.py 的分派点依赖的接口约定：
#   login  子命令把进度写进 login_state 协议文件（Web 后端只认这个文件，不直接管浏览器）
#   whoami 子命令在 stdout 打一行 JSON（web/app.py 按行解析，取最后一个 '{' 开头的行）
#   --content 让发布页的正文不必落临时文件

import json  # noqa: E402


def test_login_subcommand_parses_web_args():
    ns = tp._login_parser().parse_args(
        ["--qr-out", "/tmp/q.png", "--status-file", "/tmp/s.json", "--timeout", "120"])

    assert ns.qr_out == "/tmp/q.png"
    assert ns.status_file == "/tmp/s.json"
    assert ns.timeout == 120


def test_login_subcommand_writes_login_state_protocol(monkeypatch, tmp_path):
    import login_state

    qr, sf = tmp_path / "q.png", tmp_path / "s.json"
    seen: list[str] = []

    def fake_qr_login(profile, qr_out, status_file, timeout_s, headed=False):
        login_state.write_status(str(status_file), "starting")
        seen.append("starting")
        qr_out.write_bytes(b"png")
        login_state.write_status(str(status_file), "qr_ready", "扫码", qr=str(qr_out))
        seen.append("qr_ready")
        return 0

    monkeypatch.setattr(tp, "_qr_login", fake_qr_login)

    assert tp.main(["login", "--qr-out", str(qr), "--status-file", str(sf)]) == 0
    data = json.loads(sf.read_text(encoding="utf-8"))
    assert seen == ["starting", "qr_ready"]
    assert data["state"] == "qr_ready"
    assert data["qr"] == str(qr)


def test_login_subcommand_defaults_to_outputs_login_dir(monkeypatch):
    """不传 --qr-out/--status-file 时落到 outputs/_login（与其它平台同款约定）。"""
    captured: dict = {}

    def fake_qr_login(profile, qr_out, status_file, timeout_s, headed=False):
        captured.update(qr_out=qr_out, status_file=status_file)
        return 0

    monkeypatch.setattr(tp, "_qr_login", fake_qr_login)

    assert tp.main(["login"]) == 0
    assert captured["qr_out"].name == "toutiao.png"
    assert captured["status_file"].name == "toutiao.json"
    assert captured["status_file"].parent.name == "_login"


def test_phone_binding_is_not_a_completed_login():
    """扫码后手机号绑定页位于头条域名，也不能放行发布。"""
    class Visible:
        def is_visible(self):
            return True

    class BindingPage:
        url = "https://mp.toutiao.com/profile/v4/index"
        frames = []

        def get_by_text(self, text, exact=False):
            assert text == "手机绑定" and exact
            return type("Locator", (), {"first": Visible()})()

        def locator(self, selector):
            assert "placeholder" in selector
            return type("Locator", (), {"first": Visible()})()

    page = BindingPage()
    assert tp._needs_phone_binding(page)
    assert not tp._is_logged_in(page)


def test_backend_confirmation_rejects_intermediate_redirect(monkeypatch):
    """扫码后的临时跳转不能跳过后台的手机绑定要求。"""
    class RedirectPage:
        url = "https://mp.toutiao.com/intermediate"
        binding = False

        def goto(self, url, **kwargs):
            assert url == tp.HOME_URL
            self.url = url
            self.binding = True

        def wait_for_timeout(self, ms):
            assert ms >= 2000

    page = RedirectPage()
    monkeypatch.setattr(tp, "_needs_phone_binding", lambda p: p.binding)
    assert not tp._backend_authenticated(page)
    assert page.binding


def test_whoami_prints_single_json_line(monkeypatch, capsys):
    monkeypatch.setattr(tp, "_probe_identity",
                        lambda *a, **k: {"loggedIn": True, "name": "我的头条号", "avatar": ""})

    assert tp.main(["whoami"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("{")]
    assert json.loads(lines[-1]) == {"loggedIn": True, "name": "我的头条号", "avatar": ""}


def test_whoami_failure_carries_error_field(monkeypatch, capsys):
    """校验本身失败必须带 error——Web 端据此不缓存「未登录」假阴性。"""
    monkeypatch.setattr(
        tp, "_probe_identity",
        lambda *a, **k: {"loggedIn": False, "name": "", "avatar": "", "error": "浏览器起不来"})

    assert tp.main(["whoami"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("{")]
    assert json.loads(lines[-1])["error"] == "浏览器起不来"


def test_content_and_input_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--content", "正文", "--input", "x.md", "--title", "标题"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 2


def test_missing_content_source_errors(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["toutiao_publish.py", "--title", "标题"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 2


def test_content_is_published_without_temp_file(monkeypatch, tmp_path):
    """--content 直接把正文送进发布流程，不读文件。"""
    captured: dict = {}

    def fake_publish(content, title, tags, cover, images, dry_run, headed, as_draft, timeout_ms):
        captured.update(content=content, title=title, tags=tags)
        return {"platform": "toutiao", "steps": {"title": True, "body": True}}

    monkeypatch.setattr(tp, "publish_article", fake_publish)
    monkeypatch.setattr(tp, "_write_record", lambda result: tmp_path / "r.json")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--content", "第一段\n\n第二段", "--title", "标题"])

    assert tp.main() == 0
    assert captured["content"] == "第一段\n\n第二段"
    assert captured["title"] == "标题"


def test_login_launch_failure_writes_error_state(monkeypatch, tmp_path):
    """浏览器起不来（内核没装 / profile 被占用）也必须把状态写成 error。

    真机踩到过：launch 抛异常时状态文件卡在 starting，前端只能等进程退出兜底兜出来。
    """
    import login_state

    qr, sf = tmp_path / "q.png", tmp_path / "s.json"

    class BoomChromium:
        @staticmethod
        def launch_persistent_context(*a, **k):
            raise RuntimeError("Executable doesn't exist at .../chrome-headless-shell.exe")

    class BoomPlaywright:
        chromium = BoomChromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tp, "_require_playwright", lambda: (lambda: BoomPlaywright()))

    assert tp.main(["login", "--qr-out", str(qr), "--status-file", str(sf)]) == 1

    data = json.loads(sf.read_text(encoding="utf-8"))
    assert data["state"] == "error", f"状态应立刻变 error，实际：{data}"
    assert "Executable" in data["message"], data["message"]
    assert login_state is not None  # 协议模块确实被用到


# --------------------------------------------------------------------------- #
# 正文插图（--images）
# --------------------------------------------------------------------------- #

class _FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def insert_text(self, text):
        self.page.events.append(("text", text))

    def press(self, key):
        self.page.events.append(("press", key))


class _FakeLocator:
    def __init__(self, page, sel):
        self.page = page
        self.sel = sel

    @property
    def first(self):
        return self

    def count(self):
        if self.sel == tp.EDITOR_IMG_SELECTOR:
            return self.page.img_count
        if self.sel in tp.BODY_SELECTORS:
            return 1
        if self.sel in tp.IMAGE_BUTTON_SELECTORS:
            return 1
        if self.sel in tp.IMAGE_CONFIRM_SELECTORS:
            return 1
        if self.sel == tp.UPLOADED_THUMB_SELECTORS:
            return self.page.pending
        if self.sel == "input[type=file]:visible":
            return 1
        if self.sel == "div[contenteditable='true'] input[type='file']":
            return 1 if self.page.editor_has_file_input else 0
        return 0

    def is_visible(self):
        return True

    def click(self):
        self.page.clicked.append(self.sel)
        self.page.events.append(("click", self.sel))
        # 点「确定」= 面板里待插入的图进编辑器（真机 2026-10 校准的第三步）
        if self.sel in tp.IMAGE_CONFIRM_SELECTORS and self.page.pending:
            self.page.img_count += self.page.pending
            self.page.pending = 0

    def set_input_files(self, path):
        self.page.uploaded.append(path)
        self.page.events.append(("upload", path))
        if self.sel == "div[contenteditable='true'] input[type='file']":
            self.page.img_count += 1      # 编辑器自带 input：塞进去直接就是正文里的图
        else:
            self.page.pending += 1         # 面板上传：要等点「确定」才进正文


class _FakePage:
    """够用的假浏览器：按顺序记录「打字 / 上传图 / 点按钮」，用来验证插图位置。"""

    def __init__(self, editor_has_file_input=True):
        self.events = []
        self.keyboard = _FakeKeyboard(self)
        self.uploaded = []
        self.clicked = []
        self.img_count = 0
        self.pending = 0
        self.editor_has_file_input = editor_has_file_input

    def locator(self, sel):
        return _FakeLocator(self, sel)

    def wait_for_timeout(self, ms):
        pass


def _event_kinds(page):
    return [(k, str(v)) for k, v in page.events]


def test_fill_body_inserts_images_at_placeholder_positions(tmp_path):
    """正文里独占一行的 ![]() 占位符 → 图插在那个位置。"""
    img = tmp_path / "fig1.png"
    img.write_bytes(b"x")
    page = _FakePage()

    body = f"第一段\n\n![]({img})\n\n第二段"
    ok, failed = tp._fill_body(page, body, [img], 1000)

    assert ok is True
    assert failed == [], failed
    assert [Path(p).name for p in page.uploaded] == ["fig1.png"], page.uploaded

    # 顺序：先打「第一段」→ 上传图 → 再打「第二段」
    text_idx = [i for i, (k, _) in enumerate(page.events) if k == "text"]
    upload_idx = [i for i, (k, _) in enumerate(page.events) if k == "upload"]
    assert len(text_idx) == 2 and len(upload_idx) == 1, page.events
    assert text_idx[0] < upload_idx[0] < text_idx[1], page.events
    texts = [v for k, v in _event_kinds(page) if k == "text"]
    assert texts == ["第一段", "第二段"], texts


def test_fill_body_appends_unreferenced_images_at_end(tmp_path):
    """正文没引用到的图 → 追加到末尾，而不是丢掉。"""
    img = tmp_path / "fig2.png"
    img.write_bytes(b"x")
    page = _FakePage()

    ok, failed = tp._fill_body(page, "只有一段文字", [img], 1000)

    assert ok is True
    assert failed == [], failed
    assert [Path(p).name for p in page.uploaded] == ["fig2.png"], page.uploaded


def test_fill_body_falls_back_to_toolbar_when_no_editor_file_input(tmp_path):
    """编辑器里没有 file input 时，走「工具栏图片工具 → 面板上传 → 点确定」三步。"""
    img = tmp_path / "fig3.png"
    img.write_bytes(b"x")
    page = _FakePage(editor_has_file_input=False)

    ok, failed = tp._fill_body(page, f"![]({img})", [img], 1000)

    assert ok is True
    assert failed == [], failed
    assert [Path(p).name for p in page.uploaded] == ["fig3.png"], page.uploaded
    # 真机三步：点工具栏图片工具 → 塞图 → 点「确定」才进正文
    assert ".syl-toolbar-tool.image" in page.clicked, page.clicked
    assert any("确定" in c for c in page.clicked), page.clicked
    assert page.img_count == 1, page.img_count


def test_missing_image_file_errors(monkeypatch, tmp_path, capsys):
    """--images 里有不存在的图 → 直接报错退出，不起浏览器。"""
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--content", "正文", "--title", "标题",
        "--images", f"{tmp_path / 'nope.png'}"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 1
    assert "插图不存在" in capsys.readouterr().err


def test_images_flag_parses_existing_files(monkeypatch, tmp_path):
    """两张图都在 → 两张都进发布流程。"""
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    captured: dict = {}

    def fake_publish(content, title, tags, cover, images, dry_run, headed, as_draft, timeout_ms):
        captured.update(images=images)
        return {"platform": "toutiao", "steps": {"title": True, "body": True}}

    monkeypatch.setattr(tp, "publish_article", fake_publish)
    monkeypatch.setattr(tp, "_write_record", lambda result: tmp_path / "r.json")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--content", "正文", "--title", "标题",
        "--images", f"{a},{b}"])

    assert tp.main() == 0
    assert [p.name for p in captured["images"]] == ["a.png", "b.png"], captured["images"]
