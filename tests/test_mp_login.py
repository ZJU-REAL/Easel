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

if __name__ == '__main__':
    unittest.main()
