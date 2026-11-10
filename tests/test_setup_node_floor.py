"""Installer version boundaries, including OpenClaw's stricter 2026.10.8 patch floor."""
import os
import shutil
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')


@pytest.mark.skipif(os.name == 'nt' or not BASH, reason='POSIX installer; PowerShell has separate checks')
@pytest.mark.parametrize('version,expected', [
    ('24.21.0', False), ('24.22.0', False), ('24.22.1', True), ('24.23.0', True),
    ('25.3.0', False), ('26.1.0', False), ('26.12.0', False), ('26.12.1', True), ('27.0.0', True),
])
def test_openclaw_installer_floor_checks_patch_version(version, expected):
    source = (ROOT / 'setup.sh').read_text()
    function = source[source.index('node_version_ok()'):source.index('NODE_OK=false')]
    result = subprocess.run([BASH, '-c', 'CHAT_MODE=http\n' + function + '\nnode_version_ok "$@"',
                             'check', *version.split('.')], timeout=5)
    assert (result.returncode == 0) is expected


@pytest.mark.skipif(os.name == 'nt' or not BASH, reason='POSIX installer')
@pytest.mark.parametrize('version,expected', [('20.18.0', False), ('20.19.0', True), ('22.11.0', False), ('22.12.0', True), ('24.21.0', True)])
def test_web_only_install_keeps_its_own_node_floor(version, expected):
    source = (ROOT / 'setup.sh').read_text()
    function = source[source.index('node_version_ok()'):source.index('NODE_OK=false')]
    result = subprocess.run([BASH, '-c', 'CHAT_MODE=api\n' + function + '\nnode_version_ok "$@"',
                             'check', *version.split('.')], timeout=5)
    assert (result.returncode == 0) is expected


@pytest.mark.parametrize('version,patched,expected', [('24.21.0', False, True), ('24.21.0', True, False),
    ('24.22.0', True, False), ('24.22.1', True, True), ('26.12.0', True, False), ('26.12.1', True, True)])
def test_doctor_keeps_older_release_compatibility_and_checks_stricter_patch(monkeypatch, version, patched, expected):
    from easel.commands import doctor
    monkeypatch.setattr(doctor.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='v'+version))
    assert doctor._node_version_ok(True, patched) is expected
