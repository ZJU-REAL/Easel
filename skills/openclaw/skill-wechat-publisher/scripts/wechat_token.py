#!/usr/bin/env python3
"""
access_token 获取与缓存

- 按账号隔离缓存(文件名: .token_cache_<account_key>.json)
- 缓存文件权限 0600,避免共享机器泄漏
- 5 分钟安全 margin(token TTL 是 7200s,到 6900s 就主动刷新)
- 网络瞬时错误自动重试(5xx / Timeout,最多 3 次指数退避)
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Optional, Any

import requests

from config import get_config


TOKEN_CACHE_DIR = Path(__file__).parent
TOKEN_SAFETY_MARGIN_SEC = 300  # 提前 5 分钟刷新
TOKEN_TIMEOUT_SEC = 10
TOKEN_API_URL = "https://api.weixin.qq.com/cgi-bin/token"

# 进程内缓存: account_key → {"token": str, "expires_at": float}
_token_caches: Dict[str, Dict[str, Any]] = {}


def _get_token_cache_file(account_key: str = "default") -> Path:
    """获取指定账号的 token 缓存文件路径。"""
    if account_key == "default":
        return TOKEN_CACHE_DIR / ".token_cache.json"
    return TOKEN_CACHE_DIR / f".token_cache_{account_key}.json"


def _load_token_cache(account_key: str = "default") -> None:
    """把磁盘缓存读进进程内缓存;失效或读失败则置空。"""
    cache_file = _get_token_cache_file(account_key)
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if cached.get("expires_at", 0) > time.time() + TOKEN_SAFETY_MARGIN_SEC:
                    _token_caches[account_key] = cached
                    return
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    _token_caches.setdefault(account_key, {"token": None, "expires_at": 0})


def _save_token_cache(account_key: str = "default") -> None:
    """
    保存进程内缓存到磁盘。

    文件权限强制为 0600,避免多用户机器泄漏 token。
    """
    cache = _token_caches.get(account_key)
    if not cache:
        return
    try:
        cache_file = _get_token_cache_file(account_key)
        # O_CREAT|O_WRONLY|O_TRUNC + mode 0o600 确保权限安全
        fd = os.open(
            str(cache_file),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass


def _fetch_token_with_retry(app_id: str, app_secret: str, account_key: str, retries: int = 2) -> Dict[str, Any]:
    """调微信 token 接口,对 5xx / Timeout 重试。40164(IP 白名单)不重试。"""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                TOKEN_API_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": app_id,
                    "secret": app_secret,
                },
                timeout=TOKEN_TIMEOUT_SEC,
            )
            if 500 <= resp.status_code < 600:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                if attempt < retries:
                    time.sleep(1.5 ** attempt)
                    continue
                resp.raise_for_status()

            data = resp.json()
            if "access_token" in data:
                return data

            # 微信应用层错误
            error_code = data.get("errcode", -1)
            error_msg = data.get("errmsg", "未知错误")
            # 40164: 不在 IP 白名单,重试也没用
            if error_code == 40164 or attempt >= retries:
                raise RuntimeError(
                    f"获取 access_token 失败 [{error_code}] (账号: {account_key}): {error_msg}"
                )
            last_exc = RuntimeError(f"[{error_code}] {error_msg}")
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(1.5 ** attempt)
                continue
            raise

    # 理论上到不了这里
    raise last_exc or RuntimeError("获取 access_token 失败(未知原因)")


def get_access_token(force_refresh: bool = False, account_name: Optional[str] = None) -> str:
    """
    获取 access_token,自动缓存 + 失效前 5 分钟刷新。

    Args:
        force_refresh: 跳过缓存强制刷新
        account_name: 账号名,None 时用当前激活账号

    Returns:
        str: 有效的 access_token
    """
    config = get_config(account_name)
    account_key = config.get("account_key", "default")

    _load_token_cache(account_key)
    cache = _token_caches.get(account_key, {"token": None, "expires_at": 0})

    if not force_refresh and cache["token"] and cache["expires_at"] > time.time() + TOKEN_SAFETY_MARGIN_SEC:
        return cache["token"]

    data = _fetch_token_with_retry(
        app_id=config["app_id"],
        app_secret=config["app_secret"],
        account_key=account_key,
    )

    _token_caches[account_key] = {
        "token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 7200),
    }
    _save_token_cache(account_key)

    return data["access_token"]
