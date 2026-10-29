"""Adversarial boundaries: hostile input stays a per-source failure, never a Web crash."""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "web")]
from easel.trends import management, service as service_module
from easel.trends.protocol import MAX_MANAGEMENT_BYTES, CollectorError, decode_payload, safe_json, utc_now, validate_payload
from easel.trends.runner import collect
from easel.trends.service import TrendService
from easel.trends.sources import ConfigError, display_label, load_sources
from easel.trends.rss import parse_feed


def payload():
    return {"version": 1, "fetched_at": utc_now(), "items": [{"title": "safe result"}]}


def config(root, rows):
    path = root / "config/trend-sources.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"version": 1, "include_builtin": False, "sources": rows}), encoding="utf-8")
    return path


def script_source(root, body, **kwargs):
    path = root / "collector.py"
    path.write_text(body, encoding="utf-8")
    config(root, [{"id": "safe", "label": "安全来源 · Python", "type": "python", "script": "../collector.py", **kwargs}])
    return load_sources(root, {})[0]


@pytest.mark.parametrize("raw", [b"[" * 10000 + b"]" * 10000, b'{"version":1,"version":2}',
                                 b'{"n":NaN}', b'{"n":Infinity}', b'{"n":1e9999}',
                                 b'{"n":' + b'9' * 100 + b'}'])
def test_hostile_json_is_rejected_before_use(raw):
    with pytest.raises(CollectorError, match="invalid_response"):
        safe_json(raw)


@pytest.mark.parametrize("field,value", [("title", "\ud800"), ("id", "\udfff"), ("title", "a\x00b"),
                                         ("url", "https://example.com/\\@evil.com"),
                                         ("url", "https://example.com/" + "x" * 8192),
                                         ("heat", {"text": "x" * 129}), ("heat", {"unit": "x" * 33}),
                                         ("heat", {"value": 2 ** 60})])
def test_bad_field_values_do_not_raise_raw_python_errors(field, value):
    data = payload()
    data["items"][0][field] = value
    with pytest.raises(CollectorError):
        validate_payload(data)


def test_xml_depth_is_bounded():
    xml = '<rss><channel>' + '<x>' * 50 + '</x>' * 50 + '</channel></rss>'
    with pytest.raises(CollectorError):
        parse_feed(xml.encode(), "https://example.com/rss")


def test_invalid_source_is_isolated_and_suffix_is_hidden(tmp_path):
    config(tmp_path, [{"id": "bad", "label": "bad", "type": "shell"},
                      {"id": "good", "label": "资讯 · HTTP", "type": "http", "url": "https://example.com/"}])
    warnings = []
    sources = load_sources(tmp_path, {}, warnings=warnings)
    assert len(sources) == 1 and sources[0].id == "good" and warnings
    assert sources[0].public()["label"] == "资讯"
    assert display_label("my python tutorial") == "my python tutorial"


def test_broken_unicode_in_skipped_rows_cannot_break_management_json(tmp_path):
    config(tmp_path, [{"id": "broken", "label": "\ud800", "type": "http", "url": "https://example.com"},
                      {"id": "\udfff", "label": "bad id", "type": "http", "url": "https://example.com"}])
    response = management.describe(tmp_path, {})
    json.dumps(response, ensure_ascii=False).encode("utf-8")
    assert response["warnings"]
    management.update(tmp_path, {}, {"action": "add", "type": "rss", "label": "新订阅", "url": "https://example.com/feed"})
    management.update(tmp_path, {}, {"action": "delete", "id": "broken"})
    with pytest.raises(ConfigError):
        management.update(tmp_path, {}, {"action": "toggle", "id": "\udfff", "enabled": False})


def test_worker_does_not_inherit_unrelated_secrets(tmp_path):
    data = json.dumps(payload())
    source = script_source(tmp_path, f'''import os
assert 'EASEL_DIRECT_API_KEY' not in os.environ
assert 'UNRELATED_SECRET' not in os.environ
assert os.environ['LOCAL_TOKEN'] == 'needed-token'
print({data!r})
''', env={"LOCAL_TOKEN": "${SOURCE_TOKEN}"})
    result = collect(source, {**os.environ, "EASEL_DIRECT_API_KEY": "must-not-leak", "UNRELATED_SECRET": "secret",
                              "SOURCE_TOKEN": "needed-token"})
    assert result["items"][0]["title"] == "safe result"


