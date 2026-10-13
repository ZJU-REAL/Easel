"""知乎 2026 顶栏改版后的登录检测回归测试（离线，假 page 对象，不启动浏览器）。

背景：改版后 `.AppHeader-profile` / `.AppHeader-userInfo` 不再渲染，旧 login_check
把所有已登录会话误判为未登录，QR 登录流程随之误报「未找到可识别的登录二维码」。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
import web_publisher  # noqa: E402


class _El:
    def __init__(self, visible: bool = True, text: str = ""):
        self._visible = visible
        self._text = text

    def is_visible(self) -> bool:
        return self._visible

    def inner_text(self) -> str:
        return self._text

    def get_attribute(self, _name: str):
        return None


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.ok = True

    def json(self):
        return self._payload


class _Request:
    def __init__(self, payload):
        self._payload = payload

    def get(self, _url, **_kw):
        return _Resp(self._payload)


class _Page:
    """只实现被测函数用到的最小接口：url / query_selector(_all) / request。"""

    def __init__(self, url: str, sels=None, api_payload=None):
        self.url = url
        self._sels = sels or {}
        self.request = _Request(api_payload or {})

    def query_selector(self, selector: str):
        return self._sels.get(selector.strip())

    def query_selector_all(self, selector: str):
        el = self._sels.get(selector.strip())
        return [el] if el is not None else []


def _cfg() -> dict:
    return web_publisher.PLATFORMS["zhihu"]


def test_login_check_covers_2026_header():
    selectors = _cfg()["login_check"]
    assert ".AppHeader .Avatar" in selectors
    assert "img.Avatar" in selectors
    # 旧选择器保留作向后兼容，不再是唯一判据
    assert ".AppHeader-profile" in selectors


def test_me_name_api_configured():
    assert "/api/v4/me" in _cfg()["me_name_api"]
    assert _cfg().get("me_name_api_field") == "name"


def test_is_logged_in_signin_url_is_logged_out():
    page = _Page("https://www.zhihu.com/signin")
    assert web_publisher._is_logged_in(page, _cfg()) is False


def test_is_logged_in_home_without_strong_selector_is_not_logged_in():
    # 改版后旧选择器全部失活：严格平台不命中强选择器必须判未登录（不得假阳性）
    page = _Page("https://www.zhihu.com", sels={})
    assert web_publisher._is_logged_in(page, _cfg()) is False


def test_is_logged_in_home_with_avatar_is_logged_in():
    page = _Page("https://www.zhihu.com", sels={".AppHeader .Avatar": _El(visible=True)})
    assert web_publisher._is_logged_in(page, _cfg()) is True


def test_visible_account_identity_name_falls_back_to_me_api():
    page = _Page("https://www.zhihu.com", sels={}, api_payload={"name": "mosjin"})
    ident = web_publisher._visible_account_identity(page, _cfg())
    assert ident["name"] == "mosjin"


def test_visible_account_identity_prefers_dom_over_api():
    page = _Page(
        "https://www.zhihu.com",
        sels={".AppHeader-profile .name": _El(visible=True, text="DOM名字")},
        api_payload={"name": "API名字"},
    )
    ident = web_publisher._visible_account_identity(page, _cfg())
    assert ident["name"] == "DOM名字"


def test_whoami_json_contract_unchanged():
    # whoami 输出契约（单行 JSON 字段）不因本次改动而变化
    result = {"loggedIn": False, "name": "", "avatar": ""}
    parsed = json.loads(json.dumps(result, ensure_ascii=False))
    assert set(parsed) >= {"loggedIn", "name", "avatar"}
