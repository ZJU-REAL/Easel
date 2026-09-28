"""Built-in runtime registry."""

from __future__ import annotations

import os

from .base import *  # noqa: F401,F403 - public seam
from .common import ENV_FILE, env_file_value, runtime_env
from .openclaw import OpenClawAdapter
from .opencode import OpenCodeAdapter

_REGISTRY = {
    "openclaw": OpenClawAdapter(),
    "opencode": OpenCodeAdapter(),
}


def list_runtimes():
    return tuple(adapter.descriptor for adapter in _REGISTRY.values())


def get_runtime(runtime_id: str | None = None):
    value = (runtime_id or os.environ.get("EASEL_AGENT_RUNTIME")
             or env_file_value("EASEL_AGENT_RUNTIME") or "openclaw").lower()
    try:
        return _REGISTRY[value]
    except KeyError:
        raise ValueError(
            f"无效的 EASEL_AGENT_RUNTIME={value!r}；有效值：{', '.join(_REGISTRY)}"
        ) from None
