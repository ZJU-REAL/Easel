#!/usr/bin/env python3
"""
微信公众号 API 调用

- 图片上传(封面图 / 正文图 / 贴图素材图)
- 新建草稿(图文 news / 贴图 newspic 两种)
- 一站式发布便捷函数 publish_article / publish_newspic

对瞬时错误(5xx / Timeout)自动重试;对应用层错误(如 40164 IP 白名单)直接抛出不重试。
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests

from config import get_config, set_account
from wechat_token import get_access_token


API_TIMEOUT_SEC = 30
API_RETRIES = 2
API_BASE = "https://api.weixin.qq.com/cgi-bin"


# ============================================================
# 共享工具
# ============================================================

_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _guess_mime(path: Path) -> str:
    """根据扩展名推断 MIME 类型,未知扩展名兜底 image/jpeg。"""
    return _MIME_MAP.get(path.suffix.lower(), "image/jpeg")


def _api_request_with_retry(method: str, url: str, retries: int = API_RETRIES, **kwargs) -> requests.Response:
    """
    HTTP 调用 + 5xx/Timeout 重试;4xx 不重试(是客户端问题)。
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, timeout=API_TIMEOUT_SEC, **kwargs)
            if 500 <= resp.status_code < 600 and attempt < retries:
                time.sleep(1.5 ** attempt)
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(1.5 ** attempt)
                continue
            raise
    raise last_exc or RuntimeError("API 请求失败(未知原因)")


# ============================================================
# 图片上传
# ============================================================

def upload_thumb_image(image_path: Union[str, Path]) -> str:
    """
    上传封面图(永久素材)。

    ⚠️ 占用公众号永久素材配额(图片上限 5000 个)。
    返回的 media_id 用于创建草稿时的 thumb_media_id。
    """
    token = get_access_token()
    url = f"{API_BASE}/material/add_material?access_token={token}&type=image"

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    mime_type = _guess_mime(image_path)

    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, mime_type)}
        resp = _api_request_with_retry("POST", url, files=files)

    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"上传封面图失败 [{error_code}]: {error_msg}")

    print(f"封面图上传成功: media_id={data['media_id']}")
    return data["media_id"]


def upload_newspic_image(image_path: Union[str, Path]) -> str:
    """
    上传贴图(图片消息)所需的素材图,返回 media_id。

    ⚠️ 和 `upload_thumb_image` 一样走 `add_material` 永久素材接口,
    占用公众号永久素材配额(图片上限 5000 个)。
    newspic 的 `image_info.image_list[].image_media_id` 必须是永久素材 media_id,
    不能用 `uploadimg` 返回的 URL。

    每个贴图 5-10 张图就要占掉 5-10 个素材名额,发布前心里有数。
    """
    token = get_access_token()
    url = f"{API_BASE}/material/add_material?access_token={token}&type=image"

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    mime_type = _guess_mime(image_path)

    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, mime_type)}
        resp = _api_request_with_retry("POST", url, files=files)

    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"上传 newspic 素材图失败 [{error_code}]: {error_msg}")

    print(f"贴图素材上传成功: media_id={data['media_id']}")
    return data["media_id"]


def upload_content_image(image_path: Union[str, Path]) -> str:
    """
    上传文章正文图片(uploadimg 接口,不占永久素材配额)。

    返回 https:// 格式的 CDN URL(微信有时返回 http,这里统一改 https
    以避免草稿 HTML 里的混合内容阻拦)。
    """
    token = get_access_token()
    url = f"{API_BASE}/media/uploadimg?access_token={token}"

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    mime_type = _guess_mime(image_path)

    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, mime_type)}
        resp = _api_request_with_retry("POST", url, files=files)

    resp.raise_for_status()
    data = resp.json()

    if "url" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"上传正文图片失败 [{error_code}]: {error_msg}")

    img_url = data["url"]
    if img_url.startswith("http://"):
        img_url = "https://" + img_url[len("http://"):]
    print(f"正文图片上传成功: {img_url}")
    return img_url


# ============================================================
# 草稿
# ============================================================

