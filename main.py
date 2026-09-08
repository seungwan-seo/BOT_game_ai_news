from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

from game_ai_news_bot.collectors import Collector
from game_ai_news_bot.config import env_settings, load_config
from game_ai_news_bot.digest import build_article_post
from game_ai_news_bot.feedback import (
    build_feedback_report,
    preference_adjustment,
    prune_feedback,
    register_deliveries,
)
from game_ai_news_bot.feedback_collection import FeedbackCollectionError, collect_feedback
from game_ai_news_bot.guide import build_channel_guide_post
from game_ai_news_bot.promotion import (
    build_promotion_post,
    mark_promotion_sent,
    promotion_is_due,
    select_promotion,
)
from game_ai_news_bot.ranking import rank_articles
from game_ai_news_bot.scheduling import planned_news_limit
from game_ai_news_bot.selection import select_enriched_articles
from game_ai_news_bot.state import (
    KST,
    delivered_today,
    delivered_for_source_today,
    load_state,
    mark_delivered,
    mark_seen,
    save_state,
)
from game_ai_news_bot.summarizer import summarize, translation_session
from game_ai_news_bot.telegram import TelegramSendError, send_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="게임 AI 뉴스를 선별해 텔레그램 브리핑으로 보냅니다.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="전송·상태 저장 없이 콘솔에 출력")
    parser.add_argument("--show-all", action="store_true", help="이미 본 기사도 후보에 포함")
    parser.add_argument(
        "--preview-send",
        action="store_true",
        help="이전 옵션의 안전한 별칭: 채널 전송 없이 콘솔 미리보기만 출력",
    )
    parser.add_argument(
        "--send-promo-now",
        action="store_true",
        help="다음 자매 채널 홍보를 즉시 보내고 홍보 주기를 갱신",
    )
    parser.add_argument(
        "--send-channel-guide",
        action="store_true",
        help="고정용 채널 안내 게시물을 상태 변경 없이 즉시 발송",
    )
    parser.add_argument("--bootstrap", action="store_true", help="현재 기사 전체를 읽음 처리하고 종료")
    parser.add_argument("--no-ai", action="store_true", help="Gemini 키가 있어도 규칙 기반 요약 사용")
    parser.add_argument("--limit", type=int, help="이번 실행의 최대 기사 수")
    parser.add_argument("--source", help="설정에 등록된 소스 ID로 수집 범위 제한")
    parser.add_argument("--article-url", help="피드에 존재하는 특정 기사 1건만 정상 발송")
    parser.add_argument("--no-promo", action="store_true", help="이번 회차 자매 채널 홍보 생략")
    parser.add_argument("--collect-feedback", action="store_true", help="반응만 수집·저장하고 종료 (발송 없음)")
    parser.add_argument("--feedback-report", action="store_true", help="저장된 반응 통계를 콘솔에 출력 (API 호출 없음)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")
    if args.collect_feedback or args.feedback_report:
        if (args.collect_feedback and args.feedback_report) or any((
            args.bootstrap, args.send_promo_now, args.send_channel_guide,
            args.article_url, args.preview_send,
        )):
            parser.error("반응 수집/조회는 다른 발송·기준점 옵션과 함께 사용할 수 없습니다.")
    if args.article_url and (not args.source or args.preview_send or args.show_all):
        parser.error("--article-url은 --source와 함께 사용하며 읽음 기록을 우회할 수 없습니다.")
    if args.article_url and (args.bootstrap or args.send_promo_now or args.send_channel_guide):
        parser.error("--article-url은 다른 발송/기준점 생성 옵션과 함께 사용할 수 없습니다.")
    if args.preview_send:
        if args.bootstrap:
            parser.error("미리보기에서 기준점을 변경할 수 없습니다.")
        args.dry_run = True
        args.show_all = True
        args.no_promo = True
    return args


