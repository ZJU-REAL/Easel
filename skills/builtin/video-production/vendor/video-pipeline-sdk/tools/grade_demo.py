import subprocess, os
from PIL import Image, ImageDraw, ImageFont

LUT_DIR = (os.environ.get("TEMP") or "/tmp") + "/grade_compare"
OUT = (os.environ.get("TEMP") or "/tmp") + "/grade_demo"
LUTS = OUT + "/luts"
os.makedirs(LUTS, exist_ok=True)
base = os.environ.get("REMOTION_PROJECT", ".") + "/public/assets/proxy.mp4"

def clean_lut(name):
    src = os.path.join(LUT_DIR, name)
    dst = os.path.join(LUTS, name)
    raw = open(src, encoding='utf-8', errors='ignore').read().splitlines()
    # 首行体检
    print(f"== {name}: {raw[0].strip()} / {raw[1].strip() if len(raw)>1 else ''} / 共{len(raw)}行")
    out = []
    for ln in raw:
        s = ln.strip()
        if s.startswith(("DOMAIN_MIN", "DOMAIN_MAX")):
            out.append("# " + ln)
        else:
            out.append(ln)
    open(dst, "w", encoding='utf-8').write("\n".join(out))
    return name

clean_lut("Portra160NC_c.cube")
clean_lut("Fuji400H_c.cube")

times = [8, 40, 60]
variants = [
    ("orig", None),
    ("A", "hqdn3d=2:1.5:2:2,split=2[o][p];[p]lut3d=file='Portra160NC_c.cube'[g];[o][g]blend=all_expr='A*0.4+B*0.6',format=yuv420p[v]"),
    ("B", "hqdn3d=2:1.5:2:2,split=2[o][p];[p]lut3d=file='Fuji400H_c.cube'[g];[o][g]blend=all_expr='A*0.55+B*0.45',format=yuv420p[v]"),
]

for t in times:
    for tag, fc in variants:
        outp = f"{OUT}/f{t}_{tag}.png"
        if fc is None:
            cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", base, "-frames:v", "1", outp]
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=LUTS)
        else:
            fc_full = "[0:v]" + fc
            cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", base, "-filter_complex", fc_full, "-map", "[v]", "-frames:v", "1", outp]
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=LUTS)
        ok = os.path.exists(outp) and os.path.getsize(outp) > 10000
        if not ok:
            print(f"FAIL {t}s {tag}: {r.stderr.strip()[:220]}")
        else:
            print(f"OK {t}s {tag}")

# 拼表：3 行(时间) × 3 列(原/A/B)
CW, CH = 640, 360
HDR = 58
canvas = Image.new("RGB", (CW * 3, HDR + 3 * (CH + 26)), (10, 12, 16))
dr = ImageDraw.Draw(canvas)
font = ImageFont.truetype(os.environ.get("CJK_FONT", "C:/Windows/Fonts/simhei.ttf"), 26)
font_s = ImageFont.truetype(os.environ.get("CJK_FONT", "C:/Windows/Fonts/simhei.ttf"), 20)
cols = ["原片（无处理）", "方案A · Portra160NC 60% + 降噪", "方案B · Fuji400H 45% + 降噪"]
for i, c in enumerate(cols):
    dr.text((i * CW + CW // 2, HDR // 2 + 2), c, font=font, fill=(235, 240, 248), anchor="mm")
for r_i, t in enumerate(times):
    y = HDR + r_i * (CH + 26)
    for c_i, tag in enumerate(["orig", "A", "B"]):
        p = f"{OUT}/f{t}_{tag}.png"
        if os.path.exists(p):
            im = Image.open(p).convert("RGB").resize((CW, CH))
            canvas.paste(im, (c_i * CW, y))
    dr.text((10, y + CH + 3), f"t={t}s", font=font_s, fill=(150, 170, 190))
sheet = OUT + "/grade_sheet.png"
canvas.save(sheet)
print("SHEET", sheet, canvas.size)
