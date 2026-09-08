from __future__ import annotations

import html
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar

import requests

from .models import Article, DigestItem
from .ranking import category_trend
from .geeknews import build_summary as geeknews_summary, build_insight as geeknews_insight

logger = logging.getLogger(__name__)

MYMEMORY_TRANSLATE_URL = "https://api.mymemory.translated.net/get"
_FAILED_PROVIDERS: ContextVar[set[str] | None] = ContextVar("failed_translation_providers", default=None)


@contextmanager
def translation_session():
    """Share outage status across refill batches, reset it for the next run."""
    if _FAILED_PROVIDERS.get() is not None:
        yield
        return
    token = _FAILED_PROVIDERS.set(set())
    try:
        yield
    finally:
        _FAILED_PROVIDERS.reset(token)


def _provider_failed(provider: str) -> bool:
    return provider in (_FAILED_PROVIDERS.get() or set())


def _mark_provider_failed(provider: str) -> None:
    failed = _FAILED_PROVIDERS.get()
    if failed is not None:
        failed.add(provider)


def _korean_text(value: object) -> bool:
    return isinstance(value, str) and len(re.findall(r"[가-힣]", value)) >= 2


def _ready(item: DigestItem) -> bool:
    # Validate each user-facing field, not EN · original-title display metadata.
    return all(_korean_text(text) for text in (item.title_ko, item.summary_ko, item.insight_ko))


def _held(article: Article) -> None:
    logger.warning("한국어 제목·요약 미완성으로 발행 보류 (읽음 기록 없음): %s", article.url)


INSIGHT_RULES = (
    (("gamescom", "gdc", "conference", "interview"), "행사 데모보다 현업 개발자들이 반복해서 꺼낸 문제와 실제 도입 온도를 읽기 좋은 자료입니다."),
    (("open source", "github", "source code", "repository"), "공개 코드가 있어 홍보 문구에 머물지 않고 직접 재현·개조해 볼 수 있다는 점이 핵심입니다."),
    (("benchmark", "dataset", "evaluation"), "새 모델의 숫자보다 게임 상황을 얼마나 현실적으로 측정하는 평가 기준인지가 더 중요한 소식입니다."),
    (("latency", "real-time", "realtime"), "실시간 게임에서는 모델 정확도보다 지연시간이 곧 조작감이므로 실제 프레임 예산에 넣어 볼 가치가 큽니다."),
    (("dialogue", "conversation", "voice", "speech"), "NPC 대화의 자연스러움보다 플레이 상태를 읽고 말과 행동을 함께 바꾸는지가 제품화의 승부처입니다."),
    (("agent", "autonomous", "companion", "npc"), "에이전트가 스크립트를 벗어날수록 디자이너가 행동을 통제하고 같은 상황을 재현할 수 있는 장치가 중요해집니다."),
    (("procedural", "level generation", "world generation"), "생성 속도보다 디자이너가 결과를 수정하고 같은 조건을 다시 만들 수 있는지가 실무 채택을 가릅니다."),
    (("world model", "simulation"), "플레이 가능한 세계를 예측·생성하는 모델은 콘텐츠 제작과 AI 플레이어 훈련을 한 파이프라인으로 묶을 가능성이 있습니다."),
    (("unity", "unreal", "engine", "plugin", "sdk"), "성능 시연보다 기존 엔진의 반복 수정·버전 관리 흐름에 얼마나 자연스럽게 들어오는지가 핵심입니다."),
    (("playtest", "qa", "testing", "bug"), "자동 플레이어가 사람처럼 실패하고 우회하는지를 검증해야 실제 QA 시간을 줄일 수 있습니다."),
    (("copyright", "regulation", "policy", "lawsuit"), "기술 성능보다 학습 데이터와 표시 의무가 실제 출시 가능 범위를 결정하는 사안입니다."),
    (("release", "launch", "announce", "available"), "연구 데모가 아니라 개발자가 바로 시험할 수 있는 단계로 내려왔는지가 이 소식의 관전 포인트입니다."),
)

