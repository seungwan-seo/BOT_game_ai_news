from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import Article


_GROUP_DAYS = 7
_FETCH_DAYS = 14  # 최근 7일 기사와 그 기사에 앞선 기능 릴리스 묶음을 함께 확인한다.
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_VERSION = re.compile(r"(?:^|[-_])v?(\d+)\.(\d+)\.(\d+)(?:\+[A-Za-z0-9.-]+)?$", re.I)
_FEATURE = re.compile(
    r"\b(?:add(?:ed|s|ing)?|new|introduc\w*|support\w*|now|enable\w*|"
    r"security|CVE-\d|workflow\w*|improv\w*|allow\w*|feature\w*)\b", re.I
)
_FIX_START = re.compile(r"^(?:fix(?:ed|es)?|hotfix|bugfix|resolve[ds]?|correct(?:ed|s)?|repair\w*)\b", re.I)
_BOILERPLATE = re.compile(
    r"^(?:full change(?:log|\s+list)|changelog|what['’]?s changed|new contributors|contributors|"
    r"installation|install(?:ing)?(?:\s|$)|downloads?|assets?|checksums?|sha256|"
    r"thanks\b|thank you\b|\*?\*?note:|npm install|brew (?:install|upgrade)|"
    r"pip install|docker (?:pull|run)|see (?:the )?(?:full )?(?:release|change)|"
    r"for (?:a|the) (?:full|complete) (?:rundown|list|overview)|https?://)", re.I
)
_INTRO_BOILERPLATE = re.compile(
    r"^(?:this|the) release\b.*\b(?:a few bugs|minor features|various bug fixes)\b"
    r".*\b(?:previous release|full rundown|full changelog)\b", re.I
)
_GENERIC = re.compile(
    r"^(?:(?:various|minor|general|miscellaneous|additional)\s+)?"
    r"(?:bug\s*fix(?:es)?|fixes|improvements?|maintenance|stability|performance)"
    r"(?:[\s,./&+-]+(?:and\s+)?(?:bug\s*fix(?:es)?|fixes|improvements?|updates?|"
    r"maintenance|stability|performance))*[.!:]?$", re.I
)
_ABBREVIATION_END = re.compile(
    r"(?:\b(?:[A-Za-z]\.){2,}|\b(?:etc|vs|Dr|Mr|Ms|Mrs|Prof|No|Fig)\.)$", re.I
)


@dataclass
class _Release:
    tag: str
    series: str
    url: str
    published: datetime
    lines: list[str]
    feature_lines: list[str]


@dataclass
class _Group:
    anchor: _Release
    members: list[_Release] = field(default_factory=list)


