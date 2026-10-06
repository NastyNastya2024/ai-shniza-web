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
    """Publish worker result for waiters and for async pollers.

    Stores the full payload on the job record (so GET can poll without BRPOP)
    and also pushes to the result list (legacy sync wait_for_result).
    """
    r = get_redis()
    status = result.get("status") or ("succeeded" if result.get("ok") else "failed")
    # Keep job metadata + public result fields for /api/generate/jobs/:id
    public_fields = {
        k: v
        for k, v in result.items()
        if k
        in {
            "ok",
            "kind",
            "urls",
            "reply",
            "error",
            "detail",
            "model",
            "provider",
            "upstream_model",
            "replicate_model",
            "fal_model",
            "prediction_id",
            "job_id",
        }
    }
    set_job(job_id, status=status, result=public_fields, **public_fields)
    r.lpush(result_key(job_id), dumps(result))
    r.expire(result_key(job_id), JOB_TTL_SEC)


def peek_result(job_id: str) -> dict[str, Any] | None:
    """Non-destructive read of the latest published result (if any)."""
    raw = get_redis().lindex(result_key(job_id), 0)
    data = loads(raw)
    return data if isinstance(data, dict) else None


def generate_job_public(job_id: str) -> dict[str, Any] | None:
    """Normalized status payload for async generate polling."""
    job = get_job(job_id)
    if not job:
        return None
    status = str(job.get("status") or "queued")
    out: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "model": job.get("model") or job.get("model_id"),
        "kind": job.get("kind"),
        "provider": job.get("provider"),
    }
    if status in {"succeeded", "failed", "error"}:
        result = job.get("result") if isinstance(job.get("result"), dict) else None
        if not result:
            result = peek_result(job_id)
        if isinstance(result, dict):
            for key in (
                "ok",
                "kind",
                "urls",
                "reply",
                "error",
                "detail",
                "upstream_model",
                "replicate_model",
                "fal_model",
                "prediction_id",
            ):
                if key in result and key not in out:
                    out[key] = result[key]
            if "kind" in result:
                out["kind"] = result["kind"]
            if result.get("ok") is False and status == "succeeded":
                out["status"] = "failed"
        if status in {"failed", "error"}:
            out.setdefault("ok", False)
            out.setdefault("error", job.get("error") or "failed")
            if job.get("detail"):
                out.setdefault("detail", job.get("detail"))
        elif status == "succeeded":
            out.setdefault("ok", True)
    return out


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
