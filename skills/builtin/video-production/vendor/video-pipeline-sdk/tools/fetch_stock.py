import subprocess, os, json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
D = os.environ.get("REMOTION_PROJECT", ".") + "/public/stock"
os.makedirs(D, exist_ok=True)

items = [
    ("stock_milkyway", 4148, "milky-way-seen-at-night", "night-sky"),
    ("stock_snowforest", 3350, "moon-in-the-sky-a-snowy-forest", "forest"),
    ("stock_sunset", 15169, "red-sunset-over-the-ocean", "ocean"),
    ("stock_editor", 44071, "boy-editing-a-video-on-a-computer", "technology"),
    ("stock_tunnel", 31497, "traveling-through-a-tunnel-of-black-cubes-in-3d", "technology"),
]

log = []
for name, vid, slug, cat in items:
    done = False
    for res in ["1080", "720", "360"]:
        url = f"https://assets.mixkit.co/videos/{vid}/{vid}-{res}.mp4"
        out = f"{D}/{name}.mp4"
        try:
            subprocess.run(["curl", "-sL", "-A", UA, "-o", out, url], capture_output=True, timeout=240)
        except Exception as e:
            print(name, res, "ERR", e)
            continue
        if not os.path.exists(out):
            continue
        size = os.path.getsize(out)
        head = open(out, "rb").read(16)
        is_video = b"ftyp" in head
        print(f"{name} [{res}] size={size} video={is_video}")
        if is_video and size > 200000:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration", "-of", "csv=p=0", out],
                capture_output=True, text=True,
            )
            print("   probe:", probe.stdout.strip())
            log.append({"name": name, "vid": vid, "slug": slug, "category": cat, "res": res, "url": url, "probe": probe.stdout.strip()})
            done = True
            break
    if not done:
        print(name, "FAILED")

with open(D + "/SOURCES.json", "w", encoding="utf-8") as f:
    json.dump(log, f, indent=2, ensure_ascii=False)
print("DONE", len(log), "ok")
