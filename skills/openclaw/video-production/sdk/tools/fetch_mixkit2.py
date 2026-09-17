import subprocess, re, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
TMP = os.environ.get("TEMP") or "/tmp"
os.makedirs(TMP + "/mixkit2", exist_ok=True)
slugs = ["money", "business", "abstract", "office"]

for slug in slugs:
    url = f"https://mixkit.co/free-stock-video/{slug}/"
    try:
        out = subprocess.run(["curl", "-sL", "-A", UA, url], capture_output=True, text=True, timeout=90)
        html = out.stdout
    except Exception as e:
        print(f"== {slug}: FAIL {e}")
        continue
    pairs = {}
    for m in re.finditer(r'/free-stock-video/([a-z0-9][a-z0-9-]*?)-(\d+)/', html):
        pairs.setdefault(m.group(2), set()).add(m.group(1))
    mp4ids = set(re.findall(r'/videos/(\d+)/\d+-', html))
    print(f"\n===== {slug} ({len(pairs)} items) =====")
    for pid in sorted(pairs, key=lambda x: int(x)):
        if pid not in mp4ids:
            continue
        print(f"{pid:>7} | {' / '.join(sorted(pairs[pid]))[:110]}")
