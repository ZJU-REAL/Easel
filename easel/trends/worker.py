"""Short-lived resource-limited worker; external responses never parse in the Web process."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from easel.trends.protocol import MAX_BYTES, MAX_WORKER_REQUEST_BYTES, CollectorError, safe_json
from easel.trends.sources import Source
from easel.trends.process_limits import restrict_current_process


def main():
    try:
        request = safe_json(sys.stdin.buffer.read(MAX_WORKER_REQUEST_BYTES + 1), MAX_WORKER_REQUEST_BYTES)
        source = Source(**request["source"])
        restrict_current_process(int(source.options.get("memory_mb", 256)), source.timeout)
        from easel.trends.runner import _collect_direct
        payload = _collect_direct(source, request["environment"])
        result = {"ok": True, "payload": payload}
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise CollectorError("output_too_large")
    except CollectorError as error:
        encoded = json.dumps({"ok": False, "error": error.code}).encode()
    except (MemoryError, RecursionError):
        encoded = b'{"ok": false, "error": "resource_limit"}'
    except BaseException:
        encoded = b'{"ok": false, "error": "collector_failed"}'
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
