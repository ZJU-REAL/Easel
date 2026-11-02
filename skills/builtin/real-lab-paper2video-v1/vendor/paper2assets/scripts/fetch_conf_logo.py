#!/usr/bin/env python3
"""Fetch a conference's (generic) logo from Wikidata/Wikimedia Commons for the poster header.

Deterministic, NO WebSearch — pure HTTP against the Wikidata + Commons APIs. Given a venue
string (metadata.json `venue`, e.g. "NeurIPS 2023" / "Advances in NeurIPS 36 (2023)"), resolve
the conference's Wikidata item, read its P154 ("logo image") claim, and download the Commons file
(rendered to PNG) to <outdir>/assets/logos/_venue.png. Best-effort: on any miss it writes nothing
and exits 0 (the poster header falls back to its text VENUE/YEAR badge).

The logo is the conference's GENERIC mark (Wikidata has no per-year / per-host-city logos).

Usage:
    python fetch_conf_logo.py --outdir <outdir> --venue "NeurIPS 2023"
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

# Make the sibling utils/ importable for the best-effort logo autotrim.
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
try:
    from utils.logo_trim import autotrim
except Exception:  # best-effort: a missing trim util / dep degrades to a no-op
    def autotrim(p):
        return p

UA = "Mozilla/5.0 (paper2assets fetch_conf_logo)"

# short acronym (lowercased) -> Wikidata search term (the conference *series* name)
ALIASES = {
    "neurips": "Conference on Neural Information Processing Systems",
    "nips": "Conference on Neural Information Processing Systems",
    "icml": "International Conference on Machine Learning",
    "iclr": "International Conference on Learning Representations",
    "cvpr": "Conference on Computer Vision and Pattern Recognition",
    "iccv": "International Conference on Computer Vision",
    "eccv": "European Conference on Computer Vision",
    "acl": "Association for Computational Linguistics",
    "emnlp": "Empirical Methods in Natural Language Processing",
    "naacl": "North American Chapter of the Association for Computational Linguistics",
    "aaai": "AAAI Conference on Artificial Intelligence",
    "kdd": "SIGKDD",
    "siggraph": "SIGGRAPH",
    "interspeech": "Interspeech",
    "icassp": "International Conference on Acoustics, Speech, and Signal Processing",
    "www": "The Web Conference",
    "sigir": "Special Interest Group on Information Retrieval",
    "ijcai": "International Joint Conference on Artificial Intelligence",
    "uai": "Conference on Uncertainty in Artificial Intelligence",
    "aistats": "International Conference on Artificial Intelligence and Statistics",
    "colt": "Conference on Learning Theory",
    "corl": "Conference on Robot Learning",
    "rss": "Robotics: Science and Systems",
    "icra": "IEEE International Conference on Robotics and Automation",
    "iros": "International Conference on Intelligent Robots and Systems",
    "miccai": "Medical Image Computing and Computer Assisted Intervention",
    "wacv": "Winter Conference on Applications of Computer Vision",
    "bmvc": "British Machine Vision Conference",
}
KNOWN = sorted(ALIASES.keys(), key=len, reverse=True)
DESC_HINTS = ("conference", "academic", "workshop", "symposium", "society",
              "association", "special interest", "proceedings")


def fetch(url, timeout=20, retries=4):
    """HTTP GET with retry + backoff. Conference logos mostly DO exist online; a miss
    is usually a transient Wikipedia/Commons rate-limit or timeout (worse under the
    concurrent wave), so ride it out rather than give up on the first failure."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))  # 1.5, 3, 4.5, 6s
    raise last


def fetch_json(url):
    return json.loads(fetch(url).decode("utf-8"))


def conf_term(venue):
    """Map a raw venue string to a Wikidata search term (conference series name)."""
    low = (venue or "").lower()
    for acro in KNOWN:
        if re.search(r"\b" + re.escape(acro) + r"\b", low):
            return ALIASES[acro]
    v = re.sub(r"\b(19|20)\d{2}\b", " ", venue or "")
    v = re.sub(r"(?i)\b(proceedings of|advances in|the|\d+(st|nd|rd|th)|vol\.?|volume)\b", " ", v)
    v = re.sub(r"[()\[\],]", " ", v)
    v = re.sub(r"\s+", " ", v).strip(" .-")
    return v or None


def wikidata_item(term):
    url = ("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json"
           "&language=en&type=item&limit=7&search=" + urllib.parse.quote(term))
    hits = fetch_json(url).get("search", [])
    for hit in hits:
        if any(k in (hit.get("description") or "").lower() for k in DESC_HINTS):
            return hit["id"]
    return hits[0]["id"] if hits else None


