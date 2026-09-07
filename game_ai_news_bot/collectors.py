from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .models import Article

logger = logging.getLogger(__name__)

BOILERPLATE_MARKERS = (
    "hello all and welcome",
    "welcome to this week's",
    "welcome to this week’s",
    "subscribe to",
    "sign up for",
    "read more",
    "cookie policy",
    "fantastic time",
    "thank everyone",
    "i'm exhausted",
    "i’m exhausted",
    "far from recovered",
)

SUMMARY_SIGNAL_TERMS = (
    "ai",
    "agent",
    "npc",
    "game",
    "model",
    "research",
    "developer",
    "engine",
    "tool",
    "release",
    "launch",
    "announc",
    "generat",
    "playtest",
    "pipeline",
    "governance",
    "on-device",
    "tool design",
    "qa",
)


def clean_text(value: str, limit: int = 1200) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def canonical_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"}:
        return ""
    kept_query = []
    for pair in parts.query.split("&") if parts.query else []:
        key = pair.partition("=")[0].lower()
        if key.startswith("utm_") or key in {"fbclid", "gclid", "mc_cid", "mc_eid"}:
            continue
        kept_query.append(pair)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "&".join(kept_query), ""))


def media_url(value: str, base_url: str = "") -> str:
    if not value:
        return ""
    candidate = urljoin(base_url, html.unescape(value).strip())
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username:
        return ""
    if parts.path.casefold().endswith((".svg", ".gif")):
        return ""
    return candidate


def _srcset_candidate(value: str) -> str:
    candidates = [part.strip().split()[0] for part in value.split(",") if part.strip()]
    return candidates[-1] if candidates else ""


def image_from_html(value: str, base_url: str = "") -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for image in soup.find_all("img"):
        candidate = ""
        for attribute in ("src", "data-src", "data-original", "data-lazy-src"):
            candidate = image.get(attribute, "")
            if candidate:
                break
        if not candidate and image.get("srcset"):
            candidate = _srcset_candidate(image["srcset"])
        resolved = media_url(candidate, base_url)
        if resolved:
            return resolved
    return ""


def image_from_feed_entry(entry: ET.Element, description_html: str, article_url: str) -> str:
    for node in entry.iter():
        name = _local_name(node.tag)
        if name not in {"thumbnail", "content", "enclosure", "image"}:
            continue
        media_type = str(node.attrib.get("type", "")).casefold()
        medium = str(node.attrib.get("medium", "")).casefold()
        if name == "enclosure" and media_type and not media_type.startswith("image/"):
            continue
        if name == "content" and media_type and not media_type.startswith("image/") and medium != "image":
            continue
        candidate = node.attrib.get("url") or node.attrib.get("href") or ""
        resolved = media_url(candidate, article_url)
        if resolved:
            return resolved
    return image_from_html(description_html, article_url)


def _excerpt_score(value: str, title: str) -> float:
    lowered = value.casefold()
    score = min(len(value), 500) / 100
    if any(marker in lowered for marker in BOILERPLATE_MARKERS):
        score -= 8
    title_terms = {
        term
        for term in re.findall(r"[a-z0-9가-힣]{3,}", title.casefold())
        if term
        not in {
            "with",
            "from",
            "about",
            "this",
            "that",
            "game",
            "games",
            "gamescom",
            "post",
            "musings",
            "gossip",
            "dev",
        }
    }
    score += sum(2 for term in title_terms if term in lowered)
    score += sum(0.5 for term in SUMMARY_SIGNAL_TERMS if term in lowered)
    return score


