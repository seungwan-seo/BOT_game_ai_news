from __future__ import annotations

import re
from datetime import datetime, timezone

from game_ai_news_bot.state import KST, delivered_today


def _integer(value: object, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range")
    return value


def _morning_schedule(digest_config: dict) -> tuple[int, int, int, list[tuple[int, int]]] | None:
    morning = digest_config.get("morning_target", {})
    if not isinstance(morning, dict):
        raise ValueError("digest.morning_target must be a mapping")
    enabled = morning.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("digest.morning_target.enabled must be a boolean")
    if not enabled:
        return None

    count = _integer(morning.get("count", 10), "morning_target.count", minimum=1)
    deadline = 60 * _integer(
        morning.get("deadline_hour", 12), "morning_target.deadline_hour", maximum=23
    )
    end = 60 * _integer(morning.get("end_hour", 22), "morning_target.end_hour", maximum=24)
    if deadline >= end:
        raise ValueError("morning_target.deadline_hour must precede end_hour")
    raw_milestones = morning.get("milestones", [
        {"time": "07:00", "count": count // 3},
        {"time": "08:30", "count": 2 * count // 3},
        {"time": "10:00", "count": count},
    ])
    if not isinstance(raw_milestones, list) or not raw_milestones:
        raise ValueError("morning_target.milestones must be a non-empty list")
    milestones: list[tuple[int, int]] = []
    for item in raw_milestones:
        if not isinstance(item, dict):
            raise ValueError("Each morning_target milestone must be a mapping")
        clock = item.get("time")
        if not isinstance(clock, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
            raise ValueError("Each morning_target milestone time must use HH:MM (KST)")
        hour, minute = (int(part) for part in clock.split(":"))
        minute_of_day = hour * 60 + minute
        target = _integer(item.get("count"), "milestone.count", maximum=count)
        if minute_of_day >= deadline:
            raise ValueError("All morning_target milestones must precede deadline_hour")
        if milestones and minute_of_day <= milestones[-1][0]:
            raise ValueError("morning_target milestone times must increase strictly")
        if milestones and target < milestones[-1][1]:
            raise ValueError("morning_target milestone counts must not decrease")
        milestones.append((minute_of_day, target))
    if milestones[-1][1] != count:
        raise ValueError("The final morning_target milestone count must equal count")
    return count, deadline, end, milestones


def validate_morning_target(digest_config: dict) -> None:
    """Reject an invalid enabled morning schedule without reading or changing state."""
    _morning_schedule(digest_config)


def planned_news_limit(digest_config: dict, state: dict, now: datetime | None = None) -> int:
    """Return the outstanding KST news quota for this run, capped by the daily limit.

    Milestone counts are cumulative delivered-article targets, not batch sizes.
    At and after the deadline, the ordinary per-run limit resumes; a missed
    morning target can still be recovered before the configured end hour.
    Without enabled morning_target settings, the legacy per-run policy applies.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("planned_news_limit requires a timezone-aware datetime")
    schedule = _morning_schedule(digest_config)
    per_run = max(0, int(digest_config.get("max_items_per_run", digest_config.get("max_items", 1))))
    daily_limit = max(1, int(digest_config.get("daily_post_limit", 10)))
    delivered = delivered_today(state, now)
    remaining = max(0, daily_limit - delivered)
    if schedule is None:
        return min(per_run, remaining)

    count, deadline, end, milestones = schedule
    local_now = now.astimezone(KST)
    minute_of_day = local_now.hour * 60 + local_now.minute
    if minute_of_day < milestones[0][0] or minute_of_day >= end:
        return 0
    if minute_of_day >= deadline:
        return min(remaining, max(per_run, count - delivered))

    target = 0
    for milestone_time, milestone_count in milestones:
        if minute_of_day < milestone_time:
            break
        target = milestone_count
    return min(remaining, max(0, target - delivered))
