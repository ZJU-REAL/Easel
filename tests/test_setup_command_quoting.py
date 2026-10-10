"""The installer must preserve executable paths, profiles and JSON arguments."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parents[1] / "setup.sh"


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt",
                    reason="requires a native POSIX executable")
def test_openclaw_helpers_preserve_spaces_and_json_flags(tmp_path):
    executable = tmp_path / "node installation [local]" / "openclaw"
    executable.parent.mkdir()
    calls = tmp_path / "calls.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        'with open(os.environ["CALLS"], "a") as output:\n'
        '    output.write(json.dumps(sys.argv[1:]) + "\\n")\n'
        'if "--help" in sys.argv: print("--replace")\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    source = SETUP.read_text(encoding="utf-8")
    wrapper = next(line for line in source.splitlines() if line.startswith("oc()"))
    helpers = source[source.index("oc_supports() {"):source.index("# 静默尝试")]
    script = "\n".join([
        "set -euo pipefail",
        'PROFILE="easel test [local]"',
        "SETUP_MODE=full",
        wrapper,
        helpers,
        "oc_supports 'config set' --replace",
        "_oc_run models.providers.test '{\"apiKey\":\"test key\",\"models\":[]}' --json-replace",
    ])
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30,
        env={**os.environ, "OPENCLAW_BIN": str(executable), "CALLS": str(calls)},
    )
    assert result.returncode == 0, result.stderr
    arguments = [json.loads(line) for line in calls.read_text().splitlines()]
    assert arguments == [
        ["--profile", "easel test [local]", "config", "set", "--help"],
        ["--profile", "easel test [local]", "config", "set", "models.providers.test",
         '{"apiKey":"test key","models":[]}', "--strict-json", "--replace"],
    ]