def page_metadata(html_text: str, page_url: str, title: str) -> tuple[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    image = ""
    for attributes in (
        {"property": "og:image:secure_url"},
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"name": "twitter:image:src"},
    ):
        node = soup.find("meta", attrs=attributes)
        image = media_url(node.get("content", "") if node else "", page_url)
        if image:
            break
    if not image:
        image_link = soup.find("link", rel=lambda value: value and "image_src" in value)
        image = media_url(image_link.get("href", "") if image_link else "", page_url)
    if not image:
        content_root = soup.find("article") or soup.find("main") or soup
        image = image_from_html(str(content_root), page_url)

    excerpts: list[str] = []
    for attributes in (
        {"property": "og:description"},
        {"name": "twitter:description"},
        {"name": "description"},
    ):
        node = soup.find("meta", attrs=attributes)
        excerpt = clean_text(node.get("content", "") if node else "", 700)
        if len(excerpt) >= 40:
            excerpts.append(excerpt)
    content_root = soup.find("article") or soup.find("main")
    if content_root:
        for paragraph in content_root.find_all("p")[:40]:
            excerpt = clean_text(paragraph.get_text(" ", strip=True), 700)
            if len(excerpt) >= 40:
                excerpts.append(excerpt)
    best_excerpt = max(excerpts, key=lambda value: _excerpt_score(value, title), default="")
    return image, best_excerpt


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _children_by_name(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _local_name(child.tag) == name]


def _first_text(element: ET.Element, *names: str) -> str:
    # 호출자가 준 순서를 우선순위로 사용한다. 예: 짧은 description보다 encoded 본문이 우선.
    for name in names:
        wanted = name.lower()
        for child in list(element):
            if _local_name(child.tag) == wanted:
                if len(child):
                    return (child.text or "") + "".join(
                        ET.tostring(node, encoding="unicode") for node in child
                    )
                if child.text and child.text.strip():
                    return child.text.strip()
    return ""


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        result = None
    if result is None:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def parse_date_from_text(value: str) -> datetime | None:
    if not value:
        return None
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value)
    if iso_match:
        return datetime.strptime(iso_match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    month_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},\s+20\d{2}\b",
        value,
        flags=re.IGNORECASE,
    )
    if month_match:
        return datetime.strptime(month_match.group(0).title(), "%B %d, %Y").replace(tzinfo=timezone.utc)
    return None


def parse_feed(xml_text: str, source: dict, description_limit: int = 900) -> list[Article]:
    # 일부 CDN은 정상 XML 뒤에 챌린지 <script>를 덧붙인다. 첫 피드 문서까지만 파싱한다.
    for closing_tag in ("</rss>", "</feed>"):
        end = xml_text.find(closing_tag)
        if end >= 0:
            xml_text = xml_text[: end + len(closing_tag)]
            break
    root = ET.fromstring(xml_text)
    root_name = _local_name(root.tag)
    entries: list[ET.Element] = []
    if root_name == "rss":
        channel = next((c for c in list(root) if _local_name(c.tag) == "channel"), root)
        entries = _children_by_name(channel, "item")
    elif root_name == "feed":
        entries = _children_by_name(root, "entry")
    else:
        entries = [e for e in root.iter() if _local_name(e.tag) in {"item", "entry"}]

    articles: list[Article] = []
    for entry in entries:
        title = clean_text(_first_text(entry, "title"), 300)
        description = _first_text(entry, "encoded", "content", "summary", "description")
        link = _first_text(entry, "link")
        if not link:
            for node in _children_by_name(entry, "link"):
                href = node.attrib.get("href", "")
                rel = node.attrib.get("rel", "alternate")
                if href and rel in {"alternate", ""}:
                    link = href
                    break
        published = _first_text(entry, "pubdate", "published", "updated", "date")
        url = canonical_url(link)
        if not title or not url:
            continue
        is_geeknews = source.get("editorial_filter") == "geeknews"
        metadata = {
            "language": source.get("language", ""),
            "tags": [clean_text(node.text or node.attrib.get("term", ""), 100)
                     for node in _children_by_name(entry, "category")],
        }
        if is_geeknews:
            metadata["editorial_filter"] = "geeknews"
            metadata["button_text"] = "📰 긱뉴스에서 읽기"
            # 한국어 목록을 한 줄로 합치면 짧은 소개가 중간 문장에서 잘린다.
            soup = BeautifulSoup(description, "html.parser")
            blocks = soup.find_all(lambda tag: tag.name.split(":")[-1] in {"li", "p"})
            lines = [node.get_text(" ", strip=True) for node in blocks]
            plain_description = "\n".join(lines) if lines else soup.get_text(" ", strip=True)
        else:
            plain_description = clean_text(description, description_limit)
        articles.append(
            Article(
                source_id=source["id"],
                source_name=source["name"],
                title=title,
                url=url,
                description=plain_description[:description_limit],
                published_at=parse_datetime(published),
                source_weight=int(source.get("source_weight", 0)),
                perspective=source.get("perspective", "unknown"),
                image_url=image_from_feed_entry(entry, description, url),
                metadata=metadata,
            )
        )
    return articles


