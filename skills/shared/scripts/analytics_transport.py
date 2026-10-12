"""Bounded, credential-free prefetch of Xiaohongshu's public creator assets."""
from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests


def _route_assets(assets: dict[str, bytes]) -> list[str]:
    runtime_url = next((url for url in assets if "/bundler-runtime." in url), None)
    index_url = next((url for url in assets if re.search(r"/index\.[a-f0-9]+\.js$", url)), None)
    if runtime_url is None or index_url is None:
        return []
    runtime = assets[runtime_url].decode("utf-8", "replace")
    index = assets[index_url].decode("utf-8", "replace")
    chunk_ids = []
    for route in ("home", "noteManager"):
        match = re.search(r'name:"' + route + r'",path:"[^"]+",component:(.{0,1600}?)meta:', index)
        if match:
            chunk_ids.extend(re.findall(r'\.e\("(\d+)"\)', match.group(1)))
    paths = []
    root = runtime_url.rsplit("resource/js/", 1)[0]
    for method, folder in ((".u=", "js"), (".miniCssF=", "css")):
        start = runtime.find(method)
        if start < 0:
            continue
        end = runtime.find("},", start)
        hashes = dict(re.findall(r'(\d+):"([a-f0-9]{8,})"', runtime[start:end]))
        for chunk_id in dict.fromkeys(chunk_ids):
            if chunk_id in hashes:
                paths.append(f"{root}resource/{folder}/async/{chunk_id}.{hashes[chunk_id]}.{folder}")
    return paths[:64]


def prepare(context, home_url: str, cache_dir: Path) -> None:
    try:
        response = context.request.get(home_url, timeout=5000)
        if response.status != 200:
            return
        urls = list(dict.fromkeys(
            url for url in re.findall(r'<(?:script|link)\b[^>]+(?:src|href)=["\']([^"\']+)',
                                      response.text())
            if urlparse(url).scheme == "https"
            and urlparse(url).hostname == "fe-static.xhscdn.com"
            and urlparse(url).path.endswith((".js", ".css"))
        ))[:48]
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    def download(url, deadline):
        cached = cache_dir / (hashlib.sha256(url.encode()).hexdigest() + Path(urlparse(url).path).suffix)
        try:
            if cached.is_file() and time.time() - cached.stat().st_mtime < 7 * 86400:
                body = cached.read_bytes()
                if body:
                    return url, body
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(url, timeout=(min(1.5, remaining), min(3, remaining)),
                                       allow_redirects=False)
                if response.status_code != 200 or not response.content or len(response.content) > 5 * 1024 * 1024:
                    return None
                body = response.content
                temporary = cached.with_suffix(cached.suffix + ".tmp")
                try:
                    temporary.write_bytes(body)
                    temporary.replace(cached)
                finally:
                    temporary.unlink(missing_ok=True)
                return url, body
        except Exception:
            return None

    assets = {}
    for batch in (urls, None):
        if batch is None:
            batch = _route_assets(assets)
        deadline = time.monotonic() + 5
        batch_deadline = deadline

        def download_batch(url, expires=batch_deadline):
            return download(url, expires)

        executor = ThreadPoolExecutor(max_workers=16)
        try:
            futures = [executor.submit(download_batch, url) for url in batch]
            for future in as_completed(futures, timeout=5):
                asset = future.result()
                if asset is not None:
                    assets[asset[0]] = asset[1]
        except FuturesTimeoutError:
            pass
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    try:
        for old in sorted(cache_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)[128:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
    if not assets:
        return

    def handle(route, request):
        body = assets.get(request.url)
        if body is None:
            route.continue_()
        else:
            route.fulfill(body=body, content_type=(
                "text/css" if urlparse(request.url).path.endswith(".css") else "application/javascript"))

    context.route("https://fe-static.xhscdn.com/**", handle)
