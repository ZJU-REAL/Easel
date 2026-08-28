"""
Tests for scripts/config.py.

Covers:
- default account resolution
- explicit account selection
- ConfigError raised on missing account / missing yaml / missing fields
- list_accounts() shape consistency
- sync_platforms parsing from list / comma-string / missing
"""

from __future__ import annotations

import textwrap

import pytest


def test_get_config_default_account(tmp_config_yaml):
    """No --account specified → returns the account named by `default:`."""
    import config

    cfg = config.get_config()
    assert cfg["account_key"] == "main"
    assert cfg["app_id"] == "wx_fake_main_app_id_0001"
    assert cfg["author"] == "飞哥"
    assert cfg["theme"] == "refined-blue"


def test_get_config_explicit_account(tmp_config_yaml):
    """Passing account_name explicitly should override the default."""
    import config

    cfg = config.get_config("tech")
    assert cfg["account_key"] == "tech"
    assert cfg["app_id"] == "wx_fake_tech_app_id_0002"
    assert cfg["author"] == "葱哥"
    assert cfg["theme"] == "minimal-mono"


def test_unified_config_reads_wechat_publisher_yaml(tmp_path, monkeypatch):
    """wechat-publisher.yaml should be the single supported config source."""
    yaml_path = tmp_path / "wechat-publisher.yaml"
    yaml_path.write_text(textwrap.dedent("""\
        default: main
        accounts:
          main:
            name: "Unified Main"
            app_id: "wx_unified"
            app_secret: "unified_secret"
            author: "飞哥"
            theme: "refined-blue"
        image_generation:
          generator: "baoyu-danger-gemini-web"
    """), encoding="utf-8")

    import config

    config.set_account(None)
    monkeypatch.setattr(config, "_config_path", lambda: yaml_path)
    cfg = config.get_config()
    assert cfg["account_key"] == "main"
    assert cfg["app_id"] == "wx_unified"
    assert cfg["image_generator"] == "baoyu-danger-gemini-web"


def test_load_env_reads_unified_image_and_integration_config(tmp_path, monkeypatch):
    """load_env() should export unified YAML settings as process env fallbacks."""
    for key in (
        "WECHATSYNC_MCP_TOKEN",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_IMAGE_MODEL",
        "GEMINI_PROXY_API_KEY",
        "GEMINI_PROXY_BASE_URL",
        "GEMINI_PROXY_IMAGE_MODEL",
        "WECHAT_PUBLISHER_IMAGE_GENERATOR",
    ):
        monkeypatch.delenv(key, raising=False)

    yaml_path = tmp_path / "wechat-publisher.yaml"
    yaml_path.write_text(textwrap.dedent("""\
        default: main
        accounts:
          main:
            name: "Unified Main"
            app_id: "wx_unified"
            app_secret: "unified_secret"
            author: "飞哥"
        image_generation:
          generator: "baoyu-image-gen"
          openai:
            api_key: "sk_openai"
            base_url: "https://api.example/v1"
            image_model: "gpt-image-1"
          gemini_proxy:
            api_key: "cr_proxy"
            base_url: "https://proxy.example"
            image_model: "gemini-3-pro-image-preview"
        integrations:
          wechatsync_mcp_token: "sync_token"
    """), encoding="utf-8")

    import config

    monkeypatch.setattr(config, "_config_path", lambda: yaml_path)
    config.load_env()
    assert config.os.environ["WECHAT_PUBLISHER_IMAGE_GENERATOR"] == "baoyu-image-gen"
    assert config.os.environ["OPENAI_API_KEY"] == "sk_openai"
    assert config.os.environ["GEMINI_PROXY_BASE_URL"] == "https://proxy.example"
    assert config.os.environ["WECHATSYNC_MCP_TOKEN"] == "sync_token"


def test_set_account_affects_get_config(tmp_config_yaml):
    """set_account() should stick as a global selection until reset."""
    import config

    config.set_account("tech")
    try:
        cfg = config.get_config()
        assert cfg["account_key"] == "tech"
    finally:
        config.set_account(None)


def test_get_config_raises_on_missing_account(tmp_config_yaml):
    """Asking for a non-existent account should raise ConfigError."""
    import config
    from config import ConfigError

    with pytest.raises(ConfigError) as exc:
        config.get_config("does_not_exist")

    msg = str(exc.value)
    # The error message should name the missing account and list available ones.
    assert "does_not_exist" in msg
    assert "main" in msg or "tech" in msg


def test_get_config_raises_on_missing_yaml(tmp_path, monkeypatch):
    """
    With no wechat-publisher.yaml reachable, get_config must raise ConfigError
    (never sys.exit — CLI handles exit, library callers handle the exception).
    """
    import config

    # Force a cold reload in case earlier tests left module state around.
    config.set_account(None)

    from config import ConfigError

    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "missing.yaml")

    with pytest.raises(ConfigError) as exc:
        config.get_config()

    assert "wechat-publisher.yaml" in str(exc.value)


def test_get_config_raises_on_missing_fields(write_config_yaml):
    """Account with blank app_id / app_secret should raise ConfigError."""
    write_config_yaml(textwrap.dedent("""\
        default: broken
        accounts:
          broken:
            name: "Broken"
            app_id: ""
            app_secret: ""
            author: "nobody"
    """))

    import config
    from config import ConfigError

    with pytest.raises(ConfigError) as exc:
        config.get_config()
    assert "app_id" in str(exc.value) or "app_secret" in str(exc.value)


def test_list_accounts_shape_consistent(tmp_config_yaml):
    """Every dict in list_accounts() output must have the same keys."""
    import config

    rows = config.list_accounts()
    assert len(rows) >= 2

    expected_keys = {"key", "name", "app_id", "author", "is_default"}
    for row in rows:
        assert set(row.keys()) == expected_keys, row

    # Exactly one account should be is_default=True when default is set.
    defaults = [r for r in rows if r["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["key"] == "main"


def test_sync_platforms_parsed_from_list(write_config_yaml):
    """sync_platforms: [zhihu, juejin] → ['zhihu', 'juejin']."""
    write_config_yaml(textwrap.dedent("""\
        default: main
        accounts:
          main:
            name: "Main"
            app_id: "wx_abc"
            app_secret: "sec"
            author: "x"
            sync_platforms: [zhihu, juejin, csdn]
    """))

    import config

    cfg = config.get_config()
    assert cfg["sync_platforms"] == ["zhihu", "juejin", "csdn"]


def test_sync_platforms_parsed_from_string(write_config_yaml):
    """sync_platforms: "zhihu, juejin" (comma-string) → still parses cleanly."""
    write_config_yaml(textwrap.dedent("""\
        default: main
        accounts:
          main:
            name: "Main"
            app_id: "wx_abc"
            app_secret: "sec"
            author: "x"
            sync_platforms: "zhihu, juejin, csdn"
    """))

    import config

    cfg = config.get_config()
    assert cfg["sync_platforms"] == ["zhihu", "juejin", "csdn"]


def test_sync_platforms_none_when_missing(write_config_yaml):
    """No sync_platforms key → None, not [] (tests can distinguish)."""
    write_config_yaml(textwrap.dedent("""\
        default: main
        accounts:
          main:
            name: "Main"
            app_id: "wx_abc"
            app_secret: "sec"
            author: "x"
    """))

    import config

    cfg = config.get_config()
    assert cfg["sync_platforms"] is None

