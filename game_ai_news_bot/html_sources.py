"""Bounded collectors for public, server-rendered source pages without an RSS link."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .models import Article

logger = logging.getLogger(__name__)
HTML_SOURCE_KINDS = {"cursor_changelog", "meshy_blog", "convai_blog", "eighty_level"}
MAX_ITEMS = 20
MAX_DETAIL_REQUESTS = 20
_ARTICLE_TYPES = {"Article", "BlogPosting", "NewsArticle", "TechArticle", "HowTo"}
_RESOURCE_TAGS = {"tutorial", "tutorials", "interview", "interviews", "workflow", "workflows", "user stories", "case study", "case studies", "guide", "guides"}
_NEWS_TAGS = {"news", "product", "product update", "updates", "changelog", "release notes"}


def _json_articles(soup):
    def walk(value):
        if isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if _ARTICLE_TYPES.intersection(types):
                yield value
            for key in ("@graph", "itemListElement", "item", "mainEntity"):
                yield from walk(value.get(key))
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.get_text()))
        except (ValueError, TypeError):
            continue


def _absolute_date(value):
    from .collectors import parse_datetime

    value = re.sub(r"\s+", " ", str(value)).strip()
    date = parse_datetime(value)
    if date:
        return date
    patterns = (
        (r"\b\d{1,2} [A-Za-z]+ 20\d{2}\b", ("%d %B %Y", "%d %b %Y")),
        (r"\b[A-Za-z]+ \d{1,2}, 20\d{2}\b", ("%B %d, %Y", "%b %d, %Y")),
        (r"\b20\d{2}-\d{2}-\d{2}\b", ("%Y-%m-%d",)),
    )
    for pattern, formats in patterns:
        match = re.search(pattern, value)
        if match:
            for date_format in formats:
                try:
                    return datetime.strptime(match.group(), date_format).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
    # Relative dates and modified-only metadata never establish publication time.
    return None


def _published(soup, records=(), *, listing=False):
    for record in records:
        date = _absolute_date(record.get("datePublished", ""))
        if date:
            return date, "jsonld:datePublished"
    for selector, evidence in (
        ('[itemprop="datePublished"]', "itemprop:datePublished"),
        ('meta[property="article:published_time"]', "meta:article:published_time"),
        ('meta[name="datePublished"]', "meta:datePublished"),
        ('time[datetime]', "list:time" if listing else "detail:time"),
    ):
        for node in soup.select(selector):
            date = _absolute_date(node.get("content") or node.get("datetime") or node.get_text(" ", strip=True))
            if date:
                return date, evidence
    if listing:
        date = _absolute_date(soup.get_text(" ", strip=True))
        if date:
            return date, "list:text"
    return None, ""


def _tags(soup, kind):
    tags = []
    for node in soup.select('[rel="tag"], [class*="badge"], [data-category], [data-tag]'):
        value = node.get("data-category") or node.get("data-tag") or node.get_text(" ", strip=True)
        if value and len(value) <= 80:
            tags.append(value.strip("# "))
    if kind == "eighty_level":
        tags.extend(node.get_text(" ", strip=True).lstrip("# ") for node in soup.select("span")
                    if node.get_text(" ", strip=True).startswith("#") and len(node.get_text()) <= 80)
    if kind == "meshy_blog":
        known = _RESOURCE_TAGS | _NEWS_TAGS | {"research", "game development", "3d printing", "comparisons", "company"}
        tags.extend(text for text in soup.stripped_strings if text.casefold() in known)
    if kind == "cursor_changelog":
        tags.append("Changelog")
    return list(dict.fromkeys(tags))


def _content_metadata(title, tags, intro="", record_types=()):
    tags = list(dict.fromkeys(tags))
    metadata = {"tags": tags}
    lowered = {tag.casefold() for tag in tags}
    evidence = [f"tag:{tag}" for tag in tags if tag.casefold() in _RESOURCE_TAGS]
    match = re.search(r"\b(tutorial|walkthrough|interview|step.by.step|how to)\b", title, re.I)
    if match:
        evidence.append(f"title:{match.group()}")
    match = re.search(r"\b(?:this|the|our) (tutorial|walkthrough|interview|step.by.step guide)\b", intro, re.I)
    if match:
        evidence.append(f"intro:{match.group()}")
    if "HowTo" in record_types:
        evidence.append("jsonld:@type=HowTo")
    if evidence:
        metadata.update(content_kind="resource", content_kind_evidence=evidence)
    elif lowered & _NEWS_TAGS:
        metadata.update(content_kind="news", content_kind_evidence=[f"tag:{tag}" for tag in tags if tag.casefold() in _NEWS_TAGS])
    if any(re.search(r"\b(sponsored|advertisement|advertorial|paid promotion)\b|광고", tag, re.I) for tag in tags):
        metadata["sponsored"] = True
    return metadata


def _cards(soup, kind):
    if kind == "cursor_changelog":
        for card in soup.select("article"):
            link = card.select_one('h1 a[href*="/changelog/"], h2 a[href*="/changelog/"]')
            if link:
                yield card, link, link
        return
    path = "/articles/" if kind == "eighty_level" else "/blog/"
    for link in soup.select(f'a[href*="{path}"]'):
        heading = link.select_one("h1,h2,h3")
        if not heading or "/category/" in link["href"]:
            continue
        card = link
        if kind == "eighty_level":
            # Title, excerpt, tags and lazy image share this card in the public HTML.
            card = link.find_parent(class_="_3TcmX") or link.find_parent("article") or link.parent.parent
        yield card, link, heading


def _excerpt(card, kind, limit):
    from .collectors import clean_text

    node = card.select_one(".prose p") if kind == "cursor_changelog" else card.select_one("p")
    if not node:
        return ""
    clone = BeautifulSoup(str(node), "html.parser")
    if kind == "eighty_level":
        for date in clone.select("span"):
            if _absolute_date(date.get_text()):
                date.decompose()
    return clean_text(str(clone), limit)


def _relative_order(card):
    """Prioritize Meshy's recent cards before pinned older releases, not publication dating."""
    match = re.search(r"\b(\d+)\s+(minute|hour|day|week|month|year)s? ago\b", card.get_text(" ", strip=True), re.I)
    if not match:
        return float("inf")
    days = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 31, "year": 366}
    return int(match.group(1)) * days[match.group(2).lower()]


