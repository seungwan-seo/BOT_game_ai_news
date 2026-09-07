from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Article:
    source_id: str
    source_name: str
    title: str
    url: str
    description: str = ""
    published_at: datetime | None = None
    source_weight: int = 0
    perspective: str = "unknown"
    relevance: int = 0
    score: float = 0.0
    category: str = "기타"
    image_url: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def identity_urls(self) -> set[str]:
        """동일 기사의 집계 페이지와 확인된 원문 URL을 함께 비교한다."""
        urls = {self.url}
        original = self.metadata.get("original_url")
        if isinstance(original, str) and original.startswith(("https://", "http://")):
            urls.add(original)
        aliases = self.metadata.get("alias_urls", [])
        if isinstance(aliases, list):
            urls.update(alias for alias in aliases if isinstance(alias, str) and alias.startswith(("https://", "http://")))
        return urls


@dataclass(slots=True)
class DigestItem:
    article: Article
    title_ko: str
    summary_ko: str
    insight_ko: str
