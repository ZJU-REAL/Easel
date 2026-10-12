from pathlib import Path
import re

from easel import __version__


def test_package_version_matches_runtime():
    metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    project = metadata.split("[project]", 1)[1].split("\n[", 1)[0]
    version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE)
    assert version is not None
    assert version.group(1) == __version__
