"""Per-collector proxy normalization without changing the host/CLI environment."""
from __future__ import annotations

import os


def proxy_environment(environment: dict[str, str], default_no_proxy: str) -> dict[str, str]:
    result = dict(environment)
    def choose(name: str):
        keys = sorted((key for key in environment if key.lower() == name), key=lambda key: (key != name, key))
        if not keys:
            return None
        if os.name == "nt":
            return next((environment[key] for key in keys if environment[key].strip()), environment[keys[0]])
        return environment[keys[0]]
    fallback = choose("easel_proxy")
    for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        value = choose(name)
        for key in list(result):
            if key.lower() == name:
                del result[key]
        if value is None:
            value = default_no_proxy if name == "no_proxy" else fallback if name != "all_proxy" else None
        if value is not None:
            result[name] = value
    return result