class Collector:
    def __init__(self, http_config: dict, description_limit: int = 900):
        self.timeout = int(http_config.get("timeout_seconds", 25))
        self.delay = float(http_config.get("delay_seconds", 0.5))
        self.description_limit = description_limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": http_config.get("user_agent", "game-ai-news-bot/0.1"),
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.8",
            }
        )

    def _get(self, url: str, **kwargs) -> requests.Response:
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        time.sleep(self.delay)
        return response

    def enrich_article(self, article: Article) -> Article:
        """선별된 기사만 열어 대표 이미지와 더 나은 공개 요약 문맥을 보강한다."""
        if article.metadata.get("enriched") or article.metadata.get("repository"):
            # 구조화된 릴리스 본문과 이미 조회한 상세 소개를 HTML 메뉴로 덮어쓰지 않는다.
            return article
        try:
            response = self._get(
                article.url,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2"
                },
            )
            content_type = response.headers.get("content-type", "").casefold()
            if content_type and "html" not in content_type:
                return article
            discovered_image, excerpt = page_metadata(
                response.text, article.url, article.title
            )
            if article.metadata.get("editorial_filter") == "geeknews":
                # 공개 상세 페이지가 응답할 때만 제목 링크를 사용한다. 403은
                # 아래 예외 처리로 RSS 소개와 Telegram 링크 미리보기를 유지한다.
                soup = BeautifulSoup(response.text, "html.parser")
                heading_link = soup.select_one(".topictitle a[href]")
                if heading_link:
                    original = canonical_url(urljoin(article.url, heading_link["href"]))
                    if original and urlsplit(original).hostname != "news.hada.io":
                        article.metadata["original_url"] = original
                if discovered_image:
                    article.image_url = discovered_image
                # 한국어 피드 소개를 영문 원문이나 페이지 메뉴로 덮어쓰지 않는다.
                return article
            if not article.image_url and discovered_image:
                article.image_url = discovered_image
            if excerpt and (
                not article.description
                or _excerpt_score(excerpt, article.title)
                > _excerpt_score(article.description, article.title) + 1
            ):
                article.description = clean_text(excerpt, self.description_limit)
        except Exception as exc:
            logger.info("기사 메타데이터 보강 실패 (%s): %s", article.url, exc)
        return article

    def collect_source(self, source: dict) -> list[Article]:
        kind = source.get("kind", "rss")
        if kind == "github_releases":
            from .github_releases import collect_github_releases
            return collect_github_releases(self, source)
        if kind in {"cursor_changelog", "meshy_blog", "convai_blog", "eighty_level"}:
            from .html_sources import collect_html_source
            return collect_html_source(self, source)
        if kind == "rss":
            return self._collect_rss(source)
        if kind == "html":
            return self._collect_html(source)
        if kind == "arxiv":
            return self._collect_arxiv(source)
        if kind == "krafton_blog":
            return self._collect_krafton_blog(source)
        raise ValueError(f"지원하지 않는 source kind: {kind}")

    def collect_all(self, sources: list[dict]) -> tuple[list[Article], list[str]]:
        articles: list[Article] = []
        errors: list[str] = []
        for source in sources:
            if source.get("enabled", True) is False:
                continue
            try:
                found = self.collect_source(source)
                logger.info("%s: %d건 수집", source["name"], len(found))
                articles.extend(found)
            except Exception as exc:  # 한 소스 장애가 전체 브리핑을 막지 않게 한다.
                logger.warning("%s 수집 실패: %s", source.get("name", source.get("id")), exc)
                errors.append(f"{source.get('name', source.get('id'))}: {exc}")
        return articles, errors

    def _collect_rss(self, source: dict) -> list[Article]:
        response = self._get(source["url"])
        return parse_feed(response.text, source, self.description_limit)

    def _collect_arxiv(self, source: dict) -> list[Article]:
        params = {
            "search_query": source["query"],
            "start": 0,
            "max_results": int(source.get("max_results", 30)),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = "https://export.arxiv.org/api/query?" + urlencode(params)
        response = self._get(url)
        return parse_feed(response.text, source, self.description_limit)

    def _collect_html(self, source: dict) -> list[Article]:
        response = self._get(source["url"])
        soup = BeautifulSoup(response.content, "html.parser")
        pattern = re.compile(source["link_pattern"], re.IGNORECASE)
        seen: set[str] = set()
        articles: list[Article] = []
        for anchor in soup.find_all("a", href=True):
            url = canonical_url(urljoin(source["url"], anchor["href"]))
            if not url or not pattern.search(url) or url in seen:
                continue
            title = clean_text(anchor.get("aria-label") or anchor.get_text(" ", strip=True), 300)
            if len(title) < 10:
                continue
            container = anchor.find_parent("article") or anchor.find_parent("li") or anchor.parent
            description = clean_text(container.get_text(" ", strip=True) if container else "", self.description_limit)
            image_url = image_from_html(str(container) if container else "", source["url"])
            if description == title:
                description = ""
            published = parse_date_from_text(description)
            if source.get("require_date", False) and published is None:
                continue
            seen.add(url)
            articles.append(
                Article(
                    source_id=source["id"],
                    source_name=source["name"],
                    title=title,
                    url=url,
                    description=description,
                    published_at=published,
                    source_weight=int(source.get("source_weight", 0)),
                    perspective=source.get("perspective", "unknown"),
                    image_url=image_url,
                )
            )
            if len(articles) >= int(source.get("max_results", 30)):
                break
        return articles

    def _collect_krafton_blog(self, source: dict) -> list[Article]:
        """KRAFTON AI가 페이지 안에 제공하는 공개 영문 포스트 메타데이터를 읽는다."""
        response = self._get(source["url"])
        text = response.content.decode("utf-8", errors="replace")
        pattern = re.compile(
            r'\{\s*date_en:\s*"(?P<date>(?:\\.|[^"\\])*)"'
            r'.*?title_en:\s*"(?P<title>(?:\\.|[^"\\])*)"'
            r'.*?excerpt_en:\s*"(?P<description>(?:\\.|[^"\\])*)"'
            r'.*?file_en:\s*"(?P<file>(?:\\.|[^"\\])*)"',
            re.DOTALL,
        )

        def unescape(value: str) -> str:
            return (
                value.replace("\\'", "'")
                .replace('\\"', '"')
                .replace("\\n", " ")
                .replace("\\/", "/")
            )

        articles: list[Article] = []
        for match in pattern.finditer(text):
            date_value = unescape(match.group("date"))
            published = None
            try:
                published = datetime.strptime(date_value, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            title = clean_text(unescape(match.group("title")), 300)
            description = clean_text(unescape(match.group("description")), self.description_limit)
            url = canonical_url(urljoin(source["url"], unescape(match.group("file"))))
            if title and url:
                articles.append(
                    Article(
                        source_id=source["id"],
                        source_name=source["name"],
                        title=title,
                        url=url,
                        description=description,
                        published_at=published,
                        source_weight=int(source.get("source_weight", 0)),
                        perspective=source.get("perspective", "unknown"),
                    )
                )
        return articles[: int(source.get("max_results", 30))]