def add_newspic_draft(
    title: str,
    content: str,
    image_media_ids: List[str],
    author: str = "",
    need_open_comment: int = 0,
    only_fans_can_comment: int = 0,
) -> str:
    """
    新建"贴图"(图片消息)草稿。

    对应微信 `/cgi-bin/draft/add` 接口,`article_type = "newspic"`。
    和普通图文草稿的区别:
      - 没有 thumb_media_id,封面默认用 image_list[0]
      - 没有 HTML content,content 是一段纯文本短描述(100-300 字)
      - image_list 必须是已上传过的永久素材 media_id(用 `upload_newspic_image` 得到)

    Args:
        title: 标题(可选,微信允许空)
        content: 短描述文本(建议 100-300 字,太长不好看)
        image_media_ids: 5-20 张图的 media_id 列表,顺序即展示顺序,第 1 张是封面
        author: 作者名
        need_open_comment: 1 开启留言 / 0 关闭
        only_fans_can_comment: 1 只粉丝可留言 / 0 所有人

    Returns:
        草稿 media_id(字符串)
    """
    if not image_media_ids:
        raise ValueError("newspic 至少需要 1 张图")
    if len(image_media_ids) > 20:
        raise ValueError(f"newspic 最多 20 张图,当前 {len(image_media_ids)} 张")

    token = get_access_token()
    url = f"{API_BASE}/draft/add?access_token={token}"

    article: Dict[str, Any] = {
        "article_type": "newspic",
        "title": title,
        "content": content,
        "need_open_comment": need_open_comment,
        "only_fans_can_comment": only_fans_can_comment,
        "image_info": {
            "image_list": [{"image_media_id": mid} for mid in image_media_ids],
        },
    }
    if author:
        article["author"] = author

    payload = {"articles": [article]}

    resp = _api_request_with_retry(
        "POST", url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"新建贴图草稿失败 [{error_code}]: {error_msg}")

    print(f"贴图草稿创建成功! media_id={data['media_id']}")
    return data["media_id"]


def add_draft(articles: Union[Dict[str, Any], List[Dict[str, Any]]]) -> str:
    """
    新建草稿。

    Args:
        articles: 单篇(dict)或多篇(list[dict])。每篇字典必选字段:
            - title, content (HTML), thumb_media_id
            可选: author, digest, content_source_url, need_open_comment, only_fans_can_comment

    Returns:
        str: 草稿 media_id
    """
    token = get_access_token()
    url = f"{API_BASE}/draft/add?access_token={token}"

    if isinstance(articles, dict):
        articles = [articles]

    payload = {"articles": articles}

    resp = _api_request_with_retry(
        "POST", url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"新建草稿失败 [{error_code}]: {error_msg}")

    print(f"草稿创建成功! media_id={data['media_id']}")
    return data["media_id"]


# ============================================================
# 便捷函数
# ============================================================

def publish_article(
    title: str,
    html_content: str,
    cover_image_path: Union[str, Path],
    author: str = "",
    digest: str = "",
    source_url: str = "",
    account_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    一站式发布:上传封面图 → 创建草稿。

    Args:
        title: 文章标题
        html_content: 已排版的 HTML
        cover_image_path: 封面图路径
        author: 作者(空时从账号配置读)
        digest: 摘要(自动截 120 字)
        source_url: 原文链接
        account_name: 账号名(可选,默认用当前激活账号)

    Returns:
        {"media_id": str, "status": "success", "account": str}
    """
    if account_name:
        set_account(account_name)

    config = get_config(account_name)
    if not author:
        author = config.get("author", "")

    account_display = config.get("account_name", "default")
    print(f"开始发布文章: {title}")
    print(f"目标账号: {account_display}")
    print("=" * 50)

    print("[1/2] 上传封面图...")
    thumb_media_id = upload_thumb_image(cover_image_path)

    print("[2/2] 创建草稿...")
    article = {
        "title": title,
        "content": html_content,
        "thumb_media_id": thumb_media_id,
        "author": author,
        "digest": digest[:120] if digest else "",
    }
    if source_url:
        article["content_source_url"] = source_url

    media_id = add_draft(article)

    print("=" * 50)
    print("发布成功! 文章已保存到草稿箱。")
    print("请登录微信公众平台查看和发布。")

    return {"media_id": media_id, "status": "success", "account": account_display}


def publish_newspic(
    title: str,
    content: str,
    image_paths: List[Union[str, Path]],
    author: str = "",
    account_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    一站式发布贴图(图片消息):
      1. 逐张上传为永久素材,收集 media_id
      2. 调用 draft/add 创建 newspic 草稿

    Args:
        title: 标题
        content: 短文本(100-300 字)
        image_paths: 图片本地路径列表,5-20 张。第 1 张作为封面。
        author: 作者名(空时从账号配置读)
        account_name: 账号名(可选,默认用当前激活账号)

    Returns:
        {"media_id": str, "status": "success", "account": str,
         "image_media_ids": list[str]}
    """
    if account_name:
        set_account(account_name)

    config = get_config(account_name)
    if not author:
        author = config.get("author", "")

    account_display = config.get("account_name", "default")
    print(f"开始发布贴图: {title or '(无标题)'}")
    print(f"目标账号: {account_display}")
    print(f"图片张数: {len(image_paths)}")
    print("=" * 50)

    media_ids: List[str] = []
    for i, path in enumerate(image_paths, start=1):
        print(f"[{i}/{len(image_paths)}] 上传第 {i} 张...")
        media_ids.append(upload_newspic_image(path))

    print("\n创建贴图草稿...")
    draft_id = add_newspic_draft(
        title=title,
        content=content,
        image_media_ids=media_ids,
        author=author,
    )

    print("=" * 50)
    print("发布成功! 贴图已保存到草稿箱。")
    print("请登录微信公众平台查看和发布。")

    return {
        "media_id": draft_id,
        "status": "success",
        "account": account_display,
        "image_media_ids": media_ids,
    }
