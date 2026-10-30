#!/usr/bin/env python3
"""PDF acquisition, evidence previews, faithful crops and deterministic QA.
Writing and semantic/visual review are performed by the Agent using SKILL.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.parse
import urllib.request


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def fitz_module():
    try:
        import fitz
        return fitz
    except ImportError:
        raise ValueError('Install requirements.txt in the selected Python environment')


def source_url(source):
    ident = r'(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?'
    s = source.strip()
    if re.fullmatch(ident, s):
        return 'https://arxiv.org/pdf/' + s
    u = urllib.parse.urlparse(s)
    if u.scheme not in ('https', 'http'):
        raise ValueError('Input must be a local PDF, arXiv ID, or HTTP(S) PDF URL')
    if u.hostname in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
        m = re.fullmatch(r'/(?:abs|pdf)/('+ident+r')(?:\.pdf)?/?', u.path)
        if not m:
            raise ValueError('Unsupported arXiv URL; use abs/ID or pdf/ID')
        return 'https://arxiv.org/pdf/' + m[1]
    return s


def prepare(a):
    fitz = fitz_module()
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    pdf = work/'paper.pdf'
    # Do not replace an existing run silently.
    if (work/'source.json').exists():
        raise ValueError('WORK already contains a run; choose a fresh WORK directory')
    local = Path(a.source).expanduser()
    origin = a.source
    if local.is_file():
        if local.resolve() != pdf:
            shutil.copyfile(local, pdf)
        resolved = str(local.resolve())
    else:
        url = source_url(a.source)
        req = urllib.request.Request(url, headers={'User-Agent': 'REAL-Lab-Paper-Promotion/1.0'})
        tmp = work/'download.part'
        try:
            with urllib.request.urlopen(req, timeout=60) as response, tmp.open('wb') as out:
                resolved = response.geturl()
                total = 0
                while True:
                    chunk = response.read(1024*1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 200*1024*1024:
                        raise ValueError('PDF exceeds 200 MiB download limit')
                    out.write(chunk)
            if b'%PDF-' not in tmp.read_bytes()[:1024]:
                raise ValueError('URL did not return a PDF (possibly login/HTML page)')
            tmp.replace(pdf)
        finally:
            tmp.unlink(missing_ok=True)
    with fitz.open(pdf) as doc:
        if not doc.is_pdf or doc.needs_pass:
            raise ValueError('Input must be an unlocked PDF')
        previews = work/'pages'
        previews.mkdir(exist_ok=True)
        pages = []
        for i, page in enumerate(doc):
            page.get_pixmap(dpi=110, alpha=False).save(previews/f'{i+1:03d}.png')
            pages.append({'page': i+1, 'rect': list(page.rect), 'rotation': page.rotation,
                          'text': page.get_text(sort=True),
                          'blocks': page.get_text('blocks')})
        save(work/'pages.json', pages)
        (work/'text.txt').write_text('\n\n'.join(f"--- PAGE {p['page']} ---\n{p['text']}" for p in pages), encoding='utf-8')
        save(work/'source.json', {'input': origin, 'resolved': resolved, 'pdf_sha256': digest(pdf),
                                 'pages': len(doc), 'pymupdf': fitz.VersionBind})
    print(json.dumps({'work': str(work), 'pages': len(pages),
                      'low_text_pages': [p['page'] for p in pages if len(p['text'].strip()) < 50]}))


def post_content(path):
    raw = Path(path).read_text(encoding='utf-8')
    if not raw.startswith('# ') or '\n\n' not in raw:
        raise ValueError('post.md must be # title, one blank line, then body')
    title, rest = raw.split('\n', 1)
    if not rest.startswith('\n'):
        raise ValueError('Missing blank line after title')
    return title[2:], rest[1:]  # Count every body newline, including final newline.


def counts(text):
    return {'codepoints': len(text), 'utf16': len(text.encode('utf-16-le'))//2}


def check_text(path):
    title, body = post_content(path)
    for label, value, limit in [('title', title, 20), ('body', body, 1000)]:
        if not value.strip() or max(counts(value).values()) > limit:
            raise ValueError(f'{label} exceeds {limit} or is empty: {counts(value)}')
    # Catch URLs (including bare domains), Markdown links/references, HTML and embeds.
    banned = r'(?i)(?:[a-z][a-z0-9+.-]*://|www\.|(?:[a-z0-9-]+\.)+[a-z]{2,63}(?:\b|/)|\[[^\]]*\]\s*(?:\(|\[)|^\s*\[[^\]]+\]:|<[^>]+>|!\[)'
    if re.search(banned, title+'\n'+body, re.M):
        raise ValueError('Real URL/domain, Markdown link or HTML found in post')
    if re.search(r'^\s*#{1,6}\s|```', body, re.M):
        raise ValueError('Body must be plain publishable text')
    return title, body


def load_plan(a):
    fitz = fitz_module()
    work, out = Path(a.work).resolve(), Path(a.out).resolve()
    # Easel stores working materials under the same topic's assets directory.
    nested_assets = work != out/'assets' and (out/'assets') in work.parents
    if work == out or work in out.parents or (out in work.parents and not nested_assets):
        raise ValueError('WORK must be separate from OUT or inside OUT/assets/<work-name>')
    title, body = check_text(out/'post.md')
    manifest = read(work/'manifest.json')
    if manifest['pdf_sha256'] != digest(work/'paper.pdf'):
        raise ValueError('PDF hash mismatch')
    if read(work/'source.json')['pdf_sha256'] != manifest['pdf_sha256']:
        raise ValueError('Source provenance mismatch')
    doc = fitz.open(work/'paper.pdf')
    figures = manifest['images']
    if not figures:
        raise ValueError('Missing first-page image')
    previous = -1
    for i, item in enumerate(figures):
        if not re.fullmatch(rf'{i+1:02d}-[a-z0-9-]+\.png', item['file']):
            raise ValueError('Image names must be sequential NN-slug.png')
        if type(item['page']) is not int or not 1 <= item['page'] <= len(doc):
            raise ValueError('Invalid page number')
        page = doc[item['page']-1]
        if type(item.get('dpi', 180)) is not int or not 144 <= item.get('dpi', 180) <= 300:
            raise ValueError('DPI must be an integer from 144 through 300')
        if i == 0:
            if item['kind'] != 'first-page' or item['page'] != 1 or item.get('bbox') is not None:
                raise ValueError('First image must be uncropped page 1')
            continue
        if item['kind'] not in ('teaser', 'method', 'table', 'analysis'):
            raise ValueError('Invalid figure kind')
        if item['kind'] == 'teaser' and item['page'] == 1:
            raise ValueError('Do not repeat teaser already on first page')
        quote = item['text_quote']
        if not quote.strip() or body.count(quote) != 1:
            raise ValueError('text_quote must identify one exact occurrence in body')
        offset = body.index(quote)
        if offset < previous:
            raise ValueError('Figure order differs from body order')
        previous = offset
        box = fitz.Rect(item['bbox'])
        if box.is_empty or box.is_infinite or not page.rect.contains(box):
            raise ValueError('Crop outside displayed page or empty')
        for key in ('source_label', 'caption', 'reason'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError('Missing figure metadata: '+key)
        cap = fitz.Rect(item['caption_bbox'])
        if cap.is_empty or not box.contains(cap):
            raise ValueError('Caption region must be inside crop')
        if type(item.get('dpi', 180)) is not int or not 144 <= item.get('dpi', 180) <= 300:
            raise ValueError('DPI must be an integer from 144 through 300')
    return work, out, doc, figures, title, body


def pixels(doc, item):
    fitz = fitz_module()
    return doc[item['page']-1].get_pixmap(dpi=item.get('dpi', 180),
        clip=fitz.Rect(item['bbox']) if item.get('bbox') is not None else None, alpha=False)


def render(a):
    work, out, doc, figures, _, _ = load_plan(a)
    folder = out/'images'
    folder.mkdir(exist_ok=True)
    expected = {f['file'] for f in figures}
    extras = {p.name for p in folder.iterdir()}-expected
    if extras:
        raise ValueError('Remove stale files from images before rendering: '+str(sorted(extras)))
    for item in figures:
        pixels(doc, item).save(folder/item['file'])
    doc.close()
    print(f'Rendered {len(figures)} faithful PDF screenshots; visual review still required')


def binding(work, out):
    return {name: digest(path) for name, path in {
        'pdf': work/'paper.pdf', 'post': out/'post.md', 'manifest': work/'manifest.json',
        'evidence': work/'evidence.json'}.items()}


def validate(a):
    fitz = fitz_module()
    work, out, doc, figures, title, body = load_plan(a)
    folder = out/'images'
    if {p.name for p in folder.iterdir()} != {f['file'] for f in figures}:
        raise ValueError('Missing or extra screenshot files')
    entries = {p.name for p in out.iterdir()}
    if not {'post.md', 'images'} <= entries or entries - {'post.md', 'images', 'assets', '.easel.json'}:
        raise ValueError('OUT allows post.md, images/, assets/ and .easel.json only')
    for item in figures:
        actual = fitz.Pixmap(str(folder/item['file']))
        expected = pixels(doc, item)
        if (actual.width, actual.height, actual.n, actual.samples) != (expected.width, expected.height, expected.n, expected.samples):
            raise ValueError('Screenshot does not match source PDF render: '+item['file'])
    doc.close()
    evidence = read(work/'evidence.json')
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('Evidence must be a nonempty list')
    for claim in evidence:
        if not claim.get('post_quote') or claim['post_quote'] not in body:
            raise ValueError('Evidence quote missing from final body')
        if not claim.get('source_excerpt') or type(claim.get('page')) is not int or not 1 <= claim['page'] <= read(work/'source.json')['pages']:
            raise ValueError('Evidence lacks source excerpt or page')
    review = read(work/'review.json')
    if review['hashes'] != binding(work, out):
        raise ValueError('Semantic review is stale: file hashes changed')
    for key in ('facts', 'grounding', 'visual', 'style'):
        entry = review[key]
        if entry.get('passed') is not True or not entry.get('notes', '').strip():
            raise ValueError('Semantic/visual review incomplete: '+key)
    result = {'machine_passed': True, 'semantic_review_recorded': True,
              'title': counts(title), 'body': counts(body), 'images': len(figures),
              'note': 'Machine checks do not independently prove semantic or factual accuracy.'}
    save(work/'validation.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    prep = subs.add_parser('prepare', help='arXiv ID/URL, PDF URL or local PDF to working assets')
    prep.add_argument('source')
    prep.add_argument('--work', required=True)
    for command in ('render', 'validate', 'hashes'):
        sub = subs.add_parser(command)
        sub.add_argument('--work', required=True)
        sub.add_argument('--out', required=True)
    txt = subs.add_parser('check-text')
    txt.add_argument('post')
    a = parser.parse_args()
    try:
        # Validate all output destinations before dispatching a CLI operation.
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'shared' / 'scripts'))
        from output_paths import validate_output_path
        if a.command == 'prepare':
            a.work = str(validate_output_path(Path(a.work)/'source.json').parent)
        elif a.command in ('render', 'validate', 'hashes'):
            a.work = str(validate_output_path(Path(a.work)/'source.json').parent)
            a.out = str(validate_output_path(Path(a.out)/'post.md').parent)
        if a.command == 'prepare': prepare(a)
        elif a.command == 'render': render(a)
        elif a.command == 'validate': validate(a)
        elif a.command == 'hashes': print(json.dumps(binding(Path(a.work), Path(a.out)), indent=2))
        else:
            title, body = check_text(a.post)
            print(json.dumps({'title': counts(title), 'body': counts(body)}))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
