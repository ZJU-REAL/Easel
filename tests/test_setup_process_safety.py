"""Prevent recursive test interpreters and reject unsupported shells before probes."""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')
pytestmark = pytest.mark.skipif(os.name == 'nt' or not BASH, reason='POSIX shell test; Windows uses setup.ps1')


@pytest.mark.parametrize('platform', ['MINGW64_NT-10.0', 'MSYS_NT-10.0', 'CYGWIN_NT-10.0'])
def test_windows_shell_rejected_before_python_or_package_probes(tmp_path, platform):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    uname = bin_dir / 'uname'
    uname.write_text(f'#!/bin/bash\necho {shlex.quote(platform)}\n')
    uname.chmod(0o755)
    marker = tmp_path / 'unexpected'
    for name in ['python3', 'node', 'npm', 'env', 'dirname']:
        tool = bin_dir / name
        tool.write_text(f'#!/bin/bash\nprintf called > {shlex.quote(str(marker))}\nexit 99\n')
        tool.chmod(0o755)
    result = subprocess.run([BASH, str(ROOT / 'setup.sh')], cwd=tmp_path,
                            env={**os.environ, 'PATH': str(bin_dir)}, capture_output=True, text=True, timeout=5)
    assert result.returncode == 1 and 'setup.ps1' in result.stderr
    assert not marker.exists()


def test_fake_python_terminates_without_resolving_itself(tmp_path):
    from tests.test_setup_mirrors import _stub_tools
    binary_dir = _stub_tools(tmp_path, True, False, tmp_path / 'calls')
    interpreter = Path(binary_dir) / 'python3'
    assert interpreter.read_text().startswith('#!/bin/bash\n')
    result = subprocess.run([str(interpreter), '--version'],
                            env={**os.environ, 'PATH': binary_dir}, capture_output=True, text=True, timeout=2)
    assert result.returncode == 0 and result.stdout.strip() == 'Python 3.11.0'
    result = subprocess.run([str(interpreter), '-c', 'urlopen'],
                            env={**os.environ, 'PATH': binary_dir}, capture_output=True, text=True, timeout=2)
    assert result.returncode == 1


def test_timeout_stops_the_child_process_group(tmp_path):
    from tests.test_setup_mirrors import _run
    marker = tmp_path / 'child.pid'
    block = f'sleep 30 &\nprintf "%s" "$!" > {shlex.quote(str(marker))}\nwait\n'
    with pytest.raises(subprocess.TimeoutExpired):
        _run(block, tmp_path, '/usr/bin:/bin', timeout=0.5)
    child = int(marker.read_text())
    result = subprocess.run(['ps', '-p', str(child), '-o', 'stat='], capture_output=True, text=True, timeout=2)
    assert not result.stdout.strip() or result.stdout.strip().startswith('Z'), result.stdout
