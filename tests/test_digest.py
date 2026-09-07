from __future__ import annotations

import unittest
from datetime import datetime, timezone

from game_ai_news_bot.digest import TELEGRAM_SAFE_LIMIT, build_article_post
from game_ai_news_bot.models import Article, DigestItem


class DigestTests(unittest.TestCase):
    def test_resource_shows_original_publication_day_in_kst(self):
        article = Article("s", "Source", "Tutorial", "https://example.com/a",
            published_at=datetime(2026, 8, 20, 16, tzinfo=timezone.utc),
            perspective="vendor", metadata={"content_kind": "resource"})
        message = build_article_post(DigestItem(article, "제작 튜토리얼", "요약", "적용 방법"), "브리핑")
        self.assertIn("제작 자료 · 원문 공개 2026-08-21", message)
        self.assertIn("업체 관점", message)

    def test_escapes_untrusted_content_and_keeps_link(self):
        article = Article("s", "A&B", "raw", "https://example.com/a", category="🤖 NPC·에이전트")
        item = DigestItem(article, "<새 기능>", "A & B", "검증 <필요>")
        message = build_article_post(item, "브리핑")
        self.assertIn("&lt;새 기능&gt;", message)
        self.assertIn("EN · raw", message)
        self.assertIn("A &amp; B", message)
        self.assertIn("한줄 요약", message)
        self.assertIn("왜 봐야 하나", message)
        self.assertIn('href="https://example.com/a"', message)
        self.assertLess(
            message.index('href="https://example.com/a"'), message.index("A &amp; B")
        )
        self.assertIn("출처 · A&amp;B ·", message)

    def test_omits_duplicate_original_title(self):
        article = Article("s", "Source", "같은 제목", "https://example.com/a")
        item = DigestItem(article, "같은 제목", "요약", "인사이트")
        message = build_article_post(item, "브리핑")
        self.assertNotIn("EN ·", message)

    def test_article_post_stays_under_telegram_limit(self):
        article = Article("s", "Source", "raw", "https://example.com/a", category="📚 연구")
        item = DigestItem(article, "제목" * 50, "요약" * 100, "인사이트" * 50)
        message = build_article_post(item, "브리핑")
        self.assertLessEqual(len(message), TELEGRAM_SAFE_LIMIT)

    def test_korean_source_title_is_not_repeated_as_english_when_shortened(self):
        article = Article(
            "geeknews", "긱뉴스", "Claude Code와 Codex: 1만7천 회 실험으로 비교한 코딩 도구",
            "https://news.hada.io/topic?id=1", perspective="community",
        )
        item = DigestItem(article, "Claude Code와 Codex 코딩 도구 비교", "한국어 소개", "비교 결과 확인")
        message = build_article_post(item, "게임 AI 뉴스")
        self.assertNotIn("EN ·", message)
        self.assertNotIn(article.title, message)
        self.assertIn(item.title_ko, message)
        self.assertIn("출처 · 긱뉴스 · 한국어 큐레이션", message)
        self.assertIn('href="https://news.hada.io/topic?id=1"', message)


if __name__ == "__main__":
    unittest.main()
