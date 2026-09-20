import subprocess, os, json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
d = os.environ.get("REMOTION_PROJECT", ".") + "/public/stock/"

items = [
    ("stock_scrambled", 31771, "scrambled-dots-and-lines-within-a-sphere-of-dots", "technology"),
    ("stock_money", 45703, "money-counting-machine-counting-up-money", "money"),
    ("stock_worldmap", 12748, "world-map-in-a-digital-world", "business"),
    ("stock_ink", 44818, "abstract-video-of-a-liquid-with-dark-ink-flowing", "abstract"),
    ("stock_graphs", 42648, "business-man-exposing-graphs", "business"),
]

newlog = []
for name, vid, slug, cat in items:
    got = False
    for res in ["1080", "720", "360"]:
        url = f"https://assets.mixkit.co/videos/{vid}/{vid}-{res}.mp4"
        raw = d + name + "_raw.mp4"
        try:
            subprocess.run(["curl", "-sL", "-A", UA, "-o", raw, url], capture_output=True, timeout=300)
        except Exception as e:
            print(name, res, "ERR", e)
            continue
        if not os.path.exists(raw):
            continue
        if os.path.getsize(raw) < 200000 or b"ftyp" not in open(raw, "rb").read(16):
            os.remove(raw)
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
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration", "-of", "csv=p=0", d + name + ".mp4"],
                capture_output=True, text=True,
            ).stdout.strip()
            size = os.path.getsize(d + name + ".mp4") // 1024 // 1024
            print(f"{name} [{res}] OK {size}MB {probe}")
            newlog.append({"name": name, "vid": vid, "slug": slug, "category": cat, "res": res, "url": url, "probe": probe})
            got = True
            break
        else:
            print(name, res, "transcode FAIL")
    if not got:
        print(name, "FAILED")

sp = d + "SOURCES.json"
old = []
if os.path.exists(sp):
    try:
        old = json.load(open(sp, encoding="utf-8"))
    except Exception:
        old = []
old.extend(newlog)
json.dump(old, open(sp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("DONE", len(newlog), "new clips")
