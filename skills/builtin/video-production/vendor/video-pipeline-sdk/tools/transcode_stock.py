import subprocess, os

d = os.environ.get("REMOTION_PROJECT", ".") + "/public/stock/"
names = ["stock_milkyway", "stock_snowforest", "stock_sunset", "stock_editor", "stock_tunnel"]

for n in names:
    src = d + n + ".mp4"
    tmp = d + n + "_t.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src,
         "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
         "-c:v", "libx264", "-crf", "23", "-preset", "fast",
         "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-an", "-movflags", "+faststart", tmp],
        capture_output=True, text=True, timeout=900,
    )
    ok = os.path.exists(tmp) and os.path.getsize(tmp) > 100000
    if ok:
        os.remove(src)
        os.rename(tmp, src)
        size = os.path.getsize(src) // 1024 // 1024
        print(f"{n}: OK {size}MB")
    else:
        print(f"{n}: FAIL {r.stderr[-300:]}")

total = 0
for f in os.listdir(d):
    total += os.path.getsize(d + f)
print(f"stock dir total: {total // 1024 // 1024}MB")

total_pub = 0
for root, dirs, files in os.walk(os.environ.get("REMOTION_PROJECT", ".") + "/public"):
    for f in files:
        try:
            total_pub += os.path.getsize(os.path.join(root, f))
        except Exception:
            pass
print(f"public total: {total_pub // 1024 // 1024}MB")
