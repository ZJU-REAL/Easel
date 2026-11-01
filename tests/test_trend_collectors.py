"""Real subprocess/loopback HTTP collection, contract failures, cache and Web integration."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))
from easel.trends import service as service_module
from easel.trends.protocol import MAX_BYTES, CollectorError, decode_payload, utc_now, validate_payload
from easel.trends.runner import collect
from easel.trends.service import TrendService
from easel.trends.sources import ConfigError, load_sources


def payload(items=None):
    return {"version": 1, "fetched_at": utc_now(),
            "items": items if items is not None else [{"title": "测试热点", "heat": {"value": 42}}]}


def config(tmp_path, rows, **extra):
    path = tmp_path / "config" / "trend-sources.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"version": 1, "include_builtin": False, "sources": rows, **extra}), encoding="utf-8")
    return path


def python_source(tmp_path, body, **extra):
    script = tmp_path / "collector with spaces.py"
    script.write_text(body, encoding="utf-8")
    config(tmp_path, [{"id": "local", "label": "本地热点", "type": "python",
                       "script": "../" + script.name, **extra}])
    return load_sources(tmp_path, {})[0]


def test_contract_heat_ids_and_deduplication():
    result = validate_payload(payload([{"title": "A", "url": "https://example.com/1", "heat": {"value": 42}},
                                       {"title": "B", "url": "https://example.com/1"},
                                       {"id": "custom", "title": "C", "heat": {"text": "1万", "unit": "阅读"}}]))
    assert len(result["items"]) == 2
    assert [item["hot"] for item in result["items"]] == ["42", "1万"]
    assert result["items"][0]["id"] == validate_payload(payload([{"title": "A", "url": "https://example.com/1"}]))["items"][0]["id"]


@pytest.mark.parametrize("change", [
    {"version": True}, {"version": 2}, {"fetched_at": "2026-10-29T00:00:00"}, {"fetched_at": "invalid"},
    {"items": {}}, {"items": [{}]}, {"items": [{"title": " "}]},
    {"items": [{"title": "x", "url": "javascript:alert(1)"}]},
    {"items": [{"title": "x", "url": "https://user:secret@example.com/"}]},
    {"items": [{"title": "x", "published_at": "yesterday"}]},
    {"items": [{"title": "x", "heat": []}]}, {"items": [{"title": "x", "heat": None}]},
    {"items": [{"title": "x", "heat": {"value": True}}]},
    {"items": [{"title": "x", "heat": {"value": float("nan")}}]},
    {"items": [{"title": "x", "heat": {"text": 1}}]},
    {"items": [{"title": "x", "id": 1}]}, {"items": [{"title": "x"}] * 501},
])
def test_contract_rejects_invalid_defined_fields(change):
    with pytest.raises(CollectorError, match="invalid_response"):
        validate_payload({**payload(), **change})


@pytest.mark.parametrize("raw,code", [(b"not JSON", "invalid_response"),
                                     (b"x" * (MAX_BYTES + 1), "output_too_large"), (b"\xff", "invalid_response")],
                         ids=["not-json", "oversized", "invalid-utf8"])
def test_invalid_wire_bytes(raw, code):
    with pytest.raises(CollectorError, match=code):
        decode_payload(raw)


def test_config_override_disable_paths_and_missing_file(tmp_path):
    config(tmp_path, [{"id": "weibo", "enabled": False},
                      {"id": "douyin", "label": "替换抖音", "type": "python", "script": "custom.py"}], include_builtin=True)
    registry = {s.id: s for s in load_sources(tmp_path, {})}
    assert "weibo" not in registry and "zhihu" in registry
    assert registry["douyin"].label == "替换抖音"
    assert registry["douyin"].options["script"] == str(tmp_path / "config" / "custom.py")
    with pytest.raises(ConfigError):
        load_sources(tmp_path, {"EASEL_TREND_SOURCES_CONFIG": "missing.json"})


@pytest.mark.parametrize("rows,extra", [
    ([{"id": "x", "label": "x", "type": "shell"}], {}),
    ([{"id": "x", "enabled": False}, {"id": "x", "enabled": False}], {}),
    ([{"id": "x", "label": "x", "type": "http", "url": "file:///tmp/x"}], {}),
    ([{"id": "x", "label": "x", "type": "http", "url": "https://example.com", "method": "DELETE"}], {}),
    ([{"id": "x", "label": "x", "type": "http", "url": "https://example.com", "body": {}}], {}),
    ([{"id": "x", "label": "x", "type": "python", "script": "x.py", "args": "--x"}], {}),
    ([{"id": "x", "label": "x", "type": "python", "script": "x.py", "timeout_seconds": 0}], {}),
    ([{"id": "x", "label": "x", "type": "python", "script": "x.py", "max_stale_seconds": 1}], {}),
    ([], {"version": 2}), ([], {"include_builtin": "yes"}),
])
def test_invalid_local_configuration(tmp_path, rows, extra):
    config(tmp_path, rows, **extra)
    with pytest.raises(ConfigError):
        load_sources(tmp_path, {})


def test_python_utf8_cwd_arguments_and_environment(tmp_path):
    source = python_source(tmp_path, '''import json, os, sys
from pathlib import Path
assert Path.cwd() == Path(__file__).parent
assert sys.argv[1:] == ['literal; & $(command)', '中文']
assert os.environ['TOKEN'] == 'example-secret'
assert os.environ['EASEL_TREND_SOURCE_ID'] == 'local'
print('diagnostic only', file=sys.stderr)
from datetime import datetime, timezone
print(json.dumps({'version': 1, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'items': [{'title': '中文热点'}]}, ensure_ascii=False))
''', args=["literal; & $(command)", "中文"], env={"TOKEN": "${EXAMPLE_TOKEN}"})
    assert collect(source, {**os.environ, "EXAMPLE_TOKEN": "example-secret"})["items"][0]["title"] == "中文热点"


@pytest.mark.parametrize("body,code", [
    ("import time; time.sleep(10)", "timeout"),
    ("import sys; print('secret', file=sys.stderr); sys.exit(4)", "process_failed"),
    ("print('debug text before JSON')", "invalid_response"),
    ("import sys; sys.stdout.write('x' * (3 * 1024 * 1024))", "output_too_large"),
    ("import sys; sys.stderr.write('x' * (3 * 1024 * 1024))", "output_too_large"),
])
def test_python_failures_bounded_and_classified(tmp_path, body, code):
    source = python_source(tmp_path, body, timeout_seconds=0.5 if code == "timeout" else 5)
    started = time.monotonic()
    with pytest.raises(CollectorError, match=code):
        collect(source, dict(os.environ))
    assert time.monotonic() - started < 8


def test_python_missing_interpreter_and_secret(tmp_path):
    source = python_source(tmp_path, "pass", python="missing-python-collector")
    with pytest.raises(CollectorError, match="start_failed"):
        collect(source, dict(os.environ))
    source.options["env"] = {"KEY": "${MISSING_COLLECTOR_SECRET}"}
    with pytest.raises(CollectorError, match="missing_environment"):
        collect(source, dict(os.environ))


def test_source_proxy_override_wins_over_inherited_key_casing(tmp_path):
    source = python_source(tmp_path, '''import json, urllib.request
from datetime import datetime, timezone
assert urllib.request.getproxies()['http'] == 'http://source-proxy.invalid:9'
print(json.dumps({'version': 1, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'items': []}))
''', env={"HTTP_PROXY": "http://source-proxy.invalid:9"})
    result = collect(source, {**os.environ, "http_proxy": "http://old-proxy.invalid:8"})
    assert result["items"] == []


@pytest.fixture
def http_server():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append({"auth": self.headers.get("Authorization"), "method": self.command,
                          "body": self.rfile.read(int(self.headers.get("Content-Length", "0")))})
            body = json.dumps(payload(), ensure_ascii=False).encode()
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/ok")
                self.end_headers()
                return
            if self.path == "/fail":
                self.send_error(401, "secret must not reach UI")
                return
            if self.path == "/bad":
                body = b'{"data": []}'
            if self.path == "/rss":
                body = '<rss version="2.0"><channel><item><title>订阅文章</title><link>/article/1</link></item></channel></rss>'.encode()
            if self.path == "/large":
                body = b"x" * (MAX_BYTES + 1)
            if self.path == "/slow":
                time.sleep(0.6)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        do_POST = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", calls
    server.shutdown()
    server.server_close()
    thread.join()


def http_source(tmp_path, url, **extra):
    config(tmp_path, [{"id": "remote", "label": "HTTP", "type": "http", "url": url, **extra}])
    return load_sources(tmp_path, {})[0]


def test_http_get_post_auth_and_local_proxy_bypass(tmp_path, http_server):
    base, calls = http_server
    env = {**os.environ, "TOKEN": "test-only-token", "HTTP_PROXY": "http://127.0.0.1:1",
           "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": "127.0.0.1"}
    source = http_source(tmp_path, base + "/ok", headers={"Authorization": "Bearer ${TOKEN}"})
    assert collect(source, env)["items"][0]["title"] == "测试热点"
    source = http_source(tmp_path, base + "/ok", method="POST", body={"category": "中文"})
    collect(source, env)
    assert calls[0]["auth"] == "Bearer test-only-token"
    assert calls[1]["method"] == "POST" and json.loads(calls[1]["body"]) == {"category": "中文"}


def test_rss_is_registered_and_collected_via_the_same_transport(tmp_path, http_server):
    base, calls = http_server
    config(tmp_path, [{"id": "feed", "label": "订阅", "type": "rss", "url": base + "/rss",
                       "headers": {"Authorization": "Bearer ${FEED_TOKEN}"}}])
    source = load_sources(tmp_path, {})[0]
    result = collect(source, {**os.environ, "FEED_TOKEN": "private-feed-token"})
    assert source.public()["type"] == "rss"
    assert result["version"] == 1 and result["items"][0]["title"] == "订阅文章"
    assert result["items"][0]["url"] == base + "/article/1"
    assert calls[0]["auth"] == "Bearer private-feed-token"
    source.options["url"] = base + "/bad"
    with pytest.raises(CollectorError, match="invalid_feed"):
        collect(source, {**os.environ, "FEED_TOKEN": "private-feed-token"})
    config(tmp_path, [{"id": "feed", "label": "订阅", "type": "rss", "url": base + "/rss", "method": "POST"}])
    with pytest.raises(ConfigError):
        load_sources(tmp_path, {})


@pytest.mark.parametrize("path,code", [("/redirect", "http_failed"), ("/fail", "http_failed"),
                                      ("/bad", "invalid_response"), ("/large", "output_too_large"),
                                      ("/slow", "timeout")])
def test_http_errors_and_no_redirect(tmp_path, http_server, path, code):
    base, calls = http_server
    source = http_source(tmp_path, base + path, timeout_seconds=0.2 if path == "/slow" else 5)
    with pytest.raises(CollectorError, match=code):
        collect(source, dict(os.environ))
    # The smallest deadline may expire during worker startup on a loaded host.
    assert len(calls) <= 1 if path == "/slow" else len(calls) == 1


def test_cache_empty_success_stale_expiry_and_recovery(tmp_path, monkeypatch):
    source = python_source(tmp_path, "pass", refresh_seconds=10, max_stale_seconds=60)
    clock, calls = [time.time()], []

    def fetch(*args):
        calls.append(True)
        if len(calls) in (2, 3):
            raise CollectorError("http_failed")
        data = payload([] if len(calls) == 4 else None)
        data["fetched_at"] = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
        return validate_payload(data)

    monkeypatch.setattr(service_module, "collect", fetch)
    monkeypatch.setattr(service_module.time, "time", lambda: clock[0])
    service = TrendService()
    first = service.get(source, {})
    assert first["status"] == "fresh" and first["ok"]
    service.get(source, {})
    assert len(calls) == 1
    clock[0] += 11
    stale = service.get(source, {})
    assert stale["status"] == "stale" and stale["items"] == first["items"]
    assert stale["fetched_at"] == first["fetched_at"] and stale["error"]["code"] == "http_failed"
    clock[0] += 60
    expired = service.get(source, {})
    assert expired["status"] == "error" and not expired["ok"] and expired["items"] == []
    clock[0] += 11
    empty = service.get(source, {})
    assert empty["status"] == "fresh" and empty["ok"] and empty["items"] == [] and empty["error"] is None


def test_singleflight_and_cache_invalidation(tmp_path, monkeypatch):
    source = python_source(tmp_path, "pass")
    calls = []

    def fetch(*args):
        calls.append(True)
        time.sleep(0.05)
        return validate_payload(payload())

    monkeypatch.setattr(service_module, "collect", fetch)
    service = TrendService()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.get(source, {}), range(8)))
    assert len(calls) == 1 and any(r["ok"] for r in results)
    # A bounded waiter may return busy on a loaded CI host; it must not recollect.
    assert all(r["ok"] or r["error"]["code"] == "busy" for r in results)
    assert service.get(source, {})["ok"] and len(calls) == 1
    service.get(source, {"KEY": "new-value"})
    assert len(calls) == 2
    Path(source.options["script"]).write_text("# changed\npass", encoding="utf-8")
    service.get(source, {"KEY": "new-value"})
    assert len(calls) == 3


def test_unexpected_errors_hidden_and_old_future_data_rejected(tmp_path, monkeypatch):
    source = python_source(tmp_path, "pass")

    def fail(*args):
        raise RuntimeError("Authorization: Bearer secret")

    monkeypatch.setattr(service_module, "collect", fail)
    result = TrendService().get(source, {})
    assert result["error"]["code"] == "collector_failed" and "secret" not in json.dumps(result)
    for when, code in [(0, "expired_data"), (time.time() + 3600, "invalid_response")]:
        data = payload()
        data["fetched_at"] = datetime.fromtimestamp(when, timezone.utc).isoformat()
        monkeypatch.setattr(service_module, "collect", lambda *args: validate_payload(data))
        assert TrendService().get(source, {})["error"]["code"] == code


def test_example_python_runs_through_transport(tmp_path):
    source = python_source(tmp_path, "pass")
    source.options["script"] = str(ROOT / "examples/trends/python_collector.py")
    assert collect(source, dict(os.environ))["items"][0]["id"] == "example-topic-1"


def test_example_http_service_runs_through_transport(tmp_path, monkeypatch):
    import runpy

    monkeypatch.syspath_prepend(str(ROOT / "examples/trends"))
    monkeypatch.setenv("DEMO_TREND_TOKEN", "example-token")
    handler = runpy.run_path(str(ROOT / "examples/trends/http_service.py"))["Handler"]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = http_source(tmp_path, f"http://127.0.0.1:{server.server_port}/trends", method="POST",
                             body={}, headers={"Authorization": "Bearer ${DEMO_TREND_TOKEN}"})
        assert collect(source, dict(os.environ))["items"][0]["id"] == "example-topic-1"
        source.options["headers"] = {}
        with pytest.raises(CollectorError, match="http_failed"):
            collect(source, dict(os.environ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_web_discovery_registered_sources_and_failure_isolation(tmp_path, monkeypatch, http_server):
    import app as web
    from fastapi.testclient import TestClient

    base, calls = http_server
    source = python_source(tmp_path, "print('invalid')", env={"KEY": "do-not-expose"})
    remote = http_source(tmp_path, base + "/ok")
    monkeypatch.setattr(web, "_trend_registry", lambda: ([source, remote], dict(os.environ), []))
    monkeypatch.setattr(web, "_TREND_SERVICE", TrendService())
    with TestClient(web.app, base_url="http://127.0.0.1:7860") as client:
        discovery = client.get("/api/trends/sources")
        assert discovery.status_code == 200
        assert {s["id"] for s in discovery.json()["sources"]} == {"local", "remote"}
        assert "do-not-expose" not in discovery.text and "collector with spaces" not in discovery.text
        result = client.get("/api/trends?platforms=local,remote,remote,https://unregistered.example&limit=100").json()
        assert len(result["trends"]) == 2 and len(calls) == 1
        assert result["trends"][0]["status"] == "error" and result["trends"][1]["status"] == "fresh"
        assert client.get("/api/trends?platforms=").json()["trends"] == []
        assert len(client.get("/api/trends").json()["trends"]) == 2


def test_web_reports_invalid_configuration(tmp_path, monkeypatch):
    import app as web
    from fastapi.testclient import TestClient

    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("EASEL_TREND_SOURCES_CONFIG", "missing.json")
    with TestClient(web.app, base_url="http://127.0.0.1:7860") as client:
        assert client.get("/api/trends/sources").json()["warnings"]
        assert client.get("/api/trends").json()["trends"] == []