def main() -> int:
    args = parse_args()
    # Windows 기본 CP949 콘솔에서도 이모지·한글 드라이런이 깨지지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # requests의 DEBUG 로그에는 토큰이 포함된 Telegram URL이 실릴 수 있다.
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    config = load_config(args.config)
    env = env_settings()
    digest_config = config.get("digest", {})
    translation_config = config.get("translation", {})
    promotion_config = config.get("promotion", {})
    feedback_config = config.get("feedback", {})
    state_path = Path(config["base_dir"]) / "state" / "news_state.json"
    state = load_state(state_path)
    now = datetime.now(timezone.utc)

    if args.feedback_report or (args.collect_feedback and args.dry_run):
        print(json.dumps(build_feedback_report(state, feedback_config, now), ensure_ascii=False, indent=2))
        return 0

    if args.collect_feedback:
        if not feedback_config.get("enabled", False):
            logging.error("반응 수집이 설정에서 비활성화되어 있습니다.")
            return 2
        try:
            collect_feedback(state, env["telegram_token"], feedback_config, now)
            save_state(state_path, state)
        except FeedbackCollectionError as exc:
            logging.error("%s", exc)
            return 2
        print(json.dumps(build_feedback_report(state, feedback_config, now), ensure_ascii=False, indent=2))
        return 0

    if args.send_channel_guide:
        guide_config = config.get("channel_guide", {})
        guide_message = build_channel_guide_post(guide_config)
        turtle_url = str(guide_config.get("turtle_url", "")).strip()
        image_url = str(guide_config.get("image_url", "")).strip()
        is_dry = args.dry_run or not (
            env["telegram_token"] and env["telegram_chat_ids"]
        )
        if is_dry:
            print("[CHANNEL GUIDE DRY-RUN]\n" + guide_message)
            print(f"[IMAGE] {image_url or '(대표 이미지 없음)'}")
            print(f"[BUTTON] 🐢 Steam에서 거북이 게임 보기 → {turtle_url}")
            return 0
        send_message(
            env["telegram_token"],
            env["telegram_chat_ids"],
            guide_message,
            button_text="🐢 Steam에서 거북이 게임 보기",
            button_url=turtle_url,
            image_url=image_url,
            preview_url=turtle_url,
            silent=True,
        )
        logging.info("고정용 채널 안내 게시물 발송 완료")
        return 0

    if args.send_promo_now:
        promotion = select_promotion(state, promotion_config)
        if promotion is None:
            logging.error("활성화된 자매 채널 홍보 설정이 없습니다.")
            return 2
        promotion_message = build_promotion_post(promotion)
        is_dry = args.dry_run or not (env["telegram_token"] and env["telegram_chat_ids"])
        if is_dry:
            print("[PROMOTION DRY-RUN]\n" + promotion_message)
            print(f'[BUTTON] 🎁 Steam 할인 채널 방문하기 → {promotion["url"]}')
            return 0
        send_message(
            env["telegram_token"],
            env["telegram_chat_ids"],
            promotion_message,
            button_text="🎁 Steam 할인 채널 방문하기",
            button_url=str(promotion["url"]),
        )
        mark_promotion_sent(state, promotion_config)
        save_state(state_path, state)
        logging.info("자매 채널 홍보 발송 완료: %s", promotion.get("name", ""))
        return 0

    # 뉴스가 없어도 반응은 수집한다. 미리보기·기준점 생성·광고/공지에는 API 호출을 덧붙이지 않는다.
    if feedback_config.get("enabled", False) and not (args.dry_run or args.bootstrap) and env["telegram_token"]:
        try:
            collect_feedback(state, env["telegram_token"], feedback_config, now)
            save_state(state_path, state)
        except FeedbackCollectionError as exc:
            logging.warning("%s; 이번 뉴스 발송은 계속합니다.", exc)

    sources = config["sources"]
    if args.source:
        sources = [source for source in sources if source["id"] == args.source]
        if not sources:
            logging.error("등록되지 않은 소스입니다: %s", args.source)
            return 2

    per_run_limit = int(
        digest_config.get("max_items_per_run", digest_config.get("max_items", 1))
    )
    limit = 1 if args.article_url else (args.limit or per_run_limit)
    automatic_pacing = not any((
        args.bootstrap, args.article_url, args.source, args.show_all, args.preview_send,
    )) and args.limit is None
    is_live_delivery = not args.dry_run and bool(
        env["telegram_token"] and env["telegram_chat_ids"]
    )
    daily_limit = max(1, int(digest_config.get("daily_post_limit", 10)))
    if automatic_pacing:
        try:
            limit = planned_news_limit(digest_config, state, now)
        except ValueError as exc:
            logging.error("발행 목표 설정 오류: %s", exc)
            return 2
        logging.info(
            "발행 계획 (KST %s): 오늘 %d건 / 하루 상한 %d건, 이번 회차 최대 %d건",
            now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            delivered_today(state, now), daily_limit, limit,
        )
    if is_live_delivery and not args.bootstrap:
        limit = min(limit, max(0, daily_limit - delivered_today(state, now)))
    if limit <= 0 and not args.bootstrap:
        logging.info("현재 누적 목표·일일 한도를 채웠거나 발행 시간 밖입니다.")
        return 2 if args.article_url else 0

    collector = Collector(
        config.get("http", {}),
        description_limit=int(digest_config.get("max_description_chars", 900)),
    )
    articles, errors = collector.collect_all(sources)
    if not articles:
        logging.error("모든 소스에서 수집하지 못했습니다: %s", "; ".join(errors))
        return 2

    ranked = rank_articles(
        articles, config, now,
        fresh_only=not (args.preview_send or args.bootstrap),
    )
    if feedback_config.get("enabled", False) and feedback_config.get("apply_to_ranking", False):
        report = build_feedback_report(state, feedback_config, now)
        for article in ranked:
            adjustment = preference_adjustment(article, report, feedback_config)
            article.score += adjustment
            article.metadata["feedback_adjustment"] = adjustment
        # 품질·관련성 필터를 통과한 기사에만 보조 점수를 더한다.
        ranked.sort(key=lambda article: article.score, reverse=True)
    # 기간 검사는 순위 계산·중복 제거 전에 적용한다. 레이아웃 전용
    # 미리보기와 기준점 생성은 기존처럼 전체 관련 기사를 사용한다.
    fresh = ranked
    blocked = set()
    if not (args.show_all or args.preview_send):
        blocked = set(state["seen"]) | set(state.get("pending_delivery_review", {}))
        fresh = [item for item in fresh if not item.identity_urls.intersection(blocked)]
    if args.article_url:
        fresh = [item for item in fresh if item.url == args.article_url]

    collected_counts = Counter(item.source_id for item in articles)
    ranked_counts = Counter(item.source_id for item in ranked)
    fresh_counts = Counter(item.source_id for item in fresh)
    for source in sources:
        if source.get("enabled", True):
            logging.info(
                "출처별 후보 %s: 수집 %d / 선별 %d / 기간 내 미발송 %d",
                source["id"], collected_counts[source["id"]],
                ranked_counts[source["id"]], fresh_counts[source["id"]],
            )

    if args.bootstrap:
        if args.dry_run:
            print(f"[DRY-RUN] 기준점 대상 {len(ranked)}건, 상태 변경 없음")
            return 0
        mark_seen(state, [item.url for item in ranked], now)
        save_state(state_path, state)
        print(f"기준점 생성 완료: {len(ranked)}건을 읽음 처리했습니다.")
        return 0

    source_limits = {
        source["id"]: max(
            0,
            int(source["max_items_per_day"])
            - delivered_for_source_today(state, source["id"], now),
        )
        for source in sources
        if "max_items_per_day" in source
    } if not args.preview_send else {}
    api_key = "" if args.no_ai else env["gemini_api_key"]
    items = []
    attempted_urls = set()
    enriched_by_url = {}
    rank_order = {article.url: index for index, article in enumerate(fresh)}

    def enrich_once(article):
        if article.url not in enriched_by_url:
            enriched_by_url[article.url] = collector.enrich_article(article)
        return enriched_by_url[article.url]

    with translation_session():
        while len(items) < limit:
            completed_urls = {item.article.url for item in items}
            # 성공 기사를 함께 선별해 보충 배치에도 출처 한도와 중복 검사를 적용한다.
            selected = select_enriched_articles(
                [item.article for item in items]
                + [article for article in fresh if article.url not in attempted_urls],
                limit=limit,
                max_per_source=int(digest_config.get("max_items_per_source", 2)),
                source_limits=source_limits,
                blocked_urls=blocked,
                enrich_article=enrich_once,
            )
            batch = [article for article in selected if article.url not in completed_urls]
            if not batch:
                break
            # 번역 실패는 이번 실행에서만 제외하고 다음 예약 회차의 후보로 남긴다.
            attempted_urls.update(article.url for article in batch)
            translated, _trend = summarize(
                batch,
                api_key=api_key,
                model=env["gemini_model"],
                translate_titles=bool(translation_config.get("enabled", True)),
                translation_timeout=int(translation_config.get("timeout_seconds", 12)),
            )
            by_url = {item.article.url: item for item in translated}
            items.extend(by_url[article.url] for article in batch if article.url in by_url)
    items.sort(key=lambda item: rank_order[item.article.url])
    logging.info(
        "후보 현황: 수집 %d건 → 관련성·중복 선별 %d건 → 최신·미발송 %d건 → 한국어 준비 %d/%d건 (수집 실패 %d곳)",
        len(articles), len(ranked), len(fresh), len(items), limit, len(errors),
    )
    if automatic_pacing and len(items) < limit:
        logging.warning(
            "이번 회차 목표보다 %d건 부족합니다. 한국어 완성·최신성·관련성·출처 상한·중복 기준을 유지하고 다음 회차에서 보충합니다.",
            limit - len(items),
        )
    if not items:
        logging.info("한국어 게시물로 준비된 새 게임 AI 소식이 없습니다.")
        return 2 if args.article_url else 0
    messages = [
        build_article_post(
            item,
            title=digest_config.get("title", "게임 AI 뉴스"),
            timezone_name=digest_config.get("timezone", "Asia/Seoul"),
        )
        for item in items
    ]
    promotion = None
    promotion_message = ""
    if not (args.preview_send or args.no_promo or args.article_url) and promotion_is_due(state, promotion_config, now):
        promotion = select_promotion(state, promotion_config)
        if promotion is not None:
            promotion_message = build_promotion_post(promotion)

    is_dry = args.dry_run or not (env["telegram_token"] and env["telegram_chat_ids"])
    if is_dry:
        for index, (item, message) in enumerate(
            zip(items, messages, strict=True), 1
        ):
            print(f"[DRY-RUN {index}/{len(messages)}]\n{message}\n")
            print(f"[IMAGE] {item.article.image_url or '(대표 이미지 없음)'}")
            print(f"[BUTTON] {item.article.metadata.get('button_text', '🔗 원문 기사 바로 보기')} → {item.article.url}\n")
        if promotion_message:
            print("[PROMOTION DRY-RUN]\n" + promotion_message)
            print(f'[BUTTON] 🎁 Steam 할인 채널 방문하기 → {promotion["url"]}')
        if errors:
            print("\n[수집 실패 소스]\n- " + "\n- ".join(errors))
        return 0

    sent_count = 0
    for item, message in zip(items, messages, strict=True):
        # 수집·번역이 길어지거나 일부 게시 중 시간이 경계를 넘었을 수 있다.
        if automatic_pacing and planned_news_limit(
            digest_config, state, datetime.now(timezone.utc)
        ) <= 0:
            logging.info("실제 발송 시각의 누적 목표·한도·운영 시간을 다시 확인하여 이번 회차를 종료합니다.")
            break

        def record_success(receipts):
            delivery_now = datetime.now(timezone.utc)
            # 중간 게시에서 실패해도 이미 성공한 기사가 다음 실행에 중복되지 않게 즉시 기록한다.
            mark_delivered(
                state, [item.article.url], delivery_now,
                source_id=item.article.source_id,
                aliases=list(item.article.identity_urls - {item.article.url}),
            )
            if feedback_config.get("enabled", False):
                if not isinstance(state.get("feedback"), dict):
                    state["feedback"] = {}
                state.setdefault("feedback", {})["window_hours"] = feedback_config.get("window_hours", 48)
                register_deliveries(state, item.article, receipts, delivery_now)
                prune_feedback(state, delivery_now)
            save_state(state_path, state)

        try:
            receipts = send_message(
                env["telegram_token"],
                env["telegram_chat_ids"],
                message,
                button_text=item.article.metadata.get("button_text", "🔗 원문 기사 바로 보기"),
                button_url=item.article.url,
                image_url=item.article.image_url,
                preview_url=item.article.url,
                silent=bool(args.article_url),
            )
        except TelegramSendError as exc:
            if exc.receipts:
                record_success(exc.receipts)
            if exc.delivery_uncertain:
                # API 응답이 유실됐으면 자동 재발송하지 않고 운영자 확인을 기다린다.
                pending = state.setdefault("pending_delivery_review", {})
                for url in item.article.identity_urls:
                    pending[url] = now.isoformat()
                save_state(state_path, state)
            logging.error("%s", exc)
            return 2
        record_success(receipts)
        sent_count += 1

    if not args.preview_send:
        # 선택하지 않은 좋은 후보는 읽음 처리하지 않고 다음 예약 회차로 넘긴다.
        if promotion is not None and sent_count:
            send_message(
                env["telegram_token"],
                env["telegram_chat_ids"],
                promotion_message,
                button_text="🎁 Steam 할인 채널 방문하기",
                button_url=str(promotion["url"]),
            )
            mark_promotion_sent(state, promotion_config, now)
            save_state(state_path, state)
    logging.info(
        "%s %d건 발송 완료",
        "미리보기 게시물" if args.preview_send else "뉴스 게시물",
        sent_count,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
