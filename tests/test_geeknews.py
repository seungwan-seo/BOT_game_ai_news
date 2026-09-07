from __future__ import annotations

import unittest

from game_ai_news_bot.geeknews import build_insight, build_summary, evaluate_article
from game_ai_news_bot.models import Article


class GeekNewsEditorialTests(unittest.TestCase):
    def article(self, title: str, description: str = "") -> Article:
        return Article("geeknews", "긱뉴스", title, "https://news.hada.io/topic?id=1", description=description)

    def test_coding_comparison_is_useful_without_game_keyword(self):
        article = self.article(
            "Claude Code, Codex, Cursor는 어떤 도구를 선택할까? 1만7천 회 실행 분석",
            "75개 저장소와 1,163개 프롬프트로 실험 16,893회를 실행하고 유효 세션 5,292개를 분석했다.",
        )
        self.assertTrue(evaluate_article(article))
        self.assertEqual(article.category, "🛠 개발 도구")
        self.assertLessEqual(article.metadata["geeknews_score"], 20)
        self.assertIn("선택", build_insight(article))
        self.assertNotIn("NPC", build_insight(article))
        self.assertIn("16,893", build_summary(article))

    def test_korean_ai_generation_and_inference_are_adjacent_topics(self):
        for title in (
            "생성형 이미지 모델로 게임 텍스처를 제작하는 가이드",
            "인공지능 음성 합성 API 공개 및 사용법",
            "LLM 추론 비용과 지연시간을 줄인 실험 분석",
        ):
            with self.subTest(title=title):
                self.assertTrue(evaluate_article(self.article(title)))

    def test_generic_agent_is_not_always_a_game_npc(self):
        article = self.article("에이전트 코딩 도구 비교", "AI 개발 도구의 성능 평가와 비용 분석")
        self.assertTrue(evaluate_article(article))
        self.assertEqual(article.category, "🛠 개발 도구")

    def test_ai_development_pace_is_not_inference_runtime_speed(self):
        essay = self.article(
            "Alien Mind: 인간과는 다른, 낯선 지성",
            "OpenAI는 추론 모델의 발전이 재귀적 자기개선으로 이어질 수 있다고 예상하며 개발 속도를 안전성에 맞춰 제한해야 한다고 강조했다.",
        )
        self.assertFalse(evaluate_article(essay))
        self.assertTrue(evaluate_article(self.article("LLM 추론 속도 2배 개선 실험 공개")))

    def test_direct_game_npc_article(self):
        article = self.article("게임 NPC에 LLM을 통합하는 실험 공개")
        self.assertTrue(evaluate_article(article))
        self.assertEqual(article.category, "🤖 NPC·에이전트")

    def test_ai_substrings_do_not_admit_unrelated_articles(self):
        for title in ("TrailPaper: 이미지 제작 도구 공개", "Email로 개발 워크플로 자동화하기", "Chair 만들기: 3D 제작 도구"):
            with self.subTest(title=title):
                self.assertFalse(evaluate_article(self.article(title)))

    def test_ascii_boundary_still_accepts_korean_particle(self):
        self.assertTrue(evaluate_article(self.article("AI로 게임 에셋 생성하는 도구 공개")))

    def test_named_model_requires_an_actionable_development_topic(self):
        self.assertTrue(evaluate_article(self.article("GPT-5로 Unity 작업을 자동화하는 가이드")))
        self.assertTrue(evaluate_article(self.article("Claude를 사용한 코드 리뷰 비교 분석")))
        self.assertFalse(evaluate_article(self.article("ChatGPT에 일기를 쓰며 느낀 점")))

    def test_trusted_source_cannot_admit_off_topic_articles(self):
        for title in (
            "AI 기업 투자 유치 10억 달러 분석",
            "AI가 회로기판 설계를 자동화하는 도구 공개",
            "AI 의식에 관한 철학적 분석",
            "LLM의 수학 문제 평가와 인류 지능",
            "올해 좋아하는 게임 10개",
        ):
            with self.subTest(title=title):
                article = self.article(title)
                article.metadata["trusted"] = True
                self.assertFalse(evaluate_article(article))

    def test_github_mention_does_not_claim_open_source(self):
        article = self.article("AI 코딩 도구 사용 경험", "GitHub 이슈와 비교해 개발 도구의 사용법을 정리했다.")
        self.assertTrue(evaluate_article(article))
        self.assertNotIn("공개 코드", build_insight(article))
        self.assertNotIn("재현", build_insight(article))

    def test_rejected_reevaluation_clears_previous_evidence(self):
        article = self.article("Claude Code 비교 분석")
        self.assertTrue(evaluate_article(article))
        article.title = "오늘의 투자 소식"
        self.assertFalse(evaluate_article(article))
        self.assertNotIn("geeknews_reason", article.metadata)
        self.assertEqual(article.relevance, 0)

    def test_summary_prefers_lead_and_preserves_numbers_without_invention(self):
        article = self.article(
            "AI 코딩 도구 비교",
            "AI 코딩 도구 비교\n\n핵심 내용\n- 75개 저장소에서 코딩 도구의 실행 결과 5,292개를 분석했다. 두 번째 문장입니다.\n- 평균 비용은 3달러였다.",
        )
        self.assertEqual(build_summary(article), "75개 저장소에서 코딩 도구의 실행 결과 5,292개를 분석했다.")

    def test_summary_html_and_length(self):
        article = self.article("생성형 도구 분석", "<h2>핵심 요약</h2><p>이미지 &amp; 3D 모델을 생성하는 도구의 사용 조건을 비교했다.</p><p>다음 내용</p>")
        self.assertEqual(build_summary(article), "이미지 & 3D 모델을 생성하는 도구의 사용 조건을 비교했다.")
        article.description = "한국어 공개 요약입니다. " * 50
        self.assertLessEqual(len(build_summary(article)), 180)

    def test_empty_description_does_not_repeat_title(self):
        article = self.article("Claude Code와 Cursor 비교")
        self.assertNotIn(article.title, build_summary(article))


if __name__ == "__main__":
    unittest.main()