def p154_filename(qid):
    url = ("https://www.wikidata.org/w/api.php?action=wbgetclaims&format=json"
           "&property=P154&entity=" + qid)
    claims = fetch_json(url).get("claims", {}).get("P154", [])
    for c in claims:
        try:
            return c["mainsnak"]["datavalue"]["value"]
        except (KeyError, TypeError):
            continue
    return None


def commons_url(filename, width=600):
    return ("https://commons.wikimedia.org/wiki/Special:FilePath/"
            + urllib.parse.quote(filename) + "?width=" + str(width))


def is_image(b):
    s = b.lstrip()[:6].lower()
    return (b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff"
            or s.startswith(b"<svg") or s.startswith(b"<?xml") or b[:6] == b"GIF89a")


def wikipedia_lead_image(title):
    """The page's lead/infobox image via the Wikipedia REST summary — where conference
    logos actually live (Wikidata P154 is almost never populated for conferences)."""
    if not title:
        return None
    url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
           + urllib.parse.quote(title.replace(" ", "_")))
    try:
        s = fetch_json(url)
    except Exception:
        return None
    orig = (s.get("originalimage") or {}).get("source")
    thumb = (s.get("thumbnail") or {}).get("source")
    if orig and orig.lower().rsplit("?", 1)[0].endswith((".png", ".jpg", ".jpeg", ".gif")):
        return orig
    return thumb or orig


def pageimages_image(title):
    """Wikipedia page's primary image INCLUDING non-free logos (pilicense=any) — many
    conference marks are uploaded fair-use and the REST summary omits them. A separate
    endpoint from the REST summary, so it also adds a redundant path when one is flaky.
    General; no per-conference data."""
    if not title:
        return None
    url = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages"
           "&piprop=original|thumbnail&pithumbsize=600&pilicense=any&redirects=1&titles="
           + urllib.parse.quote(title))
    try:
        pages = fetch_json(url).get("query", {}).get("pages", {})
    except Exception:
        return None
    for _, pg in pages.items():
        src = (pg.get("original") or pg.get("thumbnail") or {}).get("source")
        if src:
            return src
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--venue", default=None)
    ap.add_argument("--from-metadata", default=None,
                    help="read the 'venue' field from this metadata.json "
                         "(e.g. <outdir>/assets/meta/metadata.json); --venue overrides it")
    a = ap.parse_args()
    if not a.venue and a.from_metadata:
        try:
            a.venue = (json.load(open(a.from_metadata)) or {}).get("venue") or None
        except Exception as e:
            print(json.dumps({"venue": None, "skipped": True,
                              "error": f"metadata read failed: {str(e)[:120]}"})); return 0
    if not a.venue:
        print(json.dumps({"venue": None, "skipped": True,
                          "reason": "no --venue and no 'venue' in --from-metadata"})); return 0
    base = {"venue": a.venue, "skipped": True}
    try:
        term = conf_term(a.venue)
        raw = re.split(r"\s+\d", (a.venue or "").strip())[0].strip()  # "NeurIPS 2023" -> "NeurIPS"
        # PRIMARY: Wikipedia lead/infobox image (full series name, then the raw acronym).
        img_url, source = None, "wikipedia"
        for cand in (term, raw):
            img_url = wikipedia_lead_image(cand)
            if img_url:
                break
        # SECONDARY: Wikipedia pageimages incl. non-free logos (pilicense=any).
        if not img_url:
            for cand in (term, raw):
                img_url = pageimages_image(cand)
                if img_url:
                    source = "wikipedia-pageimages"
                    break
        # TERTIARY: Wikidata P154 (rarely populated for conferences).
        if not img_url:
            qid = wikidata_item(term) if term else None
            fn = p154_filename(qid) if qid else None
            if fn:
                img_url, source = commons_url(fn), "wikidata-P154"
        if not img_url:
            print(json.dumps({**base, "reason": f"no Wikipedia lead image / P154 logo for '{term}'"})); return 0
        img = fetch(img_url)
        if not is_image(img) or len(img) < 200:
            print(json.dumps({**base, "reason": "downloaded bytes are not a valid image"})); return 0
        logos = os.path.join(a.outdir, "assets", "logos"); os.makedirs(logos, exist_ok=True)
        path = os.path.join(logos, "_venue.png")
        with open(path, "wb") as f:
            f.write(img)
        # Autotrim the venue mark in place (crop transparent/near-white border) so
        # the header chip hugs it. Best-effort: the util keeps the original on error.
        autotrim(path)
        print(json.dumps({"venue": a.venue, "term": term, "source": source, "url": img_url,
                          "path": "assets/logos/_venue.png", "bytes": len(img), "skipped": False}))
    except Exception as e:
        print(json.dumps({**base, "error": str(e)[:160]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
