"""Native configuration planning stays read-only and preserves explicit choices."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from easel.openclaw_defaults import SAFETY_DEFAULTS, updates
from easel.model_config import api_headers, validate_model_ref


def test_missing_defaults_do_not_cap_task_tool_calls_or_change_permissions():
    config = {'models': {'providers': {'private': {'apiKey': 'not-a-real-key'}}}}
    before = deepcopy(config)
    assert updates(config) == SAFETY_DEFAULTS
    assert config == before
    assert set(updates(config)) == {'tools.exec.notifyOnExit', 'tools.loopDetection.enabled',
                                    'agents.defaults.compaction.maxActiveTranscriptBytes'}


def test_explicit_native_values_and_utility_model_are_preserved():
    config = {'tools': {'exec': {'notifyOnExit': True}, 'loopDetection': {'enabled': False}},
              'agents': {'defaults': {'compaction': {'maxActiveTranscriptBytes': 0}, 'utilityModel': 'native/model'}}}
    assert updates(config, 'other/model', 'override/model') == {}


@pytest.mark.parametrize('config', [[], {'tools': None}, {'agents': {'defaults': []}},
                                   {'tools': {'exec': False}}])
def test_malformed_sections_are_rejected_without_replacing_them(config):
    before = deepcopy(config)
    with pytest.raises(ValueError):
        updates(config)
    assert config == before


def test_utility_model_uses_the_configured_primary_instead_of_inventing_small_model():
    result = updates({'agents': {'defaults': {'model': {'primary': 'anthropic/glm-5.3'}}}})
    assert result['agents.defaults.utilityModel'] == 'anthropic/glm-5.3'
    assert updates({}, 'anthropic/glm-5.3', 'openai/utility')['agents.defaults.utilityModel'] == 'openai/utility'


def test_custom_bearer_header_is_explicit_and_other_names_keep_raw_keys():
    assert api_headers('example-key', 'Authorization', 'Bearer', '2023-06-01') == {
        'Authorization': 'Bearer example-key', 'anthropic-version': '2023-06-01'}
    assert api_headers('example-key', 'api-key') == {'api-key': 'example-key'}


@pytest.mark.parametrize('name,prefix', [('Authorization\nInjected', 'Bearer'), ('Authorization', 'Bearer\nInjected')])
def test_header_config_rejects_injection_without_echoing_credentials(name, prefix):
    with pytest.raises(ValueError) as failure:
        api_headers('example-private-key', name, prefix)
    assert 'example-private-key' not in str(failure.value)


@pytest.mark.parametrize('model', ['glm-5.3[1M]', 'anthropic/glm-5.3[128k]'])
def test_glm_context_annotations_fail_before_gateway_requests(model):
    with pytest.raises(ValueError):
        validate_model_ref(model)


@pytest.mark.parametrize('model', ['glm-5.3', 'custom/vendor/qwen-3', 'native/model:latest', 'provider/real[variant]'])
def test_actual_names_and_provider_namespaces_are_preserved(model):
    assert validate_model_ref(model) is None


@pytest.mark.parametrize('primary,key', [('anthropic/glm-5.3[1M]', 'example-key'),
                                        ('anthropic/glm-5.3', 'sk-ant-REPLACE_ME')])
def test_doctor_rejects_invalid_model_and_placeholder_credentials(tmp_path, monkeypatch, primary, key):
    from easel.commands import doctor
    path = tmp_path / 'openclaw.json'
    path.write_text(json.dumps({'agents': {'defaults': {'model': {'primary': primary}}},
                               'models': {'providers': {'anthropic': {'apiKey': key}}}}))
    monkeypatch.setattr(doctor, '_openclaw_config_path', lambda: path)
    ok, detail = doctor._primary_model_routable()
    assert not ok
    assert key not in detail


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('bash'), reason='POSIX installer helper')
def test_installer_native_plan_uses_actual_helper_and_preserves_file(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = (root / 'setup.sh').read_text()
    helper = source[source.index('oc_configure_native_defaults()'):source.index('# ---- 安装报告 ----')]
    state = tmp_path / 'state'
    state.mkdir()
    config = state / 'openclaw.json'
    config.write_text(json.dumps({'tools': {'loopDetection': {'enabled': False}}}))
    before = config.read_bytes()
    (tmp_path / '.env').write_text('EASEL_OPENCLAW_UTILITY_MODEL=openai/utility\n')
    script = ('PROJECT_ROOT="$1"\noc_set() { printf "%s=%s\\n" "$2" "$3"; }\n'
              'warn_collect() { echo "unexpected warning" >&2; return 1; }\n'
              + helper + '\noc_configure_native_defaults openai/primary\n')
    result = subprocess.run([shutil.which('bash'), '-c', script, 'check', str(tmp_path)],
                            env={**os.environ, 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'],
                                 'EASEL_OPENCLAW_STATE_DIR': str(state)}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    written = {line.split('=', 1)[0]: json.loads(line.split('=', 1)[1]) for line in result.stdout.splitlines()}
    assert written == {'tools.exec.notifyOnExit': False, 'agents.defaults.compaction.maxActiveTranscriptBytes': '1mb',
                       'agents.defaults.utilityModel': 'openai/utility'}
    assert config.read_bytes() == before