CATEGORY_INSIGHTS = {
    "🤖 NPC·에이전트": "NPC AI가 말 잘하는 데모를 넘어 실제 플레이 규칙 안에서 통제 가능한 시스템이 되는지를 보여주는 흐름입니다.",
    "🌍 월드·콘텐츠 생성": "생성 결과를 디자이너가 고치고 반복 생산할 수 있는지가 콘텐츠 파이프라인의 실제 가치를 결정합니다.",
    "🛠 개발 도구": "몇 초를 줄였다는 시연보다 팀의 반복 수정과 협업 과정에 들어오는지가 도구의 생존을 가릅니다.",
    "🧪 테스트·플레이어 모델": "사람 같은 실수와 변칙 행동까지 재현해야 자동 테스트가 단순 반복 작업을 넘어섭니다.",
    "📚 연구": "당장 제품 소식은 아니지만 다음 세대 게임 AI의 평가 기준과 구현 방향을 먼저 볼 수 있습니다.",
    "⚖️ 산업·정책": "기술이 가능하다는 사실과 실제 게임에 출시할 수 있다는 사실 사이의 간격을 다루는 소식입니다.",
    "📰 기타": "게임 제작이나 플레이 경험을 실제로 바꾸는 지점을 중심으로 볼 만한 소식입니다.",
}


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _has_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text))


def _limit_utf8(text: str, max_bytes: int = 480) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _translation_source_title(title: str) -> str:
    # 뉴스레터 제목 끝의 "| 02/09/26" 같은 발행일은 번역 품질을 크게 떨어뜨린다.
    # 영문 원제에는 그대로 보존하고 번역 요청에서만 제거한다.
    without_date = re.sub(
        r"\s*[|｜]\s*\d{1,4}(?:[./-]\d{1,2}){2}\s*$",
        "",
        title,
    )
    return without_date.strip() or title


