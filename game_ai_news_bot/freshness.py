from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Article


def is_fresh(article: Article, digest_config: dict, now: datetime) -> bool:
    """원래 공개일로 뉴스/제작 자료의 후보 기간을 확인한다."""
    if article.published_at is None:
        # 날짜가 없는 자료를 무기한 최신 뉴스처럼 내보내지 않는다.
        return False
    published = article.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    days = int(digest_config.get(
        "resource_freshness_days" if article.metadata.get("content_kind") == "resource" else "freshness_days",
        30 if article.metadata.get("content_kind") == "resource" else 7,
    ))
    return now - timedelta(days=max(0, days)) <= published <= now
