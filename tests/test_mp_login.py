"""公众号重复登录及异常状态回归测试，不启动真实浏览器。"""
import ast
import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_mp_module():
    script = ROOT / 'skills/shared/scripts/weixin_mp_stats.py'
    spec = importlib.util.spec_from_file_location('mp_login_module_under_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLink:
    def __init__(self, text, on_click=None, visible=True):
        self._text = text
        self._visible = visible
        self._on_click = on_click
        self.clicked = 0

    def inner_text(self):
        return self._text

    def is_visible(self):
        return self._visible

    def click(self, timeout=None):
        self.clicked += 1
        if self._on_click:
            self._on_click()


class FakeQR:
    def __init__(self, visible=False):
        self.visible = visible

    def is_visible(self):
        return self.visible

    def bounding_box(self):
        return {'width': 122, 'height': 122} if self.visible else None

    def screenshot(self, timeout=None):
        return b'fake-png'


class FakeMask:
    def __init__(self, text, links):
        self._text = text
        self._links = links

    def inner_text(self):
        return self._text

    def query_selector_all(self, selector):
        return self._links if selector == 'a' else []


class FakePage:
    def __init__(self, qr, links=(), masks=()):
        self.qr = qr
        self.links = list(links)
        self.masks = list(masks)
        self.waits = 0

    def query_selector(self, selector):
        return self.qr

    def query_selector_all(self, selector):
        if selector.endswith('link_text'):
            return self.links
        if selector == '.login__type__container__scan_mask':
            return self.masks
        return []

    def evaluate(self, script, element):
        return True

    def wait_for_timeout(self, milliseconds):
        self.waits += 1

    def screenshot(self, **kwargs):
        raise AssertionError('不允许整页截图兜底')


def load_web_functions():
    tree = ast.parse((ROOT / 'web/app.py').read_text(encoding='utf-8'))
    names = {'api_mp_login_start', '_stop_mp_login_on_shutdown'}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    env = {'subprocess': subprocess}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'web/app.py', 'exec'), env)
    return env

