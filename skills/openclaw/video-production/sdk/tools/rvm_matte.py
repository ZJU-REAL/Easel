# RVM 抠像：任意口播视频 → RGBA PNG 序列（人像 + alpha）
# 前置：pip install torch torchvision numpy opencv-python
#       模型目录含 model/（RVM 仓库包）与 rvm_mobilenetv3.pth（15MB 权重）
# 用法：python rvm_matte.py --src in.mp4 --out rgba_dir [--rvm <RVM 目录>] [--dsr 0.375]
# 下一步：make_masks.py 把 RGBA 序列转成交付蒙版集（pa_0000.png…）
import argparse
import os
import sys
import time

import numpy as np
import cv2
import torch

ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True, help='输入视频（建议 1080p 代理）')
ap.add_argument('--out', required=True, help='输出目录（rgba_%04d.png）')
ap.add_argument('--rvm', default=os.path.expanduser('~/models/rvm'), help='RVM 目录（含 model/ 与权重）')
ap.add_argument('--weights', default='rvm_mobilenetv3.pth')
ap.add_argument('--dsr', type=float, default=0.375, help='downsample ratio')
a = ap.parse_args()

sys.path.insert(0, a.rvm)
from model import MattingNetwork

os.makedirs(a.out, exist_ok=True)
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'device: {dev}', flush=True)
m = MattingNetwork('mobilenetv3').eval().to(dev)
m.load_state_dict(torch.load(os.path.join(a.rvm, a.weights), map_location='cpu'))
if dev == 'cuda':
    m = m.half()
print('model ready', flush=True)

cap = cv2.VideoCapture(a.src)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print('frames:', n, flush=True)

rec = [None] * 4
i = 0
t0 = time.time()
with torch.no_grad():
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        src = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float().div(255).to(dev)
        if dev == 'cuda':
            src = src.half()
        fgr, pha, *rec = m(src, *rec, downsample_ratio=a.dsr)
        alpha = (pha[0, 0].float().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        rgba = np.dstack([frame, alpha])
        cv2.imwrite(f'{a.out}/rgba_{i:04d}.png', rgba)
        i += 1
        if i % 60 == 0:
            el = time.time() - t0
            print(f'{i}/{n} {el:.1f}s ({i / el:.1f} fps)', flush=True)
cap.release()
print(f'DONE {i} frames in {time.time() - t0:.1f}s', flush=True)
