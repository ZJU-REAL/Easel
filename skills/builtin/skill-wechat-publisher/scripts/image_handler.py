#!/usr/bin/env python3
"""
图片处理模块

负责文章图片的完整生命周期：
1. 从网络搜索并下载相关图片
2. 图片格式检查和基本处理
3. 上传到微信服务器获取CDN链接
4. 替换文章中的图片引用

搜索图片时会优先寻找无版权限制的图片源。
"""

import os
import re
import sys
import json
import hashlib
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse, quote

# 导入微信API
sys.path.insert(0, str(Path(__file__).parent))
from wechat_api import upload_content_image, upload_thumb_image, set_account


# ============================================================
# 上传去重 manifest
# ============================================================
# 目的：同一张图在多次发布中避免重复上传到微信 uploadimg 接口。
# 以文件字节的 md5 作 key，CDN URL 作 value，持久化到 temp_dir。
# 注：封面图走永久素材接口(add_material)，用户期望每次草稿都是新的封面,
# 因此只对正文图片 upload_content_image 做去重。

MANIFEST_FILENAME = ".uploaded_manifest.json"


def _manifest_path(temp_dir):
    """返回 manifest 文件路径。"""
    return Path(temp_dir) / MANIFEST_FILENAME


def hash_file_bytes(path):
    """计算文件字节的 md5 (去重的 key)。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(temp_dir):
    """
    加载 temp_dir 下的上传去重 manifest。
    文件缺失/损坏时返回空 dict,不抛异常。
    """
    mf = _manifest_path(temp_dir)
    if not mf.exists():
        return {}
    try:
        with open(mf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
        return {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"  警告：manifest 读取失败，将按空处理 ({mf}): {e}")
        return {}


def save_manifest(temp_dir, manifest):
    """把 manifest dict 写回磁盘,失败只打印警告,不阻断发布。"""
    mf = _manifest_path(temp_dir)
    try:
        mf.parent.mkdir(parents=True, exist_ok=True)
        with open(mf, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"  警告：manifest 写入失败 ({mf}): {e}")


def upload_content_image_cached(local_path, temp_dir, manifest=None):
    """
    带 md5 去重的正文图片上传。
    - manifest 命中 → 直接返回缓存 URL,打印"跳过重复上传"
    - 未命中 → 调用 upload_content_image 并写回 manifest

    Args:
        local_path: 本地图片路径
        temp_dir: manifest 目录(通常与图片 temp_dir 相同)
        manifest: 可选,外部传入以避免反复磁盘 IO;None 时从磁盘加载

    Returns:
        微信 CDN URL
    """
    owns_manifest = manifest is None
    if manifest is None:
        manifest = load_manifest(temp_dir)

    digest = hash_file_bytes(local_path)
    cached = manifest.get(digest)
    if cached:
        print(f"  跳过重复上传 (md5={digest[:8]}…) → {cached[:60]}…")
        return cached

    wechat_url = upload_content_image(local_path)
    manifest[digest] = wechat_url
    if owns_manifest:
        save_manifest(temp_dir, manifest)
    return wechat_url


# ============================================================
# 图片下载
# ============================================================

def download_image(url, save_dir, filename=None, timeout=15, max_retries=2):
    """
    从URL下载图片到本地，支持自动重试。

    Args:
        url: 图片URL
        save_dir: 保存目录
        filename: 文件名（可选，默认根据URL生成）
        timeout: 超时时间
        max_retries: 最大重试次数

    Returns:
        str: 本地文件路径，下载失败返回None
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        # 从URL推断文件名
        parsed = urlparse(url)
        path = parsed.path
        ext = Path(path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".jpg"
        url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
        filename = f"img_{url_hash}{ext}"

    filepath = save_dir / filename

    for attempt in range(max_retries + 1):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            resp.raise_for_status()

            # 检查是否真的是图片(放在重试循环内,允许瞬时的错误 content-type 后续重试)
            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                if attempt < max_retries:
                    print(f"  非图片类型 ({content_type})，重试 ({attempt+1}/{max_retries})...")
                    continue
                print(f"  警告：{url[:60]} 返回的不是图片类型 ({content_type})")
                return None

            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 检查文件大小（微信限制图片不超过10MB）
            file_size = filepath.stat().st_size
            if file_size < 1000:  # 小于1KB可能不是有效图片
                filepath.unlink()
                return None
            if file_size > 10 * 1024 * 1024:
                print(f"  警告：图片过大 ({file_size/1024/1024:.1f}MB)，尝试跳过：{url[:60]}")
                filepath.unlink()
                return None

            # WebP格式转JPG（微信对WebP支持不稳定）
            if filepath.suffix.lower() == ".webp":
                jpg_path = filepath.with_suffix(".jpg")
                converted = convert_webp_to_jpg(str(filepath), str(jpg_path))
                if converted:
                    filepath.unlink()
                    filepath = jpg_path

            print(f"  下载成功：{filepath.name} ({file_size/1024:.0f}KB)")
            return str(filepath)

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                print(f"  下载超时，重试 ({attempt+1}/{max_retries})...")
                continue
            print(f"  下载超时失败：{url[:60]}")
        except Exception as e:
            if attempt < max_retries:
                print(f"  下载出错，重试 ({attempt+1}/{max_retries})...")
                continue
            print(f"  下载失败 {url[:60]}: {e}")

        if filepath.exists():
            filepath.unlink()

    return None


def convert_webp_to_jpg(webp_path, jpg_path):
    """将WebP图片转换为JPG格式（微信对WebP支持不稳定）"""
    try:
        from PIL import Image
        img = Image.open(webp_path).convert("RGB")
        img.save(jpg_path, "JPEG", quality=90)
        return True
    except ImportError:
        # 没有Pillow就保留webp，微信新版本也能显示
        return False
    except Exception:
        return False


def download_images_from_urls(urls, save_dir):
    """
    批量下载图片。

    Args:
        urls: URL列表
        save_dir: 保存目录

    Returns:
        list[dict]: 下载结果列表 [{"url": ..., "local_path": ...}, ...]
    """
    results = []
    for url in urls:
        local_path = download_image(url, save_dir)
        results.append({
            "url": url,
            "local_path": local_path,
            "success": local_path is not None
        })
    return results


# ============================================================
# 图片上传到微信
# ============================================================

def upload_images_to_wechat(image_paths, as_thumb=False):
    """
    批量上传图片到微信服务器。

    Args:
        image_paths: 本地图片路径列表
        as_thumb: 是否作为封面图上传（永久素材）

    Returns:
        dict: {本地路径: 微信URL/media_id}
    """
    mapping = {}
    for path in image_paths:
        if not path or not Path(path).exists():
            continue
        try:
            if as_thumb:
                result = upload_thumb_image(path)
            else:
                result = upload_content_image(path)
            mapping[path] = result
        except Exception as e:
            print(f"上传失败 {path}: {e}")
            mapping[path] = None
    return mapping


# ============================================================
# 文章图片替换
# ============================================================

def replace_images_in_html(html_content, image_mapping):
    """
    将HTML中的本地图片路径替换为微信CDN链接。

    Args:
        html_content: HTML字符串
        image_mapping: {本地路径或原始URL: 微信CDN URL}

    Returns:
        str: 替换后的HTML
    """
    for original, wechat_url in image_mapping.items():
        if wechat_url:
            html_content = html_content.replace(original, wechat_url)
    return html_content


def replace_images_in_markdown(md_content, image_mapping):
    """
    将Markdown中的图片路径替换为微信CDN链接。

    Args:
        md_content: Markdown字符串
        image_mapping: {原始路径/URL: 微信CDN URL}

    Returns:
        str: 替换后的Markdown
    """
    for original, wechat_url in image_mapping.items():
        if wechat_url:
            md_content = md_content.replace(original, wechat_url)
    return md_content


def extract_images_from_markdown(md_content):
    """
    从Markdown中提取所有图片引用。

    Returns:
        list[dict]: [{"alt": "描述", "url": "路径/URL"}, ...]
    """
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    matches = re.findall(pattern, md_content)
    return [{"alt": alt, "url": url} for alt, url in matches]


def extract_images_from_html(html_content):
    """
    从HTML中提取所有img标签的src。

    Returns:
        list[str]: 图片URL列表
    """
    pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    return re.findall(pattern, html_content)


# ============================================================
# 完整图片处理流程
# ============================================================

def process_article_images(md_content, temp_dir=None, base_dir=None):
    """
    完整的文章图片处理流程：
    1. 提取Markdown中的所有图片引用
    2. 下载外部图片到本地(串行,便于打印进度和控制重试)
    3. 并行上传到微信服务器(md5 去重,已上传过的直接复用 CDN URL)
    4. 替换Markdown中的图片链接

    环境变量:
        WECHAT_UPLOAD_WORKERS - 并发上传的线程数(默认 4,设为 1 即为串行)

    Args:
        md_content: Markdown文章内容
        temp_dir: 临时图片目录(同时用于存放 .uploaded_manifest.json)。
                  None(默认)时自动创建 mkdtemp 隔离目录，避免并发冲突。
        base_dir: 解析相对图片路径的基准目录(通常是 article.md 所在目录)。
                  None 时相对路径按进程 cwd 解析(旧行为)。

    Returns:
        tuple: (处理后的Markdown, 图片映射字典, 第一张图片的本地路径)
    """
    if temp_dir is None:
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="wechat_images_")
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    images = extract_images_from_markdown(md_content)
    if not images:
        print("文章中没有找到图片引用")
        return md_content, {}, None

    print(f"发现 {len(images)} 张图片，开始处理...")

    # ------------------------------------------------------------
    # 阶段 1: 逐张解析为本地路径(download/已本地)
    # ------------------------------------------------------------
    # resolved[i] = (url, local_path or None)
    resolved = []
    for i, img in enumerate(images):
        url = img["url"]
        alt = img["alt"]
        print(f"[{i+1}/{len(images)}] 处理图片：{alt or url[:50]}")

        local_path = None
        if url.startswith(("http://", "https://")):
            local_path = download_image(url, temp_dir, filename=f"article_{i}.jpg")
        else:
            p = Path(url)
            if not p.is_absolute() and base_dir is not None and not p.exists():
                p = Path(base_dir) / p
            if p.exists():
                local_path = str(p)
            else:
                print(f"  跳过无效路径：{url}")

        resolved.append((url, local_path))

    # first_image_path 用第一个成功解析到本地的图片(保持原顺序)
    first_image_path = next((lp for _, lp in resolved if lp), None)

    # ------------------------------------------------------------
    # 阶段 2: 并行上传到微信(带 md5 去重)
    # ------------------------------------------------------------
    try:
        workers = int(os.environ.get("WECHAT_UPLOAD_WORKERS", "4"))
    except ValueError:
        workers = 4
    workers = max(1, min(workers, 16))

    manifest = load_manifest(temp_dir)
    mapping = {}  # 原始URL → 微信URL

    def _do_upload(idx, url, local_path):
        """单张上传任务,返回 (idx, url, wechat_url or None)。"""
        if not local_path:
            return idx, url, None
        try:
            wechat_url = upload_content_image_cached(local_path, temp_dir, manifest=manifest)
            print(f"  [{idx+1}] 上传成功 → {wechat_url[:60]}...")
            return idx, url, wechat_url
        except Exception as e:
            print(f"  [{idx+1}] 上传失败 ({local_path}): {e}")
            return idx, url, None

    if workers == 1 or len(resolved) <= 1:
        # 串行路径
        for idx, (url, local_path) in enumerate(resolved):
            _, _, wechat_url = _do_upload(idx, url, local_path)
            if wechat_url:
                mapping[url] = wechat_url
    else:
        # 并行路径。ThreadPoolExecutor 在 GIL 下对 IO-bound 上传足够。
        # manifest 写入在 futures 收集后串行执行(各 future 只更新 mapping),
        # 最终由 save_manifest 一次性落盘,不存在并发写竞争。
        # 同一 digest 若并发命中未缓存路径,最多多传一次,结果 URL 等价,可接受。
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_do_upload, idx, url, local_path)
                for idx, (url, local_path) in enumerate(resolved)
            ]
            for fut in futures:
                idx, url, wechat_url = fut.result()
                if wechat_url:
                    mapping[url] = wechat_url

    # 批量持久化 manifest(一次性落盘,避免并发写竞争)
    save_manifest(temp_dir, manifest)

    # 替换Markdown中的图片链接
    processed_md = replace_images_in_markdown(md_content, mapping)

    print(f"图片处理完成：{len(mapping)}/{len(images)} 张成功上传(并发={workers})")
    return processed_md, mapping, first_image_path


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="微信公众号图片处理工具")
    parser.add_argument("--account", help="指定公众号账号（对应 wechat-publisher.yaml 中的账号名）")
    subparsers = parser.add_subparsers(dest="command")

    # download 命令
    sub_dl = subparsers.add_parser("download", help="下载图片")
    sub_dl.add_argument("url", help="图片URL")
    sub_dl.add_argument("-d", "--dir", default=None, help="保存目录(默认 mkdtemp 自动创建)")

    # upload 命令
    sub_up = subparsers.add_parser("upload", help="上传图片到微信")
    sub_up.add_argument("path", help="本地图片路径")
    sub_up.add_argument("--thumb", action="store_true", help="作为封面图上传")

    # process 命令
    sub_proc = subparsers.add_parser("process", help="处理文章中的所有图片")
    sub_proc.add_argument("markdown_file", help="Markdown文件路径")
    sub_proc.add_argument("-o", "--output", help="输出文件路径")

    args = parser.parse_args()

    # 设置全局账号
    if args.account:
        set_account(args.account)

    if args.command == "download":
        path = download_image(args.url, args.dir)
        if path:
            print(json.dumps({"local_path": path}))
        else:
            print("下载失败", file=sys.stderr)
            sys.exit(1)

    elif args.command == "upload":
        if args.thumb:
            result = upload_thumb_image(args.path)
            print(json.dumps({"media_id": result}))
        else:
            result = upload_content_image(args.path)
            print(json.dumps({"url": result}))

    elif args.command == "process":
        with open(args.markdown_file, "r", encoding="utf-8") as f:
            md = f.read()
        processed, mapping, cover = process_article_images(md)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(processed)
        print(json.dumps({
            "cover_image": cover,
            "images_processed": len(mapping),
            "mapping": mapping
        }, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
