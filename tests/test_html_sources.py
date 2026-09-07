from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from game_ai_news_bot.html_sources import collect_html_source


# Small fixed fixtures preserve structures observed on the public source pages
# on 2026-09-07. Article text is synthetic; no full article body is retained.
CURSOR_LIST = """
<article><div><p><a href="/changelog/agent-update"><time datetime="2026-09-02T00:00:00.000Z">Sep 2, 2026</time></a></p>
<header><h1><a href="/changelog/agent-update">AI agent update</a></h1></header>
<div class="prose prose--block"><p>New agent tools for developers.</p><p>Do not copy the rest of this article.</p>
<img src="/release.png"></div></div></article>
<article><h1><a href="/changelog/undated">Undated release</a></h1><p>No date.</p></article>
"""
MESHY_LIST = """
<nav><a href="/blog/category/workflows">Workflows</a></nav>
<a class="font-barlow group" href="/blog/material-workflow"><img src="https://cdn.meshy.ai/card.webp">
<span>Workflows</span><h3>Material pipeline guide</h3><p>A short workflow introduction.</p>
<span>Author</span><span class="whitespace-nowrap">2 days ago</span></a>
"""
MESHY_DETAIL = """
<script type="application/ld+json">{"@graph":[
{"@type":"Organization","datePublished":"1999-01-01"},
{"@type":"BlogPosting","url":"/blog/material-workflow","datePublished":"2026-09-04T12:00:00Z",
"dateModified":"2026-09-07T18:00:00Z","articleSection":"Workflows","image":["https://cdn.meshy.ai/cover.webp"]}]}</script>
"""
CONVAI_LIST = """
<div class="w-dyn-item"><a class="article-link article-v1 w-inline-block" href="/blog/scene-actions">
<div class="blog-card-image-wrapper"><img src="https://cdn.example/actions.jpg"></div>
<div class="article-v1-content"><h3 class="article-title">Create AI scene actions</h3>
<div class="article-tag"><div>Convai Team</div><div class="flex-horizontal"><div class="text-100 medium">August 24, 2026</div></div></div>
</div></a></div>
"""
CONVAI_DETAIL = """
<header><article class="header__nav-link-wrapper">Use Cases</article></header>
<meta name="description" content="A concise description of character actions.">
<script type="application/ld+json">{"@type":"BlogPosting","url":"/blog/scene-actions",
"datePublished":"2026-08-24","dateModified":"2026-09-07"}</script>
<div class="c__rich-text blog_content w-richtext"><p>This tutorial covers the entire workflow for AI characters.</p>
<p>Additional content must not be copied to the description.</p></div>
"""
EIGHTY_LIST = """
<meta property="article:published_time" content="2024-02-08T10:18:03Z">
<div class="_3TcmX"><div class="_3U8l3"><a href="/articles/production-pipeline"><img image=""></a></div>
<div class="_3tFz8"><div class="_3PNsL"><a href="/articles/production-pipeline"><h1 class="_3UuWo">Studio production pipeline</h1></a>
<p class="_2hL39"><span class="_1weau">03 September 2026<!-- --> - </span>A short production interview.</p></div>
<div class="_11S7k"><span class="_1VIu2">#<!-- -->Interviews</span><span class="_1VIu2">#<!-- -->AI</span>
<span class="_1VIu2">#<!-- -->Sponsored Article</span></div></div></div>
"""
EIGHTY_DETAIL = """
<meta property="article:published_time" content="2026-09-03T16:00:00+00:00">
<meta property="article:modified_time" content="2026-09-06T20:00:00Z">
<meta property="og:image" content="https://cdn.80.lv/cover.jpg">
"""


