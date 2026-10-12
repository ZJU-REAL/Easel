#!/usr/bin/env python3
"""
统一配置管理。

仅支持 skill 根目录下的 wechat-publisher.yaml。

用法:
    from config import set_account, get_config, ConfigError
    set_account("tech")
    cfg = get_config()  # 返回当前账号的完整配置
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, List, Any

try:
    import yaml  # pyyaml
except ImportError as exc:
    raise ImportError(
        "缺少 pyyaml 依赖。请执行: pip install pyyaml --break-system-packages"
    ) from exc


# ============================================================
# 异常
# ============================================================

class ConfigError(RuntimeError):
    """配置加载失败。由库函数抛出,CLI 层捕获后退出。"""


# ============================================================
# 全局激活账号
# ============================================================

_active_account: Optional[str] = None


def set_account(account_name: Optional[str]) -> None:
    """设置当前激活的账号(全局,影响后续所有调用)。"""
    global _active_account
    _active_account = account_name


def get_account_name() -> Optional[str]:
    """读取当前激活的账号名。"""
    return _active_account


# ============================================================
# 统一配置加载
# ============================================================

UNIFIED_CONFIG_NAME = "wechat-publisher.yaml"


def _config_path() -> Path:
    return Path(__file__).parent.parent / UNIFIED_CONFIG_NAME


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _find_unified_yaml() -> Optional[Path]:
    """仅查找 skill 根目录下的 wechat-publisher.yaml。"""
    path = _config_path()
    return path if path.exists() else None


def _load_unified_yaml() -> Dict[str, Any]:
    path = _find_unified_yaml()
    if path is None:
        return {}
    return _load_yaml(path)


def _set_env_if_present(key: str, value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        os.environ.setdefault(key, text)


def _load_unified_env() -> None:
    cfg = _load_unified_yaml()
    if not cfg:
        return

    integrations = cfg.get("integrations") or {}
    if isinstance(integrations, dict):
        _set_env_if_present("WECHATSYNC_MCP_TOKEN", integrations.get("wechatsync_mcp_token"))

    image = cfg.get("image_generation") or {}
    if not isinstance(image, dict):
        return

    _set_env_if_present("WECHAT_PUBLISHER_IMAGE_GENERATOR", image.get("generator"))

    openai = image.get("openai") or {}
    if isinstance(openai, dict):
        _set_env_if_present("OPENAI_API_KEY", openai.get("api_key"))
        _set_env_if_present("OPENAI_BASE_URL", openai.get("base_url"))
        _set_env_if_present("OPENAI_IMAGE_MODEL", openai.get("image_model"))

    gemini_proxy = image.get("gemini_proxy") or {}
    if isinstance(gemini_proxy, dict):
        _set_env_if_present("GEMINI_PROXY_API_KEY", gemini_proxy.get("api_key"))
        _set_env_if_present("GEMINI_PROXY_BASE_URL", gemini_proxy.get("base_url"))
        _set_env_if_present("GEMINI_PROXY_IMAGE_MODEL", gemini_proxy.get("image_model"))

    gemini_web = image.get("gemini_web") or {}
    if isinstance(gemini_web, dict):
        _set_env_if_present("GEMINI_WEB_DATA_DIR", gemini_web.get("data_dir"))
        _set_env_if_present("GEMINI_WEB_COOKIE_PATH", gemini_web.get("cookie_path"))
        _set_env_if_present("GEMINI_WEB_CHROME_PROFILE_DIR", gemini_web.get("chrome_profile_dir"))
        _set_env_if_present("GEMINI_WEB_CHROME_PATH", gemini_web.get("chrome_path"))


def load_env() -> None:
    """
    从 wechat-publisher.yaml 加载辅助环境变量到 os.environ(不覆盖已有值)。
    """
    _load_unified_env()


def _load_config_yaml(yaml_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """加载 skill 根目录 wechat-publisher.yaml。返回 None 表示找不到文件。"""
    if yaml_path is None:
        yaml_path = _find_unified_yaml()
    if yaml_path is None:
        return None
    return _load_yaml(yaml_path)


def list_accounts() -> List[Dict[str, Any]]:
    """
    列出所有已配置的账号。

    返回统一 schema:
        {"key": str, "name": str, "app_id": str(截短), "author": str, "is_default": bool}
    """
    config = _load_config_yaml()
    if not config or "accounts" not in config:
        return []

    default_name = config.get("default", "")
    result = []
    for key, acc in config["accounts"].items():
        app_id = acc.get("app_id", "") or ""
        result.append({
            "key": key,
            "name": acc.get("name", key),
            "app_id": (app_id[:8] + "...") if app_id else "",
            "author": acc.get("author", "") or "",
            "is_default": key == default_name,
        })
    return result


def get_global_image_generator() -> str:
    """读取全局 image_generation.generator；缺失时返回空串。"""
    yaml_config = _load_config_yaml()
    if not yaml_config:
        return ""

    image_generation = yaml_config.get("image_generation") or {}
    if not isinstance(image_generation, dict):
        return ""

    return str(image_generation.get("generator", "") or "").strip()


def get_config(account_name: Optional[str] = None) -> Dict[str, Any]:
    """
    获取当前账号的完整配置。

    优先级:
      1. account_name 参数
      2. set_account() 设置的全局账号
      3. wechat-publisher.yaml 的 `default` 字段

    Raises:
        ConfigError: 配置文件缺失、账号不存在、或缺少必要字段(app_id/app_secret)

    Returns:
        dict: {
            "app_id": str,
            "app_secret": str,
            "author": str,
            "account_key": str,
            "account_name": str,
            "theme": str,
            "image_generator": str,
            "voice": str,
            "sync_platforms": list[str] | None,   # 可选,未配置为 None
        }
    """
    account_name = account_name or _active_account

    yaml_config = _load_config_yaml()
    if not yaml_config or "accounts" not in yaml_config or not yaml_config["accounts"]:
        raise ConfigError(
            "未找到 wechat-publisher.yaml 或文件为空。请参考 wechat-publisher.yaml.example 创建配置。"
        )

    if account_name is None:
        account_name = yaml_config.get("default")

    if account_name is None:
        available = ", ".join(yaml_config["accounts"].keys())
        raise ConfigError(
            f"未指定账号且 wechat-publisher.yaml 里无 default。可用账号: {available}"
        )

    if account_name not in yaml_config["accounts"]:
        available = ", ".join(yaml_config["accounts"].keys())
        raise ConfigError(
            f"未找到账号 '{account_name}'。可用账号: {available}"
        )

    acc = yaml_config["accounts"][account_name]
    image_generation = yaml_config.get("image_generation") or {}
    if not isinstance(image_generation, dict):
        image_generation = {}

    app_id = acc.get("app_id", "")
    app_secret = acc.get("app_secret", "")
    if not app_id or not app_secret:
        raise ConfigError(
            f"账号 '{account_name}' 缺少 app_id 或 app_secret"
        )

    # sync_platforms 支持两种写法: list 或 comma-separated string
    sync_platforms = acc.get("sync_platforms")
    if isinstance(sync_platforms, str):
        sync_platforms = [p.strip() for p in sync_platforms.split(",") if p.strip()]
    elif isinstance(sync_platforms, list):
        sync_platforms = [str(p).strip() for p in sync_platforms if str(p).strip()]
    else:
        sync_platforms = None

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "author": acc.get("author", "") or "",
        "account_key": account_name,
        "account_name": acc.get("name", account_name),
        "theme": acc.get("theme", "") or "",
        "image_style": acc.get("image_style", "") or "",
        "newspic_image_style": acc.get("newspic_image_style", "") or "",
        "image_generator": acc.get("image_generator", "") or image_generation.get("generator", "") or "",
        "voice": acc.get("voice", "") or "",
        "sync_platforms": sync_platforms,
    }


# ============================================================
# 图片风格(assets/image-styles/<name>.json)
# ============================================================

DEFAULT_IMAGE_STYLE = "warm-handdrawn"
# 贴图(newspic)模式的兜底风格 —— 高密度手绘水彩信息图,对标
# https://mp.weixin.qq.com/s/nSlGjh9hjM63jxz_jgUCwA
DEFAULT_NEWSPIC_IMAGE_STYLE = "infographic-warm"


def _image_styles_dir() -> Path:
    """配图风格 JSON 目录: <skill>/assets/image-styles/"""
    return Path(__file__).parent.parent / "assets" / "image-styles"


def list_image_styles() -> List[str]:
    """列出所有可用配图风格名(按名字排序)。"""
    d = _image_styles_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def get_image_style(name: Optional[str] = None) -> Dict[str, Any]:
    """
    加载一个配图风格的配置。

    Args:
        name: 风格名(对应 assets/image-styles/<name>.json)。
              None 时使用 DEFAULT_IMAGE_STYLE(hand-drawn-blue)。

    Returns:
        完整的 style dict(至少包含 style_name / display_name / prompt_template 等)。

    Raises:
        ConfigError: 风格文件不存在或 JSON 损坏。
    """
    style_name = name or DEFAULT_IMAGE_STYLE
    path = _image_styles_dir() / f"{style_name}.json"
    if not path.exists():
        available = ", ".join(list_image_styles()) or "(无)"
        raise ConfigError(
            f"未找到配图风格 '{style_name}'。可用风格: {available}"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"配图风格 '{style_name}' JSON 解析失败: {e}") from e


def resolve_image_style(
    cli_value: Optional[str] = None,
    frontmatter_value: Optional[str] = None,
    account_name: Optional[str] = None,
    mode: str = "news",
) -> Dict[str, Any]:
    """
    按优先级解析最终使用的配图风格:
      1. CLI 参数(--image-style)
      2. brief.md / article.md 的 frontmatter image_style 字段
      3. wechat-publisher.yaml 对应账号的 image_style 字段
      4. 全局默认:news 模式 → DEFAULT_IMAGE_STYLE(hand-drawn-blue);
                   newspic 模式 → DEFAULT_NEWSPIC_IMAGE_STYLE(infographic-warm)

    Args:
        mode: "news" 或 "newspic"。newspic 模式下的兜底是高密度手绘水彩
              信息图(infographic-warm),与文章模式的线条手绘风区分。

    Returns:
        与 get_image_style() 相同的 style dict。
    """
    for candidate in (cli_value, frontmatter_value):
        if candidate:
            return get_image_style(candidate)

    try:
        cfg = get_config(account_name)
        # 贴图模式优先使用账号的 newspic_image_style(如果配了),否则回退到全局 newspic 兜底。
        # 账号级别的 image_style 是给文章模式用的,不直接用于贴图模式 —— 文章手绘线条风
        # (hand-drawn-blue / marker-lime)和贴图的高密度水彩信息图是两种完全不同的视觉语言。
        if mode == "newspic":
            if cfg.get("newspic_image_style"):
                return get_image_style(cfg["newspic_image_style"])
        else:
            if cfg.get("image_style"):
                return get_image_style(cfg["image_style"])
    except ConfigError:
        pass

    fallback = DEFAULT_NEWSPIC_IMAGE_STYLE if mode == "newspic" else DEFAULT_IMAGE_STYLE
    return get_image_style(fallback)
