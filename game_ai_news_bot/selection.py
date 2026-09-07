from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from .models import Article
from .ranking import deduplicate


def select_enriched_articles(
    articles: list[Article],
    limit: int,
    max_per_source: int,
    source_limits: dict[str, int] | None,
    blocked_urls: set[str],
    enrich_article: Callable[[Article], Article],
) -> list[Article]:
    """점수순으로 보강·선별하고 원문 중복으로 빠진 자리는 다음 후보로 채운다."""
    if limit <= 0:
        return []

    selected: list[Article] = []
    counts: Counter[str] = Counter()
    source_limits = source_limits or {}

    def can_add(article: Article) -> bool:
        if article.identity_urls & blocked_urls:
            return False
        return len(deduplicate([*selected, article])) > len(selected)

    for article in articles:
        source_limit = min(
            max_per_source, source_limits.get(article.source_id, max_per_source)
        )
        if counts[article.source_id] >= source_limit:
            continue
        # 앞선 후보 보강으로 이미 확인한 중복은 페이지를 다시 열지 않는다.
        if not can_add(article):
            continue
        enriched = enrich_article(article)
        if not can_add(enriched):
            continue
        selected.append(enriched)
        counts[enriched.source_id] += 1
        if len(selected) >= limit:
            break

    return selected
