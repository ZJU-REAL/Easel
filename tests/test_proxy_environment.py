import json
import os
import subprocess
import sys

import pytest

from easel import cli, runtime_env
from easel.commands import ping, skill
from web import app as web


def test_windows_case_colliding_empty_proxy_does_not_erase_inherited_value(monkeypatch):
    monkeypatch.setattr(runtime_env, "WINDOWS", True)
    original = {"HTTP_PROXY": "http://proxy.invalid:7890", "http_proxy": "",
                "HTTPS_PROXY": "http://proxy.invalid:7890", "https_proxy": "",
                "NO_PROXY": "::1,internal.example", "no_proxy": "localhost",
                "ALL_PROXY": "socks5://proxy.invalid:1080", "UNCHANGED": "value"}
    result = runtime_env.proxy_environment(original, "localhost,127.0.0.1,10.*")
    assert result["http_proxy"] == "http://proxy.invalid:7890"
    assert result["https_proxy"] == "http://proxy.invalid:7890"
    assert result["all_proxy"] == "socks5://proxy.invalid:1080"
    assert result["no_proxy"] == "localhost"
    assert len([k for k in result if k.lower() == "http_proxy"]) == 1
    assert result["UNCHANGED"] == "value"
    assert original["http_proxy"] == ""


def test_proxy_fallback_fills_only_missing_protocol(monkeypatch):
    monkeypatch.setattr(runtime_env, "WINDOWS", True)
    result = runtime_env.proxy_environment({"HTTP_PROXY": "http://existing.invalid:80",
        "EASEL_PROXY": "http://fallback.invalid:7890"}, "localhost")
    assert result["http_proxy"] == "http://existing.invalid:80"
    assert result["https_proxy"] == "http://fallback.invalid:7890"


def test_no_proxy_configuration_does_not_inject_empty_proxy_values():
    result = runtime_env.proxy_environment({}, "localhost")
    assert not any(key.lower() in ("http_proxy", "https_proxy", "all_proxy") for key in result)


def test_unix_explicit_empty_proxy_and_distinct_aliases_are_preserved(monkeypatch):
    monkeypatch.setattr(runtime_env, "WINDOWS", False)
    original = {"http_proxy": "", "HTTP_PROXY": "http://upper.invalid:80",
                "https_proxy": "http://lower.invalid:80", "HTTPS_PROXY": "http://upper.invalid:80",
                "no_proxy": "", "EASEL_PROXY": "http://fallback.invalid:80"}
    assert runtime_env.proxy_environment(original, "localhost") == original


@pytest.mark.parametrize("windows", [True, False])
def test_explicit_empty_settings_are_not_replaced_by_fallback(monkeypatch, windows):
    monkeypatch.setattr(runtime_env, "WINDOWS", windows)
    original = {"http_proxy": "", "https_proxy": "", "no_proxy": "",
                "EASEL_PROXY": "http://fallback.invalid:80"}
    assert runtime_env.proxy_environment(original, "localhost") == original


def test_unix_uppercase_bypass_is_visible_to_wechat_consumer(monkeypatch):
    monkeypatch.setattr(runtime_env, "WINDOWS", False)
    result = runtime_env.proxy_environment({"NO_PROXY": "internal.example"}, "localhost")
    assert result["NO_PROXY"] == result["no_proxy"] == "internal.example"


@pytest.mark.parametrize("egress", ["", "http://egress.invalid:7890"])
def test_wechat_keeps_inherited_bypass_entries(monkeypatch, egress):
    monkeypatch.setattr(runtime_env, "WINDOWS", True)
    monkeypatch.setenv("WECHAT_EGRESS_PROXY", egress)
    monkeypatch.setattr(web, "_proxy_env", lambda: runtime_env.proxy_environment({
        "HTTP_PROXY": "http://proxy.invalid:7890",
        "NO_PROXY": "localhost,127.0.0.1,::1,internal.example,api.weixin.qq.com"}, "unused.invalid"))
    result = web._wechat_env()
    bypass = set(result["no_proxy"].split(","))
    assert {"localhost", "127.0.0.1", "::1", "internal.example"} <= bypass
    assert ("api.weixin.qq.com" in bypass) == (not bool(egress))


@pytest.mark.parametrize("entry", [cli, web, ping, skill])
def test_entry_point_preserves_uppercase_proxy_in_real_child(monkeypatch, entry):
    for key in list(os.environ):
        if key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "easel_proxy"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:7890")
    monkeypatch.setenv("NO_PROXY", "::1,internal.example")
    child = subprocess.run([sys.executable, "-c",
        "import json,os; print(json.dumps({k.lower():v for k,v in os.environ.items() "
        "if k.lower() in ('http_proxy','https_proxy','no_proxy')}))"],
        env=entry._proxy_env(), capture_output=True, text=True, check=True, timeout=15)
    result = json.loads(child.stdout)
    assert result["http_proxy"] == "http://proxy.invalid:7890"
    assert result["https_proxy"] == "http://proxy.invalid:7890"
    assert result["no_proxy"] == "::1,internal.example"
