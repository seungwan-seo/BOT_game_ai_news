from __future__ import annotations

import html


def build_channel_guide_post(config: dict) -> str:
    turtle_url = html.escape(
        str(config.get("turtle_url", "")).strip(), quote=True
    )
    if not turtle_url.startswith("https://store.steampowered.com/"):
        raise ValueError("채널 안내의 Turtle Game URL이 올바르지 않습니다.")

    return (
        "<b>🎮 게임 AI 개발 뉴스 안내</b>\n\n"
        "게임 개발에 직접 활용할 수 있는 AI·NPC·에이전트·생성 기술 소식을 "
        "한국어로 정리합니다.\n"
        "하루 최대 10개, 아침부터 저녁까지 간격을 두고 발행합니다.\n\n"
        "<b>🐢 운영자가 만든 Steam 게임</b>\n"
        f'<b><a href="{turtle_url}">거북이 게임</a></b>\n'
        "어릴 때 하던 물속 링 끼우기 장난감을 바람과 물리 기반 PC 게임으로 만들었습니다.\n"
        "먹이를 보내 거북이를 키우고, 링 모드에서는 물살로 링을 기둥에 끼워보세요."
    )
