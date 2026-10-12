"""小红书、知乎共用的二维码截图：验证图案，只保存二维码，不兜底整页。"""
from __future__ import annotations

import io
import math
import os
from pathlib import Path
import tempfile


def save_qr(image_bytes: bytes, output: Path, *, minimum_size: int = 0) -> bool:
    """只检测二维码位置，不解码或记录其中的登录令牌。"""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    source = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    image = Image.new("RGBA", source.size, "white")
    image.alpha_composite(source)
    image = image.convert("RGB")
    image = ImageOps.expand(image, border=max(8, math.ceil(max(image.size) * 0.12)), fill="white")
    pixels = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    detector = cv2.QRCodeDetector()
    found, points = detector.detect(pixels)
    if not found and min(image.size) < 320:
        found, points = detector.detect(cv2.resize(
            pixels, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
        if found:
            points = points / 2
    if not found or points is None:
        return False
    corners = points.reshape(-1, 2)
    left = max(0, math.floor(float(corners[:, 0].min())))
    top = max(0, math.floor(float(corners[:, 1].min())))
    right = min(image.width, math.ceil(float(corners[:, 0].max())) + 1)
    bottom = min(image.height, math.ceil(float(corners[:, 1].max())) + 1)
    if right <= left or bottom <= top:
        return False
    if min(right - left, bottom - top) < minimum_size:
        return False
    cropped = image.crop((left, top, right, bottom))
    padding = max(8, math.ceil(max(cropped.size) * 0.12))
    cropped = ImageOps.expand(cropped, border=padding, fill="white")
    if min(cropped.size) < 360:
        scale = 360 / min(cropped.size)
        cropped = cropped.resize(
            (round(cropped.width * scale), round(cropped.height * scale)),
            Image.Resampling.NEAREST)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = io.BytesIO()
    cropped.save(encoded, format="PNG")
    png_bytes = encoded.getvalue()
    try:
        if output.read_bytes() == png_bytes:
            return True
    except FileNotFoundError:
        pass
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(png_bytes)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def capture_qr(page, output: Path, selectors: str, *, attempts: int = 3,
               minimum_size: int = 0) -> None:
    """遍历可见图片/画布及二维码容器，等待实际像素就绪后裁剪。"""
    candidates = [selector.strip() for selector in selectors.split(",") if selector.strip()]
    leaf_selectors = [f"{selector} img, {selector} canvas" for selector in candidates]
    selector_list = leaf_selectors + candidates
    for attempt in range(attempts):
        seen = set()
        for selector in selector_list:
            try:
                elements = page.query_selector_all(selector)
            except Exception:
                continue
            for element in elements:
                try:
                    if not element.is_visible():
                        continue
                    bounds = element.bounding_box()
                    if not bounds or min(bounds["width"], bounds["height"]) < 48:
                        continue
                    if max(bounds["width"], bounds["height"]) > 1200:
                        continue
                    image_bytes = element.screenshot(timeout=3000, animations="disabled")
                    if image_bytes in seen:
                        continue
                    seen.add(image_bytes)
                    if save_qr(image_bytes, output, minimum_size=minimum_size):
                        return
                except Exception:
                    continue
        if attempt < attempts - 1:
            page.wait_for_timeout(800)
    raise RuntimeError("未找到可识别的登录二维码；页面可能尚未加载、被平台拦截或需要切换扫码登录")


def prepare_qr(page, output: Path, selectors: str, switch_selectors: str, *,
               minimum_size: int = 0) -> None:
    """已有可识别二维码时不点击切换控件，以免切回短信登录。"""
    try:
        page.wait_for_selector(f"{selectors}, {switch_selectors}", timeout=15000, state="visible")
    except Exception:
        pass
    try:
        capture_qr(page, output, selectors, minimum_size=minimum_size)
        return
    except RuntimeError as error:
        missing = error
    for element in page.query_selector_all(switch_selectors):
        if element.is_visible():
            element.click(timeout=3000)
            try:
                page.wait_for_selector(selectors, timeout=15000, state="visible")
            except Exception:
                pass
            capture_qr(page, output, selectors, minimum_size=minimum_size)
            return
    raise missing
