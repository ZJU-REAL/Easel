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
    monkeypatch.setattr(ss,'workspace_dir',lambda:expected)
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
    def fail():raise OSError('failed copy')
    monkeypatch.setattr(module,'synchronize_skills',fail)
    assert module.main([])==1
