#!/usr/bin/env python3
"""Run the portable paper-video tools with Easel output paths and dependencies."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS.parents[2] / "shared" / "scripts"))
from output_paths import PROJECT_ROOT, validate_output_path  # noqa: E402


def output_dir(value: str) -> Path:
    return validate_output_path(Path(value) / ".path-check").parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    init = subs.add_parser("init")
    init.add_argument("destination")
    render = subs.add_parser("render")
    render.add_argument("project")
    render.add_argument("output")
    verify = subs.add_parser("verify")
    verify.add_argument("video")
    verify.add_argument("--report", required=True)
    assets = subs.add_parser("assets")
    assets.add_argument("arguments", nargs=argparse.REMAINDER)
    args, extra = parser.parse_known_args(argv)
    env = dict(os.environ, EASEL_ROOT=str(PROJECT_ROOT))
    try:
        if args.command == "init":
            if extra:
                parser.error("Unexpected init arguments: " + " ".join(extra))
            command = [sys.executable, str(SCRIPTS / "init_project.py"), str(output_dir(args.destination))]
        elif args.command == "render":
            dest = validate_output_path(args.output)
            # Reuse the Node package shipped with Python Playwright; no npm install needed.
            spec = importlib.util.find_spec("playwright")
            if spec and spec.origin:
                bundled = Path(spec.origin).parent / "driver" / "package"
                if bundled.is_dir():
                    env.setdefault("PLAYWRIGHT_MODULE", str(bundled))
            command = ["node", str(SCRIPTS / "render.cjs"), args.project, str(dest), *extra]
        elif args.command == "verify":
            report = validate_output_path(args.report)
            command = [sys.executable, str(SCRIPTS / "verify_video.py"), args.video,
                       "--report", str(report), *extra]
        else:
            forwarded = args.arguments
            if not forwarded or extra:
                parser.error("assets requires a paper_assets.py command")
            if forwarded[0] not in {"check", "crop"}:
                options = argparse.ArgumentParser(add_help=False)
                options.add_argument("--outdir", required=True)
                parsed, _ = options.parse_known_args(forwarded[1:])
                output_dir(parsed.outdir)
            elif forwarded[0] == "crop":
                if len(forwarded) < 3:
                    parser.error("crop requires an operation and image")
                readonly = forwarded[1] in {"inspect", "blocks"} or (
                    forwarded[1] in {"top-check", "decaption"} and "--apply" not in forwarded)
                if not readonly:
                    validate_output_path(forwarded[2])
            command = [sys.executable, str(SCRIPTS / "paper_assets.py"), *forwarded]
        return subprocess.run(command, cwd=PROJECT_ROOT, env=env).returncode
    except (ValueError, OSError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
