"""Redis keys and shared constants for Generate queues."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import redis

CHANNELS = ("replicate", "fal", "omniroute")
QUEUE_INBOUND = "ai_shniza:queue:inbound"
QUEUE_BY_CHANNEL = {
    "replicate": "ai_shniza:queue:replicate",
    "fal": "ai_shniza:queue:fal",
    "omniroute": "ai_shniza:queue:omniroute",
}
HEALTH_KEY = "ai_shniza:health:{channel}"
JOB_KEY = "ai_shniza:job:{job_id}"
RESULT_KEY = "ai_shniza:result:{job_id}"

# Probe every 30s: fast enough to hide a dead channel from UI,
# slow enough not to burn provider rate limits.
HEALTH_INTERVAL_SEC = int(os.getenv("HEALTH_INTERVAL_SEC", "30"))
# Two consecutive probe failures → channel down (avoid flap on one blip).
HEALTH_FAIL_THRESHOLD = int(os.getenv("HEALTH_FAIL_THRESHOLD", "2"))
JOB_WAIT_SEC = int(os.getenv("JOB_WAIT_SEC", "360"))
JOB_TTL_SEC = int(os.getenv("JOB_TTL_SEC", "3600"))


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(redis_url(), decode_responses=True)


def new_job_id() -> str:
    return uuid.uuid4().hex


def health_key(channel: str) -> str:
    return HEALTH_KEY.format(channel=channel)


def job_key(job_id: str) -> str:
    return JOB_KEY.format(job_id=job_id)


def result_key(job_id: str) -> str:
    return RESULT_KEY.format(job_id=job_id)


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)
