"""Content comparison and non-destructive synchronization in isolated workspaces."""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

import pytest
from easel import skills_sync as ss

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    repo, ws = tmp_path/'repo', tmp_path/'ws'
    for path in (repo/'skills/builtin/demo',repo/'skills/shared',ws/'skills/demo',ws/'shared'):
        path.mkdir(parents=True)
    source=repo/'skills/builtin/demo/SKILL.md'
    target=ws/'skills/demo/SKILL.md'
    source.write_text('version one',encoding='utf-8')
    target.write_text('version one',encoding='utf-8')
    monkeypatch.setattr(ss,'PROJECT_ROOT',repo)
    monkeypatch.setattr(ss,'agent_workspace',lambda:ws)
    return repo,ws,source,target


def test_identical_contents_do_not_depend_on_mtime(workspace):
    _,_,source,target=workspace
    os.utime(source,(2000,2000));os.utime(target,(100,100))
    assert ss.skills_sync_state()[0] is True


@pytest.mark.parametrize('missing',[False,True])
def test_newer_unrelated_file_cannot_hide_old_or_missing_skill(workspace,missing):
    _,ws,source,target=workspace
    source.write_text('version two',encoding='utf-8')
    if missing:target.unlink()
    else:os.utime(target,(source.stat().st_atime,source.stat().st_mtime))
    other=ws/'skills/custom.txt'
    other.write_text('newer',encoding='utf-8');os.utime(other,(2_000_000_000,2_000_000_000))
    assert ss.skills_sync_state()[0] is False


def test_missing_workspace_is_not_synced(workspace):
    _,ws,_,_=workspace
    shutil.rmtree(ws/'skills')
    ok,detail=ss.skills_sync_state()
    assert not ok and '为空或不存在' in detail


def test_deep_script_and_shared_changes_are_checked(workspace):
    repo,ws,_,_=workspace
    (repo/'skills/builtin/demo/scripts').mkdir()
    (ws/'skills/demo/scripts').mkdir()
    (repo/'skills/builtin/demo/scripts/run.py').write_text('new',encoding='utf-8')
    (ws/'skills/demo/scripts/run.py').write_text('old',encoding='utf-8')
    (repo/'skills/shared/rules.md').write_text('current',encoding='utf-8')
    assert not ss.skills_sync_state()[0]
    assert ss.synchronize_skills()==2
    assert ss.skills_sync_state()[0]


def test_sync_keeps_memory_profiles_outputs_and_custom_files(workspace):
    repo,ws,source,target=workspace
    source.write_text('current',encoding='utf-8')
    preserved={ws/'MEMORY.md':'private memory',ws/'USER.md':'user',ws/'easel-profiles/new.md':'profile',
               ws/'outputs/new.txt':'new output',ws/'skills/demo/custom.md':'local customization'}
    for path,content in preserved.items():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
    assert ss.synchronize_skills()==1
    assert target.read_text()=='current'
    assert all(path.read_text()==value for path,value in preserved.items())
    assert ss.synchronize_skills()==0


def test_broken_or_external_target_link_is_not_written(workspace,tmp_path):
    repo,ws,source,target=workspace
    target.unlink()
    outside=tmp_path/'private.txt';outside.write_text('private',encoding='utf-8')
    try:target.symlink_to(outside)
    except OSError:pytest.skip('symlink unavailable')
    assert not ss.skills_sync_state()[0]
    with pytest.raises(ValueError):ss.synchronize_skills()
    assert outside.read_text()=='private'


def test_direct_source_link_is_already_current(workspace):
    repo,ws,source,target=workspace
    shutil.rmtree(ws/'skills')
    try:(ws/'skills').symlink_to(repo/'skills/builtin',target_is_directory=True)
    except OSError:pytest.skip('symlink unavailable')
    source.write_text('current',encoding='utf-8')
    assert ss.skills_sync_state()[0] and ss.synchronize_skills()==0
    assert source.exists()


def test_permission_failure_does_not_report_freshness(workspace,monkeypatch):
    def denied(path):raise PermissionError('denied')
    monkeypatch.setattr(ss,'_digest',denied)
    assert not ss.skills_sync_state()[0]


