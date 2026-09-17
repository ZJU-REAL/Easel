import re
import os

cats = ["night-sky", "forest", "technology", "city", "ocean", "aurora"]
for c in cats:
    html = open((os.environ.get("TEMP") or "/tmp") + f"/mixkit/{c}.html", encoding="utf-8").read()
    pairs = {}
    for m in re.finditer(r'/free-stock-video/([a-z0-9][a-z0-9-]*?)-(\d+)/', html):
        slug, pid = m.group(1), m.group(2)
        pairs.setdefault(pid, set()).add(slug)
    # 只保留出现在 mp4 链接里的 id
    mp4ids = set(re.findall(r'/videos/(\d+)/\d+-', html))
    print(f"\n===== {c} ({len(pairs)} items) =====")
    for pid in sorted(pairs, key=lambda x: int(x)):
        if pid not in mp4ids:
            continue
        slug = " / ".join(sorted(pairs[pid]))[:110]
        print(f"{pid:>7} | {slug}")
