from __future__ import annotations

import html
import re
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import DigestItem


TELEGRAM_SAFE_LIMIT = 3900
TELEGRAM_CAPTION_SAFE_LIMIT = 1000

PERSPECTIVE_LABELS = {
    "independent": "독립 분석",
    "journalism": "전문 보도",
    "research": "연구 원문",
    "vendor": "공식 발표 · 업체 관점",
    "community": "한국어 큐레이션",
}


def _esc(value: str) -> str:
    return html.escape(str(value), quote=False)


def build_article_post(
    item: DigestItem, title: str, timezone_name: str = "Asia/Seoul"
) -> str:
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # 일부 최소 Windows/Python 환경에는 IANA tzdata가 없다. KST는 DST가 없어 고정 오프셋이 안전하다.
        if timezone_name != "Asia/Seoul":
            raise
        local_timezone = timezone(timedelta(hours=9), name="KST")
    article = item.article
    perspective = PERSPECTIVE_LABELS.get(article.perspective, "출처")
    article_url = html.escape(article.url, quote=True)
    content_label = "제작 자료" if article.metadata.get("content_kind") == "resource" else "뉴스"
    published_label = (
        f"원문 공개 {article.published_at.astimezone(local_timezone):%Y-%m-%d} {article.published_at.astimezone(local_timezone):%Z}"
        if article.published_at is not None else "원문 공개일 미확인"
    )
    original_title = ""
    if (
        item.title_ko.casefold() != article.title.casefold()
        and not re.search(r"[가-힣]", article.title)
    ):
        original_title = f"\n<i>EN · {_esc(article.title)}</i>"
    message = (
        f"<b>🎮 {_esc(title)}</b>\n"
        f"<code>{content_label} · {published_label}</code>\n\n"
        f"<b>{_esc(article.category)}</b>\n"
        f'<b><a href="{article_url}">🔗 {_esc(item.title_ko)}</a></b>'
        f"{original_title}\n\n"
        f"📝 <b>한줄 요약</b>\n{_esc(item.summary_ko)}\n\n"
        f"🎯 <b>왜 봐야 하나</b>\n{_esc(item.insight_ko)}\n\n"
        f"<i>출처 · {_esc(article.source_name)} · {perspective}</i>"
    )
    if len(message) > TELEGRAM_SAFE_LIMIT:
        raise ValueError("기사 게시물이 Telegram 안전 길이를 초과했습니다.")
    visible_text = html.unescape(re.sub(r"<[^>]+>", "", message))
    if len(visible_text) > TELEGRAM_CAPTION_SAFE_LIMIT:
        raise ValueError("기사 게시물이 Telegram 사진 캡션 안전 길이를 초과했습니다.")
    return message