class HtmlSourceTests(unittest.TestCase):
    def source(self, kind, **overrides):
        urls = {"cursor_changelog": "https://cursor.com/changelog", "meshy_blog": "https://www.meshy.ai/blog",
                "convai_blog": "https://convai.com/blog", "eighty_level": "https://80.lv/articles/ai"}
        return {"id": kind, "name": kind, "kind": kind, "url": urls[kind],
                "source_weight": 4, "perspective": "vendor", **overrides}

    def collector(self, pages, limit=80):
        def get(url):
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return SimpleNamespace(text=value)
        return SimpleNamespace(_get=Mock(side_effect=get), description_limit=limit)

    def test_cursor_uses_dated_entries_and_only_opening_paragraph(self):
        source = self.source("cursor_changelog")
        collector = self.collector({source["url"]: CURSOR_LIST})
        articles = collect_html_source(collector, source)
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.published_at.isoformat(), "2026-09-02T00:00:00+00:00")
        self.assertEqual(article.description, "New agent tools for developers.")
        self.assertEqual(article.image_url, "https://cursor.com/release.png")
        self.assertEqual(article.metadata["content_kind"], "news")
        self.assertEqual(article.metadata["published_at_source"], "list:time")
        self.assertTrue(article.metadata["enriched"])
        collector._get.assert_called_once_with(source["url"])

    def test_meshy_relative_date_requires_original_jsonld_publication_date(self):
        source = self.source("meshy_blog")
        collector = self.collector({source["url"]: MESHY_LIST,
                                    "https://www.meshy.ai/blog/material-workflow": MESHY_DETAIL})
        article = collect_html_source(collector, source)[0]
        self.assertEqual(article.published_at.isoformat(), "2026-09-04T12:00:00+00:00")
        self.assertEqual(article.metadata["published_at_source"], "jsonld:datePublished")
        self.assertEqual(article.metadata["content_kind"], "resource")
        self.assertIn("tag:Workflows", article.metadata["content_kind_evidence"])
        self.assertEqual(article.image_url, "https://cdn.meshy.ai/cover.webp")
        self.assertEqual(article.perspective, "vendor")

    def test_relative_date_and_modified_only_detail_are_excluded(self):
        source = self.source("meshy_blog")
        detail = '<script type="application/ld+json">{"@type":"BlogPosting","dateModified":"2026-09-07"}</script>'
        collector = self.collector({source["url"]: MESHY_LIST,
                                    "https://www.meshy.ai/blog/material-workflow": detail})
        self.assertEqual(collect_html_source(collector, source), [])

    def test_convai_explicit_tutorial_intro_establishes_resource_kind(self):
        source = self.source("convai_blog")
        collector = self.collector({source["url"]: CONVAI_LIST,
                                    "https://convai.com/blog/scene-actions": CONVAI_DETAIL}, limit=25)
        article = collect_html_source(collector, source)[0]
        self.assertEqual(article.published_at.isoformat(), "2026-08-24T00:00:00+00:00")
        self.assertEqual(article.metadata["content_kind"], "resource")
        self.assertIn("intro:This tutorial", article.metadata["content_kind_evidence"])
        self.assertEqual(len(article.description), 25)
        self.assertNotIn("Additional", article.description)

    def test_eighty_level_preserves_sponsorship_and_original_publication_date(self):
        source = self.source("eighty_level")
        collector = self.collector({source["url"]: EIGHTY_LIST,
                                    "https://80.lv/articles/production-pipeline": EIGHTY_DETAIL})
        article = collect_html_source(collector, source)[0]
        self.assertEqual(article.published_at.isoformat(), "2026-09-03T16:00:00+00:00")
        self.assertEqual(article.description, "A short production interview.")
        self.assertEqual(article.metadata["content_kind"], "resource")
        self.assertTrue(article.metadata["sponsored"])
        self.assertEqual(article.image_url, "https://cdn.80.lv/cover.jpg")

    def test_convai_article_intro_overrides_description_reused_from_another_post(self):
        source = self.source("convai_blog")
        detail = CONVAI_DETAIL.replace(
            "A concise description of character actions.",
            "Give Unreal Engine characters live game state with Dynamic Context.",
        ).replace(
            "This tutorial covers the entire workflow for AI characters.",
            "Convai Actions let a Unity character carry out player requests. This tutorial covers action targets.",
        )
        collector = self.collector({source["url"]: CONVAI_LIST,
                                    "https://convai.com/blog/scene-actions": detail})
        article = collect_html_source(collector, source)[0]
        self.assertIn("Unity character", article.description)
        self.assertNotIn("Unreal Engine", article.description)
        self.assertNotIn("Additional content", article.description)
        self.assertLessEqual(len(article.description), 400)

    def test_known_list_date_and_type_do_not_require_detail_with_an_image(self):
        source = self.source("eighty_level")
        listing = EIGHTY_LIST.replace('image=""', 'src="https://cdn.80.lv/card.jpg"')
        collector = self.collector({source["url"]: listing})
        article = collect_html_source(collector, source)[0]
        self.assertEqual(article.published_at.isoformat(), "2026-09-03T00:00:00+00:00")
        self.assertEqual(article.metadata["published_at_source"], "list:text")
        collector._get.assert_called_once_with(source["url"])

    def test_failed_detail_keeps_absolute_list_date_without_retry(self):
        source = self.source("convai_blog")
        collector = self.collector({source["url"]: CONVAI_LIST,
                                    "https://convai.com/blog/scene-actions": RuntimeError("403 Forbidden")})
        articles = collect_html_source(collector, source)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].metadata["published_at_source"], "list:text")
        self.assertNotIn("enriched", articles[0].metadata)
        self.assertEqual(collector._get.call_count, 2)

    def test_detail_budget_and_max_results_bound_requests(self):
        source = self.source("meshy_blog", max_detail_requests=2, max_results=3)
        listing = "".join(MESHY_LIST.replace("material-workflow", f"material-{i}") for i in range(30))
        collector = self.collector({source["url"]: listing,
                                    "https://www.meshy.ai/blog/material-0": MESHY_DETAIL.replace("material-workflow", "material-0"),
                                    "https://www.meshy.ai/blog/material-1": MESHY_DETAIL.replace("material-workflow", "material-1")})
        self.assertEqual(len(collect_html_source(collector, source)), 2)
        self.assertEqual(collector._get.call_count, 3)

    def test_meshy_recent_cards_precede_old_pinned_cards_without_inventing_dates(self):
        source = self.source("meshy_blog", max_detail_requests=1)
        old = MESHY_LIST.replace("material-workflow", "pinned").replace("2 days ago", "3 months ago")
        collector = self.collector({source["url"]: old + MESHY_LIST,
                                    "https://www.meshy.ai/blog/material-workflow": MESHY_DETAIL})
        articles = collect_html_source(collector, source)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].url, "https://www.meshy.ai/blog/material-workflow")
        self.assertEqual(articles[0].published_at.isoformat(), "2026-09-04T12:00:00+00:00")
        self.assertEqual(collector._get.call_count, 2)

    def test_duplicate_links_and_external_heading_links_are_not_fetched(self):
        source = self.source("meshy_blog")
        listing = MESHY_LIST * 2 + MESHY_LIST.replace('/blog/material-workflow', 'https://unrelated.example/blog/item')
        collector = self.collector({source["url"]: listing,
                                    "https://www.meshy.ai/blog/material-workflow": MESHY_DETAIL})
        self.assertEqual(len(collect_html_source(collector, source)), 1)
        self.assertEqual(collector._get.call_count, 2)

    def test_invalid_absolute_date_does_not_crash_collection(self):
        source = self.source("cursor_changelog")
        listing = CURSOR_LIST.replace("2026-09-02T00:00:00.000Z", "2026-99-99").replace("Sep 2, 2026", "Invalid")
        collector = self.collector({source["url"]: listing})
        self.assertEqual(collect_html_source(collector, source), [])

    def test_zero_limit_and_unknown_kind(self):
        collector = self.collector({})
        self.assertEqual(collect_html_source(collector, self.source("meshy_blog", max_results=0)), [])
        collector._get.assert_not_called()
        with self.assertRaises(ValueError):
            collect_html_source(collector, {"kind": "unknown"})


if __name__ == "__main__":
    unittest.main()
