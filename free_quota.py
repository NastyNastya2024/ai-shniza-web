"""Free video quota (MSK day) + Redis prioritized free_queue."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

MSK = timezone(timedelta(hours=3))

FREE_QUEUE = "queue:free_video"
FREE_DISPATCH_KEY = "free_video:last_dispatch"
FREE_PAUSE_KEY = "free_video:pause_until"
FREE_ERR_KEY = "free_video:errors"


def msk_day_key(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(MSK)
    return now.strftime("%Y-%m-%d")


def daily_cap(base: int = 1, bonus: int = 0) -> int:
    return min(3, base + max(0, bonus))


def get_quota(db, FreeQuota, user_id: int):
    day = msk_day_key()
    row = FreeQuota.query.filter_by(user_id=user_id, day_key=day).first()
    if not row:
        # carry lifetime_success from latest row if any
        prev = (
            FreeQuota.query.filter_by(user_id=user_id)
            .order_by(FreeQuota.day_key.desc())
            .first()
        )
        row = FreeQuota(
            user_id=user_id,
            day_key=day,
            used=0,
            bonus=0,
            publish_bonus_used=False,
            lifetime_success=int(prev.lifetime_success) if prev else 0,
        )
        db.session.add(row)
        db.session.commit()
    return row


def free_left(row) -> int:
    return max(0, daily_cap(1, int(row.bonus or 0)) - int(row.used or 0))


def priority_score(row, waiting_sec: float = 0) -> int:
    score = 0
    if int(row.lifetime_success or 0) == 0:
        score += 100
    if int(row.used or 0) == 0:
        score += 50
    if int(row.bonus or 0) > 0:
        score += 10
    # publish bonus flag implies recent publish activity for today
    if row.publish_bonus_used:
        score += 10
    score += int(waiting_sec // 600)
    if int(row.used or 0) >= 2:
        score -= 30
    return score


def enqueue_free(redis_client, payload: dict[str, Any], score: int) -> None:
    # higher score first → use neg score in sorted set
    redis_client.zadd(FREE_QUEUE, {__import__("json").dumps(payload, ensure_ascii=False): -score})


def pop_free(redis_client) -> Optional[dict[str, Any]]:
    """Pop highest-priority free job (lowest zset score = highest priority)."""
    try:
        items = redis_client.zpopmin(FREE_QUEUE, count=1)
    except Exception:
        # Redis < 5 fallback
        try:
            items = redis_client.zrange(FREE_QUEUE, 0, 0, withscores=True)
            if not items:
                return None
            raw = items[0][0]
            redis_client.zrem(FREE_QUEUE, raw)
            items = [(raw, items[0][1])]
        except Exception:
            return None
    if not items:
        return None
    raw = items[0][0] if isinstance(items[0], (list, tuple)) else items[0]
    try:
        return __import__("json").loads(raw)
    except Exception:
        return None


def queue_position(redis_client, job_id: str) -> int:
    """1-based position in free queue, or 0 if not found."""
    try:
        members = redis_client.zrange(FREE_QUEUE, 0, -1)
        for i, raw in enumerate(members or []):
            try:
                data = __import__("json").loads(raw)
            except Exception:
                continue
            if str(data.get("job_id")) == str(job_id):
                return i + 1
    except Exception:
        return 0
    return 0


def queue_len(redis_client) -> int:
    try:
        return int(redis_client.zcard(FREE_QUEUE) or 0)
    except Exception:
        return 0


def capacity_24h() -> int:
    # 6/hour * 24
    return 6 * 24


def can_dispatch(redis_client) -> bool:
    now = time.time()
    try:
        pause = float(redis_client.get(FREE_PAUSE_KEY) or 0)
        if pause > now:
            return False
        last = float(redis_client.get(FREE_DISPATCH_KEY) or 0)
        if now - last < 600:  # 1 per 10 minutes
            return False
        return True
    except Exception:
        return False


def mark_dispatched(redis_client) -> None:
    redis_client.set(FREE_DISPATCH_KEY, str(time.time()))


def record_error(redis_client) -> None:
    n = int(redis_client.incr(FREE_ERR_KEY) or 0)
    redis_client.expire(FREE_ERR_KEY, 3600)
    if n >= 3:
        redis_client.set(FREE_PAUSE_KEY, str(time.time() + 1800))
        redis_client.delete(FREE_ERR_KEY)


def clear_errors(redis_client) -> None:
    redis_client.delete(FREE_ERR_KEY)


def consume_success(db, row) -> None:
    row.used = int(row.used or 0) + 1
    row.lifetime_success = int(row.lifetime_success or 0) + 1
    db.session.commit()


def grant_publish_bonus(db, row) -> bool:
    if row.publish_bonus_used:
        return False
    if free_left(row) <= 0 and int(row.bonus or 0) >= 2:
        return False
    row.bonus = int(row.bonus or 0) + 1
    row.publish_bonus_used = True
    db.session.commit()
    return True
