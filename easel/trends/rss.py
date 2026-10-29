"""RSS 2.0 / RSS 1.0 RDF / Atom to the collector v1 contract (stdlib only)."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from .protocol import MAX_BYTES, MAX_ITEMS, CollectorError, utc_now, validate_payload, web_url

ATOM = "http://www.w3.org/2005/Atom"
RSS1 = "http://purl.org/rss/1.0/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC = "http://purl.org/dc/elements/1.1/"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"


def _text(node: ET.Element | None) -> str:
    return html.unescape("".join(node.itertext()).strip()) if node is not None else ""


def _date(value: str) -> str | None:
    if not value:
        return None
    try:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(value)
        # Feeds sometimes omit the timezone. Do not invent a publication instant.
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def parse_feed(raw: bytes, url: str) -> dict:
    if len(raw) > MAX_BYTES:
        raise CollectorError("output_too_large")
    # Forbid DTD/entity declarations, including UTF-16/32 encoded declarations.
    # ElementTree does not fetch external entities, but inline expansion is unnecessary here.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw.replace(b"\x00", b""), re.I):
        raise CollectorError("invalid_response")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, LookupError):
        raise CollectorError("invalid_response") from None
    stack, count = [(root, 0)], 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > 12000 or depth > 32:
            raise CollectorError("invalid_response")
        stack.extend((child, depth + 1) for child in element)
    atom = root.tag == f"{{{ATOM}}}feed"
    base = urljoin(url, root.get(XML_BASE, ""))
    if atom:
        entries = root.findall(f"{{{ATOM}}}entry")
        prefix = f"{{{ATOM}}}"
    elif root.tag == "rss" and root.find("channel") is not None:
        channel = root.find("channel")
        base = urljoin(base, channel.get(XML_BASE, ""))
        entries = channel.findall("item")
        prefix = ""
    elif root.tag == f"{{{RDF}}}RDF":
        entries = root.findall(f"{{{RSS1}}}item")
        if not entries and root.find(f"{{{RSS1}}}channel") is None:
            raise CollectorError("invalid_response")
        prefix = f"{{{RSS1}}}"
    else:
        raise CollectorError("invalid_response")
    items = []
    for entry in entries:
        title = _text(entry.find(prefix + "title"))
        if not title:
            continue
        entry_base = urljoin(base, entry.get(XML_BASE, ""))
        link = ""
        if atom:
            for candidate in entry.findall(prefix + "link"):
                if candidate.get("rel", "alternate") == "alternate" and candidate.get("href"):
                    link = urljoin(urljoin(entry_base, candidate.get(XML_BASE, "")), candidate.get("href"))
                    break
            identifier = _text(entry.find(prefix + "id"))
            published = _text(entry.find(prefix + "published")) or _text(entry.find(prefix + "updated"))
        else:
            link_text = _text(entry.find(prefix + "link"))
            if link_text:
                link = urljoin(entry_base, link_text)
            guid = entry.find("guid")
            identifier = _text(guid) or entry.get(f"{{{RDF}}}about", "")
            if not link and guid is not None and guid.get("isPermaLink", "true").lower() != "false":
                if identifier.startswith(("http://", "https://")):
                    link = identifier
            published = _text(entry.find("pubDate")) or _text(entry.find(f"{{{DC}}}date"))
        # Unsafe/malformed links in a feed must never become clickable script URLs.
        try:
            link = web_url(link, optional=True)
        except CollectorError:
            link = ""
        item = {"title": title, "url": link, "published_at": _date(published)}
        if identifier:
            item["id"] = identifier
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return validate_payload({"version": 1, "fetched_at": utc_now(), "items": items})