def test_workspace_resolution_uses_existing_authoritative_resolver(monkeypatch,tmp_path):
    monkeypatch.delenv('EASEL_OPENCLAW_WORKSPACE',raising=False)
    expected=tmp_path/'configured'
    monkeypatch.setattr(ss,'workspace_dir',lambda **kwargs:expected)
    assert ss.agent_workspace()==expected


def test_existing_windows_copy_is_preserved(workspace,monkeypatch):
    repo,ws,_,_=workspace
    (repo/'profiles').mkdir()
    old=ws/'easel-profiles';old.mkdir();(old/'new.md').write_text('not synchronized user data')
    monkeypatch.setattr(ss,'WINDOWS',True)
    monkeypatch.setattr(ss.shutil,'which',lambda *a:pytest.fail('must not launch a repair for existing data'))
    assert ss.ensure_workspace_links()
    assert (old/'new.md').read_text()=='not synchronized user data'


@pytest.mark.skipif(os.name!='nt',reason='Actual Windows junction creation')
def test_missing_windows_junction_is_created_without_losing_data(workspace):
    repo,ws,_,_=workspace
    (repo/'profiles').mkdir();(repo/'profiles/new.md').write_text('current')
    assert ss.ensure_workspace_links()==[]
    assert (ws/'easel-profiles').samefile(repo/'profiles')
    assert (repo/'profiles/new.md').read_text()=='current'


def load_cli():
    spec=importlib.util.spec_from_file_location('sync_if_stale_test',ROOT/'scripts/sync_if_stale.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_check_only_and_invalid_flags_do_not_write(workspace,monkeypatch):
    module=load_cli()
    monkeypatch.setattr(module,'synchronize_skills',lambda:pytest.fail('check must be read only'))
    monkeypatch.setattr(module,'ensure_workspace_links',lambda:pytest.fail('check must not repair links'))
    assert module.main(['--check'])==0
    with pytest.raises(SystemExit) as caught:module.main(['--checks'])
    assert caught.value.code==2


def test_copy_failure_is_not_hidden_by_fresh_files(workspace,monkeypatch):
    module=load_cli()
    workspace[2].write_text('changed')
    def fail(*args):raise OSError('failed copy')
    monkeypatch.setattr(module,'synchronize_skills',fail)
    assert module.main([])==1


@pytest.mark.parametrize('relative', [
    'skills/builtin/demo/references/nested/rules.md',
    'skills/builtin/demo/scripts/nested/run.py',
    'skills/shared/scripts/nested/run.py',
])
@pytest.mark.parametrize('missing', [False, True])
def test_nested_resources_are_compared_by_content_and_synced(workspace, relative, missing):
    repo, ws, _, _ = workspace
    source = repo / relative
    destination = ws / relative.removeprefix('skills/').replace('builtin/', 'skills/', 1)
    source.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'new rules')
    if not missing:
        destination.write_bytes(b'old rules')
        os.utime(destination, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns))
    # A newer unrelated file must never mask this resource's equal-mtime content change.
    other = ws / 'skills' / 'custom.md'
    other.write_text('local')
    os.utime(other, (2_000_000_000, 2_000_000_000))
    ok, detail = ss.skills_sync_state()
    assert not ok
    assert str(ws) in detail and str(Path(relative)) in detail
    assert ('副本缺失' if missing else '内容不同') in detail
    assert ss.synchronize_skills() == 1
    assert destination.read_bytes() == source.read_bytes()
    assert ss.skills_sync_state()[0]
    assert ss.synchronize_skills() == 0


def test_check_reports_stale_without_writing(workspace, monkeypatch, capsys):
    module = load_cli()
    workspace[2].write_text('changed')
    monkeypatch.setattr(module, 'synchronize_skills', lambda *a: pytest.fail('check wrote files'))
    monkeypatch.setattr(module, 'ensure_workspace_links', lambda *a: pytest.fail('check repaired links'))
    assert module.main(['--check']) == 1
    assert '未确认同步' in capsys.readouterr().out
    assert workspace[3].read_text() == 'version one'


