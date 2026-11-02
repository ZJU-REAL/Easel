"""Feed formats, dates, XML safety and canonical trend mapping."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from easel.trends.protocol import MAX_BYTES, CollectorError
from easel.trends.rss import parse_feed


def parse(xml):
    return parse_feed(xml.encode('utf-8'), 'https://example.com/news/feed.xml')


def test_rss2_guids_links_and_publication_dates():
    result = parse('''<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>订阅</title>
      <item><guid isPermaLink="false">topic-1</guid><title><![CDATA[标题 &amp; 新闻]]></title>
        <link>../article/1</link><pubDate>Thu, 29 Oct 2026 10:00:00 +0800</pubDate></item>
      <item><guid>https://example.com/article/2</guid><title>第二篇</title><pubDate>not-a-date</pubDate></item>
      <item><guid isPermaLink="false">not-a-link</guid><title>第三篇</title></item>
      <item><title> </title></item>
    </channel></rss>''')
    assert len(result['items']) == 3
    first, second, third = result['items']
    assert first['id'] == 'topic-1' and first['title'] == '标题 & 新闻'
    assert first['url'] == 'https://example.com/article/1'
    assert first['published_at'] == '2026-10-29T02:00:00+00:00'
    assert second['url'] == 'https://example.com/article/2' and second['published_at'] is None
    assert third['url'] == '' and third['hot'] == ''


def test_atom_namespaces_alternate_links_and_xml_base():
    result = parse('''<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://example.com/blog/">
      <entry xml:base="posts/"><id>tag:example.com,2026:1</id><title type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Hello <b>Atom</b></div></title>
        <link rel="self" href="api/1"/><link rel="alternate" href="1"/>
        <published>2026-10-29T10:00:00+08:00</published></entry>
      <entry><title>Updated only</title><link href="2"/><updated>2026-10-29T02:00:00Z</updated></entry>
    </feed>''')
    first, second = result['items']
    assert first['id'] == 'tag:example.com,2026:1' and first['title'] == 'Hello Atom'
    assert first['url'] == 'https://example.com/blog/posts/1'
    assert second['url'] == 'https://example.com/blog/2'
    assert first['published_at'] == second['published_at'] == '2026-10-29T02:00:00+00:00'


def test_rss1_rdf_and_dublin_core_dates():
    result = parse('''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <channel rdf:about="https://example.com/feed"/>
      <item rdf:about="https://example.com/article/1"><title>RDF</title><link>https://example.com/article/1</link>
        <dc:date>2026-10-29T02:00:00Z</dc:date></item>
    </rdf:RDF>''')
    assert result['items'][0]['title'] == 'RDF'
    assert result['items'][0]['id'] == 'https://example.com/article/1'
    assert result['items'][0]['published_at'] == '2026-10-29T02:00:00+00:00'


def test_empty_feed_duplicates_invalid_links_and_naive_dates():
    assert parse('<rss><channel/></rss>')['items'] == []
    assert parse('<feed xmlns="http://www.w3.org/2005/Atom"/>')['items'] == []
    result = parse('''<rss><channel>
      <item><guid isPermaLink="false">one</guid><title>unsafe link</title><link>javascript:alert(1)</link>
        <pubDate>2026-10-29T10:00:00</pubDate></item>
      <item><guid isPermaLink="false">one</guid><title>duplicate</title></item>
    </channel></rss>''')
    assert len(result['items']) == 1
    assert result['items'][0]['url'] == '' and result['items'][0]['published_at'] is None


@pytest.mark.parametrize('xml', [
    '<html><title>Not a Feed</title></html>', '<rss>',
    '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss><channel/></rss>',
    '<!DOCTYPE rss [<!ENTITY a "expanded">]><rss><channel><item><title>&a;</title></item></channel></rss>',
    '<?xml version="1.0" encoding="unsupported-encoding"?><rss><channel/></rss>',
])
def test_invalid_or_entity_defining_feeds_rejected(xml):
    with pytest.raises(CollectorError, match='invalid_response'):
        parse(xml)


def test_utf16_entity_declaration_is_also_rejected():
    raw = '<!DOCTYPE rss [<!ENTITY a "expanded">]><rss><channel/></rss>'.encode('utf-16')
    with pytest.raises(CollectorError, match='invalid_response'):
        parse_feed(raw, 'https://example.com/feed')


def test_feed_size_and_item_count_are_bounded():
    with pytest.raises(CollectorError, match='output_too_large'):
        parse_feed(b'x' * (MAX_BYTES + 1), 'https://example.com/feed')
    items = ''.join(f'<item><title>Article {i}</title></item>' for i in range(501))
    assert len(parse('<rss><channel>' + items + '</channel></rss>')['items']) == 500


def test_bundled_feed_example_obeys_the_unified_contract():
    path = Path(__file__).resolve().parents[1] / 'examples/trends/feed.xml'
    result = parse_feed(path.read_bytes(), 'http://127.0.0.1:8767/feed.xml')
    assert result['items'][0]['id'] == 'example-rss-1'
    assert result['items'][0]['published_at'] == '2026-10-29T02:00:00+00:00'
