# 交付蒙版集：RGBA 序列 → 黑底 + alpha 的逐帧 PNG（CSS mask-image 直接引用）
# 收紧配方（实测）：alpha remap [lo,hi] + 高斯 blur（去发丝 / 软边残留）
# 用法：python make_masks.py --src rgba_dir --out masks_dir [--lo 50 --hi 200 --blur 0.6]
# 产出：<out>/pa_0000.png …（按源文件排序编号，与帧序一一对应；供 FX-16 人物蒙版分层使用）
import argparse
import glob
import os

from PIL import Image, ImageFilter

ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True, help='RGBA 序列目录（*.png）')
ap.add_argument('--out', required=True, help='输出蒙版目录')
ap.add_argument('--lo', type=int, default=50)
ap.add_argument('--hi', type=int, default=200)
ap.add_argument('--blur', type=float, default=0.6)
a = ap.parse_args()

os.makedirs(a.out, exist_ok=True)
lut = [max(0, min(255, int((v - a.lo) / (a.hi - a.lo) * 255))) for v in range(256)]

files = sorted(glob.glob(os.path.join(a.src, '*.png')))
n = 0
for i, p in enumerate(files):
    alpha = Image.open(p).getchannel('A').point(lut)
    if a.blur > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(a.blur))
    out = Image.new('RGBA', alpha.size, (0, 0, 0, 0))
    out.putalpha(alpha)
    out.save(f'{a.out}/pa_{i:04d}.png')
    n += 1
print(f'masks: {n} -> {a.out}')
