"""POSIX resource differences and real per-OS cleanup; no external network."""
import json
import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from easel.trends import environment, process_limits
from easel.trends.protocol import CollectorError, utc_now
from easel.trends.runner import collect
from easel.trends.sources import load_sources


def test_unix_proxy_aliases_respect_explicit_empty_values(monkeypatch):
    monkeypatch.setattr(environment,"os",SimpleNamespace(name="posix"))
    result=environment.proxy_environment({"http_proxy":"","HTTP_PROXY":"http://upper.invalid:1",
        "EASEL_PROXY":"http://fallback.invalid:2"},"localhost")
    assert result["http_proxy"]=="" and "HTTP_PROXY" not in result
    assert result["https_proxy"]=="http://fallback.invalid:2"


def test_windows_empty_alias_does_not_erase_configured_proxy(monkeypatch):
    monkeypatch.setattr(environment,"os",SimpleNamespace(name="nt"))
    result=environment.proxy_environment({"http_proxy":"","HTTP_PROXY":"http://configured.invalid:1"},"localhost")
    assert result["http_proxy"]=="http://configured.invalid:1"


def test_macos_skips_unsupported_as_limit_and_preserves_inherited_caps(monkeypatch):
    calls=[]
    resource=SimpleNamespace(RLIMIT_AS=1,RLIMIT_CPU=2,RLIMIT_CORE=3,RLIMIT_FSIZE=4,RLIM_INFINITY=-1,
        getrlimit=lambda kind:(1,2) if kind==2 else(-1,-1),setrlimit=lambda kind,value:calls.append((kind,value)))
    monkeypatch.setitem(sys.modules,"resource",resource)
    monkeypatch.setattr(process_limits,"os",SimpleNamespace(name="posix"))
    monkeypatch.setattr(process_limits,"sys",SimpleNamespace(platform="darwin"))
    process_limits.restrict_current_process(256,20)
    assert all(kind!=resource.RLIMIT_AS for kind,_ in calls)
    assert (resource.RLIMIT_CPU,(2,2)) in calls


def test_macos_group_rss_guard_contains_memory_growth(monkeypatch):
    monkeypatch.setattr(process_limits,"os",SimpleNamespace(name="posix"))
    monkeypatch.setattr(process_limits,"sys",SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(process_limits.subprocess,"run",lambda *a,**k:SimpleNamespace(stdout="123 50000\n123 50000\n999 10\n"))
    with pytest.raises(CollectorError,match="resource_limit"):
        process_limits.ProcessLimits(64,5).check(SimpleNamespace(pid=123))


@pytest.mark.skipif(os.name=="nt",reason="POSIX process groups")
def test_posix_descendants_are_reaped_after_script_exit(tmp_path):
    pidfile=tmp_path/"child pid.txt"
    payload={"version":1,"fetched_at":utc_now(),"items":[{"title":"POSIX 清理"}]}
    code=f'''import subprocess,sys
from pathlib import Path
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path({str(pidfile)!r}).write_text(str(p.pid))
print({json.dumps(payload)!r})
'''
    script=tmp_path/"中文 collector with spaces.py";script.write_text(code,encoding="utf-8")
    cfg=tmp_path/"config";cfg.mkdir()
    (cfg/"trend-sources.json").write_text(json.dumps({"version":1,"include_builtin":False,"sources":[
        {"id":"posix","label":"POSIX","type":"python","script":str(script)}]}),encoding="utf-8")
    collect(load_sources(tmp_path,{})[0],dict(os.environ))
    pid=int(pidfile.read_text())
    try:
        for _ in range(30):
            result=subprocess.run(["ps","-p",str(pid),"-o","stat="],capture_output=True,text=True,timeout=2)
            if result.returncode or not result.stdout.strip() or result.stdout.strip().startswith("Z"):
                return
            time.sleep(.05)
        pytest.fail("collector descendant survived process-group cleanup")
    finally:
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
