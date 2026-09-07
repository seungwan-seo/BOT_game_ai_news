"""Conservative, explainable selection of Korean GeekNews feed entries.

GeekNews is a useful community source, not a blanket game-AI relevance signal.
These rules only use the public feed title and excerpt; they do not infer that
code, benchmark results, or a working game integration exist without evidence.
"""

from __future__ import annotations

import html
import re

from .models import Article


def _matches(text: str, *terms: str) -> bool:
    """Match English words at ASCII boundaries, including Korean particles."""
    for term in terms:
        pattern = re.escape(term.casefold())
        if re.match(r"[a-z0-9]", term, re.I):
            pattern = r"(?<![a-z0-9])" + pattern
        if re.search(r"[a-z0-9]$", term, re.I):
            pattern += r"(?![a-z0-9])"
        if re.search(pattern, text.casefold()):
            return True
    return False


AI_TERMS = (
    "ai", "llm", "llms", "인공지능", "생성형", "기계학습", "머신러닝",
    "딥러닝", "강화학습", "reinforcement learning", "language model",
    "언어 모델", "언어모델", "에이전트", "agent", "agents",
    "claude", "codex", "chatgpt", "gpt", "gemini", "deepseek", "llama", "qwen",
    "github copilot", "stable diffusion",
    "midjourney", "이미지 생성 모델", "음성 합성 모델",
)
CODING_PRODUCTS = ("claude code", "codex", "cursor", "github copilot")
GAME_TERMS = (
    "게임", "game", "games", "gameplay", "unity", "unreal", "언리얼",
    "유니티", "godot", "고도 엔진", "npc", "playtesting", "플레이테스트",
)
CODING_TERMS = (
    "코딩", "코드 생성", "소프트웨어 개발", "개발 도구", "개발도구",
    "coding", "code generation", "programming", "개발 워크플로", "ide",
    "코드 리뷰", "code review",
)
PRACTICAL_TERMS = (
    "비교", "분석", "벤치마크", "benchmark", "evaluation", "실험", "평가",
    "성능", "비용", "지연", "latency", "가격", "사용법", "가이드", "설정",
    "구현", "튜토리얼", "tutorial", "사례", "워크플로", "workflow",
    "공개", "출시", "릴리스", "release", "sdk", "api", "플러그인",
    "오픈소스", "오픈 소스", "open source", "테스트", "지원", "도구",
    "만들", "제작", "자동화", "통합", "선택", "개발", "생성",
)
OFF_TOPIC_TITLE_TERMS = (
    "투자 유치", "투자유치", "시리즈 a", "시리즈 b", "기업가치", "기업 가치",
    "주가", "주식", "시가총액", "ipo", "상장", "주식시장", "증시",
    "회로기판", "회로 기판", "pcb", "철학", "의식", "sentience",
    "consciousness", "인류 멸망", "인류의 종말",
)


