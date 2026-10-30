#!/usr/bin/env python3
"""Behavioral regression checks using synthetic PDF fixtures only."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import promotion as p
try:
    import fitz
except ImportError:
    fitz = None


@unittest.skipIf(fitz is None, 'Install this skill\'s requirements.txt to run PDF checks')
class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work, self.out = self.root/'work', self.root/'out'
        self.out.mkdir()
        self.pdf = self.root/'fixture.pdf'
        doc = fitz.open()
        for i in range(2):
            page = doc.new_page(width=600, height=800)
            page.insert_text((45, 50), 'SYNTHETIC TEST DOCUMENT - NOT A RESEARCH PAPER')
            page.draw_rect(fitz.Rect(40, 90, 550, 230), color=(0, 0, 1))
            page.insert_text((50, 150), 'Test diagram: A -> B')
            page.insert_text((40, 260), 'Figure 1. Synthetic caption for regression tests.')
        doc.save(self.pdf)
        doc.close()
        self.args = SimpleNamespace(source=str(self.pdf), work=str(self.work), out=str(self.out))
        with contextlib.redirect_stdout(io.StringIO()): p.prepare(self.args)
        self.post = self.out/'post.md'
        self.post.write_text('# 测试标题\n\n方法对应测试图。\n结果对应测试表。\narXiv：2610.12402\n', encoding='utf-8')
        self.plan = {'pdf_sha256': p.digest(self.work/'paper.pdf'), 'images': [
            {'file': '01-first-page.png', 'kind': 'first-page', 'page': 1, 'bbox': None},
            {'file': '02-method.png', 'kind': 'method', 'page': 2, 'bbox': [35, 85, 560, 275],
             'caption_bbox': [35, 245, 560, 275], 'caption': 'Figure 1. Synthetic caption for regression tests.',
             'source_label': 'Figure 1', 'text_quote': '方法对应测试图。', 'reason': 'Synthetic fixture mapping'}]}
        p.save(self.work/'manifest.json', self.plan)
        p.save(self.work/'evidence.json', [{'post_quote': '方法对应测试图。', 'page': 2, 'source_excerpt': 'Test diagram'}])

    def tearDown(self): self.temp.cleanup()

    def reviewed(self):
        review = {'hashes': p.binding(self.work, self.out)}
        for key in ('facts', 'grounding', 'visual', 'style'):
            review[key] = {'passed': True, 'notes': 'Synthetic test record only; not a real semantic review'}
        p.save(self.work/'review.json', review)

    def test_end_to_end_local_pdf(self):
        p.render(self.args)
        self.reviewed()
        p.validate(self.args)
        self.assertTrue(p.read(self.work/'validation.json')['machine_passed'])

    def test_easel_assets_and_content_library_metadata(self):
        nested = self.out/'assets'/'paper-promotion'
        nested.parent.mkdir()
        self.work.rename(nested)
        self.work = nested
        self.args.work = str(nested)
        p.save(self.out/'.easel.json', {'kind': 'xhs-note', 'status': 'draft'})
        p.render(self.args)
        self.reviewed()
        p.validate(self.args)
        self.assertTrue(p.read(self.work/'validation.json')['machine_passed'])
        (self.out/'internal-report.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            p.validate(self.args)

    def test_work_cannot_be_nested_outside_assets(self):
        self.args.work = str(self.out/'images'/'work')
        with self.assertRaises(ValueError):
            p.load_plan(self.args)

    def test_title_and_body_boundaries(self):
        self.post.write_text('# '+'题'*20+'\n\n'+'文'*1000, encoding='utf-8')
        p.check_text(self.post)
        self.post.write_text('# '+'题'*21+'\n\n正文', encoding='utf-8')
        with self.assertRaises(ValueError): p.check_text(self.post)
        self.post.write_text('# 标题\n\n'+'文'*1001, encoding='utf-8')
        with self.assertRaises(ValueError): p.check_text(self.post)
        self.post.write_text('# '+'😀'*11+'\n\n正文', encoding='utf-8')
        with self.assertRaises(ValueError): p.check_text(self.post)

    def test_link_rejection(self):
        for bad in ['https://example.org/a', 'github.com/x/y', '[x](path)', '[x][ref]', '<a href="x">x</a>']:
            with self.subTest(bad=bad):
                self.post.write_text('# 标题\n\n'+bad, encoding='utf-8')
                with self.assertRaises(ValueError): p.check_text(self.post)

    def test_input_forms(self):
        for value in ['2610.12402', 'https://arxiv.org/abs/2610.12402', 'https://arxiv.org/pdf/2610.12402.pdf']:
            self.assertEqual(p.source_url(value), 'https://arxiv.org/pdf/2610.12402')
        self.assertEqual(p.source_url('https://arxiv.org/abs/2610.12402v2'), 'https://arxiv.org/pdf/2610.12402v2')
        self.assertEqual(p.source_url('hep-th/9901001'), 'https://arxiv.org/pdf/hep-th/9901001')
        self.assertEqual(p.source_url('https://example.org/file.pdf?download=1'), 'https://example.org/file.pdf?download=1')

    def test_pdf_url_download(self):
        response = io.BytesIO(self.pdf.read_bytes())
        response.geturl = lambda: 'https://example.org/final.pdf'
        args = SimpleNamespace(source='https://example.org/paper.pdf', work=str(self.root/'remote'))
        with patch('urllib.request.urlopen', return_value=response): p.prepare(args)
        self.assertEqual(p.digest(self.root/'remote/paper.pdf'), p.digest(self.pdf))

    def test_html_download_rejected(self):
        response = io.BytesIO(b'<html>Login required</html>')
        response.geturl = lambda: 'https://example.org/login'
        args = SimpleNamespace(source='https://example.org/paper.pdf', work=str(self.root/'bad'))
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaises(ValueError): p.prepare(args)

    def test_first_page_must_be_full(self):
        self.plan['images'][0]['bbox'] = [0, 0, 300, 400]
        p.save(self.work/'manifest.json', self.plan)
        with self.assertRaises(ValueError): p.render(self.args)

    def test_quote_and_order(self):
        self.plan['images'][1]['text_quote'] = '未提及的内容'
        p.save(self.work/'manifest.json', self.plan)
        with self.assertRaises(ValueError): p.render(self.args)
        self.plan['images'][1]['text_quote'] = '结果对应测试表。'
        third = dict(self.plan['images'][1], file='03-analysis.png', kind='analysis', text_quote='方法对应测试图。')
        self.plan['images'].append(third)
        p.save(self.work/'manifest.json', self.plan)
        with self.assertRaises(ValueError): p.render(self.args)

    def test_caption_outside_crop(self):
        self.plan['images'][1]['caption_bbox'] = [30, 280, 560, 310]
        p.save(self.work/'manifest.json', self.plan)
        with self.assertRaises(ValueError): p.render(self.args)

    def test_modified_screenshot_rejected(self):
        p.render(self.args)
        self.reviewed()
        file = self.out/'images/02-method.png'
        pix = fitz.Pixmap(str(file))
        pix.set_pixel(0, 0, (255, 0, 0))
        pix.save(file)
        with self.assertRaises(ValueError): p.validate(self.args)

    def test_stale_review_rejected(self):
        p.render(self.args)
        self.reviewed()
        self.post.write_text(self.post.read_text(encoding='utf-8')+'新增一句。', encoding='utf-8')
        with self.assertRaises(ValueError): p.validate(self.args)

    def test_rotated_pdf(self):
        doc = fitz.open(self.pdf)
        doc[0].set_rotation(90)
        rotated = self.root/'rotated.pdf'
        doc.save(rotated)
        doc.close()
        args = SimpleNamespace(source=str(rotated), work=str(self.root/'rotated-work'))
        p.prepare(args)
        pages = p.read(self.root/'rotated-work/pages.json')
        self.assertEqual(pages[0]['rect'], [0, 0, 800, 600])

if __name__ == '__main__':
    unittest.main()
