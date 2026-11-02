"""CLI integration checks: use isolated output roots and no external services."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROMOTION = ROOT / "skills/builtin/real-lab-paper-promotion/scripts/promotion.py"


def run(script, root, *args):
    (root / "outputs").mkdir(exist_ok=True)
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          cwd=ROOT, env=dict(os.environ, EASEL_ROOT=str(root), PYTHONUTF8="1"),
                          capture_output=True, text=True, encoding="utf-8", timeout=15)


def test_promotion_rejects_work_outside_easel_before_downloading(tmp_path):
    result = run(PROMOTION, tmp_path, "prepare", "https://example.invalid/paper.pdf",
                 "--work", tmp_path / "outside")
    assert result.returncode != 0
    assert "输出必须位于" in result.stderr
    assert not (tmp_path / "outside").exists()
