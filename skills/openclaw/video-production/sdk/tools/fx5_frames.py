import subprocess, os
from PIL import Image, ImageDraw, ImageFont

d = os.environ.get("REMOTION_PROJECT", ".") + "/public/stock/"
out = (os.environ.get("TEMP") or "/tmp") + "/fx5_frames/"
os.makedirs(out, exist_ok=True)

items = [
    ("① 听不懂的名词", "stock_scrambled", [1.5, 3.5]),
    ("② 卖出高价", "stock_money", [2.5, 4.5]),
    ("③ 用AI改变", "stock_worldmap", [2.0, 4.0]),
    ("④ 根本没有", "stock_bubbles", [2.5, 4.5]),
    ("⑤ 在卖什么", "stock_graphs", [0.8, 3.0]),
]

frames = []
for label, name, times in items:
    fl = []
    for t in times:
        p = f"{out}{name}_{t}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", d + name + ".mp4", "-frames:v", "1", p, "-y"],
            timeout=60,
        )
        fl.append(p)
    frames.append((label, fl))

cw, ch = 384, 216
sheet = Image.new("RGB", (cw * 5, 44 + ch * 2), (12, 12, 16))
draw = ImageDraw.Draw(sheet)
font = ImageFont.truetype(os.environ.get("CJK_FONT", "C:/Windows/Fonts/simhei.ttf"), 26)
for i, (label, fl) in enumerate(frames):
    x = i * cw
    draw.text((x + cw // 2, 22), label, font=font, fill=(240, 240, 240), anchor="mm")
    for j, p in enumerate(fl):
        if os.path.exists(p):
            im = Image.open(p).convert("RGB").resize((cw, ch))
            sheet.paste(im, (x, 44 + j * ch))
sheet.save(out + "fx5_check_sheet.png")
print(f"saved {out}fx5_check_sheet.png", sheet.size)

for label, fl in frames:
    for p in fl:
        print(p, os.path.exists(p))