def _public_lines(body: str) -> tuple[list[str], list[str]]:
    # Collector가 이 모듈을 불러오므로 공용 파서는 함수 안에서 가져온다.
    from .collectors import clean_text

    body = re.sub(r"```.*?```", "", body, flags=re.S)
    entries: list[tuple[bool, str]] = []
    skip_section = False
    for raw_line in body.splitlines():
        heading = re.match(r"^\s*#{1,6}\s+(.+)", raw_line)
        if heading:
            skip_section = bool(re.match(
                r"(?:full\s+)?change(?:log|\s+list)\b|(?:new\s+)?contributors?\b|"
                r"install(?:ation|ing)?\b|downloads?\b|documentation\b|assets?\b",
                heading[1], re.I,
            ))
            continue
        if skip_section:
            continue
        value = re.sub(r"!\[[^]]*\]\([^)]*\)", "", raw_line)
        value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
        is_bullet = bool(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", value))
        value = re.sub(r"^\s*[-*+>]+\s*", "", value)
        value = re.sub(r"^\s*\d+[.)]\s+", "", value)
        value = value.replace("**", "").replace("`", "").strip()
        value = re.sub(r"\s*\(@[\w-]+\s*\)\s*", " ", value)
        value = clean_text(value, 1200)
        if (len(value) < 12 or _BOILERPLATE.search(value) or _INTRO_BOILERPLATE.search(value)
                or _GENERIC.fullmatch(value) or re.match(r"#\d+\b", value)):
            continue
        if not re.search(r"[A-Za-z]{3}", value):
            continue
        entries.append((is_bullet, value))
    # Introductory prose should not displace concrete release bullets.
    lines = list(dict.fromkeys(value for _, value in sorted(entries, key=lambda entry: not entry[0])))
    features = [value for value in lines if _FEATURE.search(value) and not _FIX_START.search(value)]
    return lines, features


def _short_excerpt(value: str, limit: int, *, headline: bool = False) -> str:
    """Keep a complete opening sentence where possible, otherwise end on a word."""
    value = value.strip()
    if limit <= 0:
        return ""
    # Find boundaries in the complete text: a clipped prefix can end inside
    # a version number, domain or abbreviation and make its dot look terminal.
    boundaries = [
        match for match in re.finditer(r"[.!?;](?:[\"')\]]*)(?:\s|$)|\s+[—–]\s+", value)
        if not (value[match.start()] == "." and _ABBREVIATION_END.search(value[:match.start() + 1]))
    ]
    if headline:
        first_sentence = next((match for match in boundaries if value[match.start()] in ".!?"), None)
        if first_sentence and first_sentence.end() <= limit:
            return value[:first_sentence.end()].strip()
    if len(value) <= limit:
        return value
    prefix = value[:max(0, limit - 1)]
    # A semicolon or a spaced dash can separate a self-contained opening clause.
    clauses = [match for match in boundaries if match.end() <= len(prefix)]
    if clauses and clauses[-1].start() >= min(40, limit // 2):
        return prefix[:clauses[-1].end()].rstrip(" ;—–")
    if len(value) > len(prefix) and not value[len(prefix)].isspace():
        prefix = prefix.rsplit(" ", 1)[0] if " " in prefix else ""
    return prefix.rstrip(" ,;:—–") + "…"


def _sentence(value: str) -> str:
    return value if re.search(r"[.!?…](?:[\"')\]]*)$", value) else value + "."


def _parse_release(raw: dict, repository: str, cutoff: datetime) -> _Release | None:
    from .collectors import canonical_url

    if not isinstance(raw, dict) or raw.get("draft") or raw.get("prerelease"):
        return None
    tag = raw.get("tag_name")
    body = raw.get("body")
    if not isinstance(tag, str) or not isinstance(body, str) or not body.strip():
        return None
    version = _VERSION.search(tag)
    if not version:
        return None
    try:
        published = datetime.fromisoformat(str(raw.get("published_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        return None
    published = published.astimezone(timezone.utc)
    if published < cutoff:
        return None
    url = canonical_url(str(raw.get("html_url", "")))
    if not url.casefold().startswith(f"https://github.com/{repository}/releases/tag/".casefold()):
        return None
    lines, features = _public_lines(body)
    return _Release(tag, f"{version[1]}.{version[2]}", url, published, lines, features)


def collect_github_releases(collector, source: dict) -> list[Article]:
    """Collect substantive public releases and group nearby follow-up patch notes.

    Each feature release starts a new group, even within one major/minor series.
    Follow-up fixes join that anchor for at most seven days. Its publication date
    and URL stay fixed, so a later hotfix cannot make old feature news new again.
    """
    repository = source.get("repository", "")
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError("github_releases repository must be owner/repository")
    product = str(source.get("product") or source["name"]).strip()
    cutoff = datetime.now(timezone.utc) - timedelta(days=_FETCH_DAYS)
    records: list[_Release] = []
    urls: set[str] = set()
    for page in range(1, 4):
        response = collector._get(
            f"https://api.github.com/repos/{repository}/releases",
            params={"per_page": 100, "page": page},
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"GitHub releases response is not a list: {repository}")
        page_dates: list[datetime] = []
        for raw in payload:
            if isinstance(raw, dict):
                try:
                    date = datetime.fromisoformat(str(raw.get("published_at", "")).replace("Z", "+00:00"))
                    if date.tzinfo is not None:
                        page_dates.append(date)
                except ValueError:
                    pass
            release = _parse_release(raw, repository, cutoff)
            if release is not None and release.url not in urls:
                records.append(release)
                urls.add(release.url)
        # 야간 prerelease가 첫 100건을 채우면 공개 next 단서를 따라 계속한다.
        # 오래된 릴리스 본문까지 모두 긁지 않고 날짜가 겹치는 최대 3페이지만 확인한다.
        if len(payload) < 100 or not response.links.get("next"):
            break
        if page_dates and min(page_dates) < cutoff:
            break

    records.sort(key=lambda release: (release.published, release.tag))
    groups: list[_Group] = []
    active: dict[str, _Group] = {}
    for release in records:
        previous = active.get(release.series)
        can_join = (
            previous is not None
            and not release.feature_lines
            and release.published - previous.anchor.published <= timedelta(days=_GROUP_DAYS)
        )
        if can_join:
            previous.members.append(release)
        elif release.lines:
            group = _Group(release, [release])
            groups.append(group)
            active[release.series] = group

    articles: list[Article] = []
    for group in reversed(groups):
        anchor = group.anchor
        # 기능 신호를 먼저 담아 설치·다운로드 안내가 짧은 요약을 차지하지 않게 한다.
        ordered_lines = list(dict.fromkeys([
            *anchor.feature_lines, *anchor.lines,
            *(line for member in group.members[1:] for line in member.lines),
        ]))
        headline = _short_excerpt(ordered_lines[0], 150, headline=True)
        # Explicit punctuation survives whitespace normalization in the summarizer.
        description = _short_excerpt("\n".join(_sentence(line) for line in ordered_lines),
                                     max(0, int(collector.description_limit)))
        release_summary = " ".join(
            _sentence(_short_excerpt(line, 200, headline=True)) for line in ordered_lines[:2]
        )
        reason = f"게임 제작에 활용하는 {product}의 공식 기능·보안·작업 흐름 업데이트"
        articles.append(Article(
            source_id=source["id"],
            source_name=source["name"],
            title=f"{product} {anchor.tag} — {headline}",
            url=anchor.url,
            description=description,
            published_at=anchor.published,
            source_weight=int(source.get("source_weight", 0)),
            perspective=source.get("perspective", "vendor"),
            category="🛠 개발 도구",
            metadata={
                "content_kind": "news",
                "repository": repository,
                "product": product,
                "release_group_key": f"github:{repository.casefold()}:{anchor.tag}",
                "release_tags": [member.tag for member in group.members],
                "release_summary": release_summary,
                "alias_urls": [member.url for member in group.members],
                "published_at_source": "github.published_at",
                "editorial_reason": reason,
            },
        ))
    return articles[:max(0, int(source.get("max_results", 30)))]
