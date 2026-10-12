import subprocess, os, json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
d = os.environ.get("REMOTION_PROJECT", ".") + "/public/sfx/"
os.makedirs(d, exist_ok=True)

picks = [
    (1490, "mk-1490-fast-whoosh-transition.mp3", "Fast whoosh transition", "transition"),
    (3120, "mk-3120-technology-transition-slide.mp3", "Technology transition slide", "transition"),
    (2350, "mk-2350-magic-sparkle-whoosh.mp3", "Magic sparkle whoosh", "whoosh"),
    (1474, "mk-1474-transition-windy-swoosh.mp3", "Transition windy swoosh", "transition"),
    (1492, "mk-1492-cinematic-whoosh-fast-transition.mp3", "Cinematic whoosh fast transition", "whoosh"),
    (175, "mk-0175-short-transition-sweep.mp3", "Short transition sweep", "transition"),
    (790, "mk-0790-cinematic-trailer-riser.mp3", "Cinematic trailer riser", "riser"),
    (788, "mk-0788-big-cinematic-impact.mp3", "Big cinematic impact", "impact"),
    (1489, "mk-1489-air-woosh.mp3", "Air woosh", "whoosh"),
    (3114, "mk-3114-fast-scifi-transition-sweep.mp3", "Fast sci fi transition sweep", "transition"),
]

log = []
for sid, name, title, cat in picks:
    url = f"https://assets.mixkit.co/active_storage/sfx/{sid}/{sid}-preview.mp3"
    out = d + name
    try:
        subprocess.run(["curl", "-sL", "-A", UA, "-o", out, url], capture_output=True, timeout=120)
    except Exception as e:
        print(name, "ERR", e)
        continue
    ok = os.path.exists(out) and os.path.getsize(out) > 5000
    dur = ""
    if ok:
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
            capture_output=True, text=True,
        ).stdout.strip()
    size_kb = os.path.getsize(out) // 1024 if os.path.exists(out) else 0
    print(f"{name} {'OK' if ok else 'FAIL'} {size_kb}KB dur={dur}")
    if ok:
        log.append({"id": sid, "file": name, "title": title, "category": cat, "url": url, "duration": dur})

json.dump(log, open(d + "SOURCES-mixkit.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("DONE", len(log), "sfx")
