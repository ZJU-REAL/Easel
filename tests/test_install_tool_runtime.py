"""Environment checks use the running venv and reject incomplete runtime assets."""
import os
import json
import asyncio
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
import install_tool as tool


def recipe(name):
    return next(t for t in tool.TOOLS if t.id == name)


def test_active_venv_wins_over_path_scoring_and_stale_cache(monkeypatch, tmp_path):
    executable = str(tmp_path / 'venv' / 'python')
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / 'venv'))
    monkeypatch.setattr(sys, 'base_prefix', str(tmp_path / 'base'))
    monkeypatch.setattr(sys, 'executable', executable)
    monkeypatch.setattr(tool, '_PY_LIST', ['wrong-base-python'])
    monkeypatch.setattr(tool, '_candidate_pythons', lambda: pytest.fail('must not probe other interpreters'))
    assert tool.resolve_python() == executable


def test_metadata_only_whisper_directory_is_not_ready(monkeypatch, tmp_path):
    (tmp_path / 'config.json').write_text('{}')
    (tmp_path / 'tokenizer.json').write_text('{}')
    monkeypatch.setattr(os.path, 'expanduser', lambda p: str(tmp_path))
    assert not tool._pyfn_check_model()[0]


def test_builtin_remotion_directory_is_used_without_dir_argument():
    state = tool.check_tool(recipe('rmdeps'), sys.executable)
    assert state['state'] != 'no_dir'


def test_an_empty_browser_cache_is_not_a_ready_executable(tmp_path):
    (tmp_path / 'node_modules/.remotion/chrome-headless-shell').mkdir(parents=True)
    state = tool.check_tool(recipe('shell'), sys.executable, str(tmp_path))
    assert state['state'] == 'missing'


def test_faster_whisper_check_exercises_decoding(monkeypatch, tmp_path):
    package = tmp_path / 'faster_whisper'
    package.mkdir()
    (package / '__init__.py').write_text('__version__ = "broken-decoder"\n')
    (package / 'audio.py').write_text('def decode_audio(*args, **kwargs):\n    raise TypeError("metadata_errors")\n')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path))
    state = tool.check_tool(recipe('fw'), sys.executable)
    assert state['state'] == 'missing'
    assert 'metadata_errors' in (state['detail'] or '')


def test_venv_command_directory_is_not_added_to_user_path(monkeypatch, tmp_path):
    prefix = tmp_path / 'venv'
    binary = prefix / 'Scripts/ffmpeg.exe'
    binary.parent.mkdir(parents=True)
    binary.write_text('placeholder')
    monkeypatch.setattr(sys, 'prefix', str(prefix))
    monkeypatch.setattr(sys, 'base_prefix', str(tmp_path / 'base'))
    monkeypatch.setattr(tool.shutil, 'which', lambda name: str(binary))
    monkeypatch.setattr(tool, '_ensure_user_path', lambda path: pytest.fail('do not persist venv paths'))
    tool._ensure_cli_visible(recipe('ffmpeg'), sys.executable)


def test_complete_model_metadata_and_weight_size_are_required(monkeypatch, tmp_path):
    weights = tmp_path / 'model.bin'
    weights.write_bytes(b'placeholder')
    (tmp_path / 'config.json').write_text('{}')
    (tmp_path / 'tokenizer.json').write_text('{}')
    monkeypatch.setattr(os.path, 'expanduser', lambda p: str(tmp_path))
    stat = Path.stat
    def sized(path, *args, **kwargs):
        result = stat(path, *args, **kwargs)
        if path == weights:
            values = list(result)
            values[6] = 2_500_000_000
            return os.stat_result(values)
        return result
    monkeypatch.setattr(Path, 'stat', sized)
    assert tool._pyfn_check_model()[0]
    (tmp_path / 'tokenizer.json').write_text('incomplete')
    assert not tool._pyfn_check_model()[0]


@pytest.mark.parametrize('cached,expected,state', [('149.0.7790.0', '149.0.7790.0', 'ok'),
                                                ('148.0.0.0', '149.0.7790.0', 'missing')])
def test_browser_cache_requires_matching_renderer_version_and_executable(monkeypatch, tmp_path, cached, expected, state):
    cache = tmp_path / 'node_modules/.remotion/chrome-headless-shell'
    binary = cache / 'linux64/chrome-headless-shell-linux64/chrome-headless-shell'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'executable-placeholder')
    (cache / 'VERSION').write_text(cached)
    metadata = tmp_path / 'node_modules/@remotion/renderer/dist/browser/get-chrome-download-url.js'
    metadata.parent.mkdir(parents=True)
    metadata.write_text(f"exports.TESTED_VERSION = '{expected}';")
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(tool.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(tool, '_run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=f'Chrome Headless Shell {cached}', stderr=''))
    assert tool.check_tool(recipe('shell'), sys.executable, str(tmp_path))['state'] == state


def test_browser_download_does_not_start_when_project_installation_fails(monkeypatch, tmp_path):
    (tmp_path / 'package.json').write_text(json.dumps({'dependencies': {'remotion': '*'}}))
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=1, stdout='', stderr='package install failed')
    monkeypatch.setattr(tool, '_run', run)
    result = tool.install_tool(recipe('shell'), sys.executable, str(tmp_path))
    assert result['state'] == 'fail'
    assert not any('npx' in command for argv in commands for command in argv)


def test_bilibili_publish_dispatch_uses_the_running_python_environment(monkeypatch, tmp_path):
    import web.app as web
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'video-placeholder')
    commands = []
    monkeypatch.setattr(web, '_require_automated_publishing', lambda: None)
    monkeypatch.setattr(web, '_publish_env', lambda: {})
    monkeypatch.setattr(web, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    monkeypatch.setattr(web.subprocess, 'run', lambda argv, **kw:
                        commands.append(argv) or SimpleNamespace(returncode=1, stdout='', stderr='not executed'))
    result = asyncio.run(web.api_publish('bilibili', web.PublishRequest(title='标题', body='正文', media=['video.mp4'])))
    assert result['ok'] is False
    assert commands[0][:3] == [sys.executable, '-m', 'biliup']
