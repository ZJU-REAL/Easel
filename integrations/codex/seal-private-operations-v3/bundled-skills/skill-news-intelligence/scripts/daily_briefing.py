import json
import concurrent.futures
import sys
import os
import argparse

from fetch_news import (
    fetch_36kr, fetch_wallstreetcn, fetch_tencent,
    build_sources_map, enrich_items_with_content,
)

# 预设简报 Profile —— 面向中文社媒创作者的情报组合。
# 每个 section: {"sources": [(fetcher, limit, keyword)], "enrich": bool}
_SM = build_sources_map()


def _rss(key):
    return _SM[key]


PROFILES = {
    # 1. 创作者情报日报 —— 自媒体/内容运营 + 行业深度 + AI 动态
    "creator": {
        "自媒体运营": {"sources": [(_rss('woshipm'), 10, None)], "enrich": True},
        "行业深度":   {"sources": [(_rss('huxiu'), 8, None), (fetch_36kr, 8, None)], "enrich": True},
        "AI动态":     {"sources": [(_rss('aihot'), 8, None)], "enrich": False},
    },
    # 2. 科技数码 —— 数码/科技/开发赛道创作者
    "tech_digital": {
        "数码效率": {"sources": [(_rss('sspai'), 10, None), (_rss('geekpark'), 8, None)], "enrich": True},
        "科技商业": {"sources": [(fetch_36kr, 8, None), (_rss('tmtpost'), 8, None)], "enrich": True},
        "技术开发": {"sources": [(_rss('infoq_cn'), 6, None)], "enrich": True},
    },
    # 3. 商业财经 —— 财经/商业/职场赛道创作者
    "business": {
        "财经市场": {"sources": [(fetch_wallstreetcn, 12, None)], "enrich": True},
        "商业观察": {"sources": [(_rss('huxiu'), 8, None), (_rss('tmtpost'), 8, None)], "enrich": True},
        "创投动态": {"sources": [(fetch_36kr, 10, "融资,IPO,上市,独角兽,创投")], "enrich": True},
    },
    # 4. AI 资讯 —— AI 赛道创作者
    "ai": {
        "AI精选": {"sources": [(_rss('aihot'), 15, None)], "enrich": True},
        "技术前沿": {"sources": [(_rss('infoq_cn'), 8, "AI,大模型,LLM,Agent")], "enrich": True},
    },
    # 5. 话题素材 —— 时事/社会话题，供二创评论与选题切入
    "topics": {
        "社会时事": {"sources": [(_rss('thepaper'), 10, None), (fetch_tencent, 10, None)], "enrich": False},
        "消费商业": {"sources": [(_rss('huxiu'), 8, None)], "enrich": True},
    },
}


def fetch_section(section_name, config):
    print(f"[{section_name}] Starting fetch...", file=sys.stderr)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {}
        for func, limit, kw in config["sources"]:
            future = executor.submit(func, limit, kw)
            future_map[future] = getattr(func, '__name__', 'rss')
        for future in concurrent.futures.as_completed(future_map):
            fname = future_map[future]
            try:
                items = future.result()
                results.extend(items)
                print(f"[{section_name}] {fname} returned {len(items)} items", file=sys.stderr)
            except Exception as e:
                print(f"[{section_name}] {fname} failed: {e}", file=sys.stderr)

    if config.get("enrich") and results:
        print(f"[{section_name}] Enriching {len(results)} items...", file=sys.stderr)
        results = enrich_items_with_content(results, max_workers=10)
    return results


def save_individual_sources(data, base_dir):
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    source_map = {}
    for section, items in data.items():
        for item in items:
            src = item.get('source', 'Unknown')
            safe_name = "".join([c if c.isalnum() else "_" for c in src])
            source_map.setdefault(safe_name, []).append(item)
    for src, items in source_map.items():
        with open(os.path.join(base_dir, f"{src}.json"), 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    return list(source_map.keys())


def main():
    parser = argparse.ArgumentParser(description="Easel 创作者情报简报")
    parser.add_argument('--profile', default='creator', choices=PROFILES.keys(), help='简报 Profile')
    parser.add_argument('--outdir', help='输出目录')
    parser.add_argument('--no-save', action='store_true', help='只输出到 stdout，不落盘')
    args = parser.parse_args()

    config = PROFILES.get(args.profile, PROFILES['creator'])
    final_data = {section: fetch_section(section, sec_config) for section, sec_config in config.items()}

    if args.outdir:
        out_dir = args.outdir
    else:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports', today)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    print(json.dumps(final_data, indent=2, ensure_ascii=False))

    if not args.no_save:
        unified_path = os.path.join(out_dir, f"{args.profile}_briefing_unified.json")
        with open(unified_path, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)
        sources_saved = save_individual_sources(final_data, out_dir)
        print(f"Saved unified report and {len(sources_saved)} source files to {out_dir}", file=sys.stderr)
    else:
        print("JSON output sent to stdout only (--no-save mode)", file=sys.stderr)


if __name__ == "__main__":
    main()