@pytest.mark.parametrize('stale', [False, True])
def test_cli_pins_one_workspace_and_skips_fresh_copy(workspace, monkeypatch, capsys, stale):
    module = load_cli()
    if stale:
        workspace[2].write_text('version two')
    calls = []
    def resolve():
        calls.append(True)
        assert len(calls) == 1, 'one sync operation must not resolve different workspaces'
        return workspace[1]
    monkeypatch.setattr(module, 'agent_workspace', resolve)
    monkeypatch.setattr(ss, 'agent_workspace', lambda: pytest.fail('workspace was resolved again'))
    if not stale:
        monkeypatch.setattr(module, 'synchronize_skills', lambda *a: pytest.fail('fresh files copied'))
    assert module.main([]) == 0
    output = capsys.readouterr().out
    assert ('同步完成' if stale else '已是最新') in output
    assert f'更新 {int(stale)} 个文件' in output
    assert str(workspace[1]) in output


def test_cli_resolution_failure_is_reported(workspace, monkeypatch, capsys):
    module = load_cli()
    def fail():
        raise ValueError('bad workspace')
    monkeypatch.setattr(module, 'agent_workspace', fail)
    assert module.main(['--check']) == 1
    assert '无法解析 workspace' in capsys.readouterr().err


@pytest.fixture
def doctor_ready(workspace, monkeypatch):
    from easel import harnesses, local_agents
    from easel.commands import doctor

    repo, ws, source, _ = workspace
    for relative in ('web/frontend/dist/index.html', 'agents/openclaw.json5',
                     'scripts/gateway.ps1' if os.name == 'nt' else 'scripts/gateway.sh'):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(doctor, 'PROJECT_ROOT', repo)
    monkeypatch.setattr(doctor, 'read_settings', lambda *a: {})
    monkeypatch.setattr(harnesses, 'settings', lambda *a: {'runtime': 'openclaw'})
    monkeypatch.setattr(local_agents, 'summarize_local_agents', lambda: {'installedCount': 0})
    monkeypatch.setattr(doctor.shutil, 'which', lambda cmd: '/fake/' + cmd)
    monkeypatch.setattr(doctor, '_openclaw_version', lambda: (2026, 9, 5))
    for name in ('_node_version_ok', '_module_available', '_venv_available',
                 '_chromium_available', '_env_key_valid', '_gateway_healthy'):
        monkeypatch.setattr(doctor, name, lambda *a: True)
    monkeypatch.setattr(doctor, '_primary_model_routable', lambda: (True, ''))
    for name in ('_tool_loop_policy', '_context_budget_policy'):
        monkeypatch.setattr(doctor, name, lambda: [])
    return doctor


@pytest.mark.parametrize('stale', [False, True])
def test_doctor_distinguishes_presence_and_freshness(workspace, doctor_ready, capsys, stale):
    doctor = doctor_ready
    repo, ws, source, _ = workspace
    if stale:
        source.write_text('version two')
    assert doctor.cmd_doctor(None) == int(stale)
    output = capsys.readouterr().out
    presence = next(line for line in output.splitlines() if 'Skills synced' in line)
    freshness = next(line for line in output.splitlines() if 'Skills up-to-date' in line)
    assert 'OK' in presence
    assert ('FAIL' if stale else 'OK') in freshness
    assert str(ws) in output
    if stale:
        assert 'skills' in output and 'SKILL.md' in output
        assert 'python scripts/sync_if_stale.py' in output
        assert load_cli().main([]) == 0
        assert doctor.cmd_doctor(None) == 0
    else:
        assert '1 个现有仓库文件' in output


@pytest.mark.parametrize('failure', ['missing', 'unresolvable'])
def test_doctor_reports_workspace_failures(workspace, doctor_ready, monkeypatch, capsys, failure):
    if failure == 'missing':
        shutil.rmtree(workspace[1] / 'skills')
    else:
        def fail():
            raise ValueError('bad workspace')
        monkeypatch.setattr(ss, 'agent_workspace', fail)
    assert doctor_ready.cmd_doctor(None) == 1
    output = capsys.readouterr().out
    for label in ('Skills synced', 'Skills up-to-date'):
        assert 'FAIL' in next(line for line in output.splitlines() if label in line)
    assert 'python scripts/sync_if_stale.py' in output