def translate_text_to_korean(value: str, timeout: int = 12) -> str:
    """Translate a short public headline or excerpt through MyMemory's free API."""
    clean_value = re.sub(r"\s+", " ", value).strip()
    if not clean_value or _has_hangul(clean_value):
        return clean_value
    response = requests.get(
        MYMEMORY_TRANSLATE_URL,
        params={
            "q": _limit_utf8(clean_value),
            "langpair": "en|ko",
            "mt": "1",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if str(body.get("responseStatus", "200")) != "200":
        raise ValueError(str(body.get("responseDetails") or "번역 API 오류"))
    translated = html.unescape(
        str(body.get("responseData", {}).get("translatedText") or "")
    )
    translated = re.sub(r"\s+", " ", translated).strip()
    if not _korean_text(translated) or translated.upper().startswith("MYMEMORY WARNING"):
        raise ValueError("한국어 번역 결과를 받지 못했습니다.")
    return translated


def translate_title_to_korean(title: str, timeout: int = 12) -> str:
    """Translate one public English headline through MyMemory's free GET API."""
    clean_title = re.sub(r"\s+", " ", title).strip()
    return translate_text_to_korean(
        _translation_source_title(clean_title), timeout=timeout
    )


def _summary_source(article: Article) -> str:
    release_summary = article.metadata.get("release_summary")
    if isinstance(release_summary, str) and release_summary:
        return _truncate(release_summary, 360)
    description = re.sub(r"\s+", " ", article.description).strip()
    if not description:
        return ""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", description)
        if len(sentence.strip()) >= 35
    ]
    if not sentences:
        return _truncate(description, 360)
    title_terms = {
        term
        for term in re.findall(r"[a-z0-9가-힣]{3,}", article.title.casefold())
        if term
        not in {
            "with",
            "from",
            "about",
            "this",
            "that",
            "game",
            "games",
            "gamescom",
            "post",
            "musings",
            "gossip",
            "dev",
        }
    }

    def sentence_score(sentence: str) -> float:
        lowered = sentence.casefold()
        score = sum(2 for term in title_terms if term in lowered)
        score += sum(
            1
            for term in (
                " ai ",
                "agent",
                "npc",
                "model",
                "developer",
                "release",
                "research",
                "tool",
                "gameplay",
                "pipeline",
                "governance",
                "studio",
                "code generation",
            )
            if term in f" {lowered} "
        )
        if any(
            marker in lowered
            for marker in ("hello all", "welcome to", "subscribe", "sign up")
        ):
            score -= 8
        return score

    best = max(sentences[:30], key=sentence_score)
    return _truncate(best, 360)


def fallback_insight(article: Article) -> str:
    if article.metadata.get("editorial_reason"):
        return str(article.metadata["editorial_reason"])
    source_text = f"{article.title} {article.description}".casefold()
    for terms, insight in INSIGHT_RULES:
        if any(term in source_text for term in terms):
            return insight
    return CATEGORY_INSIGHTS.get(article.category, CATEGORY_INSIGHTS["📰 기타"])


def fallback_items(
    articles: list[Article], translate_titles: bool = True, translation_timeout: int = 12
) -> tuple[list[DigestItem], str]:
    with translation_session():
        return _fallback_items(articles, translate_titles, translation_timeout)


def _fallback_items(
    articles: list[Article], translate_titles: bool, translation_timeout: int,
) -> tuple[list[DigestItem], str]:
    items = []
    for article in articles:
        if article.metadata.get("editorial_filter") == "geeknews":
            item = DigestItem(
                article=article,
                title_ko=_truncate(article.title, 180),
                summary_ko=geeknews_summary(article),
                insight_ko=geeknews_insight(article),
            )
            if _ready(item):
                items.append(item)
            else:
                _held(article)
            continue
        summary_source = _summary_source(article)
        summary = summary_source or "공개된 요약이 없어 제목과 원문을 함께 확인해야 합니다."
        translated_title = article.title
        needs_translation = not (_korean_text(translated_title) and _korean_text(summary))
        if needs_translation and (not translate_titles or _provider_failed("mymemory")):
            _held(article)
            continue
        if translate_titles and needs_translation:
            try:
                if not _korean_text(translated_title):
                    translated_title = translate_title_to_korean(
                        article.title, timeout=translation_timeout
                    )
                if not _korean_text(translated_title):
                    raise ValueError("제목 번역이 한국어가 아닙니다.")
                if summary_source and not _korean_text(summary):
                    summary = translate_text_to_korean(
                        summary_source, timeout=translation_timeout
                    )
                if not _korean_text(summary):
                    raise ValueError("요약 번역이 한국어가 아닙니다.")
            except Exception as exc:
                # Do not repeatedly wait on an unavailable service for every item.
                # Log exception type only; provider URLs may include credentials.
                _mark_provider_failed("mymemory")
                logger.warning("MyMemory 번역 실패 (%s): %s; 이번 회차 외부 번역 중단",
                               article.source_name, type(exc).__name__)
                _held(article)
                continue
        item = DigestItem(
            article=article,
            title_ko=_truncate(translated_title, 180),
            summary_ko=_truncate(summary, 200),
            insight_ko=fallback_insight(article),
        )
        if _ready(item):
            items.append(item)
        else:
            _held(article)
    return items, category_trend([item.article for item in items])


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def summarize_with_gemini(
    articles: list[Article],
    api_key: str,
    model: str,
    timeout: int = 45,
    translate_titles: bool = True,
    translation_timeout: int = 12,
) -> tuple[list[DigestItem], str]:
    if not api_key:
        return fallback_items(articles, translate_titles, translation_timeout)

    payload_articles = [
        {
            "id": index,
            "source": article.source_name,
            "category": article.category,
            "title": article.title,
            "description": _truncate(article.description, 1600),
            "perspective": article.perspective,
            "content_kind": article.metadata.get("content_kind", "news"),
        }
        for index, article in enumerate(articles)
    ]
    prompt = f"""당신은 게임 개발자를 위한 뉴스 편집자다.
아래 자료만 근거로 한국어 브리핑을 작성하라. 과장하거나 자료에 없는 기능·수치·출시 여부를 만들지 마라.
회사 블로그는 주장으로 표현하고 사실처럼 확대하지 마라.
제작 자료는 이전에 공개된 구현 방법·사례이므로 오늘 새로 출시된 것처럼 쓰지 마라.

각 기사에 대해:
- title_ko: 고유명사를 보존한 자연스러운 한국어 제목
- summary_ko: 무엇이 새로 나왔거나 밝혀졌는지 1~2문장, 130자 이내
- insight_ko: 이 기사를 왜 지금 읽어야 하는지 기사 고유 사실과 연결한 단정형 1문장, 110자 이내
  '확인할 가치가 있습니다', '주목할 만합니다', '원문을 확인하세요' 같은 범용 문구는 금지한다.
전체 trend_ko: 여러 기사에서 공통으로 보이는 흐름 1~2문장, 160자 이내

반드시 다음 JSON 형태만 반환하라:
{{"items":[{{"id":0,"title_ko":"","summary_ko":"","insight_ko":""}}],"trend_ko":""}}

기사:
{json.dumps(payload_articles, ensure_ascii=False)}"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(_strip_code_fence(text))
    returned = {int(item["id"]): item for item in parsed.get("items", [])}
    items: list[DigestItem] = []
    missing: list[Article] = []
    for index, article in enumerate(articles):
        item = returned.get(index, {})
        title = item.get("title_ko")
        summary = item.get("summary_ko")
        insight = item.get("insight_ko")
        if not (_korean_text(title) and _korean_text(summary)):
            missing.append(article)
            continue
        candidate = DigestItem(
            article=article,
            title_ko=_truncate(title, 180),
            summary_ko=_truncate(summary, 180),
            insight_ko=_truncate(insight if _korean_text(insight) else fallback_insight(article), 130),
        )
        if _ready(candidate):
            items.append(candidate)
        else:
            missing.append(article)
    # Incomplete/English Gemini fields must not fall back to untranslated English.
    fallback, _ = fallback_items(missing, translate_titles, translation_timeout)
    by_url = {item.article.url: item for item in [*items, *fallback]}
    items = [by_url[a.url] for a in articles if a.url in by_url]
    trend = parsed.get("trend_ko")
    trend = _truncate(trend if _korean_text(trend) else category_trend([item.article for item in items]), 190)
    return items, trend


def summarize(
    articles: list[Article],
    api_key: str = "",
    model: str = "gemini-2.5-flash",
    translate_titles: bool = True,
    translation_timeout: int = 12,
) -> tuple[list[DigestItem], str]:
    with translation_session():
        return _summarize(articles, api_key, model, translate_titles, translation_timeout)


def _summarize(
    articles: list[Article], api_key: str, model: str,
    translate_titles: bool, translation_timeout: int,
) -> tuple[list[DigestItem], str]:
    # 긱뉴스의 한국어 소개를 재번역하거나 Gemini로 불필요하게 다시 만들지 않는다.
    if any(a.metadata.get("editorial_filter") == "geeknews" for a in articles):
        others = [a for a in articles if a.metadata.get("editorial_filter") != "geeknews"]
        other_items, _ = summarize(others, api_key, model, translate_titles, translation_timeout) if others else ([], "")
        by_url = {item.article.url: item for item in other_items}
        geek_items, _ = fallback_items([a for a in articles if a.metadata.get("editorial_filter") == "geeknews"])
        by_url.update({item.article.url: item for item in geek_items})
        items = [by_url[a.url] for a in articles if a.url in by_url]
        return items, category_trend([item.article for item in items])
    if not api_key or _provider_failed("gemini"):
        return fallback_items(articles, translate_titles, translation_timeout)
    try:
        return summarize_with_gemini(
            articles,
            api_key,
            model,
            translate_titles=translate_titles,
            translation_timeout=translation_timeout,
        )
    except Exception as exc:
        _mark_provider_failed("gemini")
        logger.warning("Gemini 요약 실패 (%s), 한국어 번역 경로 시도", type(exc).__name__)
        return fallback_items(articles, translate_titles, translation_timeout)
