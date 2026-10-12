import argparse
import json
import requests
from bs4 import BeautifulSoup
import sys
import time
import re
import concurrent.futures
import os
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# Headers for scraping to avoid basic bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

from bs4 import XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def filter_by_hours(items, hours=48):
    """Keep only items published within the last N hours.
    Items whose time cannot be parsed are kept (fail-open)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for item in items:
        t = item.get('time', '')
        try:
            pub = parsedate_to_datetime(str(t))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                result.append(item)
        except Exception:
            result.append(item)  # unparseable → keep
    return result


def filter_items(items, keyword=None):
    if not keyword:
        return items
    keywords = [k.strip() for k in keyword.split(',') if k.strip()]
    # 中文关键词无词边界，英文关键词用 \b；混合时统一子串匹配（对中文更友好）
    pattern = '|'.join(re.escape(k) for k in keywords)
    regex = r'(?i)(' + pattern + r')'
    return [item for item in items if re.search(regex, item.get('title', ''))]


def fetch_url_content(url):
    """抓取正文并抽取段落文本，截断到 3000 字。用于 --deep 深度模式。"""
    if not url or not url.startswith('http'):
        return ""
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()
        text = soup.get_text(separator=' ', strip=True)
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        return text[:3000]
    except Exception:
        return ""


def enrich_items_with_content(items, max_workers=10):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(fetch_url_content, item['url']): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[future]
            try:
                content = future.result()
                if content:
                    item['content'] = content
            except Exception:
                item['content'] = ""
    return items


# --- 自定义抓取器（针对中文站点专门适配，非通用 RSS）---

def fetch_36kr(limit=10, keyword=None):
    """36氪快讯 — 创投 / 科技 / 商业动态。"""
    try:
        response = requests.get("https://36kr.com/newsflashes", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for item in soup.select('.newsflash-item'):
            title_tag = item.select_one('.item-title')
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get('href', '')
            time_tag = item.select_one('.time')
            time_str = time_tag.get_text(strip=True) if time_tag else ""
            items.append({
                "source": "36氪",
                "title": title,
                "url": f"https://36kr.com{href}" if href and not href.startswith('http') else href,
                "time": time_str,
                "heat": ""
            })
        return filter_items(items, keyword)[:limit]
    except Exception:
        return []


def fetch_wallstreetcn(limit=10, keyword=None):
    """华尔街见闻 — 财经 / 宏观 / 市场快讯。"""
    try:
        url = "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30"
        data = requests.get(url, timeout=10).json()
        items = []
        for item in data['data']['items']:
            res = item.get('resource')
            if res and (res.get('title') or res.get('content_short')):
                ts = res.get('display_time', 0)
                time_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else ""
                items.append({
                    "source": "华尔街见闻",
                    "title": res.get('title') or res.get('content_short'),
                    "url": res.get('uri'),
                    "time": time_str
                })
        return filter_items(items, keyword)[:limit]
    except Exception:
        return []


def fetch_tencent(limit=10, keyword=None):
    """腾讯新闻 — 综合中文时事，适合作为二创 / 评论素材。"""
    try:
        url = "https://i.news.qq.com/web_backend/v2/getTagInfo?tagId=aEWqxLtdgmQ%3D"
        data = requests.get(url, headers={"Referer": "https://news.qq.com/"}, timeout=10).json()
        items = []
        for news in data['data']['tabs'][0]['articleList']:
            items.append({
                "source": "腾讯新闻",
                "title": news['title'],
                "url": news.get('url') or news.get('link_info', {}).get('url'),
                "time": news.get('pub_time', '') or news.get('publish_time', '')
            })
        return filter_items(items, keyword)[:limit]
    except Exception:
        return []


# --- RSS 中文源 ---

from rss_parser import fetch_rss_feed


def create_single_rss_fetcher(url, name, hours=None):
    """构造单个 RSS 源抓取器。hours 非空时按时间窗口过滤。"""
    def fetcher(limit=10, keyword=None):
        raw = fetch_rss_feed(url, name, max(limit * 4, 30))
        if hours:
            raw = filter_by_hours(raw, hours=hours)
        return filter_items(raw, keyword)[:limit]
    return fetcher


# key -> (显示名, RSS URL, 领域标签, [时间窗口小时数])
RSS_SOURCES = {
    # 自媒体 / 内容运营 —— 创作者最相关的行业媒体
    'woshipm':   ("人人都是产品经理", "https://www.woshipm.com/feed", "自媒体·运营·内容"),
    # 商业 / 科技 / 消费深度报道 —— 二创与选题素材
    'huxiu':     ("虎嗅", "https://www.huxiu.com/rss/0.xml", "商业·科技·消费"),
    'tmtpost':   ("钛媒体", "https://www.tmtpost.com/feed", "科技·商业"),
    'geekpark':  ("极客公园", "http://www.geekpark.net/rss", "科技·数码·消费"),
    # 数码 / 效率 / 生活方式
    'sspai':     ("少数派", "https://sspai.com/feed", "数码·效率·生活方式"),
    # 技术 / 开发
    'infoq_cn':  ("InfoQ 中文", "https://www.infoq.cn/feed.xml", "技术·开发"),
    # AI 中文精选（跨源编辑稿，日更）
    'aihot':     ("AIHOT", "https://aihot.virxact.com/rss", "AI 资讯", 24),
    # 时事 / 社会话题 —— 二创与话题切入素材
    'thepaper':  ("澎湃新闻", "https://feedx.net/rss/thepaper.xml", "时事·社会", 48),
}


def save_report(data, source_name, out_dir):
    """保存原始抓取结果为 JSON（供 agent 二次处理）。"""
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    safe_name = "".join([c if c.isalnum() else "_" for c in source_name]).lower()
    timestamp = datetime.now().strftime("%H%M")
    json_path = os.path.join(out_dir, f"{safe_name}_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return json_path


def build_sources_map():
    sources_map = {
        '36kr': fetch_36kr,
        'wallstreetcn': fetch_wallstreetcn,
        'tencent': fetch_tencent,
    }
    for key, spec in RSS_SOURCES.items():
        name, url = spec[0], spec[1]
        hours = spec[3] if len(spec) > 3 else None
        sources_map[key] = create_single_rss_fetcher(url, name, hours)
    return sources_map


def source_domain(key):
    """返回源的领域标签（用于展示）。"""
    if key in RSS_SOURCES:
        return RSS_SOURCES[key][2]
    return {'36kr': "创投·科技·商业", 'wallstreetcn': "财经·宏观", 'tencent': "综合时事"}.get(key, "")


def main():
    parser = argparse.ArgumentParser(description="Easel 中文资讯情报抓取器")
    sources_map = build_sources_map()

    parser.add_argument('--source', default='all', help='源 key，逗号分隔（--list-sources 查看全部）')
    parser.add_argument('--limit', type=int, default=10, help='每源最大条数（默认 10）')
    parser.add_argument('--keyword', help='关键词过滤，逗号分隔')
    parser.add_argument('--deep', action='store_true', help='下载正文做深度分析')
    parser.add_argument('--save', action='store_true', help='保存 JSON 到 reports 目录')
    parser.add_argument('--no-save', action='store_true', dest='no_save', help='只输出到 stdout，不落盘')
    parser.add_argument('--outdir', help='自定义输出目录')
    parser.add_argument('--list-sources', action='store_true', help='列出全部源 key')
    args = parser.parse_args()

    if args.list_sources:
        print(f"{'源 Key':<16} | {'名称':<18} | 领域")
        print("-" * 56)
        for key in sources_map:
            name = RSS_SOURCES[key][0] if key in RSS_SOURCES else \
                {'36kr': '36氪', 'wallstreetcn': '华尔街见闻', 'tencent': '腾讯新闻'}.get(key, key)
            print(f"{key:<16} | {name:<18} | {source_domain(key)}")
        return

    to_run = []
    if args.source == 'all':
        to_run = list(sources_map.values())
    else:
        for s in [x.strip() for x in args.source.split(',')]:
            if s in sources_map:
                to_run.append(sources_map[s])

    def run_fetchers(fetchers, limit, kw):
        res = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(func, limit, kw) for func in fetchers]
            for future in concurrent.futures.as_completed(futures):
                try:
                    res.extend(future.result())
                except Exception:
                    pass
        return res

    results = run_fetchers(to_run, args.limit, args.keyword)

    # 关键词过滤后结果稀疏时，用无关键词的宽抓取补足（标注 smart_fill）
    MIN_ITEMS = 5
    if args.keyword and len(results) < MIN_ITEMS:
        sys.stderr.write(f"Smart Fill triggered: {len(results)} items, filling gaps...\n")
        fill_results = run_fetchers(to_run, MIN_ITEMS, None)
        existing_urls = {item.get('url') for item in results}
        existing_titles = {item.get('title') for item in results}
        for item in fill_results:
            if len(results) >= MIN_ITEMS:
                break
            u, t = item.get('url'), item.get('title')
            if u not in existing_urls and t not in existing_titles:
                item['smart_fill'] = True
                if 'time' in item:
                    item['time'] = f"⚠️ {item['time']}"
                results.append(item)
                existing_urls.add(u)
                existing_titles.add(t)

    if args.deep and results:
        sys.stderr.write(f"Deep fetching content for {len(results)} items...\n")
        results = enrich_items_with_content(results)

    print(json.dumps(results, indent=2, ensure_ascii=False))

    if not getattr(args, 'no_save', False) and (args.save or args.source != 'all'):
        if args.outdir:
            out_dir = args.outdir
        else:
            today = datetime.now().strftime('%Y-%m-%d')
            out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports', today)
        md_file = save_report(results, args.source, out_dir)
        sys.stderr.write(f"\n[Saved] Raw Data: {md_file} (Agent to process)\n")


if __name__ == "__main__":
    main()
