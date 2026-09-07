from datetime import datetime, timedelta, timezone
import unittest

from game_ai_news_bot.freshness import is_fresh
from game_ai_news_bot.models import Article


class FreshnessTests(unittest.TestCase):
    def test_news_and_resources_use_original_date_and_separate_windows(self):
        now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        config = {"freshness_days": 7, "resource_freshness_days": 30}
        for kind, age, expected in [
            ("news", 7, True), ("news", 8, False),
            ("resource", 8, True), ("resource", 30, True), ("resource", 31, False),
        ]:
            with self.subTest(kind=kind, age=age):
                article = Article("s", "Source", "Title", "https://example.com/a",
                    published_at=now - timedelta(days=age), metadata={"content_kind": kind})
                self.assertEqual(is_fresh(article, config, now), expected)

    def test_undated_or_future_articles_cannot_fill_quota(self):
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        for published in [None, now + timedelta(seconds=1)]:
            with self.subTest(published=published):
                article = Article("s", "Source", "Title", "https://example.com/a", published_at=published)
                self.assertFalse(is_fresh(article, {}, now))
