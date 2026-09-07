"""Select practical tool updates and production references from broad new feeds.

Only public titles, excerpts and source-provided tags are used. A source profile
describes its subject area; it is not permission to publish every vendor post.
"""

from __future__ import annotations

import html
import re

from .models import Article


def _plain(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip().casefold()


def _has(text: str, *terms: str) -> bool:
    for term in terms:
        pattern = re.escape(term.casefold())
        if re.match(r"[a-z0-9]", term, re.I):
            pattern = r"(?<![a-z0-9])" + pattern
        if re.search(r"[a-z0-9]$", term, re.I):
            pattern += r"(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def _tags(article: Article) -> str:
    values: list[str] = []
    for key in ("tags", "categories", "content_type"):
        value = article.metadata.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(item for item in value if isinstance(item, str))
    return _plain(" ".join(values))


_RESOURCE = (
    "tutorial", "tutorials", "how to", "how-to", "guide", "walkthrough",
    "interview", "interviews", "case study", "case studies", "postmortem",
    "post-mortem", "breakdown", "사용법", "튜토리얼", "가이드", "인터뷰",
    "제작 사례", "적용 사례", "사례 연구",
)
_NEWS = (
    "announcing", "announced", "introducing", "release", "released",
    "releases", "launch", "launches", "launched", "update", "updates",
    "what's new", "now available", "now native", "day-0 support",
    "출시", "발표", "업데이트", "릴리스",
)
# HTML collectors establish these category labels separately from headline
# words. In particular, a headline mentioning a workflow is not itself a guide.
_RESOURCE_TAGS = {
    "tutorial", "tutorials", "interview", "interviews", "workflow", "workflows",
    "user stories", "case study", "case studies", "guide", "guides",
}


def _has_resource_evidence(article: Article) -> bool:
    """Accept only the specific evidence vocabulary emitted by HTML collectors."""
    if article.metadata.get("content_kind") != "resource":
        return False
    evidence = article.metadata.get("content_kind_evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, (list, tuple)):
        return False
    for raw in evidence:
        value = _plain(raw)
        if value in {"jsonld:@type=howto", "jsonld:howto"}:
            return True
        if value.startswith("tag:") and value.partition(":")[2] in _RESOURCE_TAGS:
            return True
        if value.startswith("title:") and _has(value.partition(":")[2], *_RESOURCE, "step-by-step", "step by step"):
            return True
        if re.fullmatch(r"intro:(?:this|the|our) (?:tutorial|walkthrough|interview|step.by.step guide)", value):
            return True
    return False


def classify_content_kind(article: Article, source: dict) -> str:
    """Return news/resource without extending ordinary news through body keywords.

Release entries remain news even when their notes contain tutorial links. A
weekly digest remains news even when one of its featured links is a resource.
"""
    title = _plain(article.title)
    tags = _tags(article)
    if _has(title, "weekly", "digest", "gossip", "newsletter", "roundup", "round-up", "주간", "뉴스레터"):
        return "news"
    if source.get("kind") in {"github_release", "github_releases", "cursor_changelog"} or any(
        article.metadata.get(key) for key in ("release_tag", "tag_name", "release_group_key")
    ):
        return "news"
    if re.match(r"^(?:announcing|introducing|release\b|released\b)", title):
        return "news"
    if _has(title, *_RESOURCE):
        return "resource"
    if _has(title, *_NEWS):
        return "news"
    if _has(tags, "news", "release", "releases", "changelog", "updates"):
        return "news"
    if _has(tags, *_RESOURCE):
        return "resource"
    if _has_resource_evidence(article):
        return "resource"
    if _has(title, "workflow", "workflows", "pipeline", "production", "워크플로", "제작") and _has(
        title, "how", "using", "building", "creating", "use cases", "in practice",
        "tips", "lessons", "사용", "방법", "사례",
    ):
        return "resource"
    return "news"


_PROMOTION = (
    "sponsored", "sponsored article", "advertorial", "paid partnership",
    "partner announcement", "partnership", "partnering", "fundraising",
    "funding round", "funding", "investment", "investments", "investors",
    "venture capital", "series a", "series b", "series c", "valuation", "ipo",
    "stock price", "trading", "crypto", "nft", "acquisition", "acquired", "hiring", "we're hiring",
    "meet the team", "our team", "company news", "anniversary",
    "giveaway", "coupon", "discount", "sale ends", "black friday",
    "challenge", "competition", "contest", "winners", "winner", "hackathon",
    "webinar", "conference", "summit", "join us", "meet us", "fellowship",
    "reseller", "licensing service", "consulting service", "consulting services",
    "forward deployed creatives", "후원", "광고", "투자 유치", "투자유치",
    "기업가치", "제휴", "할인", "이벤트", "챌린지", "공모전", "수상자",
)
_CHANGE = (
    "added", "adds", "adding", "introducing", "introduced", "new", "native",
    "released", "release", "launch", "launched", "now", "support", "supports",
    "supported", "improved", "improves", "enhanced", "enables", "enabled",
    "build", "building", "built", "create", "creating", "generate", "generation",
    "deploy", "deployment", "configure", "configuration", "integrate",
    "integration", "integrating", "open sourcing", "open-source", "open source",
    "추가", "지원", "개선", "공개", "생성", "구현", "통합", "설정", "제작",
)
_CODING = (
    "code review", "code completion", "coding", "debugging", "diff", "terminal",
    "command", "commands", "cli", "ide", "mcp", "sandbox", "agent", "agents",
    "subagent", "subagents", "repository", "repositories", "self-hosted",
    "self hosted", "checkpoint", "checkpoints", "hooks", "skills", "context",
    "model picker", "model support",
    "코딩", "코드 리뷰", "터미널", "디버깅", "개발 도구",
)
_ASSET = (
    "3d", "image", "images", "video", "animation", "texture", "textures",
    "pbr", "mesh", "meshes", "geometry", "topology", "rigging", "lora", "loras",
    "inpainting", "outpainting", "controlnet", "controlnets", "music", "audio",
    "asset", "assets", "canvas", "vae", "vram", "fp8",
    "text-to-image", "image-to-3d", "text-to-3d", "이미지", "영상", "텍스처",
    "메시", "리깅", "애니메이션", "에셋", "음악", "음성",
)
_GAME = (
    "game", "games", "gameplay", "game development", "unity", "unreal",
    "godot", "npc", "npcs", "게임", "유니티", "언리얼",
)
_AI = (
    "ai", "generative", "inference", "llm", "machine learning", "ai-powered",
    "ai-generated", "text-to-image", "image-to-3d", "text-to-3d", "인공지능",
    "생성형", "추론",
)


def evaluate_source_article(article: Article, source: dict) -> bool:
    """Apply an explicit source profile and annotate accepted practical content.

Sources without a profile retain their existing ranking rules. The caller can
combine editorial_score with source weight and recency; no final score is set.
"""
    for key in ("editorial_score", "editorial_reason"):
        article.metadata.pop(key, None)
    kind = classify_content_kind(article, source)
    article.metadata["content_kind"] = kind
    profile = source.get("editorial_profile")
    if not profile:
        return True

    title = _plain(article.title)
    tags = _tags(article)
    description = _plain(article.description)
    text = f"{title} {description} {tags}"
    if article.metadata.get("sponsored") is True or _has(f"{title} {tags}", *_PROMOTION):
        return False
    if _has(text, "sponsored article", "sponsored by", "paid partnership", "advertorial"):
        return False
    if re.search(r"\b(?:raises?|raised|secures?|secured)\s+(?:\$|€|£|funding\b|investment\b)", title):
        return False
    security_issue = bool(re.search(r"\bcve-\d{4}-\d+\b", text)) or _has(
        text, "security patch", "security fix", "security fixes", "security issue",
        "security vulnerability", "security hole", "security holes", "vulnerability",
        "vulnerabilities", "remote code execution", "arbitrary code execution",
        "path traversal", "보안 취약점", "보안 패치",
    )
    security_fix = security_issue and _has(
        text, "fixed", "fix", "fixes", "patch", "patches", "patched", "resolved",
        "closes", "close", "addressed", "security update", "수정", "보안 패치",
    )
    # A validated release repository supplies product context even if a short
    # security notice does not repeat "image" or "coding" in its excerpt.
    source_repository = source.get("repository")
    security_release = bool(
        security_fix and source.get("kind") in {"github_release", "github_releases"}
        and isinstance(source_repository, str) and source_repository
        and _plain(article.metadata.get("repository")) == source_repository.casefold()
    )
    if kind == "news" and not security_fix and _has(description, "fixed", "bug fixes", "bugfix", "bugfixes") and not _has(
        description, "added", "adds", "adding", "new features", "support", "supports",
        "introduced", "introducing", "enables", "enabled", "기능 추가", "지원",
    ):
        return False
    # Descriptions such as "Bug fixes and reliability improvements" do not
    # explain a workflow change, even when a version headline looks important.
    practical = kind == "resource" or security_fix or _has(text, *_CHANGE)
    category = ""
    reason = ""

    if profile == "coding_tool" and practical and (_has(text, *_CODING) or security_release):
        category = "🛠 개발 도구"
        if _has(text, "self-hosted", "self hosted", "deploy", "deployment", "sandbox"):
            reason = "AI 코딩 에이전트의 실행 환경과 배포·격리 방식을 게임 개발 환경에 맞춰 검토할 자료입니다."
        elif _has(text, "diff", "code review", "review", "코드 리뷰"):
            reason = "AI가 수정한 게임 코드의 변경 내용을 확인하고 검토하는 작업에 적용할 기능을 다룹니다."
        else:
            reason = "AI 코딩 도구의 명령 실행·컨텍스트·도구 연결 방식 중 소개된 변경을 개발 작업에 적용해 볼 자료입니다."
    elif profile == "asset_tool" and practical and (
        _has(text, *_ASSET) or security_release or (_has(text, "mcp") and _has(text, "workflow", "workflows"))
    ):
        category = "🌍 월드·콘텐츠 생성"
        if _has(text, "geometry", "topology", "mesh", "meshes", "pbr", "image-to-3d", "text-to-3d"):
            reason = "생성한 3D 모델의 형상·메시·재질을 에셋 제작 과정에서 다루는 기능과 제약을 살펴볼 자료입니다."
        elif _has(text, "rigging", "animation", "리깅", "애니메이션"):
            reason = "생성 에셋의 리깅·애니메이션 작업에 적용할 기능과 결과물의 수정 가능성을 검토할 자료입니다."
        elif _has(text, "music", "audio", "음악", "음성"):
            reason = "게임 사운드 제작에 활용할 생성 기능과 공개된 작업 흐름을 검토할 자료입니다."
        else:
            reason = "이미지·영상 에셋의 생성과 편집을 반복하는 작업에 적용할 기능을 살펴볼 자료입니다."
    elif profile == "npc_tool" and practical and _has(text, *_GAME) and _has(
        text, "npc", "npcs", "character", "characters", "agent", "agents",
        "dialogue", "conversation", "conversational", "actions", "behavior",
        "캐릭터", "대화", "행동",
    ):
        category = "🤖 NPC·에이전트"
        reason = "게임 엔진에서 AI 캐릭터의 대화·행동을 연결하고 제어하는 구현 방법을 살펴볼 자료입니다."
    elif profile == "game_case" and _has(text, *_AI) and (
        _has(text, *_GAME) or (_has(text, *_ASSET) and _has(text, "pipeline", "workflow", "workflows", "production"))
    ) and (kind == "resource" or _has(text, "prototype", "prototypes", "implementation", "implemented", "integration", "workflow", "pipeline")):
        category = "🛠 개발 도구"
        reason = "실제 게임·에셋 제작 사례에서 AI를 적용한 단계와 사람이 통제한 범위를 살펴볼 자료입니다."
    else:
        return False

    if security_fix:
        reason = "AI 개발·에셋 제작 도구의 취약점 수정 내용과 업데이트가 필요한 적용 범위를 확인할 자료입니다."

    score = 12 + (2 if kind == "resource" else 0)
    if _has(text, *_GAME):
        score += 2
    if _has(text, "workflow", "pipeline", "sdk", "mcp", "benchmark", "evaluation", "워크플로", "벤치마크"):
        score += 2
    if _has(text, "limitations", "constraints", "trade-offs", "제약", "한계"):
        score += 2
    article.category = category
    article.relevance = min(20, score)
    article.metadata.update(editorial_score=article.relevance, editorial_reason=reason)
    return True