def evaluate_article(article: Article) -> bool:
    """Set a bounded editorial score only for relevant, actionable entries."""
    title = article.title.casefold()
    text = f"{article.title}\n{article.description}".casefold()
    for key in ("geeknews_reason", "geeknews_score", "geeknews_signals"):
        article.metadata.pop(key, None)
    article.relevance = 0

    coding_product = _matches(text, *CODING_PRODUCTS)
    has_ai = _matches(text, *AI_TERMS) or (
        coding_product and _matches(text, *CODING_TERMS, "개발", "비교", "도구", "프롬프트")
    )
    if not has_ai or _matches(title, *OFF_TOPIC_TITLE_TERMS):
        return False

    game = _matches(text, *GAME_TERMS)
    coding = coding_product or _matches(text, *CODING_TERMS)
    practical = _matches(text, *PRACTICAL_TERMS)
    compare = _matches(text, "비교", "벤치마크", "benchmark", "evaluation", "평가", "실험")
    measured = bool(re.search(r"\d[\d,.]*\s*(?:회|개|건|%|ms|초|달러|원|세션|저장소)", text))
    generation = _matches(text, "생성", "합성", "generation", "generative", "text-to-image", "text-to-3d", "tts")
    visual = _matches(text, "이미지", "3d", "텍스처", "에셋", "애니메이션", "image", "texture", "asset", "animation")
    voice = _matches(text, "음성", "tts", "speech", "voice")
    inference = _matches(text, "추론", "inference", "llm", "언어 모델", "언어모델", "모델 api")
    runtime = _matches(
        text, "비용", "지연시간", "지연 시간", "latency", "토큰 가격", "메모리",
        "온디바이스", "on-device", "양자화", "quantization", "추론 속도", "추론속도",
        "응답 속도", "응답속도", "inference speed", "tokens per second", "토큰/초",
    )

    if coding and practical:
        category = "🛠 개발 도구"
        reason = (
            "AI 코딩 도구의 비교 기준을 살펴보며 개발 작업에 맞는 선택지를 좁힐 수 있습니다."
            if compare or _matches(text, "선택") else
            "게임 코드 작업에도 쓰이는 AI 개발 도구의 사용 방식과 제약을 살펴볼 자료입니다."
        )
        topic = "AI 코딩 실무"
    elif generation and (visual or voice) and practical:
        category = "🌍 월드·콘텐츠 생성"
        reason = (
            "음성 제작에 쓸 생성 도구를 검토할 때 사용 조건과 결과물을 비교해 볼 자료입니다."
            if voice and not visual else
            "게임 에셋 제작에 쓸 생성 도구를 검토할 때 사용 조건과 결과물을 비교해 볼 자료입니다."
        )
        topic = "생성 도구"
    elif inference and runtime and practical:
        category = "🛠 개발 도구"
        reason = "AI 기능을 운영할 때 드는 추론 비용이나 응답 지연을 검토하는 데 참고할 자료입니다."
        topic = "추론 운영"
    elif game and practical:
        if _matches(text, "npc", "게임 캐릭터", "게임 에이전트", "game agent", "대화형 캐릭터"):
            category = "🤖 NPC·에이전트"
            reason = "게임 안에서 AI 캐릭터나 에이전트를 다루는 사례로, 소개된 기능과 적용 범위를 살펴볼 자료입니다."
        elif _matches(text, "플레이테스트", "playtesting", "qa", "자동 테스트"):
            category = "🧪 테스트·플레이어 모델"
            reason = "게임 테스트에 AI를 적용하는 방식을 다루며, 어떤 작업을 평가했는지 살펴볼 자료입니다."
        else:
            category = "🛠 개발 도구"
            reason = "게임 제작에 AI를 적용하는 사례로, 소개된 사용 방법과 적용 범위를 살펴볼 자료입니다."
        topic = "게임 AI 직접 관련"
    else:
        return False

    signals = [topic]
    score = 12 if game else 10
    if compare:
        score += 3
        signals.append("비교·평가 언급")
    if measured:
        score += 2
        signals.append("수치 근거 언급")
    if _matches(text, "튜토리얼", "tutorial", "사용법", "설정", "가이드", "사례"):
        score += 2
        signals.append("사용 방법·사례")
    article.category = category
    article.relevance = min(20, score)
    article.metadata.update(
        geeknews_score=article.relevance,
        geeknews_reason=reason,
        geeknews_signals=signals,
    )
    return True


def _clean_line(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"^[\s*#•·\-–>]+|^\d+[.)]\s+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, limit: int = 180) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def build_summary(article: Article) -> str:
    """Return a short source-grounded Korean excerpt without a translation API."""
    description = re.sub(r"<(?:br\s*/?|/?(?:p|li|ul|ol|h[1-6]))\b[^>]*>", "\n", article.description, flags=re.I)
    title = _clean_line(article.title).rstrip(".!?")
    candidates = []
    for raw_line in description.splitlines():
        line = _clean_line(raw_line)
        if not line or line.rstrip(".!?") == title:
            continue
        if len(line) < 18 or re.fullmatch(r"https?://\S+", line):
            continue
        if _matches(line, "댓글 보기", "댓글과 토론", "원문 보기", "구독하기", "로그인하세요"):
            continue
        # A complete lead is preferable to a later, context-dependent bullet.
        sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0]
        candidates.append(sentence)
    if candidates:
        return _truncate(candidates[0])
    return "공개된 설명이 짧아 자세한 내용은 긱뉴스 소개와 원문에서 확인할 수 있습니다."


def build_insight(article: Article) -> str:
    if "geeknews_reason" not in article.metadata:
        evaluate_article(article)
    return article.metadata.get(
        "geeknews_reason",
        "긱뉴스에 소개된 자료의 적용 범위와 근거를 확인해 주세요.",
    )
