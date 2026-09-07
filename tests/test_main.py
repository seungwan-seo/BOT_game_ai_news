from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import main as app
from game_ai_news_bot.feedback_collection import FeedbackCollectionError
from game_ai_news_bot.models import Article
from game_ai_news_bot.state import load_state, mark_delivered, save_state
from game_ai_news_bot.telegram import TelegramSendError


class ProductionDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_path = Path(self.temporary.name) / "state" / "news_state.json"
        self.source = {
            "id": "geeknews", "name": "GeekNews · 긱뉴스",
            "editorial_filter": "geeknews", "max_items_per_day": 2,
        }
        self.config = {
            "base_dir": self.temporary.name,
            "sources": [self.source, {"id": "other", "name": "Other"}],
            "digest": {"daily_post_limit": 10, "max_items_per_run": 1},
            "promotion": {
                "enabled": True, "interval_days": 5,
                "channels": [{"name": "Sister", "url": "https://t.me/sister_test"}],
            },
        }
        self.env = {
            "telegram_token": "unit-test-placeholder", "telegram_chat_ids": ["unit-test"],
            "gemini_api_key": "", "gemini_model": "unused",
        }
        self.article = Article(
            "geeknews", "GeekNews · 긱뉴스", "Claude Code와 Codex 코딩 도구 비교",
            "https://news.hada.io/topic?id=12345",
            description="두 AI 코딩 도구의 선택 결과를 100회 실험으로 비교한 분석입니다.",
            published_at=datetime.now(timezone.utc), perspective="community",
            metadata={"editorial_filter": "geeknews", "button_text": "📰 긱뉴스에서 읽기"},
        )
        self.original_url = "https://example.com/coding-comparison"

    def execute(self, *args, send_error=None, poll_error=None, receipt_date=None, articles=None):
        with ExitStack() as stack:
            stack.enter_context(patch("sys.argv", ["main.py", *args]))
            stack.enter_context(patch.object(app, "load_config", return_value=self.config))
            stack.enter_context(patch.object(app, "env_settings", return_value=self.env))
            collector = stack.enter_context(patch.object(app, "Collector")).return_value
            collector.collect_all.return_value = (articles if articles is not None else [self.article], [])

            def enrich(article):
                article.metadata["original_url"] = (
                    self.original_url if article.url == self.article.url else article.url + "/original"
                )
                return article

            collector.enrich_article.side_effect = enrich
            sender = stack.enter_context(patch.object(app, "send_message"))
            sender.return_value = [{
                "chat_id": -100123, "message_id": 81, "chat_type": "channel",
                "date": receipt_date or int(datetime.now(timezone.utc).timestamp()),
            }]
            if send_error:
                sender.side_effect = send_error
            self.poller = stack.enter_context(patch.object(app, "collect_feedback"))

            def poll(state, token, config, now):
                state.setdefault("feedback", {})["last_poll_at"] = now.isoformat()
                return {"received": 0, "changed": 0}

            self.poller.side_effect = poll_error or poll
            # A test must never make live translation or Telegram requests.
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            result = app.main()
        return result, sender, collector, output.getvalue()

    def single(self, *args):
        return self.execute("--source", "geeknews", "--article-url", self.article.url, *args)

    def test_specific_article_sends_once_without_promo_and_records_state(self):
        result, sender, collector, _ = self.single("--limit", "10")
        self.assertEqual(result, 0)
        sender.assert_called_once()
        collector.collect_all.assert_called_once_with([self.source])
        message = sender.call_args.args[2]
        for marker in ("테스트 메시지", "테스트 발송", "DRY-RUN", "미리보기", "Sister"):
            self.assertNotIn(marker, message)
        self.assertIn(self.article.title, message)
        self.assertEqual(sender.call_args.kwargs["button_text"], "📰 긱뉴스에서 읽기")
        self.assertTrue(sender.call_args.kwargs["silent"])
        state = load_state(self.state_path)
        self.assertEqual(state["delivery_count"], 1)
        self.assertEqual(state["delivery_source_counts"], {"geeknews": 1})
        self.assertIn(self.article.url, state["seen"])
        self.assertIn(self.original_url, state["seen"])
        self.assertFalse(state["last_promo_at"])
        result, sender, _, _ = self.single()
        self.assertEqual(result, 2)
        sender.assert_not_called()

    def test_previously_sent_original_is_detected_after_enrichment(self):
        state = load_state(self.state_path)
        mark_delivered(state, [self.original_url], source_id="other")
        save_state(self.state_path, state)
        result, sender, collector, _ = self.single()
        self.assertEqual(result, 2)
        collector.enrich_article.assert_called_once()
        sender.assert_not_called()

    def test_dry_run_and_legacy_preview_never_send_or_write(self):
        for args in (
            ("--source", "geeknews", "--dry-run", "--no-promo"),
            ("--source", "geeknews", "--preview-send"),
            ("--source", "geeknews", "--bootstrap", "--dry-run"),
        ):
            with self.subTest(args=args):
                result, sender, _, output = self.execute(*args)
                self.assertEqual(result, 0)
                sender.assert_not_called()
                self.assertIn("DRY-RUN", output)
                self.assertFalse(self.state_path.exists())

    def test_news_receipts_are_registered_for_reaction_analysis(self):
        self.config["feedback"] = {"enabled": True}
        result, sender, _, _ = self.single()
        self.assertEqual(result, 0)
        self.poller.assert_called_once()
        sender.assert_called_once()
        state = load_state(self.state_path)
        post = state["feedback"]["posts"]["-100123:81"]
        self.assertEqual(post["url"], self.article.url)
        self.assertEqual(post["source_id"], "geeknews")
        self.assertEqual(state["delivery_count"], 1)

    def test_reaction_only_collects_without_news_or_promotion(self):
        self.config["feedback"] = {"enabled": True}
        result, sender, collector, _ = self.execute("--collect-feedback")
        self.assertEqual(result, 0)
        sender.assert_not_called()
        collector.collect_all.assert_not_called()
        self.poller.assert_called_once()
        self.assertEqual(load_state(self.state_path)["delivery_count"], 0)

    def test_receipt_after_collection_start_is_not_pruned(self):
        self.config["feedback"] = {"enabled": True}
        started = datetime.now(timezone.utc)
        with patch.object(app, "datetime", wraps=datetime) as clock:
            clock.now.side_effect = [started, started + timedelta(seconds=4)]
            result, _, _, _ = self.execute(
                "--source", "geeknews", "--no-promo",
                receipt_date=int((started + timedelta(seconds=3)).timestamp()),
            )
        self.assertEqual(result, 0)
        self.assertIn("-100123:81", load_state(self.state_path)["feedback"]["posts"])

    def test_report_and_reaction_dry_run_are_offline_and_read_only(self):
        self.config["feedback"] = {"enabled": True}
        for args in (("--feedback-report",), ("--collect-feedback", "--dry-run"), ("--source", "geeknews", "--dry-run")):
            with self.subTest(args=args):
                result, sender, _, _ = self.execute(*args)
                self.assertEqual(result, 0)
                sender.assert_not_called()
                self.poller.assert_not_called()
                self.assertFalse(self.state_path.exists())

    def test_reaction_failure_does_not_stop_scheduled_news(self):
        self.config["feedback"] = {"enabled": True}
        result, sender, _, _ = self.execute("--source", "geeknews", "--no-promo", poll_error=FeedbackCollectionError("unavailable"))
        self.assertEqual(result, 0)
        sender.assert_called_once()
        result, sender, _, _ = self.execute("--collect-feedback", poll_error=FeedbackCollectionError("unavailable"))
        self.assertEqual(result, 2)
        sender.assert_not_called()

    def test_promotion_is_excluded_from_feedback(self):
        self.config["feedback"] = {"enabled": True}
        result, sender, _, _ = self.execute("--send-promo-now")
        self.assertEqual(result, 0)
        sender.assert_called_once()
        self.poller.assert_not_called()
        self.assertNotIn("feedback", load_state(self.state_path))

    def test_uncertain_delivery_is_held_for_manual_review_not_resent(self):
        result, sender, _, _ = self.execute(
            "--source", "geeknews", "--no-promo",
            send_error=TelegramSendError("response missing", delivery_uncertain=True),
        )
        self.assertEqual(result, 2)
        sender.assert_called_once()
        state = load_state(self.state_path)
        self.assertIn(self.article.url, state["pending_delivery_review"])
        self.assertEqual(state["delivery_count"], 0)
        result, sender, _, _ = self.execute("--source", "geeknews", "--no-promo")
        self.assertEqual(result, 0)
        sender.assert_not_called()

    def test_partial_delivery_preserves_successful_receipt(self):
        self.config["feedback"] = {"enabled": True}
        receipt = {"chat_id": -100123, "message_id": 82, "chat_type": "channel", "date": int(datetime.now(timezone.utc).timestamp())}
        result, _, _, _ = self.execute(
            "--source", "geeknews", "--no-promo",
            send_error=TelegramSendError("second target failed", receipts=[receipt]),
        )
        self.assertEqual(result, 2)
        state = load_state(self.state_path)
        self.assertEqual(state["delivery_count"], 1)
        self.assertIn("-100123:82", state["feedback"]["posts"])

    def test_unlisted_article_url_cannot_be_published(self):
        result, sender, collector, _ = self.execute(
            "--source", "geeknews", "--article-url", "https://example.com/arbitrary",
        )
        self.assertEqual(result, 2)
        sender.assert_not_called()
        collector.enrich_article.assert_not_called()

    def test_source_and_total_daily_caps_apply_across_runs(self):
        for count, source_id in ((2, "geeknews"), (10, "other")):
            with self.subTest(count=count, source_id=source_id):
                state = load_state(Path(self.temporary.name) / "missing.json")
                mark_delivered(state, [f"https://example.com/{i}" for i in range(count)], source_id=source_id)
                save_state(self.state_path, state)
                result, sender, _, _ = self.single()
                self.assertEqual(result, 2)
                sender.assert_not_called()

    def test_twenty_total_ten_geeknews_policy_respects_remaining_quota(self):
        self.source["max_items_per_day"] = 10
        self.config["digest"].update({"daily_post_limit": 20, "max_items_per_run": 2})
        second = Article(
            "geeknews", "긱뉴스", "게임 NPC 음성 생성 모델 지연시간 벤치마크",
            "https://news.hada.io/topic?id=98765",
            description="게임 개발에 쓰는 AI 음성 모델의 추론 지연과 비용을 비교한 실험입니다.",
            published_at=self.article.published_at,
        )
        for total, geeknews, expected in [(2, 2, 2), (9, 9, 1), (10, 10, 0), (19, 9, 1), (20, 9, 0)]:
            with self.subTest(total=total, geeknews=geeknews):
                state = load_state(Path(self.temporary.name) / "missing.json")
                mark_delivered(state, [f"https://example.com/geek/{i}" for i in range(geeknews)], source_id="geeknews")
                if total > geeknews:
                    mark_delivered(state, [f"https://example.com/other/{i}" for i in range(total - geeknews)], source_id="other")
                save_state(self.state_path, state)
                result, sender, _, _ = self.execute(
                    "--source", "geeknews", "--no-promo", articles=[self.article, second],
                )
                self.assertEqual(result, 0)
                self.assertEqual(sender.call_count, expected)
                updated = load_state(self.state_path)
                self.assertEqual(updated["delivery_count"], total + expected)
                self.assertEqual(updated["delivery_source_counts"]["geeknews"], geeknews + expected)

    def test_conflicting_single_article_flags_are_rejected(self):
        for flag in ("--bootstrap", "--send-promo-now", "--send-channel-guide", "--preview-send", "--show-all"):
            with self.subTest(flag=flag), patch("sys.argv", [
                "main.py", "--source", "geeknews", "--article-url", self.article.url, flag,
            ]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                app.parse_args()
            self.assertEqual(raised.exception.code, 2)

    def test_automatic_morning_catchup_then_skip_and_resume_afternoon(self):
        self.config["digest"].update({
            "daily_post_limit": 20,
            "morning_target": {"enabled": True, "count": 10},
        })
        now = datetime(2026, 9, 7, 1, 13, tzinfo=timezone.utc)  # KST 10:13
        state = load_state(self.state_path)
        mark_delivered(state, ["https://example.com/sent-a", "https://example.com/sent-b"], now, source_id="geeknews")
        save_state(self.state_path, state)
        headlines = [
            "Procedural worlds from sketches", "Adaptive enemy behavior trees",
            "Voice synthesis for dialogue", "Automated game playtesting",
            "Motion capture animation model", "Texture generation workflow",
            "Navigation mesh learning", "Character memory benchmark",
        ]
        candidates = [Article(
            f"source-{i // 2}", f"Source {i // 2}", title,
            f"https://example.com/fresh/{i}", published_at=now,
        ) for i, title in enumerate(headlines)]
        self.config["translation"] = {"enabled": False}
        with patch.object(app, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            result, sender, _, _ = self.execute("--no-promo", articles=candidates)
            self.assertEqual(result, 0)
            self.assertEqual(sender.call_count, 8)
            self.assertEqual(load_state(self.state_path)["delivery_count"], 10)
            result, sender, collector, _ = self.execute("--no-promo", articles=candidates)
            self.assertEqual(result, 0)
            sender.assert_not_called()
            collector.collect_all.assert_not_called()
            clock.now.return_value = now + timedelta(hours=3)
            fresh = Article("other", "Other", "AI lighting assistant release", "https://example.com/afternoon", published_at=now)
            result, sender, _, _ = self.execute("--no-promo", articles=[fresh])
            self.assertEqual(result, 0)
            sender.assert_called_once()
            self.assertEqual(load_state(self.state_path)["delivery_count"], 11)

    def test_manual_limits_and_source_are_not_expanded_by_morning_target(self):
        self.config["digest"]["morning_target"] = {"enabled": True, "count": 10}
        for args in (("--limit", "1"), ("--source", "geeknews"), ("--article-url", self.article.url, "--source", "geeknews")):
            with self.subTest(args=args), patch.object(app, "planned_news_limit") as planner:
                result, sender, _, _ = self.execute(*args, "--dry-run", "--no-promo")
                self.assertEqual(result, 0)
                planner.assert_not_called()
                sender.assert_not_called()
                self.assertFalse(self.state_path.exists())

    def test_automatic_dry_run_uses_plan_without_delivery_or_state_changes(self):
        self.config["digest"]["morning_target"] = {"enabled": True, "count": 10}
        with patch.object(app, "planned_news_limit", return_value=8) as planner:
            result, sender, _, output = self.execute("--dry-run", "--no-promo")
        self.assertEqual(result, 0)
        planner.assert_called_once()
        sender.assert_not_called()
        self.assertIn("DRY-RUN", output)
        self.assertFalse(self.state_path.exists())

    def test_nonpositive_manual_limit_is_rejected(self):
        for limit in ("0", "-1"):
            with self.subTest(limit=limit), patch("sys.argv", ["main.py", "--limit", limit]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                app.parse_args()

    def test_automatic_delivery_rechecks_hours_after_slow_collection(self):
        self.config["digest"].update({
            "daily_post_limit": 20,
            "morning_target": {"enabled": True, "count": 10},
        })
        started = datetime(2026, 9, 7, 12, 59, tzinfo=timezone.utc)  # KST 21:59
        with patch.object(app, "datetime", wraps=datetime) as clock:
            clock.now.side_effect = [started, started + timedelta(minutes=2)]
            result, sender, collector, _ = self.execute()
        self.assertEqual(result, 0)
        collector.enrich_article.assert_called_once()
        sender.assert_not_called()  # 기사와 홍보 모두 발송하지 않는다.
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
