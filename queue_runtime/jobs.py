"""Enqueue / wait helpers for Generate jobs."""

from __future__ import annotations

from typing import Any

from queue_runtime import (
    JOB_TTL_SEC,
    JOB_WAIT_SEC,
    QUEUE_INBOUND,
    dumps,
    get_redis,
    job_key,
    loads,
    new_job_id,
    result_key,
)


def enqueue_inbound(payload: dict[str, Any]) -> str:
    job_id = new_job_id()
    r = get_redis()
    job = {
        "id": job_id,
        "status": "queued",
        **payload,
    }
    pipe = r.pipeline()
    pipe.set(job_key(job_id), dumps(job), ex=JOB_TTL_SEC)
    pipe.lpush(QUEUE_INBOUND, dumps({"job_id": job_id}))
    pipe.execute()
    return job_id


def set_job(job_id: str, **fields: Any) -> dict[str, Any]:
    r = get_redis()
    job = loads(r.get(job_key(job_id))) or {"id": job_id}
    job.update(fields)
    r.set(job_key(job_id), dumps(job), ex=JOB_TTL_SEC)
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    return loads(get_redis().get(job_key(job_id)))


def publish_result(job_id: str, result: dict[str, Any]) -> None:
    r = get_redis()
    set_job(job_id, status=result.get("status") or ("succeeded" if result.get("ok") else "failed"))
    r.lpush(result_key(job_id), dumps(result))
    r.expire(result_key(job_id), JOB_TTL_SEC)


def wait_for_result(job_id: str, timeout: int | None = None) -> dict[str, Any]:
    timeout = JOB_WAIT_SEC if timeout is None else timeout
    r = get_redis()
    item = r.brpop(result_key(job_id), timeout=timeout)
    if not item:
        return {"ok": False, "error": "timeout", "status": 504, "detail": "job wait timeout"}
    _key, raw = item
    data = loads(raw)
    if not isinstance(data, dict):
        return {"ok": False, "error": "bad_result", "status": 502}
    return data
