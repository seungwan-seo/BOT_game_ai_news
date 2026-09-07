from __future__ import annotations

import unittest
from datetime import datetime, timezone

from game_ai_news_bot.models import Article
from game_ai_news_bot.ranking import deduplicate, keyword_score, rank_articles, select_diverse


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "sources": [{"id": "news", "min_relevance": 5}],
            "ranking": {
                "positive_keywords": {"ai npc": 9, "game development": 5},
                "negative_keywords": {"crypto": -10},
            },
        }

    def article(self, title: str, url: str = "https://example.com/a") -> Article:
        return Article("news", "News", title, url, published_at=datetime.now(timezone.utc), source_weight=5)

    def test_title_match_is_weighted(self):
        article = self.article("AI NPC arrives")
        self.assertEqual(keyword_score(article, {"ai npc": 9}, {}), 18)

    def test_filters_irrelevant_general_ai(self):
        results = rank_articles([self.article("A new office language model")], self.config)
        self.assertEqual(results, [])

    def test_negative_crypto_signal(self):
        article = self.article("AI NPC crypto token sale")
        score = keyword_score(article, {"ai npc": 9}, {"crypto": -10, "token sale": -10})
        self.assertLess(score, 0)

    def test_deduplicates_similar_titles(self):
        first = self.article("NVIDIA launches a new AI NPC system", "https://one.example/a")
        second = self.article("NVIDIA launches new AI NPC system", "https://two.example/a")
        self.assertEqual(len(deduplicate([first, second])), 1)

    def test_limits_articles_per_source(self):
        articles = [self.article(f"AI NPC item {index}", f"https://example.com/{index}") for index in range(4)]
        other = Article("other", "Other", "Game AI research", "https://other.example/a")
        selected = select_diverse(articles + [other], limit=4, max_per_source=2)
        self.assertEqual([item.source_id for item in selected], ["news", "news", "other"])

    def test_geeknews_trusted_source_still_requires_editorial_relevance(self):
        config = {
            "sources": [{"id": "geeknews", "editorial_filter": "geeknews", "trusted": True}],
            "ranking": {"positive_keywords": {"ai": 100, "game": 100}},
        }
        irrelevant = Article("geeknews", "긱뉴스", "AI 기업 투자 유치 분석", "https://news.hada.io/topic?id=1")
        useful = Article("geeknews", "긱뉴스", "Claude Code와 Codex 코딩 도구 비교", "https://news.hada.io/topic?id=2")
        ranked = rank_articles([irrelevant, useful], config)
        self.assertEqual(ranked, [useful])
        self.assertEqual(useful.category, "🛠 개발 도구")
        self.assertLessEqual(useful.relevance, 20)
        self.assertIn("geeknews_reason", useful.metadata)

    def test_source_specific_remaining_quota_is_respected(self):
        articles = [self.article(f"Article {index}", f"https://example.com/{index}") for index in range(3)]
        other = Article("other", "Other", "A different report", "https://other.example/a")
        selected = select_diverse(articles + [other], limit=3, max_per_source=2, source_limits={"news": 1})
        self.assertEqual(selected, [articles[0], other])
        self.assertEqual(select_diverse(articles + [other], limit=3, source_limits={"news": 0}), [other])

    def test_source_override_cannot_raise_global_diversity_cap(self):
        articles = [self.article(f"Article {index}", f"https://example.com/{index}") for index in range(3)]
        selected = select_diverse(articles, limit=3, max_per_source=2, source_limits={"news": 10})
        self.assertEqual(selected, articles[:2])

    def test_original_url_alias_deduplicates_across_languages_in_both_orders(self):
        original = self.article("Coding assistants empirical performance comparison", "https://example.com/report")
        korean = Article(
            "geeknews", "긱뉴스", "코딩 도구 실행 결과 1만7천 회 분석", "https://news.hada.io/topic?id=3",
            metadata={"original_url": original.url},
        )
        self.assertEqual(deduplicate([original, korean]), [original])
        self.assertEqual(deduplicate([korean, original]), [korean])

    def test_grouped_release_aliases_prevent_hotfix_republication(self):
        group = self.article("Tool 1.2 new rendering support", "https://example.com/releases/1.2.0")
        group.metadata["alias_urls"] = ["https://example.com/releases/1.2.1", "javascript:bad"]
        patch = self.article("완전히 다른 언어로 쓴 패치 소개", "https://example.com/releases/1.2.1")
        self.assertEqual(deduplicate([group, patch]), [group])
        self.assertNotIn("javascript:bad", group.identity_urls)

    def test_distinct_feature_groups_are_not_merged_only_by_version_titles(self):
        first = self.article("Claude Code v2.1.260 agent worktree support", "https://example.com/260")
        second = self.article("Claude Code v2.1.261 agent worktree support", "https://example.com/261")
        first.metadata["release_group_key"] = "github:claude:260"
        second.metadata["release_group_key"] = "github:claude:261"
        self.assertEqual(deduplicate([first, second]), [first, second])


if __name__ == "__main__":
    unittest.main()
