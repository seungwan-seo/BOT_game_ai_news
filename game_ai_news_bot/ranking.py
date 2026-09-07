from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher

from .models import Article
from .geeknews import evaluate_article as evaluate_geeknews
from .editorial import classify_content_kind, evaluate_source_article
from .freshness import is_fresh


CATEGORY_RULES = [
    ("🤖 NPC·에이전트", ("npc", "character", "companion", "agent", "cpc", "dialogue", "behavior tree")),
    ("🌍 월드·콘텐츠 생성", ("world model", "procedural", "content generation", "3d generation", "world generation")),
    ("🛠 개발 도구", ("game development", "game developer", "engine", "unity", "unreal", "copilot", "workflow", "asset")),
    ("🧪 테스트·플레이어 모델", ("playtest", "testing", "player model", "matchmaking", "anti-cheat", "telemetry")),
    ("📚 연구", ("paper", "research", "benchmark", "reinforcement learning", "arxiv", "model")),
    ("⚖️ 산업·정책", ("copyright", "law", "policy", "industry", "studio", "developer survey", "regulation")),
]


def normalized_title(title: str) -> str:
    value = title.casefold()
    value = re.sub(r"[^0-9a-z가-힣]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def keyword_score(article: Article, positive: dict, negative: dict) -> int:
    title = article.title.casefold()
    body = f"{article.title} {article.description}".casefold()
    total = 0
    consumed: set[str] = set()
    for keyword, weight in sorted(positive.items(), key=lambda pair: len(pair[0]), reverse=True):
        key = keyword.casefold()
        if key in body:
            # 제목 일치는 본문/설명 일치보다 신호가 강하다.
            total += int(weight) * (2 if key in title else 1)
            consumed.add(key)
    for keyword, weight in negative.items():
        if keyword.casefold() in body:
            total += int(weight)
    return total


def classify(article: Article) -> str:
    text = f"{article.title} {article.description}".casefold()
    best = (0, "📰 기타")
    for category, terms in CATEGORY_RULES:
        hits = sum(1 for term in terms if term in text)
        if hits > best[0]:
            best = (hits, category)
    return best[1]


def _recency_score(article: Article, now: datetime) -> float:
    if article.published_at is None:
        return 1.0
    age_hours = max(0.0, (now - article.published_at).total_seconds() / 3600)
    if age_hours <= 24:
        return 6.0
    if age_hours <= 72:
        return 4.0
    if age_hours <= 168:
        return 2.0
    return 0.0


def rank_articles(
    articles: list[Article], config: dict, now: datetime | None = None,
    *, fresh_only: bool = False,
) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    ranking = config.get("ranking", {})
    positive = ranking.get("positive_keywords", {})
    negative = ranking.get("negative_keywords", {})
    source_config = {item["id"]: item for item in config["sources"]}
    ranked: list[Article] = []

    for article in articles:
        source = source_config.get(article.source_id, {})
        article.metadata["content_kind"] = classify_content_kind(article, source)
        # Invalid or expired dates must not suppress an eligible duplicate.
        if fresh_only and not is_fresh(article, config.get("digest", {}), now):
            continue
        if source.get("editorial_profile"):
            if not evaluate_source_article(article, source):
                continue
            article.score = (
                article.source_weight + article.metadata["editorial_score"]
                + _recency_score(article, now)
            )
            ranked.append(article)
            continue
        if source.get("editorial_filter") == "geeknews":
            if not evaluate_geeknews(article):
                continue
            article.score = (
                article.source_weight
                + article.metadata["geeknews_score"]
                + _recency_score(article, now)
            )
            ranked.append(article)
            continue
        article.relevance = keyword_score(article, positive, negative)
        minimum = int(source.get("min_relevance", 0))
        if not source.get("trusted", False) and article.relevance < minimum:
            continue
        if article.relevance < -2:
            continue
        article.category = classify(article)
        article.score = article.source_weight + article.relevance + _recency_score(article, now)
        ranked.append(article)

    ranked.sort(key=lambda item: (item.score, item.published_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return deduplicate(ranked)


def deduplicate(articles: list[Article], similarity: float = 0.84) -> list[Article]:
    kept: list[Article] = []
    seen_urls: set[str] = set()
    seen_titles: list[tuple[str, str]] = []
    for article in articles:
        if article.identity_urls & seen_urls:
            continue
        title = normalized_title(article.title)
        release_group = str(article.metadata.get("release_group_key", ""))
        duplicate = any(
            SequenceMatcher(None, title, previous).ratio() >= similarity
            for previous, previous_group in seen_titles
            if title and previous
            and not (release_group and previous_group and release_group != previous_group)
        )
        if duplicate:
            continue
        seen_urls.update(article.identity_urls)
        seen_titles.append((title, release_group))
        kept.append(article)
    return kept


def select_diverse(
    articles: list[Article], limit: int, max_per_source: int = 2,
    *, source_limits: dict[str, int] | None = None,
) -> list[Article]:
    """한 출처가 브리핑을 독점하지 않도록 점수 순서를 유지하며 출처별 상한을 둔다."""
    selected: list[Article] = []
    counts: Counter[str] = Counter()
    for article in articles:
        source_limit = min(max_per_source, (source_limits or {}).get(article.source_id, max_per_source))
        if counts[article.source_id] >= source_limit:
            continue
        selected.append(article)
        counts[article.source_id] += 1
        if len(selected) >= limit:
            break
    return selected


def category_trend(articles: list[Article]) -> str:
    if not articles:
        return "새로 선별된 게임 AI 소식이 없습니다."
    counts = Counter(article.category for article in articles)
    category, count = counts.most_common(1)[0]
    if count == 1 and len(counts) > 1:
        return "오늘은 개발 도구·연구·산업 소식이 고르게 분포했습니다."
    return f"오늘은 {category} 관련 움직임이 {count}건으로 가장 두드러집니다."
