#!/usr/bin/env python3
"""把已校验的公众号正文片段（纯 <section>）包成带「复制」按钮的浏览器预览页。

用户打开预览页 → 点右上角「复制到公众号」→ 按钮选中并复制里面渲染后的富文本
（等价手动 Ctrl+A/Ctrl+C，样式全保留）→ 到公众号编辑器 Ctrl+V 粘贴即可。

按钮和 JS 只存在于预览外壳里，**不在被复制的 section 内**，所以粘进公众号的
仍是干净合规的正文，不含 <script>/<button>。校验请对原始 section 文件跑
validate_gzh_html.py（本预览页含 script/style，不参与校验）。

用法:
    wrap_preview.py <section.html> [output.html]
    默认输出 <section去扩展名>_预览.html
"""

import base64
import mimetypes
import os
import re
import sys
from urllib.parse import unquote

# 把正文里引用本地图片的 <img src="xxx.png"> 内联成 base64 data-URI。
# 复制粘贴进公众号时，图片字节随剪贴板一起走，公众号会把内联图上传到自己 CDN；
# 否则它要回源抓 src 指向的 Easel 本地/相对地址 → 抓不到 → 图片超时/裂图。
_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])(.*?)\2', re.IGNORECASE)
_INLINE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def _inline_images(html, base_dir):
    def repl(m):
        prefix, quote, src = m.group(1), m.group(2), m.group(3)
        s = src.strip()
        # 已是 data-URI / 远程 http(s) / 协议相对，跳过
        if s.startswith(("data:", "http://", "https://", "//")):
            return m.group(0)
        path = unquote(s.split("?", 1)[0].split("#", 1)[0])
        img = path if os.path.isabs(path) else os.path.join(base_dir, path)
        ext = os.path.splitext(img)[1].lower()
        if ext not in _INLINE_EXT or not os.path.isfile(img):
            return m.group(0)  # 找不到/不支持就原样保留
        try:
            data = open(img, "rb").read()
        except OSError:
            return m.group(0)
        mime = mimetypes.guess_type(img)[0] or ("image/svg+xml" if ext == ".svg" else "image/png")
        b64 = base64.b64encode(data).decode("ascii")
        return f'{prefix}{quote}data:{mime};base64,{b64}{quote}'
    return _IMG_SRC.sub(repl, html)


def main():
    if len(sys.argv) < 2:
        print("用法: wrap_preview.py <section.html> [output.html]")
        sys.exit(1)
    src = sys.argv[1]
    if not os.path.isfile(src):
        print(f"✗ 找不到文件: {src}")
        sys.exit(1)

    content = open(src, encoding="utf-8").read().strip()
    # 本地图内联 base64，让「复制到公众号」粘贴后图片不裂（相对路径按 section 文件所在目录解析）
    content = _inline_images(content, os.path.dirname(os.path.abspath(src)))
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "assets", "preview-template.html")
    tpl = open(tpl_path, encoding="utf-8").read()

    title = os.path.splitext(os.path.basename(src))[0]
    out_html = tpl.replace("{{TITLE}}", title).replace("<!--GZH_CONTENT-->", content)

    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_预览.html"
    open(out, "w", encoding="utf-8").write(out_html)
    print(f"✓ 已生成带「复制」按钮的预览页: {out}")
    print("  用浏览器打开它，点右上角「复制到公众号」，再去公众号编辑器 Ctrl/⌘+V 粘贴。")


if __name__ == "__main__":
    main()