def collect_html_source(collector, source: dict) -> list[Article]:
    """Fetch one public list plus at most 20 public details; never paginate or retry blocks."""
    from .collectors import canonical_url, clean_text, image_from_html, media_url

    kind = source["kind"]
    if kind not in HTML_SOURCE_KINDS:
        raise ValueError(f"지원하지 않는 HTML source kind: {kind}")
    item_limit = max(0, min(MAX_ITEMS, int(source.get("max_items", source.get("max_results", MAX_ITEMS)))))
    default_details = {"cursor_changelog": 0, "meshy_blog": 6, "convai_blog": 6, "eighty_level": 4}
    detail_limit = max(0, min(MAX_DETAIL_REQUESTS, int(source.get("max_detail_requests", default_details[kind]))))
    if item_limit == 0:
        return []
    soup = BeautifulSoup(collector._get(source["url"]).text, "html.parser")
    articles = []
    seen_urls = set()
    detail_requests = 0
    cards = list(_cards(soup, kind))
    if kind == "meshy_blog":
        cards.sort(key=lambda item: _relative_order(item[0]))
    for card, link, heading in cards:
        url = canonical_url(urljoin(source["url"], link["href"]))
        if not url or urlsplit(url).hostname != urlsplit(source["url"]).hostname or url in seen_urls:
            continue
        seen_urls.add(url)
        if len(seen_urls) > item_limit:
            break
        title = clean_text(str(heading), 300)
        if not title:
            continue
        published_at, date_evidence = _published(card, _json_articles(card), listing=True)
        description = _excerpt(card, kind, collector.description_limit)
        image = image_from_html(str(card), url)
        tags = _tags(card, kind)
        intro = ""
        record_types = []
        detail_checked = False
        # Cursor's list contains the actual dated release entries. Other sites use
        # details for original datePublished, missing thumbnails and explicit type.
        known_kind = _content_metadata(title, tags).get("content_kind")
        needs_detail = published_at is None or not image or not known_kind
        if kind != "cursor_changelog" and needs_detail and detail_requests < detail_limit:
            detail_requests += 1
            try:
                detail = BeautifulSoup(collector._get(url).text, "html.parser")
                detail_checked = True
                records = []
                for record in _json_articles(detail):
                    record_url = record.get("url")
                    if isinstance(record_url, str) and canonical_url(urljoin(url, record_url)) != url:
                        continue
                    records.append(record)
                detail_date, detail_evidence = _published(detail, records)
                if detail_date:
                    published_at, date_evidence = detail_date, detail_evidence
                for record in records:
                    section = record.get("articleSection", [])
                    if isinstance(section, str):
                        section = [section]
                    tags.extend(item for item in section if isinstance(item, str) and item)
                    types = record.get("@type", [])
                    record_types.extend([types] if isinstance(types, str) else types)
                    if not description:
                        description = clean_text(record.get("description", ""), collector.description_limit)
                    record_image = record.get("image", "")
                    if isinstance(record_image, list):
                        record_image = record_image[0] if record_image else ""
                    if isinstance(record_image, dict):
                        record_image = record_image.get("url", "")
                    image = media_url(record_image, url) or image
                for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]'):
                    node = detail.select_one(selector)
                    if node:
                        image = media_url(node.get("content", ""), url) or image
                        break
                if not description:
                    node = detail.select_one('meta[name="description"], meta[property="og:description"]')
                    if node:
                        description = clean_text(node.get("content", ""), collector.description_limit)
                content = detail.select_one(".blog_content") or detail.select_one("main") or detail.select_one("article")
                if content:
                    intro = content.get_text(" ", strip=True)[:2500]
                    # Only use the opening for explicit tutorial/interview evidence;
                    # do not store or distribute the article body.
                    if kind == "convai_blog":
                        # Convai can reuse another post's SEO description. Prefer
                        # a short, explicit introduction in this article itself.
                        for paragraph in content.select("p")[:3]:
                            opening = paragraph.get_text(" ", strip=True)
                            if re.search(r"\b(?:this tutorial|this walkthrough|convai)\b", opening, re.I):
                                description = clean_text(opening, min(400, collector.description_limit))
                                break
                if kind == "eighty_level" and not tags:
                    tags.extend(_tags(content or detail, kind))
            except Exception as exc:
                logger.info("공개 기사 메타데이터 확인 실패 (%s): %s", url, exc)
        if published_at is None:
            logger.info("발행일을 확인할 수 없어 제외: %s", url)
            continue
        metadata = _content_metadata(title, tags, intro, record_types)
        metadata["published_at_source"] = date_evidence
        if detail_checked or kind == "cursor_changelog":
            metadata["enriched"] = True
        articles.append(Article(
            source_id=source["id"], source_name=source["name"], title=title, url=url,
            description=description, published_at=published_at,
            source_weight=int(source.get("source_weight", 0)),
            perspective=source.get("perspective", "unknown"), image_url=image,
            metadata=metadata,
        ))
    return articles
