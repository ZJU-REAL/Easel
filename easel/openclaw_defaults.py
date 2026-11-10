"""Missing-only native defaults; never replace an explicit user preference."""
from __future__ import annotations

from typing import Any

from easel.model_config import validate_model_ref

SAFETY_DEFAULTS = {
    'tools.exec.notifyOnExit': False,
    'tools.loopDetection.enabled': True,
    'agents.defaults.compaction.maxActiveTranscriptBytes': '1mb',
}


def missing(config: dict, path: str) -> bool:
    node: Any = config
    for part in path.split('.'):
        if not isinstance(node, dict):
            raise ValueError('OpenClaw configuration section must be an object')
        if part not in node:
            return True
        node = node[part]
    return False


def updates(config: dict, primary: str = '', utility: str = '') -> dict:
    if not isinstance(config, dict):
        raise ValueError('OpenClaw configuration must be an object')
    result = {path: value for path, value in SAFETY_DEFAULTS.items() if missing(config, path)}
    if missing(config, 'agents.defaults.utilityModel'):
        defaults = config.get('agents', {}).get('defaults', {})
        model = defaults.get('model', {})
        chosen = utility or primary or (model if isinstance(model, str) else model.get('primary', '') if isinstance(model, dict) else '')
        if chosen:
            validate_model_ref(chosen)
            result['agents.defaults.utilityModel'] = chosen
    return result