class MpLoginTests(unittest.TestCase):
    def test_repeated_start_preserves_existing_session(self):
        env = load_web_functions()
        proc = Mock()
        proc.poll.return_value = None
        status = {'state': 'qr_ready', 'qr': '_login/wechat-oa-mp.png'}
        env.update(LOGIN_RUNNERS={'wechat-oa': {'backend': 'wechat-oa'}},
                   LOGIN_PROCESSES={'wechat-oa-mp': proc}, _mp_login_status=lambda: status)
        # 文件目录与启动依赖未提供；复用会话不应碰触它们。
        for _ in range(2):
            self.assertEqual(asyncio.run(env['api_mp_login_start']('wechat-oa')), {'mode': 'qr', **status})

    def test_shutdown_reaps_login_process(self):
        env = load_web_functions()
        proc = Mock()
        proc.poll.return_value = None
        marker = Mock()
        env.update(LOGIN_PROCESSES={'wechat-oa-mp': proc}, _write_login_marker=marker)
        env['_stop_mp_login_on_shutdown']()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)
        self.assertEqual(env['LOGIN_PROCESSES'], {})
        self.assertEqual(marker.call_args.args[1], 'expired')

    def test_browser_failure_writes_error_state(self):
        script = ROOT / 'skills/shared/scripts/weixin_mp_stats.py'
        spec = importlib.util.spec_from_file_location('mp_login_under_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            args = Mock(status_file=str(Path(d) / 'status.json'))
            with patch.object(module, '_run_login', side_effect=RuntimeError('browser launch failed')):
                self.assertEqual(module.cmd_login(args), 1)
            self.assertEqual(module.login_state.read_status(args.status_file)['state'], 'error')

    def test_ensure_qr_mode_clicks_scan_login_when_fast_login_hides_qr(self):
        """记住微信账号后默认是「微信快捷登录」，必须点「扫码登录」才能拿到二维码。"""
        module = load_mp_module()
        qr = FakeQR(visible=False)
        link = FakeLink('扫码登录', on_click=lambda: setattr(qr, 'visible', True))
        page = FakePage(qr, links=[link])
        self.assertTrue(module._ensure_qr_mode(page, timeout=3))
        self.assertEqual(link.clicked, 1)

    def test_ensure_qr_mode_switches_at_most_once(self):
        """重复点「扫码登录」会重建会话并作废刚扫的码，因此一轮只允许切一次。"""
        module = load_mp_module()
        link = FakeLink('扫码登录')
        page = FakePage(FakeQR(visible=False), links=[link])
        self.assertFalse(module._ensure_qr_mode(page, timeout=0.3))
        self.assertEqual(link.clicked, 1)

    def test_ensure_qr_mode_keeps_visible_qr(self):
        module = load_mp_module()
        qr = FakeQR(visible=True)
        link = FakeLink('微信快捷登录')
        page = FakePage(qr, links=[link])
        self.assertTrue(module._ensure_qr_mode(page, timeout=1))
        self.assertEqual(link.clicked, 0)

    def test_capture_qr_rejects_non_qr_and_never_screenshots_full_page(self):
        """页面不是二维码时返回 False，绝不把整页截图当二维码保存。"""
        module = load_mp_module()
        page = FakePage(FakeQR(visible=True))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'qr.png'
            with patch.object(module.login_qr, 'save_qr', return_value=False) as save:
                self.assertFalse(module._capture_qr(page, out, attempts=1))
            self.assertTrue(save.called)
            self.assertFalse(out.exists())

    def test_capture_qr_saves_verified_qr(self):
        module = load_mp_module()
        page = FakePage(FakeQR(visible=True))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'qr.png'
            with patch.object(module.login_qr, 'save_qr', return_value=True) as save:
                self.assertTrue(module._capture_qr(page, out, attempts=1))
            self.assertEqual(save.call_args.args[0], b'fake-png')

    def test_refresh_expired_qr_only_clicks_expired_mask(self):
        module = load_mp_module()
        scanned = FakeLink('重新扫码')
        expired = FakeLink('点击刷新')
        page = FakePage(
            FakeQR(visible=True),
            masks=[FakeMask('扫码成功 请在微信中确认账号登录', [scanned]),
                   FakeMask('二维码已过期 点击刷新', [expired])],
        )
        self.assertTrue(module._refresh_expired_qr(page))
        self.assertEqual(scanned.clicked, 0)
        self.assertEqual(expired.clicked, 1)

    def test_weixin_resolve_content_image_maps_api_media(self):
        script = ROOT / 'skills/shared/scripts/weixin_mp_stats.py'
        spec = importlib.util.spec_from_file_location('mp_stats_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            module.PROJECT_ROOT = tmp_path
            image = tmp_path / "outputs" / "gallery" / "a.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")
            html = tmp_path / "outputs" / "articles" / "a.html"
            html.parent.mkdir(parents=True)
            html.write_text("<p></p>", encoding="utf-8")
            self.assertEqual(module.resolve_content_image("/api/media/gallery/a.png", html), image.resolve())
            self.assertEqual(module.resolve_content_image("https://127.0.0.1:7860/api/media/gallery/a.png", html), image.resolve())
            self.assertIsNone(module.resolve_content_image("https://cdn.example/x.png", html))
            self.assertIsNone(module.resolve_content_image("/api/media/_login/secret.png", html))

    def test_weixin_profile_lock_rejects_second_holder(self):
        script = ROOT / 'skills/shared/scripts/weixin_mp_stats.py'
        spec = importlib.util.spec_from_file_location('mp_stats_test2', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d) / "WeixinMpProfile"
            holder = module._lock_profile(prof)
            try:
                with self.assertRaises(RuntimeError):
                    module._lock_profile(prof)
            finally:
                module._unlock_profile(holder)

if __name__ == '__main__':
    unittest.main()