@pytest.mark.parametrize('runtime', ['api', 'codex', 'opencode', 'acp'])
def test_other_runtimes_never_probe_openclaw(workspace, doctor_ready, monkeypatch, capsys, runtime):
    from easel import harnesses
    monkeypatch.setattr(harnesses, 'settings', lambda *a: {'runtime': runtime})
    monkeypatch.setattr(harnesses, 'describe', lambda *a: {'installed': True, 'install_hint': ''})
    monkeypatch.setattr(doctor_ready, 'api_config', lambda *a: ('local', 'test', ''))
    def forbidden(*a):
        pytest.fail('other runtimes must not resolve or check OpenClaw workspace')
    monkeypatch.setattr(ss, 'agent_workspace', forbidden)
    monkeypatch.setattr(doctor_ready, '_skills_synced', forbidden)
    monkeypatch.setattr(doctor_ready, '_skills_fresh', forbidden)
    assert doctor_ready.cmd_doctor(None) == 0
    assert 'Skills up-to-date' not in capsys.readouterr().out


@pytest.mark.parametrize('operation', ['copy', 'replace'])
def test_failed_atomic_copy_preserves_old_destination(workspace, monkeypatch, operation):
    _, ws, source, target = workspace
    source.write_text('version two')
    if operation == 'copy':
        def fail(source, temporary):
            temporary.write_text('partial copy')
            raise OSError('copy failed')
        monkeypatch.setattr(ss.shutil, 'copy2', fail)
    else:
        def fail(*a):
            raise PermissionError('replace denied')
        monkeypatch.setattr(ss.os, 'replace', fail)
    with pytest.raises(OSError):
        ss.synchronize_skills()
    assert target.read_text() == 'version one'
    assert not list(ws.rglob('.easel-sync-*'))
    assert not ss.skills_sync_state()[0]


def test_all_destinations_are_validated_before_any_copy(workspace, tmp_path):
    repo, ws, source, target = workspace
    source.write_text('version two')
    extra = repo / 'skills/shared/rules.md'
    extra.write_text('new rules')
    outside = tmp_path / 'private.md'
    outside.write_text('private')
    try:
        (ws / 'shared/rules.md').symlink_to(outside)
    except OSError:
        pytest.skip('symlink unavailable')
    with pytest.raises(ValueError):
        ss.synchronize_skills()
    assert target.read_text() == 'version one'
    assert outside.read_text() == 'private'


def test_source_symlink_is_not_followed(workspace, tmp_path):
    repo, ws, _, _ = workspace
    outside = tmp_path / 'private'
    outside.mkdir()
    (outside / 'private.md').write_text('private')
    link = repo / 'skills/builtin/demo/references'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink unavailable')
    assert not ss.skills_sync_state()[0]
    with pytest.raises(ValueError):
        ss.synchronize_skills()
    assert not (ws / 'skills/demo/references').exists()


@pytest.mark.parametrize('failure', ['verification', 'links'])
def test_cli_does_not_report_success_after_incomplete_sync(workspace, monkeypatch, capsys, failure):
    module = load_cli()
    workspace[2].write_text('version two')
    if failure == 'verification':
        monkeypatch.setattr(module, 'synchronize_skills', lambda *a: 0)
    else:
        monkeypatch.setattr(module, 'ensure_workspace_links', lambda *a: ['outputs 存在不同的副本'])
    assert module.main([]) == 1
    output = capsys.readouterr()
    assert '未完成全部同步检查' in output.err
    assert '同步完成' not in output.out


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows junction validation')
@pytest.mark.parametrize('relative', ['skills/shared', 'skills/builtin/demo/references/nested'])
def test_source_junction_cannot_import_external_files(workspace, tmp_path, relative):
    import subprocess
    repo, ws, source, target = workspace
    outside = tmp_path / 'private'
    outside.mkdir()
    (outside / 'private.md').write_text('private')
    junction = repo / relative
    if junction.exists():
        junction.rmdir()  # Only the empty fixture's shared directory.
    junction.parent.mkdir(parents=True, exist_ok=True)
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                    '$ErrorActionPreference="Stop"; New-Item -ItemType Junction -Path '
                    + quote(junction) + ' -Value ' + quote(outside) + ' | Out-Null'], check=True)
    ok, detail = ss.skills_sync_state()
    assert not ok and '无法完整校验' in detail
    source.write_text('version two')
    with pytest.raises(ValueError):
        ss.synchronize_skills()
    assert target.read_text() == 'version one'
    assert not list((ws / 'skills').rglob('private.md'))
    assert (outside / 'private.md').read_text() == 'private'
