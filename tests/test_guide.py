from __future__ import annotations

import unittest

from game_ai_news_bot.guide import build_channel_guide_post


class ChannelGuideTests(unittest.TestCase):
    def test_builds_evergreen_guide_without_sister_channel_promotion(self):
        post = build_channel_guide_post(
            {
                "turtle_url": "https://store.steampowered.com/app/3952050/Turtle_Game/",
            }
        )
        self.assertIn("게임 AI 개발 뉴스 안내", post)
        self.assertIn("운영자가 만든 Steam 게임", post)
        self.assertIn("https://store.steampowered.com/app/3952050/Turtle_Game/", post)
        self.assertNotIn("함께 운영하는 채널", post)
        self.assertNotIn("Steam Deals", post)
        self.assertNotIn("https://t.me/steam_deals_free", post)
        self.assertNotIn("무료 배포", post)
        self.assertNotIn("앞서 해보기", post)
        self.assertNotIn("reviews", post.casefold())
        self.assertNotIn("₩", post)


if __name__ == "__main__":
    unittest.main()
