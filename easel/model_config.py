"""Shared model configuration validation and explicit header construction."""
from __future__ import annotations

import re


def validate_model_ref(model: str) -> None:
    if not isinstance(model, str) or any(ord(c) < 32 for c in model):
        raise ValueError('模型名不能包含控制字符')
    if re.search(r'(?:^|/)glm-[^/\s]*\[\d+(?:\.\d+)?[km]\]$', model, re.I):
        raise ValueError('GLM 模型名不能带 [1M] 等上下文标注，请使用服务商返回的实际模型 ID')


def api_headers(key: str, name: str = '', prefix: str = '', version: str = '') -> dict[str, str]:
    headers = {}
    token = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
    if name:
        if not re.fullmatch(token, name):
            raise ValueError('API Key Header 名称无效')
        if prefix and not re.fullmatch(token, prefix):
            raise ValueError('API Key 前缀必须是单个认证方案名称，例如 Bearer')
        headers[name] = f'{prefix} {key}' if prefix else key
    if version:
        if '\r' in version or '\n' in version:
            raise ValueError('Anthropic 版本标头无效')
        headers['anthropic-version'] = version
    return headers
