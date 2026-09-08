from __future__ import annotations

import unittest
import json
from unittest.mock import Mock, patch

from game_ai_news_bot.models import Article
from game_ai_news_bot.summarizer import (
    fallback_insight,
    fallback_items,
    summarize,
    translate_text_to_korean,
    translate_title_to_korean,
    translation_session,
)


def translation_response(text):
    response = Mock()
    response.json.return_value = {
        "responseStatus": 200,
        "responseData": {"translatedText": text},
    }
    return response


def gemini_response(items):
    response = Mock()
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({
        "items": items, "trend_ko": "게임 개발 동향",
    }, ensure_ascii=False)}]}}]}
    return response


class TitleTranslationTests(unittest.TestCase):
    def setUp(self):
        # A missing mock must not turn a regression test into a live API request.
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_translates_english_title(self, mock_get: Mock):
        response = Mock()
        response.json.return_value = {
            "responseStatus": 200,
            "responseData": {"translatedText": "AI NPC는 플레이어를 기억할 수 있다"},
        }
        mock_get.return_value = response

        translated = translate_title_to_korean("AI NPCs can remember players | 02/09/26")

        self.assertEqual(translated, "AI NPC는 플레이어를 기억할 수 있다")
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(mock_get.call_args.kwargs["params"]["langpair"], "en|ko")
        self.assertEqual(mock_get.call_args.kwargs["params"]["q"], "AI NPCs can remember players")

    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_skips_already_korean_title(self, mock_get: Mock):
        translated = translate_title_to_korean("게임 AI 연구 공개")

        self.assertEqual(translated, "게임 AI 연구 공개")
        mock_get.assert_not_called()

    @patch("game_ai_news_bot.summarizer.translate_title_to_korean")
    def test_translation_failure_holds_article_instead_of_publishing_original(self, mock_translate: Mock):
        mock_translate.side_effect = TimeoutError("timeout")
        article = Article("s", "Source", "Original title", "https://example.com/a")

        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"):
            items, _ = fallback_items([article])

        self.assertEqual(items, [])
        mock_translate.assert_called_once_with(article.title, timeout=12)
        self.assertEqual(article.title, "Original title")
        self.assertEqual(article.metadata, {})

    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_http_success_with_english_echo_is_not_a_korean_translation(self, get: Mock):
        original = "NPCs now remember earlier player conversations."
        get.return_value = translation_response(original)
        with self.assertRaises(ValueError):
            translate_text_to_korean(original)
        get.return_value.raise_for_status.assert_called_once_with()

    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_korean_title_cannot_hide_an_english_summary(self, get: Mock):
        article = Article(
            "s", "Source", "NPC 대화 기억 기능 공개", "https://example.com/mixed-language",
            description="NPCs now remember earlier player conversations during game sessions.",
        )
        get.return_value = translation_response(article.description)
        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"):
            items, _ = fallback_items([article])
        self.assertEqual(items, [])
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["params"]["q"], article.description)

    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_disabled_translation_still_requires_each_field_to_be_korean(self, get: Mock):
        korean_title = "NPC 대화 기억 기능 공개"
        korean_summary = "NPC가 이전 대화 내용을 기억하고 게임 상태에 맞게 응답합니다."
        articles = [
            Article("s", "Source", "NPC memory update", "https://example.com/title", description=korean_summary),
            Article("s", "Source", korean_title, "https://example.com/summary", description="NPCs now remember earlier conversations."),
            Article("s", "Source", korean_title, "https://example.com/insight", description=korean_summary,
                    metadata={"editorial_reason": "Review the memory system integration requirements."}),
        ]
        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"):
            items, _ = fallback_items(articles, translate_titles=False)
        self.assertEqual(items, [])
        get.assert_not_called()

    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_translation_outage_is_shared_across_batches_but_retried_next_session(self, get: Mock):
        first = Article("a", "First", "NPC memory update", "https://example.com/first",
                        description="NPCs now remember conversations from earlier game sessions.")
        second = Article("b", "Second", "Game engine testing tools", "https://example.com/second",
                         description="A game engine adds tools for automated game testing.")
        get.side_effect = [
            TimeoutError("provider unavailable"),
            translation_response("NPC 대화 기억 기능 공개"),
            translation_response("NPC가 이전 게임 세션의 대화 내용을 기억합니다."),
        ]
        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"), translation_session():
            first_items, _ = summarize([first])
            second_items, _ = summarize([second])
        self.assertEqual(first_items, [])
        self.assertEqual(second_items, [])
        self.assertEqual(get.call_count, 1)

        with translation_session():
            retried, _ = summarize([first])
        self.assertEqual([item.article for item in retried], [first])
        self.assertEqual(retried[0].summary_ko, "NPC가 이전 게임 세션의 대화 내용을 기억합니다.")
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["q"], first.title)

    @patch("game_ai_news_bot.summarizer.translate_text_to_korean")
    @patch("game_ai_news_bot.summarizer.translate_title_to_korean")
    def test_fallback_translates_useful_excerpt(
        self, title_translate: Mock, text_translate: Mock
    ):
        title_translate.return_value = "게임 상태를 읽는 NPC"
        text_translate.return_value = "NPC가 실시간 게임 상태에 따라 행동을 바꿉니다."
        article = Article(
            "s",
            "Source",
            "NPC reads live game state",
            "https://example.com/a",
            description="The NPC reads live game state and changes behavior during playtests.",
            category="🤖 NPC·에이전트",
        )

        items, _ = fallback_items([article])

        self.assertEqual(items[0].summary_ko, text_translate.return_value)
        self.assertNotIn("확인할 가치", items[0].insight_ko)

    def test_insight_uses_article_specific_signal(self):
        article = Article(
            "s",
            "Source",
            "Open source game agent released",
            "https://example.com/a",
            description="The source code and GitHub repository are available.",
        )
        self.assertIn("공개 코드", fallback_insight(article))

    @patch("game_ai_news_bot.summarizer.requests.post")
    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_geeknews_does_not_call_translation_or_gemini_even_with_key(self, get: Mock, post: Mock):
        article = Article(
            "geeknews", "긱뉴스", "Claude Code와 Codex 코딩 도구 비교", "https://news.hada.io/topic?id=1",
            description="75개 저장소에서 유효 세션 5,292개의 결과를 비교했다.",
            metadata={"editorial_filter": "geeknews"},
        )
        items, _ = summarize([article], api_key="unused-key", translate_titles=True)
        get.assert_not_called()
        post.assert_not_called()
        self.assertEqual(items[0].title_ko, article.title)
        self.assertEqual(items[0].summary_ko, article.description)
        self.assertNotIn("NPC", items[0].insight_ko)

    @patch("game_ai_news_bot.summarizer.requests.post")
    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_mixed_batch_keeps_source_order_and_sends_only_foreign_articles_to_gemini(self, get: Mock, post: Mock):
        english_a = Article("a", "First source", "NPC benchmark published", "https://example.com/a", description="A benchmark evaluates game NPCs.")
        korean = Article(
            "geeknews", "긱뉴스", "Claude Code와 Codex 코딩 도구 비교", "https://news.hada.io/topic?id=2",
            description="75개 저장소에서 코딩 도구의 결과를 비교했다.",
            metadata={"editorial_filter": "geeknews"},
        )
        english_b = Article("b", "Last source", "Game engine AI tools", "https://example.com/b", description="A game engine adds AI development tools.")
        response = Mock()
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({
            "items": [
                {"id": 0, "title_ko": "NPC 평가 공개", "summary_ko": "평가 자료 소개", "insight_ko": "평가 조건 확인"},
                {"id": 1, "title_ko": "게임 엔진 AI 도구", "summary_ko": "개발 도구 소개", "insight_ko": "지원 범위 확인"},
            ], "trend_ko": "개발 동향",
        }, ensure_ascii=False)}]}}]}
        post.return_value = response
        items, _ = summarize([english_a, korean, english_b], api_key="unused-key")
        self.assertEqual([item.article for item in items], [english_a, korean, english_b])
        self.assertEqual([item.title_ko for item in items], ["NPC 평가 공개", korean.title, "게임 엔진 AI 도구"])
        self.assertEqual(items[1].summary_ko, korean.description)
        post.assert_called_once()
        prompt = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertNotIn(korean.title, prompt)
        self.assertIn(english_a.title, prompt)
        self.assertIn(english_b.title, prompt)
        get.assert_not_called()

    @patch("game_ai_news_bot.summarizer.requests.post", side_effect=TimeoutError("Gemini unavailable"))
    @patch("game_ai_news_bot.summarizer.requests.get", side_effect=TimeoutError("MyMemory unavailable"))
    def test_provider_outage_keeps_surviving_korean_and_geeknews_in_original_order(self, get: Mock, post: Mock):
        english_a = Article("a", "First", "NPC benchmark published", "https://example.com/a",
                            description="A benchmark evaluates game NPCs.")
        geek_a = Article(
            "geeknews", "긱뉴스", "Claude Code와 Codex 코딩 도구 비교", "https://news.hada.io/topic?id=31",
            description="75개 저장소에서 코딩 도구의 결과를 비교했다.",
            metadata={"editorial_filter": "geeknews"},
        )
        korean = Article("k", "한국어 소스", "게임 NPC 대화 기억 기능 공개", "https://example.com/korean",
                         description="게임 NPC가 이전 대화와 플레이 상태를 함께 기억합니다.")
        english_b = Article("b", "Last", "Game engine AI tools", "https://example.com/b",
                            description="A game engine adds AI development tools.")
        geek_b = Article(
            "geeknews", "긱뉴스", "게임 에셋 생성 도구의 제작 사례", "https://news.hada.io/topic?id=32",
            description="이미지 생성 도구로 게임 에셋을 제작한 과정과 제약을 설명했다.",
            metadata={"editorial_filter": "geeknews"},
        )
        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"):
            items, _ = summarize([english_a, geek_a, korean, english_b, geek_b], api_key="unused-key")
        self.assertEqual([item.article for item in items], [geek_a, korean, geek_b])
        self.assertEqual([item.summary_ko for item in items], [geek_a.description, korean.description, geek_b.description])
        get.assert_called_once()
        post.assert_called_once()

    @patch("game_ai_news_bot.summarizer.requests.post")
    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_missing_gemini_index_translates_only_that_article_and_preserves_identity(self, get: Mock, post: Mock):
        first = Article("a", "First", "NPC memory update", "https://example.com/a",
                        description="NPCs now remember conversations from earlier game sessions.")
        missing = Article("b", "Missing", "Game engine testing tools", "https://example.com/b",
                          description="A game engine adds tools for automated game testing.")
        last = Article("c", "Last", "Procedural terrain workflow", "https://example.com/c",
                       description="A workflow generates procedural terrain for game developers.")
        # An out-of-order, partial Gemini response must never shift summaries to another article.
        post.return_value = gemini_response([
            {"id": 2, "title_ko": "지형 생성 작업 흐름", "summary_ko": "게임 지형을 생성하는 작업 흐름입니다.", "insight_ko": "지형 수정 범위를 검토합니다."},
            {"id": 0, "title_ko": "NPC 대화 기억 업데이트", "summary_ko": "이전 게임 대화를 기억합니다.", "insight_ko": "기억 유지 조건을 검토합니다."},
        ])
        get.side_effect = [translation_response("게임 엔진 테스트 도구"), translation_response("게임 엔진에 자동 테스트 도구가 추가되었습니다.")]
        items, _ = summarize([first, missing, last], api_key="unused-key")
        self.assertEqual([item.article for item in items], [first, missing, last])
        self.assertEqual([item.summary_ko for item in items], [
            "이전 게임 대화를 기억합니다.", "게임 엔진에 자동 테스트 도구가 추가되었습니다.", "게임 지형을 생성하는 작업 흐름입니다.",
        ])
        self.assertEqual([call.kwargs["params"]["q"] for call in get.call_args_list], [missing.title, missing.description])
        post.assert_called_once()

    @patch("game_ai_news_bot.summarizer.requests.post")
    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_english_or_empty_gemini_summary_uses_translated_fallback(self, get: Mock, post: Mock):
        article = Article("s", "Source", "NPC memory update", "https://example.com/a",
                          description="NPCs now remember conversations from earlier game sessions.")
        for invalid_summary in ("NPCs remember earlier conversations.", "", None):
            with self.subTest(summary=invalid_summary):
                post.return_value = gemini_response([{
                    "id": 0, "title_ko": "NPC 대화 기억 업데이트", "summary_ko": invalid_summary,
                    "insight_ko": "기억 유지 조건을 검토합니다.",
                }])
                get.side_effect = [translation_response("NPC 대화 기억 기능"), translation_response("NPC가 이전 게임 대화를 기억합니다.")]
                items, _ = summarize([article], api_key="unused-key")
                self.assertEqual(len(items), 1)
                self.assertIs(items[0].article, article)
                self.assertEqual(items[0].summary_ko, "NPC가 이전 게임 대화를 기억합니다.")

    @patch("game_ai_news_bot.summarizer.requests.post")
    @patch("game_ai_news_bot.summarizer.requests.get", side_effect=TimeoutError("translation unavailable"))
    def test_invalid_gemini_item_and_failed_translation_leave_no_publishable_item(self, get: Mock, post: Mock):
        article = Article("s", "Source", "NPC memory update", "https://example.com/a",
                          description="NPCs now remember conversations from earlier game sessions.")
        post.return_value = gemini_response([{
            "id": 0, "title_ko": "NPC 대화 기억 업데이트", "summary_ko": "NPCs now remember earlier conversations.",
            "insight_ko": "기억 유지 조건을 검토합니다.",
        }])
        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"):
            items, _ = summarize([article], api_key="unused-key")
        self.assertEqual(items, [])
        get.assert_called_once()
        post.assert_called_once()

    @patch("game_ai_news_bot.summarizer.requests.post")
    @patch("game_ai_news_bot.summarizer.requests.get")
    def test_failed_fallback_for_missing_index_does_not_discard_valid_gemini_item(self, get: Mock, post: Mock):
        first = Article("a", "Missing", "NPC memory update", "https://example.com/a")
        second = Article("b", "Valid", "Game testing tools", "https://example.com/b")
        post.return_value = gemini_response([{
            "id": 1, "title_ko": "게임 테스트 도구", "summary_ko": "게임 엔진에 자동 테스트가 추가되었습니다.",
            "insight_ko": "테스트 시나리오의 지원 범위를 살펴봅니다.",
        }])
        with self.assertLogs("game_ai_news_bot.summarizer", level="WARNING"):
            items, _ = summarize([first, second], api_key="unused-key", translate_titles=False)
        self.assertEqual([item.article for item in items], [second])
        self.assertEqual(items[0].summary_ko, "게임 엔진에 자동 테스트가 추가되었습니다.")
        get.assert_not_called()
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
