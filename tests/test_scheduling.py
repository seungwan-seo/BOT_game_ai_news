from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone

from game_ai_news_bot.scheduling import planned_news_limit, validate_morning_target
from game_ai_news_bot.state import KST, mark_delivered


class MorningScheduleTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "daily_post_limit": 20,
            "max_items_per_run": 1,
            "morning_target": {
                "enabled": True,
                "count": 10,
                "deadline_hour": 12,
                "end_hour": 22,
                "milestones": [
                    {"time": "07:00", "count": 3},
                    {"time": "08:30", "count": 6},
                    {"time": "10:00", "count": 10},
                ],
            },
        }

    def at(self, hour, minute=0, second=0):
        return datetime(2026, 9, 7, hour, minute, second, tzinfo=KST)

    def state(self, count):
        return {"delivery_day_kst": "2026-09-07", "delivery_count": count}

    def test_milestone_boundaries_and_operating_hours(self):
        cases = [
            (6, 59, 59, 0),
            (7, 0, 0, 3),
            (8, 29, 59, 3),
            (8, 30, 0, 6),
            (9, 59, 59, 6),
            (10, 0, 0, 10),
            (11, 59, 59, 10),
            (12, 0, 0, 10),
            (21, 59, 59, 10),
            (22, 0, 0, 0),
            (23, 59, 59, 0),
        ]
        for hour, minute, second, expected in cases:
            with self.subTest(time=(hour, minute, second)):
                self.assertEqual(
                    planned_news_limit(self.config, {}, self.at(hour, minute, second)), expected
                )

    def test_cumulative_milestones_subtract_only_successful_deliveries(self):
        state = {"seen": {}}
        for hour, minute, expected in [(7, 0, 3), (8, 30, 3), (10, 0, 4)]:
            now = self.at(hour, minute)
            limit = planned_news_limit(self.config, state, now)
            self.assertEqual(limit, expected)
            mark_delivered(state, [f"https://example.com/{hour}/{i}" for i in range(limit)], now)
            self.assertEqual(planned_news_limit(self.config, state, now), 0)
        self.assertEqual(state["delivery_count"], 10)

    def test_partial_delivery_and_skipped_schedule_catch_up(self):
        for hour, minute, count, expected in [
            (7, 30, 1, 2), (8, 45, 1, 5), (10, 30, 3, 7),
            (11, 59, 6, 4), (12, 0, 2, 8), (16, 0, 0, 10),
        ]:
            with self.subTest(time=(hour, minute), delivered=count):
                self.assertEqual(
                    planned_news_limit(self.config, self.state(count), self.at(hour, minute)), expected
                )

    def test_target_completion_waits_until_noon_then_resumes_existing_per_run_limit(self):
        for hour, minute, expected in [(10, 0, 0), (11, 59, 0), (12, 0, 1), (21, 59, 1), (22, 0, 0)]:
            with self.subTest(time=(hour, minute)):
                self.assertEqual(
                    planned_news_limit(self.config, self.state(10), self.at(hour, minute)), expected
                )
        self.config["max_items_per_run"] = 2
        self.assertEqual(planned_news_limit(self.config, self.state(9), self.at(13)), 2)
        self.assertEqual(planned_news_limit(self.config, self.state(12), self.at(13)), 2)

    def test_daily_limit_caps_both_morning_and_afternoon(self):
        self.config["daily_post_limit"] = 8
        self.assertEqual(planned_news_limit(self.config, self.state(6), self.at(10)), 2)
        self.assertEqual(planned_news_limit(self.config, self.state(6), self.at(14)), 2)
        self.assertEqual(planned_news_limit(self.config, self.state(8), self.at(10)), 0)
        self.config["daily_post_limit"] = 20
        self.config["max_items_per_run"] = 3
        self.assertEqual(planned_news_limit(self.config, self.state(19), self.at(14)), 1)
        self.assertEqual(planned_news_limit(self.config, self.state(20), self.at(14)), 0)
        self.assertEqual(planned_news_limit(self.config, self.state(25), self.at(14)), 0)

    def test_counts_kst_day_even_when_utc_day_is_previous_day(self):
        now = datetime(2026, 9, 6, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(planned_news_limit(self.config, self.state(2), now), 1)
        old_state = {"delivery_day_kst": "2026-09-06", "delivery_count": 20}
        self.assertEqual(planned_news_limit(self.config, old_state, now), 3)

    def test_midnight_resets_without_mutating_state_or_config(self):
        self.config["morning_target"]["end_hour"] = 24
        state = self.state(20)
        original_state = copy.deepcopy(state)
        original_config = copy.deepcopy(self.config)
        before = datetime(2026, 9, 7, 14, 59, 59, tzinfo=timezone.utc)
        midnight = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)
        next_morning = datetime(2026, 9, 7, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(planned_news_limit(self.config, state, before), 0)
        self.assertEqual(planned_news_limit(self.config, state, midnight), 0)
        self.assertEqual(planned_news_limit(self.config, state, next_morning), 3)
        self.assertEqual(state, original_state)
        self.assertEqual(self.config, original_config)

    def test_default_milestones_match_explicit_configuration(self):
        explicit = copy.deepcopy(self.config)
        del self.config["morning_target"]["milestones"]
        for hour, minute in [(6, 59), (7, 0), (8, 30), (10, 0), (12, 0), (22, 0)]:
            now = self.at(hour, minute)
            self.assertEqual(
                planned_news_limit(self.config, {}, now), planned_news_limit(explicit, {}, now)
            )

    def test_custom_milestones_determine_start_and_target_times(self):
        self.config["morning_target"]["count"] = 5
        self.config["morning_target"]["milestones"] = [
            {"time": "06:15", "count": 2}, {"time": "09:45", "count": 5}
        ]
        self.assertEqual(planned_news_limit(self.config, {}, self.at(6, 14)), 0)
        self.assertEqual(planned_news_limit(self.config, {}, self.at(6, 15)), 2)
        self.assertEqual(planned_news_limit(self.config, self.state(2), self.at(9, 45)), 3)

    def test_disabled_or_missing_setting_preserves_legacy_per_run_behavior(self):
        for morning in [None, {}, {"count": "ignored"}, {"enabled": False, "count": "ignored"}]:
            config = {"daily_post_limit": 20, "max_items_per_run": 2}
            if morning is not None:
                config["morning_target"] = morning
            with self.subTest(morning=morning):
                self.assertEqual(planned_news_limit(config, {}, self.at(2)), 2)
                self.assertEqual(planned_news_limit(config, self.state(19), self.at(23)), 1)
                self.assertEqual(planned_news_limit(config, self.state(20), self.at(23)), 0)
        self.assertEqual(planned_news_limit({"max_items": 3}, {}, self.at(2)), 3)

    def test_invalid_enabled_schedule_is_rejected(self):
        invalid = [
            {"enabled": "true"}, {"count": 0}, {"count": True}, {"count": 1.5},
            {"deadline_hour": 22}, {"deadline_hour": 24}, {"deadline_hour": -1},
            {"end_hour": 12}, {"end_hour": 25}, {"end_hour": True},
            {"milestones": []}, {"milestones": {}}, {"milestones": [None]},
            {"milestones": [{"time": "7:00", "count": 10}]},
            {"milestones": [{"time": "07:60", "count": 10}]},
            {"milestones": [{"time": "24:00", "count": 10}]},
            {"milestones": [{"time": "12:00", "count": 10}]},
            {"milestones": [{"time": "07:00", "count": 9}]},
            {"milestones": [{"time": "07:00", "count": 11}]},
            {"milestones": [{"time": "07:00", "count": -1}, {"time": "10:00", "count": 10}]},
            {"milestones": [{"time": "07:00", "count": True}, {"time": "10:00", "count": 10}]},
            {"milestones": [{"time": "08:00", "count": 3}, {"time": "07:00", "count": 10}]},
            {"milestones": [{"time": "07:00", "count": 3}, {"time": "07:00", "count": 10}]},
            {"milestones": [
                {"time": "07:00", "count": 6}, {"time": "08:00", "count": 3},
                {"time": "10:00", "count": 10},
            ]},
        ]
        for changes in invalid:
            config = copy.deepcopy(self.config)
            config["morning_target"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_morning_target(config)
        self.config["morning_target"] = "invalid"
        with self.assertRaises(ValueError):
            planned_news_limit(self.config, {}, self.at(7))

    def test_timezone_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            planned_news_limit(self.config, {}, datetime(2026, 9, 7, 7))


if __name__ == "__main__":
    unittest.main()
