import subprocess, re, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
TMP = os.environ.get("TEMP") or "/tmp"
os.makedirs(TMP + "/mixkit", exist_ok=True)
slugs = ["night-sky", "forest", "technology", "city", "ocean", "aurora"]

for slug in slugs:
    url = f"https://mixkit.co/free-stock-video/{slug}/"
    try:
        out = subprocess.run(["curl", "-sL", "-A", UA, url], capture_output=True, text=True, timeout=90)
        html = out.stdout
    except Exception as e:
        print(f"== {slug}: FAIL {e}")
        continue
    urls = sorted(set(re.findall(r"https://assets\.mixkit\.co/[^\"'\s]+?\.mp4", html)))
    print(f"== {slug}: {len(html)} bytes, {len(urls)} mp4 urls")
    for u in urls[:14]:
        print("   ", u)
    with open(f"{TMP}/mixkit/{slug}.html", "w", encoding="utf-8") as f:
        f.write(html)
print("DONE")
