"""Create a local handoff package without contacting a social platform."""
from __future__ import annotations

import html
import json
import re
import uuid
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

PLATFORMS = {
    "xiaohongshu": ("小红书", "https://creator.xiaohongshu.com/publish/publish?source=official"),
    "douyin": ("抖音", "https://creator.douyin.com/"),
    "kuaishou": ("快手", "https://cp.kuaishou.com/article/publish/video"),
    "weixin-channels": ("视频号", "https://channels.weixin.qq.com/platform/post/create"),
    "zhihu": ("知乎", "https://zhuanlan.zhihu.com/write"),
    "juejin": ("掘金", "https://juejin.cn/editor/drafts/new?v=2"),
    "twitter-x": ("推特 X", "https://x.com/compose/post"),
    "toutiao": ("今日头条", "https://mp.toutiao.com/profile_v4/graphic/publish"),
    "bilibili": ("B站", "https://member.bilibili.com/"),
    "wechat-oa": ("公众号", "https://mp.weixin.qq.com/"),
}
MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif",
                    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".flv", ".ts"}


def publishing_mode(settings: Mapping[str, str]) -> str:
    """Preserve automatic publishing by default; reject unknown configured modes."""
    mode = settings.get("EASEL_PUBLISH_MODE", "").strip().lower()
    return "automated" if mode in ("", "automated") else "manual"


def build_package(outputs: Path, platform: str, title: str, body: str,
                  tags: str, media: list[str], reviewed: bool) -> Path:
    if platform not in PLATFORMS:
        raise ValueError("未知平台")
    if reviewed is not True:
        raise ValueError("请先人工审核当前版本")
    if not title.strip() and not body.strip():
        raise ValueError("标题或正文不能为空")
    if len(media) > 32:
        raise ValueError("一次最多导出 32 个媒体文件")
    root = outputs.resolve()
    files: list[Path] = []
    for relative in dict.fromkeys(media):
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError("媒体路径超出内容库")
        parts = path.relative_to(root).parts
        if any(part.startswith(("_", ".")) for part in parts):
            raise ValueError("不能导出系统目录或隐藏文件")
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError("只能导出内容库中的图片或视频")
        files.append(path)
    if sum(path.stat().st_size for path in files) > 2 * 1024**3:
        raise ValueError("素材超过 2GB，请分批导出")
    destination = root / "_publish" / "manual"
    destination.mkdir(parents=True, exist_ok=True)
    package = destination / f"easel-{platform}-{uuid.uuid4().hex[:12]}.zip"
    label, url = PLATFORMS[platform]
    metadata = {"platform": platform, "title": title, "tags": tags,
                "reviewed": True, "exportedAt": datetime.now(timezone.utc).isoformat(),
                "status": "ready_for_manual_submission", "officialUrl": url,
                "media": [f"media/{index:02d}_{path.name}" for index, path in enumerate(files, 1)]}
    try:
        with zipfile.ZipFile(package, "w") as archive:
            for name, text in {"title.txt": title, "body.txt": body, "tags.txt": tags,
                               "manifest.json": json.dumps(metadata, ensure_ascii=False, indent=2),
                               "使用说明.txt": (
                                   f"{label} · 人工发布包\n\n1. 解压此文件。\n2. 打开 {url}\n"
                                   "3. 在官方页面登录、粘贴标题正文、上传 media 中的素材，并核对话题。\n"
                                   "4. 检查预览，按平台要求标注 AI 辅助创作，再亲自点击发布。\n"
                                   "5. 到 Easel 填写作品链接，人工记录发布结果。\n\n"
                                   "导出不等于上传或发布；此包不包含登录凭证。\n")}.items():
                archive.writestr(name, text, compress_type=zipfile.ZIP_DEFLATED)
            for index, path in enumerate(files, 1):
                archive.write(path, f"media/{index:02d}_{path.name}", compress_type=zipfile.ZIP_STORED)
            if platform == "wechat-oa":
                import markdown
                paragraphs = markdown.markdown(html.escape(body), extensions=["sane_lists"])
                # Raw HTML is escaped above; strip Markdown-generated links and remote images.
                paragraphs = re.sub(r'<a\b[^>]*>', '<a>', paragraphs)
                paragraphs = re.sub(r'<img\b[^>]*>', '', paragraphs)
                paragraphs = paragraphs.replace('<p>', '<p style="margin:18px 0;line-height:1.9">')
                article = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                           '<title>公众号排版预览</title><body><article style="max-width:680px;'
                           'margin:32px auto;padding:24px;font:16px/1.9 sans-serif;color:#222">'
                           f'<h1 style="font-size:24px">{html.escape(title)}</h1>{paragraphs}'
                           '</article></body></html>')
                archive.writestr("article.html", article, compress_type=zipfile.ZIP_DEFLATED)
        return package
    except Exception:
        package.unlink(missing_ok=True)
        raise
