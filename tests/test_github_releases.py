from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from game_ai_news_bot.github_releases import _short_excerpt, collect_github_releases


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
SOURCE = {
    "id": "claude_code",
    "name": "Claude Code Releases",
    "product": "Claude Code",
    "kind": "github_releases",
    "repository": "anthropics/claude-code",
    "source_weight": 4,
    "perspective": "vendor",
}


def release(tag="v2.1.100", date="2026-09-01T10:00:00Z", body="Added native support for parallel agent workflows.", **changes):
    value = {
        "tag_name": tag,
        "name": tag,
        "html_url": f"https://github.com/anthropics/claude-code/releases/tag/{tag}",
        "published_at": date,
        "created_at": "2020-01-01T00:00:00Z",
        "body": body,
        "draft": False,
        "prerelease": False,
    }
    value.update(changes)
    return value


class GithubReleasesTests(unittest.TestCase):
    def collect(self, rows, *, source=None, description_limit=900, pages=None):
        collector = Mock(description_limit=description_limit)
        responses = []
        for index, payload in enumerate(pages if pages is not None else [rows]):
            response = Mock()
            response.json.return_value = payload
            response.links = {"next": {"url": "https://api.github.com/next"}} if pages and index < len(pages) - 1 else {}
            responses.append(response)
        collector._get.side_effect = responses
        with patch("game_ai_news_bot.github_releases.datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            result = collect_github_releases(collector, source or SOURCE)
        return result, collector

    def test_public_api_preserves_publication_date_and_product_metadata(self):
        row = release()
        articles, collector = self.collect([row])
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.published_at.isoformat(), "2026-09-01T10:00:00+00:00")
        self.assertEqual(article.url, row["html_url"])
        self.assertTrue(article.title.startswith("Claude Code v2.1.100 — Added native support"))
        self.assertEqual(article.metadata["content_kind"], "news")
        self.assertEqual(article.metadata["product"], "Claude Code")
        self.assertEqual(article.metadata["alias_urls"], [row["html_url"]])
        self.assertEqual(article.metadata["release_group_key"], "github:anthropics/claude-code:v2.1.100")
        self.assertEqual(article.perspective, "vendor")
        collector._get.assert_called_once_with(
            "https://api.github.com/repos/anthropics/claude-code/releases",
            params={"per_page": 100, "page": 1},
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )

    def test_rejects_drafts_prereleases_empty_tags_and_generic_notes(self):
        rows = [
            release(draft=True), release(prerelease=True), release(body=""), release(body=None),
            release(body="Bug fixes"), release(body="Various bug fixes and improvements."),
            release(body="## What's Changed\nFull Changelog: https://github.com/a/b/compare/a...b"),
            release(tag="rust-v0.1.0-alpha.1"), release(tag="latest"),
            release(published_at=None), release(published_at="not a date"),
            release(published_at="2026-09-01T10:00:00"),
            release(html_url="https://unrelated.example/releases/tag/v2.1.100"),
            release(date="2026-08-01T00:00:00Z"), {}, None,
        ]
        articles, _ = self.collect(rows)
        self.assertEqual(articles, [])

    def test_follows_hotfixes_under_original_feature_anchor(self):
        first = release()
        fix = release("v2.1.101", "2026-09-02T10:00:00Z", "Fixed a crash when restoring a disconnected agent session.")
        generic = release("v2.1.102", "2026-09-03T10:00:00Z", "Bug fixes")
        articles, _ = self.collect([generic, fix, first])
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.url, first["html_url"])
        self.assertEqual(article.published_at.isoformat(), first["published_at"].replace("Z", "+00:00"))
        self.assertEqual(article.metadata["alias_urls"], [first["html_url"], fix["html_url"], generic["html_url"]])
        self.assertEqual(article.metadata["release_tags"], ["v2.1.100", "v2.1.101", "v2.1.102"])
        self.assertIn("Fixed a crash", article.description)
        self.assertNotIn("Bug fixes", article.description)

    def test_same_minor_new_feature_is_separate_news_with_new_identity(self):
        first = release()
        fix = release("v2.1.101", "2026-09-02T10:00:00Z", "Fixed support for reopening a saved agent session.")
        new_feature = release("v2.1.102", "2026-09-03T10:00:00Z", "Added a new interactive level design planning workflow.")
        articles, _ = self.collect([new_feature, fix, first])
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].url, new_feature["html_url"])
        self.assertEqual(articles[1].metadata["alias_urls"], [first["html_url"], fix["html_url"]])
        self.assertNotEqual(articles[0].metadata["release_group_key"], articles[1].metadata["release_group_key"])

    def test_group_window_does_not_slide_forward_with_hotfixes(self):
        first = release(date="2026-08-25T10:00:00Z")
        fix = release("v2.1.101", "2026-08-31T10:00:00Z", "Fixed a crash when restoring a disconnected agent session.")
        later_fix = release("v2.1.102", "2026-09-02T10:00:00Z", "Fixed incorrect context handling during remote sessions.")
        articles, _ = self.collect([later_fix, fix, first])
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].url, later_fix["html_url"])
        self.assertEqual(articles[1].metadata["release_tags"], ["v2.1.100", "v2.1.101"])

    def test_different_minor_versions_do_not_merge_patch_notes(self):
        first = release()
        other = release("v2.2.0", "2026-09-02T10:00:00Z", "Fixed a crash when restoring a disconnected agent session.")
        articles, _ = self.collect([other, first])
        self.assertEqual(len(articles), 2)

    def test_feature_excerpt_precedes_installation_and_detailed_fixes(self):
        body = """## Installation
```sh
npm install -g a-very-long-package-name
```
Full Changelog: https://github.com/a/b/compare/a...b
## Bug Fixes
- Fixed intermittent crashes when reconnecting to a large workspace.
## New Features
- Added [MCP support](https://example.com/docs) for procedural scene editing.
- Security controls now restrict shell commands in shared projects.
## Changelog
- #123 Added MCP support for procedural scene editing by @contributor
"""
        articles, _ = self.collect([release(body=body)], description_limit=140)
        self.assertLessEqual(len(articles[0].description), 140)
        self.assertTrue(articles[0].description.startswith("Added MCP support for procedural scene editing."))
        self.assertIn("Security controls", articles[0].description)
        self.assertNotIn("npm install", articles[0].description)
        self.assertNotIn("https://", articles[0].description)
        self.assertNotIn("#123", articles[0].description)

    def test_codex_tag_prefix_and_invokeai_repository_are_supported(self):
        for repository, product, tag in [("openai/codex", "Codex", "rust-v0.110.0"), ("invoke-ai/InvokeAI", "InvokeAI", "v6.10.0")]:
            source = {**SOURCE, "repository": repository, "product": product}
            row = release(tag, html_url=f"https://github.com/{repository}/releases/tag/{tag}")
            with self.subTest(repository=repository):
                articles, collector = self.collect([row], source=source)
                self.assertEqual(len(articles), 1)
                self.assertTrue(articles[0].title.startswith(f"{product} {tag}"))
                self.assertEqual(collector._get.call_args.args[0], f"https://api.github.com/repos/{repository}/releases")

    def test_invokeai_generic_intro_and_detailed_commit_list_do_not_hide_features(self):
        body = """This release fixes a few bugs in version 6.14 and adds a couple of minor features that didn't make it into the previous release. For a full rundown of recently-added features please see [6.14.0 Release](https://github.com/invoke-ai/InvokeAI/releases/tag/v6.14.0)

## New Features in this release
* Workflows can now be screenshot and saved as PNGs (@JPPhoto)
* Middle clicks in the gallery will now open the media in a new browser tab. Enable the option in settings to get this feature. (@DustyShoe )
* Krea-2 LoRAs built with ai-toolkit's DoRA magnitudes are now supported (@Pfannkuchensack )
## Bug fixes
* Improve VRAM memory reservation for VAEs (@Pfannkuchensack )
## Full change list with pointers to detailed descriptions:
* Workflow screenshot as PNG by @JPPhoto in https://github.com/invoke-ai/InvokeAI/pull/9501
* chore(deps): bump diffusers to 0.40.0 by @lstein
"""
        articles, _ = self.collect([release(body=body)])
        article = articles[0]
        self.assertTrue(article.title.endswith("Workflows can now be screenshot and saved as PNGs"))
        self.assertTrue(article.metadata["release_summary"].startswith(
            "Workflows can now be screenshot and saved as PNGs. Middle clicks"))
        self.assertNotIn("Enable the option", article.metadata["release_summary"])
        self.assertIn("Krea-2 LoRAs", article.description)
        self.assertNotIn("This release", article.description)
        self.assertNotIn("by @", article.description)
        self.assertNotIn("(@", article.description)
        self.assertNotIn("chore(deps)", article.description)

    def test_bullet_sentence_boundaries_survive_whitespace_normalization(self):
        body = """- Added a model picker with custom model aliases
- Improved parallel coding agent session restoration
- Fixed project settings not loading after restart
"""
        articles, _ = self.collect([release(body=body)])
        normalized = " ".join(articles[0].description.split())
        self.assertIn("aliases. Improved parallel", normalized)
        self.assertIn("restoration. Fixed project", normalized)
        self.assertEqual(articles[0].metadata["release_summary"],
                         "Added a model picker with custom model aliases. "
                         "Improved parallel coding agent session restoration.")

    def test_headline_uses_opening_sentence_or_word_boundary_with_ellipsis(self):
        line = "Added a model picker for project-specific settings. " + "Further details about configuration " * 8
        articles, _ = self.collect([release(body="- " + line)])
        self.assertTrue(articles[0].title.endswith("Added a model picker for project-specific settings."))
        long_line = "Added support for " + "procedural scene editing workflows " * 8
        headline = _short_excerpt(long_line, 150, headline=True)
        self.assertLessEqual(len(headline), 150)
        self.assertTrue(headline.endswith("…"))
        self.assertTrue(long_line.startswith(headline[:-1] + " "))
        self.assertLessEqual(len(_short_excerpt(long_line, 0)), 0)

    def test_concrete_bullets_precede_introductory_prose_without_dropping_real_features(self):
        body = """This release introduces support for a new model family.
- Added a scene export workflow for game engine integration
- Fixed project selection after reconnecting
"""
        articles, _ = self.collect([release(body=body)])
        self.assertTrue(articles[0].title.endswith("Added a scene export workflow for game engine integration"))
        self.assertIn("This release introduces support for a new model family.", articles[0].description)

    def test_release_summary_keeps_prompt_cache_examples_after_abbreviation(self):
        body = """- Added a diff panel that opens beside the conversation in fullscreen mode and shows your uncommitted changes as Claude edits; toggle it with `/diff`
- Added a likely cause for prompt-cache misses (e.g. tool definitions or system prompt changed, idle past the TTL) to `/cost` and the status line's `prompt_cache` field
"""
        articles, _ = self.collect([release("v2.1.260", body=body)])
        summary = articles[0].metadata["release_summary"]
        self.assertIn("e.g. tool definitions or system prompt changed, idle past the TTL", summary)
        self.assertTrue(summary.endswith("prompt_cache field."))

    def test_excerpt_does_not_treat_abbreviations_or_internal_dots_as_sentence_ends(self):
        for abbreviation in ("e.g.", "i.e.", "U.S.", "vs."):
            first = f"Added examples for release configuration ({abbreviation} custom model identifiers)."
            with self.subTest(abbreviation=abbreviation):
                self.assertEqual(_short_excerpt(first + " See more details in the documentation.", 150,
                                                headline=True), first)
                # The abbreviation also cannot become a clause boundary on overflow.
                long = f"Added likely explanations for prompt-cache misses ({abbreviation} " + "configuration " * 20
                excerpt = _short_excerpt(long, 130)
                self.assertTrue(excerpt.endswith("…"))
                self.assertIn(f"{abbreviation} configuration", excerpt)
        for token in ("v2.1.260", "0.75", "config.example.com"):
            line = "Added configurable compatibility settings for local workspaces using " + token + " with shared settings"
            first_dot = line.index(".")
            with self.subTest(token=token):
                excerpt = _short_excerpt(line, first_dot + 2, headline=True)
                self.assertTrue(excerpt.endswith("…"))
                self.assertNotIn(token.split(".")[0] + ".", excerpt)

    def test_next_page_clue_recovers_stable_release_after_nightlies(self):
        prereleases = [release(f"v2.1.{number}", prerelease=True) for number in range(100)]
        articles, collector = self.collect([], pages=[prereleases, [release()]])
        self.assertEqual(len(articles), 1)
        self.assertEqual(collector._get.call_count, 2)
        self.assertEqual(collector._get.call_args.kwargs["params"]["page"], 2)

    def test_stops_pagination_after_old_page_or_three_pages(self):
        old_page = [release(f"v2.1.{number}", date="2026-08-01T00:00:00Z") for number in range(100)]
        articles, collector = self.collect([], pages=[old_page, [release()]])
        self.assertEqual(articles, [])
        collector._get.assert_called_once()
        recent_page = [release(f"v2.1.{number}", prerelease=True) for number in range(100)]
        articles, collector = self.collect([], pages=[recent_page, recent_page, recent_page, [release()]])
        self.assertEqual(articles, [])
        self.assertEqual(collector._get.call_count, 3)

    def test_invalid_repository_or_nonlist_api_body_is_rejected(self):
        for repository in ["https://github.com/a/b", "a/b/releases", "../x?token=y", "", None]:
            with self.subTest(repository=repository), self.assertRaises(ValueError):
                self.collect([], source={**SOURCE, "repository": repository})
        with self.assertRaises(ValueError):
            self.collect({"message": "API error"})

    def test_duplicate_page_items_are_not_repeated_and_result_limit_applies(self):
        first = release()
        other = release("v2.1.101", "2026-09-02T10:00:00Z", "Added local asset editing support for Unity projects.")
        articles, _ = self.collect([other, first, other], source={**SOURCE, "max_results": 1})
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].url, other["html_url"])
        self.assertEqual(articles[0].metadata["release_tags"], [other["tag_name"]])


if __name__ == "__main__":
    unittest.main()
