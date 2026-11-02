"""Easel 自定义 Python 采集器：UTF-8 标准输出只输出一份 JSON，日志写标准错误。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def collect() -> list[dict]:
    """采集入口：把这里替换为你的 API / 网页 / 数据库采集逻辑。失败时抛出异常。"""
    return [{
        "id": "example-topic-1",               # 可选：来源内稳定 ID，用于去重
        "title": "示例热点：请替换为实际采集结果",   # 必填：非空标题
        "url": "https://example.com/topic/1",   # 可选：HTTP(S) 原文链接
        "published_at": None,                  # 可选：带时区的 ISO 8601 时间
        "heat": {"value": 123, "text": "123", "unit": "阅读"},
    }]


def main() -> int:
    try:
        items = collect()  # 成功但没有数据时返回 []；采集失败不要伪装成空列表
        result = {
            "version": 1,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        # 协议出口：stdout 只输出这一份 JSON；不要在 stdout 打印调试日志。
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        print("采集失败，请检查采集逻辑和上游服务。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
