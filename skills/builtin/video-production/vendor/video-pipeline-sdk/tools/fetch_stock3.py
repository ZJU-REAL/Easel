import subprocess, os, json
from PIL import Image, ImageDraw, ImageFont

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
d = os.environ.get("REMOTION_PROJECT", ".") + "/public/stock/"
TMP = os.environ.get("TEMP") or "/tmp"
os.makedirs(TMP + "/fx5b", exist_ok=True)

items = [
    ("stock_bubbles", 51869, "blurry-sky-background-with-bubbles-floating-in-front", "bubbles"),
    ("stock_dunes", 4149, "dunes-in-the-sahara-desert", "desert"),
]

newlog = []
for name, vid, slug, cat in items:
    for res in ["1080", "720", "360"]:
        url = f"https://assets.mixkit.co/videos/{vid}/{vid}-{res}.mp4"
        raw = d + name + "_raw.mp4"
        try:
            subprocess.run(["curl", "-sL", "-A", UA, "-o", raw, url], capture_output=True, timeout=300)
        except Exception as e:
            print(name, res, "ERR", e)
            continue
        if not os.path.exists(raw) or os.path.getsize(raw) < 200000 or b"ftyp" not in open(raw, "rb").read(16):
            continue
        tmp = d + name + "_t.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", raw,
             "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
             "-c:v", "libx264", "-crf", "23", "-preset", "fast",
             "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-an", "-movflags", "+faststart", tmp],
            capture_output=True, text=True, timeout=600,
        )
        os.remove(raw)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 100000:
            os.rename(tmp, d + name + ".mp4")
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration", "-of", "csv=p=0", d + name + ".mp4"], capture_output=True, text=True).stdout.strip()
            print(f"{name} [{res}] OK {os.path.getsize(d+name+'.mp4')//1048576}MB {probe}")
            newlog.append({"name": name, "vid": vid, "slug": slug, "category": cat, "res": res, "url": url, "probe": probe})
            break
    else:
        print(name, "FAILED")

# 抽帧
frames = []
for name, label in [("stock_bubbles", "A 泡泡·天空（泡影）"), ("stock_dunes", "B 撒哈拉沙丘（空）")]:
    fl = []
    for t in [1.0, 3.5]:
        p = f"{TMP}/fx5b/{name}_{t}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", d + name + ".mp4", "-frames:v", "1", p, "-y"], timeout=60)
        fl.append(p)
    frames.append((label, fl))

cw, ch = 640, 360
sheet = Image.new("RGB", (cw * 2, 46 + ch * 2), (12, 12, 16))
draw = ImageDraw.Draw(sheet)
font = ImageFont.truetype(os.environ.get("CJK_FONT", "C:/Windows/Fonts/simhei.ttf"), 28)
for i, (label, fl) in enumerate(frames):
    x = i * cw
    draw.text((x + cw // 2, 23), label, font=font, fill=(240, 240, 240), anchor="mm")
    for j, p in enumerate(fl):
        if os.path.exists(p):
            im = Image.open(p).convert("RGB").resize((cw, ch))
            sheet.paste(im, (x, 46 + j * ch))
sheet.save(TMP + "/fx5b_sheet.png")
print(f"saved {TMP}/fx5b_sheet.png", sheet.size)

sp = d + "SOURCES.json"
old = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else []
old.extend(newlog)
json.dump(old, open(sp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("DONE")
