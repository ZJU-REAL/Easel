#!/usr/bin/env python3
"""Thin CLI for the Easel MoneyPrinterTurbo adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


for parent in Path(__file__).resolve().parents:
    if (parent / "pyproject.toml").is_file() and (parent / "easel").is_dir():
        sys.path.insert(0, str(parent))
        break

from easel.moneyprinterturbo import (  # noqa: E402
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    BridgeResult,
    MoneyPrinterTurboBridge,
    MoneyPrinterTurboError,
    MoneyPrinterTurboPaths,
    MoneyPrinterTurboRequest,
    configure_managed_runtime,
    prepare_request,
)


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Easel project root")


def _add_request(parser: argparse.ArgumentParser) -> None:
    _add_root(parser)
    parser.add_argument("--project", required=True, help="human-readable output project name")
    parser.add_argument("--aspect", required=True, choices=("9:16", "16:9", "1:1"))
    parser.add_argument(
        "--source",
        required=True,
        choices=(
            "local",
            "pexels",
            "pixabay",
            "coverr",
            "volcengine_seedance",
            "ofox",
            "metaso_minimax",
        ),
    )
    content = parser.add_mutually_exclusive_group(required=True)
    content.add_argument("--topic")
    content.add_argument("--script")
    parser.add_argument("--material", action="append", default=[], type=Path)
    parser.add_argument("--confirm-seedance-charge", action="store_true")
    parser.add_argument("--confirm-ofox-charge", action="store_true")
    parser.add_argument("--confirm-metaso-minimax-charge", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pinned MoneyPrinterTurbo through Easel")
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure", help="configure the managed local-Qwen runtime")
    _add_root(configure)
    _add_request(commands.add_parser("run", help="generate and deliver one video"))
    _add_request(commands.add_parser("dry-run", help="validate and print the redacted argv"))
    return parser


def _request(args: argparse.Namespace) -> MoneyPrinterTurboRequest:
    return MoneyPrinterTurboRequest(
        project_name=args.project,
        aspect=args.aspect,
        source=args.source,
        topic=args.topic,
        script=args.script,
        materials=tuple(args.material),
        confirm_seedance_charge=args.confirm_seedance_charge,
        confirm_ofox_charge=args.confirm_ofox_charge,
        confirm_metaso_minimax_charge=args.confirm_metaso_minimax_charge,
    )


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = MoneyPrinterTurboPaths.for_root(args.root)
    llm_base_url = os.environ.get("EASEL_MPT_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
    llm_model = os.environ.get("EASEL_MPT_LLM_MODEL", DEFAULT_LLM_MODEL)
    if args.command == "configure":
        try:
            configure_managed_runtime(paths, llm_base_url=llm_base_url, llm_model=llm_model)
        except MoneyPrinterTurboError as exc:
            print(str(exc)[:1_000], file=sys.stderr)
            return 1
        _emit({"status": "configured"})
        return 0

    request = _request(args)
    try:
        prepare_request(paths, request)
    except MoneyPrinterTurboError as exc:
        print(str(exc)[:1_000], file=sys.stderr)
        return 2
    bridge = MoneyPrinterTurboBridge(
        paths,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
    )
    try:
        result = bridge.run(request, dry_run=args.command == "dry-run")
    except MoneyPrinterTurboError as exc:
        print(str(exc)[:1_000], file=sys.stderr)
        return 1
    if isinstance(result, list):
        _emit({"status": "dry-run", "argv": result})
    else:
        assert isinstance(result, BridgeResult)
        _emit(
            {
                "status": result.status,
                "task_id": result.task_id,
                "final_path": str(result.final_path),
                "warnings": list(result.warnings),
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