def test_memory_exhaustion_is_contained_and_next_collector_still_works(tmp_path):
    source = script_source(tmp_path, "import time\nallocated = bytearray(128 * 1024 * 1024)\ntime.sleep(2)\n", memory_mb=64, timeout_seconds=3)
    start = time.monotonic()
    with pytest.raises(CollectorError) as caught:
        collect(source, dict(os.environ))
    assert caught.value.code in {"resource_limit", "process_failed"}
    assert time.monotonic() - start < 8
    source = script_source(tmp_path, f"print({json.dumps(payload())!r})")
    assert collect(source, dict(os.environ))["items"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object process-tree boundary")
def test_descendant_process_is_killed_even_after_script_exits(tmp_path):
    pid_path = tmp_path / "child.pid"
    source = script_source(tmp_path, f'''import subprocess, sys
from pathlib import Path
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path({str(pid_path)!r}).write_text(str(p.pid))
print({json.dumps(payload())!r})
''')
    collect(source, dict(os.environ))
    pid = int(pid_path.read_text())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    for _ in range(20):
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            if code.value != 259:
                return
        finally:
            kernel.CloseHandle(handle)
        time.sleep(0.05)
    pytest.fail("collector descendant survived its Job Object")


def test_global_concurrency_and_queue_wait_are_bounded(tmp_path, monkeypatch):
    source = script_source(tmp_path, "pass")
    active, peak = [0], [0]
    lock = threading.Lock()

    def slow(*args):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.3)
        with lock:
            active[0] -= 1
        return payload()

    monkeypatch.setattr(service_module, "collect", slow)
    service = TrendService()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: service.get(replace(source, id=f"source-{i}"), {}), range(8)))
    assert peak[0] <= 4
    assert any(result["error"] and result["error"]["code"] == "busy" for result in results)
    assert any(result["ok"] for result in results)


def test_management_is_atomic_and_cannot_register_arbitrary_commands(tmp_path, monkeypatch):
    config(tmp_path, [])
    added = management.update(tmp_path, {}, {"action": "add", "type": "rss", "label": "订阅 · Atom", "url": "https://example.com/feed"})
    assert management.describe(tmp_path, {})["sources"][-1]["label"] == "订阅"
    with pytest.raises(ConfigError):
        management.update(tmp_path, {}, {"action": "add", "type": "python", "label": "bad", "script": "../evil.py", "python": "cmd.exe"})
    before = (tmp_path / "config/trend-sources.json").read_bytes()
    monkeypatch.setattr(management.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        management.update(tmp_path, {}, {"action": "toggle", "id": added["id"], "enabled": False})
    assert (tmp_path / "config/trend-sources.json").read_bytes() == before


def test_management_toggle_delete_and_preapproved_scripts(tmp_path):
    config(tmp_path, [])
    script = tmp_path / "config/approved.py"
    script.write_text("print('approved')")
    (tmp_path / "config/trend-scripts.json").write_text(json.dumps({"version": 1, "scripts": [
        {"id": "approved", "label": "已登记", "script": "approved.py"}]}), encoding="utf-8")
    result = management.update(tmp_path, {}, {"action": "add", "type": "python", "label": "采集", "script_id": "approved"})
    assert load_sources(tmp_path, {})[0].options["script"] == str(script)
    management.update(tmp_path, {}, {"action": "toggle", "id": result["id"], "enabled": False})
    assert load_sources(tmp_path, {}) == []
    management.update(tmp_path, {}, {"action": "toggle", "id": result["id"], "enabled": True})
    assert load_sources(tmp_path, {})
    management.update(tmp_path, {}, {"action": "delete", "id": result["id"]})
    assert load_sources(tmp_path, {}) == []


def test_configuration_writers_are_serialized_across_processes(tmp_path):
    config(tmp_path, [])
    code = '''import sys
from pathlib import Path
from easel.trends.management import update
for i in range(3):
    update(Path(sys.argv[1]), {}, {"action":"add", "type":"rss", "label":"feed", "url":"https://example.com/feed"})
'''
    processes = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", code, str(tmp_path)], cwd=ROOT,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for _ in range(4)]
    for process in processes:
        _, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr.decode("utf-8", "replace")
    assert len(load_sources(tmp_path, {})) == 12


def test_manager_endpoints_reject_remote_clients_even_with_forged_origin(tmp_path, monkeypatch):
    import app as web
    from fastapi.testclient import TestClient
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    with TestClient(web.app, base_url="http://127.0.0.1:7860", client=("192.0.2.1", 50000),
                    headers={"Origin": "http://127.0.0.1:7860"}) as client:
        assert client.get("/api/trends/manage").status_code == 403
        assert client.post("/api/trends/manage", json={"action": "add"}).status_code == 403
    with TestClient(web.app, base_url="http://127.0.0.1:7860", client=("127.0.0.1", 50000)) as client:
        assert client.post("/api/trends/manage", content='x' * (MAX_MANAGEMENT_BYTES + 1)).status_code == 413
        assert client.post("/api/trends/manage", content='{"action":"add","action":"delete"}').status_code == 400
        added = client.post("/api/trends/manage", json={"action": "add", "type": "rss", "label": "订阅", "url": "https://example.com/feed"})
        assert added.status_code == 200
        assert any(source["id"] == added.json()["id"] for source in client.get("/api/trends/sources").json()["sources"])
