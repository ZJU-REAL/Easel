import re
import os

for slug in ["whoosh", "riser", "impact", "transition"]:
    try:
        html = open((os.environ.get("TEMP") or "/tmp") + f"/mixkit_sfx/{slug}.html", encoding="utf-8").read()
    except FileNotFoundError:
        print(f"== {slug}: html 未保存，跳过")
        continue
    # 按 audio-player 块切
    blocks = html.split('data-test-id="audio-player"')
    print(f"\n===== {slug} ({len(blocks)-1} items) =====")
    for b in blocks[1:]:
        m = re.search(r"sfx/(\d+)/\d+-preview\.mp3", b)
        t = re.search(r'item-grid-card__title">\s*([^<]+?)\s*</h2>', b)
        if m and t:
            print(f"{m.group(1):>6} | {t.group(1)}")
