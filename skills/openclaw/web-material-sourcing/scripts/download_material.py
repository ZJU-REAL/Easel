#!/usr/bin/env python3
"""Download one previously verified web material and append its provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[3] / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
from output_paths import validate_output_path

MAX_BYTES = 50 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="下载已验证网络素材并记录来源")
    ap.add_argument("--url", required=True, help="原始资源直接 URL，不是搜索缩略图")
    ap.add_argument("--output", required=True, help="outputs/<具体主题>/assets/<文件>")
    ap.add_argument("--source-page", required=True, help="包含许可证与归属的原页")
    ap.add_argument("--title", required=True)
    ap.add_argument("--creator", default="")
    ap.add_argument("--license", required=True, dest="license_name")
    ap.add_argument("--usage-note", default="")
    args = ap.parse_args(argv)

    target = validate_output_path(args.output, create_parent=True)
    request = urllib.request.Request(args.url, headers={"User-Agent": "Easel-material-sourcing/1.0"})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as out:
            if getattr(response, "status", 200) >= 400:
                raise RuntimeError(f"HTTP {response.status}")
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError(f"资源超过 {MAX_BYTES // 1024 // 1024} MB 上限")
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    manifest = target.parent / "materials.json"
    records = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else []
    if not isinstance(records, list):
        raise RuntimeError(f"materials.json 必须是数组: {manifest}")
    records.append({
        "file": target.name,
        "source_url": args.url,
        "source_page": args.source_page,
        "title": args.title,
        "creator": args.creator,
        "license": args.license_name,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sha256": digest.hexdigest(),
        "bytes": total,
        "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        "usage_note": args.usage_note,
    })
    tmp = manifest.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(manifest)
    print(json.dumps(records[-1], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
