#!/usr/bin/env python3
"""
微信公众号 API - 对外统一入口 facade

实际实现已拆分到:
  - config.py        账号配置加载(wechat-publisher.yaml)
  - wechat_token.py  access_token 获取与缓存
  - api.py           图片上传 / 草稿 / 发布

本文件只做两件事:
  1. 重新导出上述三个模块的公共 API(保持 `from wechat_api import xxx` 不变)
  2. 提供命令行入口(`python3 scripts/wechat_api.py list-accounts` 等)
"""

# 按依赖顺序 re-export
from config import (  # noqa: F401
    ConfigError,
    set_account,
    get_account_name,
    list_accounts,
    get_config,
    load_env,
    get_image_style,
    list_image_styles,
    resolve_image_style,
    DEFAULT_IMAGE_STYLE,
)
from wechat_token import (  # noqa: F401
    get_access_token,
)
from api import (  # noqa: F401
    upload_thumb_image,
    upload_content_image,
    upload_newspic_image,
    add_draft,
    add_newspic_draft,
    publish_article,
    publish_newspic,
)


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="微信公众号 API 工具")
    parser.add_argument("--account", help="指定公众号账号(对应 wechat-publisher.yaml 中的账号名)")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-accounts", help="列出所有已配置的账号")

    subparsers.add_parser("token", help="获取 access_token")

    sub_upload = subparsers.add_parser("upload-thumb", help="上传封面图(永久素材)")
    sub_upload.add_argument("image", help="图片文件路径")

    sub_img = subparsers.add_parser("upload-img", help="上传正文图片")
    sub_img.add_argument("image", help="图片文件路径")

    sub_draft = subparsers.add_parser("draft", help="从 HTML 创建草稿")
    sub_draft.add_argument("--title", required=True, help="文章标题")
    sub_draft.add_argument("--content", required=True, help="HTML 内容文件路径")
    sub_draft.add_argument("--cover", required=True, help="封面图路径")
    sub_draft.add_argument("--author", default="", help="作者(默认从账号配置读)")
    sub_draft.add_argument("--digest", default="", help="摘要")

    sub_newspic = subparsers.add_parser("newspic", help="从一组图片创建贴图(图片消息)草稿")
    sub_newspic.add_argument("--title", default="", help="标题(可空)")
    sub_newspic.add_argument("--content", required=True,
                             help="短文本(100-300 字),可以是字符串或文件路径")
    sub_newspic.add_argument("--images", required=True, nargs="+",
                             help="图片路径列表(5-20 张),顺序即展示顺序,第 1 张是封面")
    sub_newspic.add_argument("--author", default="", help="作者(默认从账号配置读)")

    subparsers.add_parser("list-image-styles", help="列出所有可用配图风格")

    args = parser.parse_args()

    if args.account:
        set_account(args.account)

    try:
        if args.command == "list-accounts":
            accounts = list_accounts()
            if not accounts:
                print("未找到任何账号配置。请参考 wechat-publisher.yaml.example 创建 wechat-publisher.yaml。")
            else:
                print(f"已配置 {len(accounts)} 个账号:")
                for acc in accounts:
                    default_mark = " (默认)" if acc.get("is_default") else ""
                    print(
                        f"  {acc['key']:12s}  {acc['name']:16s}  "
                        f"AppID: {acc['app_id']}  作者: {acc['author'] or '-'}{default_mark}"
                    )

        elif args.command == "token":
            token = get_access_token()
            print(f"access_token: {token}")

        elif args.command == "upload-thumb":
            media_id = upload_thumb_image(args.image)
            print(json.dumps({"media_id": media_id}, ensure_ascii=False))

        elif args.command == "upload-img":
            url = upload_content_image(args.image)
            print(json.dumps({"url": url}, ensure_ascii=False))

        elif args.command == "draft":
            with open(args.content, "r", encoding="utf-8") as f:
                html = f.read()
            result = publish_article(
                title=args.title,
                html_content=html,
                cover_image_path=args.cover,
                author=args.author,
                digest=args.digest,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.command == "newspic":
            # content 允许是文件路径也允许是字符串
            content_arg = args.content
            from pathlib import Path as _P
            if _P(content_arg).exists():
                with open(content_arg, "r", encoding="utf-8") as f:
                    content_text = f.read().strip()
            else:
                content_text = content_arg
            result = publish_newspic(
                title=args.title,
                content=content_text,
                image_paths=args.images,
                author=args.author,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.command == "list-image-styles":
            styles = list_image_styles()
            if not styles:
                print("未找到任何配图风格(assets/image-styles/ 为空)")
            else:
                print(f"已配置 {len(styles)} 个配图风格:")
                for s in styles:
                    default_mark = " (默认)" if s == DEFAULT_IMAGE_STYLE else ""
                    meta = get_image_style(s)
                    print(f"  {s:26s}  {meta.get('display_name', ''):16s}  "
                          f"{meta.get('description', '')[:40]}...{default_mark}")

        else:
            parser.print_help()

    except ConfigError as e:
        print(f"[配置错误] {e}", file=sys.stderr)
        sys.exit(1)
