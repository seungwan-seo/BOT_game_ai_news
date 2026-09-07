from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from game_ai_news_bot.editorial import classify_content_kind, evaluate_source_article
from game_ai_news_bot.freshness import is_fresh
from game_ai_news_bot.models import Article


class EditorialTests(unittest.TestCase):
    def article(self, title: str, description: str = "", **metadata) -> Article:
        return Article("source", "Official source", title, "https://example.com/post", description=description, metadata=metadata)

    def test_practical_updates_and_production_references_are_selected(self):
        examples = [
            ("coding_tool", "Claude Code v2.1.261", "Added command output limits and skills context reporting.", "news"),
            ("coding_tool", "Codex 0.153.0", "Added code review and sandbox configuration support.", "news"),
            ("coding_tool", "Codex 0.153.1", "Added support for configuring a new model without changing the model picker.", "news"),
            ("coding_tool", "Introducing self-hosted cloud agents", "Run coding agents inside your own repository infrastructure.", "news"),
            ("asset_tool", "Trellis.2 and Pixal3D Are Now Native in ComfyUI", "New mesh processing nodes and a PBR texturing pipeline for image-to-3D generation.", "news"),
            ("asset_tool", "Meshy 7: Pushing the frontier of 3D alignment", "A new image-to-3D model tuned for geometry alignment, with benchmark results and limitations.", "news"),
            ("asset_tool", "InvokeAI 6.14.1", "Added workflow screenshots and support for Krea-2 LoRAs.", "news"),
            ("asset_tool", "Open Sourcing Comfy MCP on Local", "Run Comfy workflows through MCP with local agents.", "news"),
            ("asset_tool", "Meshy in ComfyUI: How to Use the Official Partner Node for AI 3D Generation", "An image-to-3D workflow for game assets.", "resource"),
            ("npc_tool", "Unity Actions: Make AI Characters Interact with Your World", "New SDK support connects NPC actions to the Unity game environment.", "news"),
            ("npc_tool", "How to build NPC dialogue in Unreal Engine", "Configure character actions using the SDK tutorial.", "resource"),
            ("game_case", "Interview: New Indie Game Uses Local AI Model Trained on Studio's Own Artists", "Studio Atelico describes on-device inference, testing and authored constraints after ten game prototypes.", "resource"),
        ]
        for profile, title, description, kind in examples:
            with self.subTest(title=title):
                article = self.article(title, description)
                self.assertTrue(evaluate_source_article(article, {"editorial_profile": profile}))
                self.assertEqual(article.metadata["content_kind"], kind)
                self.assertGreaterEqual(article.metadata["editorial_score"], 10)
                self.assertLessEqual(article.metadata["editorial_score"], 20)
                self.assertRegex(article.metadata["editorial_reason"], "[가-힣]")

    def test_vendor_marketing_is_not_mistaken_for_practical_news(self):
        titles = [
            "Comfy Is Now an Official Reseller of MiniMax H3 Commercial Licenses",
            "Forward Deployed Creatives",
            "Comfy H3 Sync Sound Challenge: The Winners",
            "Join us at the AI game development conference",
            "New partnership brings AI 3D tools to everyone",
            "Meshy raises $100 million for AI 3D generation",
            "Meshy Series B funding round",
            "AI 3D art investment guide",
            "New AI assets holiday discount",
            "Company news: our new leadership team",
        ]
        for title in titles:
            with self.subTest(title=title):
                article = self.article(title, "New image, video and 3D generation tools for game workflows.")
                self.assertFalse(evaluate_source_article(article, {"editorial_profile": "asset_tool"}))

    def test_sponsored_case_studies_are_excluded_by_source_metadata(self):
        for metadata in ({"tags": ["Interviews", "AI", "Sponsored Article"]}, {"categories": "AI, Sponsored Article"}, {"sponsored": True}):
            with self.subTest(metadata=metadata):
                article = self.article("How Agents 404 Devs Created a Prototype", "AI coding workflow used to build a Unity game.", **metadata)
                self.assertFalse(evaluate_source_article(article, {"editorial_profile": "game_case"}))

    def test_sponsored_excerpt_is_excluded_without_tags(self):
        article = self.article("An AI production workflow", "This sponsored article explains how to create a game with AI.")
        self.assertFalse(evaluate_source_article(article, {"editorial_profile": "game_case"}))

    def test_generic_bugfix_and_empty_release_posts_are_not_news(self):
        for profile in ("coding_tool", "asset_tool", "npc_tool"):
            for description in ("", "Bug fixes and reliability improvements", "Fixed an issue in the coding agent."):
                with self.subTest(profile=profile, description=description):
                    article = self.article("v2.1.263", description)
                    self.assertFalse(evaluate_source_article(article, {"editorial_profile": profile}))
        article = self.article("New Claude Code release", "Fixed a typo in the coding agent status label.")
        self.assertFalse(evaluate_source_article(article, {"editorial_profile": "coding_tool"}))

    def test_wrong_subject_is_rejected_even_with_practical_headlines(self):
        examples = [
            ("coding_tool", "How to make AI stock predictions", "A tutorial for investors."),
            ("asset_tool", "The future of artificial intelligence", "An inspiring new chapter for everyone."),
            ("npc_tool", "How to build a sales avatar", "AI characters answer retail customer questions."),
            ("game_case", "How to make a Blender character", "Hand-painted modeling and a traditional rigging pipeline without machine generation."),
            ("game_case", "Interview about AI investment", "A CEO explains the global AI market."),
        ]
        for profile, title, description in examples:
            with self.subTest(title=title):
                self.assertFalse(evaluate_source_article(self.article(title, description), {"editorial_profile": profile}))

    def test_news_body_tutorial_links_do_not_extend_freshness(self):
        article = self.article("Introducing the new 3D model", "Read our tutorial and how-to workflow guide.", tags=["Tutorial"])
        self.assertEqual(classify_content_kind(article, {}), "news")
        release = self.article("Code review guide improvements", "Read the tutorial.", release_tag="v1.2.3")
        self.assertEqual(classify_content_kind(release, {}), "news")

    def test_generic_weekly_news_is_not_a_thirty_day_resource(self):
        for title in ("#005 - Gamescom Gossip", "Weekly AI digest", "AI newsletter: new workflows", "This week's news roundup"):
            with self.subTest(title=title):
                article = self.article(title, "Tutorials, interviews and workflow guides inside.", tags=["Tutorials"])
                self.assertEqual(classify_content_kind(article, {}), "news")

    def test_explicit_production_tutorial_and_interview_tags_are_resources(self):
        examples = [
            self.article("Batch Generation in Comfy MCP: Use Cases in Production"),
            self.article("Making a local NPC", tags=["Interview", "Game Development"]),
            self.article("How to use a new image generation model"),
            self.article("게임 NPC 제작 사례"),
        ]
        for article in examples:
            with self.subTest(title=article.title):
                self.assertEqual(classify_content_kind(article, {}), "resource")

    def test_existing_sources_keep_their_relevance_and_receive_only_kind(self):
        article = self.article("How to implement game AI")
        article.relevance = 7
        article.score = 25
        self.assertTrue(evaluate_source_article(article, {}))
        self.assertEqual(article.metadata, {"content_kind": "resource"})
        self.assertEqual((article.relevance, article.score), (7, 25))

    def test_rejected_re_evaluation_clears_prior_editorial_approval(self):
        article = self.article("New 3D generation workflow")
        source = {"editorial_profile": "asset_tool"}
        self.assertTrue(evaluate_source_article(article, source))
        article.title = "New sponsored 3D generation workflow"
        self.assertFalse(evaluate_source_article(article, source))
        self.assertNotIn("editorial_score", article.metadata)
        self.assertNotIn("editorial_reason", article.metadata)

    def test_unknown_profile_is_not_implicitly_trusted(self):
        self.assertFalse(evaluate_source_article(self.article("New AI tool"), {"editorial_profile": "unknown"}))

    def test_html_resource_evidence_survives_without_a_tutorial_headline(self):
        for evidence in (["intro:this tutorial"], ["intro:our interview"], ["jsonld:@type=HowTo"], ["tag:Case Study"]):
            with self.subTest(evidence=evidence):
                article = self.article("Bring NPCs to Life in Unity", "Connect character actions to your game.", content_kind="resource", content_kind_evidence=evidence)
                self.assertEqual(classify_content_kind(article, {}), "resource")
                self.assertTrue(evaluate_source_article(article, {"editorial_profile": "npc_tool"}))
                self.assertEqual(article.metadata["content_kind"], "resource")

    def test_bare_or_unrecognized_metadata_cannot_extend_freshness(self):
        for evidence in (None, [], ["resource"], ["intro:see our tutorial link"], {"tutorial": True}):
            with self.subTest(evidence=evidence):
                article = self.article("AI industry thoughts", content_kind="resource", content_kind_evidence=evidence)
                self.assertEqual(classify_content_kind(article, {}), "news")

    def test_verified_html_resource_categories_keep_thirty_day_window(self):
        now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        for tag in ("Workflows", "User Stories", "Guides"):
            with self.subTest(tag=tag):
                article = self.article(
                    "Bringing History to Life: Moesgaard Museum",
                    "Creating detailed 3D assets for a production pipeline.",
                    tags=[tag], content_kind="resource", content_kind_evidence=[f"tag:{tag}"],
                )
                article.published_at = now - timedelta(days=20)
                self.assertTrue(evaluate_source_article(article, {"editorial_profile": "asset_tool"}))
                self.assertEqual(article.metadata["content_kind"], "resource")
                self.assertTrue(is_fresh(article, {"freshness_days": 7, "resource_freshness_days": 30}, now))

    def test_workflow_word_and_unverified_categories_do_not_extend_news(self):
        examples = [
            self.article("An improved image workflow", "A release notice about workflow controls."),
            self.article("Workflow updates now available", content_kind="resource", content_kind_evidence=["tag:Workflows"]),
            self.article("New image generation controls", tags=["Workflows"], content_kind="resource"),
            self.article("New image generation controls", content_kind="resource", content_kind_evidence=["tag:Workflow marketing"]),
        ]
        for article in examples:
            with self.subTest(title=article.title, metadata=article.metadata):
                self.assertEqual(classify_content_kind(article, {}), "news")

    def test_release_news_and_digest_override_resource_evidence(self):
        for title, metadata, source in (
            ("Weekly game AI digest", {}, {}),
            ("Introducing Unity actions", {}, {}),
            ("Unity SDK update", {}, {}),
            ("Unity actions", {"tags": ["News"]}, {}),
            ("Bring NPCs to Life", {}, {"kind": "github_releases"}),
            ("Bring NPCs to Life", {"release_group_key": "github:example/repo:v1.0.0"}, {}),
        ):
            with self.subTest(title=title, source=source):
                article = self.article(title, content_kind="resource", content_kind_evidence=["intro:this tutorial"], **metadata)
                self.assertEqual(classify_content_kind(article, source), "news")

    def test_meaningful_security_fix_keeps_existing_subject_filters(self):
        examples = [
            ("coding_tool", "Codex security patch", "Fixed CVE-2026-12345 in command execution isolation."),
            ("asset_tool", "InvokeAI security fix", "Fixed an image upload vulnerability."),
            ("npc_tool", "Convai Unity SDK patch", "Fixed a vulnerability in NPC dialogue requests."),
        ]
        for profile, title, description in examples:
            with self.subTest(title=title):
                article = self.article(title, description)
                self.assertTrue(evaluate_source_article(article, {"editorial_profile": profile}))
                self.assertIn("취약점", article.metadata["editorial_reason"])
        for title in ("Sponsored security patch for coding agents", "Stock trading security patch"):
            article = self.article(title, "Fixed CVE-2026-12345 in command execution.")
            self.assertFalse(evaluate_source_article(article, {"editorial_profile": "coding_tool"}))
        article = self.article("Security patch", "Fixed a vulnerability in hotel bookings.")
        self.assertFalse(evaluate_source_article(article, {"editorial_profile": "coding_tool"}))

    def test_security_release_can_use_verified_repository_product_context(self):
        source = {"kind": "github_releases", "repository": "invoke-ai/InvokeAI", "editorial_profile": "asset_tool"}
        article = self.article("InvokeAI 6.13.8 security patch", "Fixed two security holes.", repository="invoke-ai/InvokeAI")
        self.assertTrue(evaluate_source_article(article, source))
        article.metadata["repository"] = "unrelated/project"
        self.assertFalse(evaluate_source_article(article, source))

    def test_word_boundaries_do_not_confuse_ai_with_unrelated_text(self):
        article = self.article("Interview: Detailed game pipeline", "A traditional retail asset pipeline.")
        self.assertFalse(evaluate_source_article(article, {"editorial_profile": "game_case"}))


if __name__ == "__main__":
    unittest.main()
