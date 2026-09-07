from __future__ import annotations

import unittest
from unittest.mock import Mock

from game_ai_news_bot.models import Article
from game_ai_news_bot.selection import select_enriched_articles


class EnrichedSelectionTests(unittest.TestCase):
    def article(self, source: str, title: str, key: str) -> Article:
        return Article(source, source, title, f"https://{source}.example/{key}")

    def test_seen_original_is_replaced_by_next_candidate(self):
        repeated = self.article("geeknews", "코딩 도구 비교 보고서", "repeated")
        replacement = self.article("news", "Procedural terrain research", "replacement")
        unused = self.article("tools", "Audio synthesis workflow", "unused")
        original_url = "https://original.example/report"

        def enrich(article):
            if article is repeated:
                article.metadata["original_url"] = original_url
            return article

        enrich_mock = Mock(side_effect=enrich)
        selected = select_enriched_articles(
            [repeated, replacement, unused], 1, 2, {}, {original_url}, enrich_mock
        )

        self.assertEqual(selected, [replacement])
        self.assertEqual([call.args[0] for call in enrich_mock.call_args_list], [repeated, replacement])

    def test_duplicate_original_is_replaced_without_consuming_source_quota(self):
        first = self.article("news", "Coding assistants performance comparison", "report")
        duplicate = self.article("geeknews", "코딩 도구 실행 결과 분석", "duplicate")
        replacement = self.article("geeknews", "에이전트 애니메이션 제작 기법", "replacement")

        def enrich(article):
            if article is duplicate:
                article.metadata["original_url"] = first.url
            return article

        selected = select_enriched_articles(
            [first, duplicate, replacement], 2, 2, {"geeknews": 1}, set(), enrich
        )

        self.assertEqual(selected, [first, replacement])

    def test_daily_geeknews_and_per_run_source_caps_skip_enrichment(self):
        geek_first = self.article("geeknews", "코드 작성 도구 실무 적용", "first")
        geek_capped = self.article("geeknews", "에이전트 활용 분석", "capped")
        news_first = self.article("news", "Procedural terrain research", "first")
        news_second = self.article("news", "Copyright policy for studios", "second")
        news_capped = self.article("news", "Audio synthesis workflow", "capped")
        other = self.article("tools", "Robot navigation benchmark", "other")
        enrich = Mock(side_effect=lambda article: article)
        limits = {"geeknews": 1, "news": 10}

        selected = select_enriched_articles(
            [geek_first, geek_capped, news_first, news_second, news_capped, other],
            4, 2, limits, set(), enrich,
        )

        self.assertEqual(selected, [geek_first, news_first, news_second, other])
        self.assertEqual([call.args[0] for call in enrich.call_args_list], selected)
        self.assertEqual(limits, {"geeknews": 1, "news": 10})

    def test_exhausted_daily_quota_never_enriches_source(self):
        capped = self.article("geeknews", "코드 작성 도구 실무 적용", "capped")
        enrich = Mock(side_effect=lambda article: article)

        selected = select_enriched_articles([capped], 2, 2, {"geeknews": 0}, set(), enrich)

        self.assertEqual(selected, [])
        enrich.assert_not_called()

    def test_similar_title_after_enrichment_is_replaced(self):
        first = self.article("news", "NVIDIA launches a new AI NPC system", "first")
        duplicate = self.article("tools", "A placeholder title before metadata", "duplicate")
        replacement = self.article("tools", "Procedural terrain research", "replacement")

        def enrich(article):
            if article is duplicate:
                article.title = "NVIDIA launches new AI NPC system"
            return article

        selected = select_enriched_articles(
            [first, duplicate, replacement], 2, 1, None, set(), enrich
        )

        self.assertEqual(selected, [first, replacement])

    def test_alias_discovered_on_selected_article_skips_known_duplicate_enrichment(self):
        first = self.article("geeknews", "게임 제작에 쓰는 코딩 도구", "first")
        duplicate = self.article("news", "Coding assistant developer report", "duplicate")
        replacement = self.article("news", "Audio synthesis workflow", "replacement")

        def enrich(article):
            if article is first:
                article.metadata["original_url"] = duplicate.url
            return article

        enrich_mock = Mock(side_effect=enrich)
        selected = select_enriched_articles(
            [first, duplicate, replacement], 2, 2, {}, set(), enrich_mock
        )

        self.assertEqual(selected, [first, replacement])
        self.assertEqual([call.args[0] for call in enrich_mock.call_args_list], selected)

    def test_candidate_shortage_returns_available_articles(self):
        only = self.article("news", "Procedural terrain research", "only")
        enrich = Mock(side_effect=lambda article: article)

        self.assertEqual(select_enriched_articles([only], 10, 2, {}, set(), enrich), [only])
        self.assertEqual(select_enriched_articles([], 10, 2, {}, set(), enrich), [])
        enrich.assert_called_once_with(only)

    def test_nonpositive_limit_never_enriches(self):
        article = self.article("news", "Procedural terrain research", "article")

        for limit in (0, -1):
            with self.subTest(limit=limit):
                enrich = Mock(side_effect=lambda article: article)
                self.assertEqual(
                    select_enriched_articles([article], limit, 2, {}, set(), enrich), []
                )
                enrich.assert_not_called()


if __name__ == "__main__":
    unittest.main()
