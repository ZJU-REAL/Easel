import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIDEO_SCRIPT = PROJECT_ROOT / "skills" / "shared" / "scripts" / "ai_video.py"


def test_ai_video_check_accepts_explicit_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "video.env"
    env_file.write_text("DASHSCOPE_API_KEY=from-file\n", encoding="utf-8")

    env = os.environ.copy()
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_KEY", "ALIYUN_API_KEY"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(VIDEO_SCRIPT.parent)

    result = subprocess.run(
        [
            sys.executable,
            str(VIDEO_SCRIPT),
            "check",
            "--provider",
            "dashscope",
            "--env-file",
            str(env_file),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[OK]   DASHSCOPE_API_KEY" in result.stdout


def test_ai_video_check_survives_non_utf8_stdout(tmp_path: Path) -> None:
    """Windows 的非交互式 stdout 默认落到 ANSI 代码页（如 cp1252），cmd_check 打印的
    必填/可选/缺失提示全是中文——没有 reconfigure 成 utf-8 就会在这类环境下
    UnicodeEncodeError 崩溃退出（而不是真的因为配置缺失才非零退出）。"""
    env_file = tmp_path / "video.env"
    env_file.write_text("DASHSCOPE_API_KEY=from-file\n", encoding="utf-8")

    env = os.environ.copy()
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_KEY", "ALIYUN_API_KEY"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(VIDEO_SCRIPT.parent)
    env["PYTHONIOENCODING"] = "cp1252"

    result = subprocess.run(
        [
            sys.executable,
            str(VIDEO_SCRIPT),
            "check",
            "--provider",
            "dashscope",
            "--env-file",
            str(env_file),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "UnicodeEncodeError" not in result.stderr
