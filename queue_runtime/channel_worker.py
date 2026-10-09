"""Channel workers: consume per-provider queues and call upstream APIs."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

# Ensure project root on path when run as script
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auth import load_env  # noqa: E402

load_env(_ROOT)

from queue_runtime import (  # noqa: E402
    PROCESSING_BY_CHANNEL,
    QUEUE_BY_CHANNEL,
    WORKER_SHUTDOWN_GRACE_SEC,
    get_redis,
    inflight_key,
    loads,
    worker_concurrency,
)
from queue_runtime.health import is_channel_healthy, write_health  # noqa: E402
from queue_runtime.jobs import TERMINAL_STATUSES, get_job, publish_result, set_job  # noqa: E402

_running = True
_inflight_lock = threading.Lock()
_active_inflight = 0


def _stop(*_args) -> None:
    global _running
    _running = False


def _wait_seconds(model_id: str, kind: str) -> int:
    try:
        import server as srv

        spec = srv.INTEGRATED_MODELS.get(model_id) or {}
        ws = spec.get("wait_sec")
        if isinstance(ws, (int, float)) and ws > 0:
            return int(ws)
    except Exception:  # noqa: BLE001
        pass
    long_ids = {
        "happy-horse-1-1-t2v-fal",
        "gemini-omni-flash-fal",
        "grok-imagine-video-1-5",
        "grok-imagine-video-1-5-i2v-fal",
        "seedance-2-0-t2v-fal",
        "kling-o3-standard-i2v-fal",
        "minimax-h3-ref-to-video-fal",
        "wan-3-0",
        "wan-3-0-t2v-fal",
        "wan-3-0-i2v-fal",
        "seedance-2-5",
        "seedance-2-5-hf",
        "kling-v2-5-turbo-pro-hf",
        "kling-v3-0-hf",
        "veo-3-1-hf",
        "ltx-2-3-t2v-fal",
        "ltx-2-3-t2v-fast-fal",
        "ltx-2-3-i2v-fal",
        "ltx-2-3-i2v-fast-fal",
        "ltx-2-3-a2v-fal",
        "pixverse-v6-t2v-fal",
        "pixverse-v6-i2v-fal",
        "minimax-music-2-5",
        "dreamactor-m2",
        "seedance-2-5-t2v-fal",
        "seedance-2-5-ref2v-fal",
        "veo-3-1-t2v-fal",
        "veo-3-1-i2v-fal",
        "veo-3-1-fast-t2v-fal",
        "veo-3-1-fast-i2v-fal",
        "kling-v2-5-turbo-pro-t2v-fal",
        "kling-v2-5-turbo-pro-i2v-fal",
        "hailuo-02-t2v-fal",
        "hailuo-02-i2v-fal",
    }
    if model_id in long_ids:
        return 300
    if kind == "video" or model_id in {
        "elevenlabs-music",
        "lyria-2",
        "minimax-music-01",
        "ace-step",
        "flux-music",
    }:
        return 180
    return 120


def _format_success(job: dict[str, Any], prediction: dict[str, Any], provider: str) -> dict[str, Any]:
    # Import late to avoid circular import at module load of server.
    import server as srv

    kind = job["kind"]
    model_id = job["model_id"]
    upstream_model = job["upstream_model"]
    if provider == "fal":
        outputs = srv._fal_extract_outputs(prediction, kind)
    elif provider == "higgsfield":
        outputs = srv._higgsfield_extract_outputs(prediction, kind)
    else:
        outputs = srv._flatten_output(prediction.get("output"))

    common = {
        "ok": True,
        "status": "succeeded",
        "job_id": job["id"],
        "model": model_id,
        "provider": provider,
        "upstream_model": upstream_model,
        "replicate_model": job.get("replicate_model"),
        "fal_model": job.get("fal_model"),
        "higgsfield_model": job.get("higgsfield_model"),
        "prediction_id": prediction.get("id") or prediction.get("request_id"),
    }

    if kind in {"llm", "stt"}:
        if kind == "stt" and isinstance(prediction.get("output"), dict):
            out = prediction["output"]
            reply = (out.get("text") or "").strip()
            lang = out.get("language_code")
            if reply and lang:
                reply = f"{reply}\n\n— язык: {lang}"
            elif not reply:
                reply = str(out)
        else:
            reply = "\n".join(outputs).strip() or str(
                prediction.get("output") or prediction.get("text") or ""
            )
        return {"kind": "text", "reply": reply, **common}

    media_urls = [u for u in outputs if isinstance(u, str) and u.startswith("http")]
    if kind == "image":
        return {
            "kind": "image",
            "urls": media_urls,
            "reply": "Готово." if media_urls else "Модель завершилась без URL изображения.",
            **common,
        }
    if kind == "video":
        return {
            "kind": "video",
            "urls": media_urls,
            "reply": "Видео готово." if media_urls else "Модель завершилась без URL видео.",
            **common,
        }
    if kind == "audio":
        return {
            "kind": "audio",
            "urls": media_urls,
            "reply": "Аудио готово." if media_urls else "Модель завершилась без URL аудио.",
            **common,
        }
    return {"ok": False, "error": "unsupported_kind", "kind": kind, "status": 500, **common}


def _fail_from_result(job: dict[str, Any], channel: str, result: dict[str, Any]) -> dict[str, Any]:
    write_health(channel, False, str(result.get("detail") or result.get("error") or "upstream"))
    out = {
        "ok": False,
        "error": result.get("error") or "upstream",
        "detail": result.get("detail"),
        "status": int(result.get("status") or 502),
        "model": job.get("model_id"),
        "provider": channel,
        "upstream_model": job.get("upstream_model"),
        "job_id": job.get("id"),
    }
    if result.get("phase"):
        out["phase"] = result["phase"]
    return out


def _run_omniroute(job: dict[str, Any]) -> dict[str, Any]:
    import server as srv

    wait = _wait_seconds(job["model_id"], job.get("kind") or "llm")
    upstream = job.get("upstream_model") or "auto/chat"
    payload = job.get("input_payload") or {}
    set_job(job["id"], status="running", chosen_channel="omniroute", started_at=time.time())
    result = srv._run_omniroute_prediction(upstream, payload, wait_seconds=wait)
    if not result.get("ok"):
        return _fail_from_result(job, "omniroute", result)
    write_health("omniroute", True, "job_ok")
    return _format_success(job, result["prediction"], "omniroute")


def process_job(channel: str, job: dict[str, Any], *, resume: bool = False) -> dict[str, Any]:
    if not is_channel_healthy(channel):
        return {
            "ok": False,
            "error": "channel_unavailable",
            "status": 503,
            "detail": f"{channel} became unhealthy before run",
            "provider": channel,
            "job_id": job.get("id"),
            "phase": "submit",
        }

    if channel == "omniroute":
        return _run_omniroute(job)

    import server as srv

    wait = _wait_seconds(job["model_id"], job["kind"])
    upstream = job["upstream_model"]
    payload = job["input_payload"]
    ref = job.get("upstream_ref") if (resume or job.get("upstream_ref")) else None

    if not ref:
        if channel == "fal":
            submitted = srv._fal_submit(upstream, payload)
        elif channel == "higgsfield":
            submitted = srv._higgsfield_submit(upstream, payload)
        else:
            submitted = srv._replicate_submit(upstream, payload)

        if not submitted.get("ok"):
            return _fail_from_result(job, channel, submitted)

        prediction = submitted.get("prediction") or {}
        if channel == "fal":
            ref = {
                "request_id": submitted.get("request_id"),
                "status_url": submitted.get("status_url"),
                "response_url": submitted.get("response_url"),
            }
            # Immediate result without queue urls
            if prediction and not submitted.get("status_url"):
                set_job(
                    job["id"],
                    status="running",
                    chosen_channel=channel,
                    started_at=time.time(),
                    upstream_ref=ref,
                )
                write_health(channel, True, "job_ok")
                return _format_success(job, prediction, channel)
        elif channel == "higgsfield":
            ref = {
                "request_id": submitted.get("request_id"),
                "status_url": submitted.get("status_url"),
                "response_url": submitted.get("response_url"),
                "cancel_url": submitted.get("cancel_url"),
            }
            if prediction and prediction.get("video"):
                set_job(
                    job["id"],
                    status="running",
                    chosen_channel=channel,
                    started_at=time.time(),
                    upstream_ref=ref,
                )
                write_health(channel, True, "job_ok")
                return _format_success(job, prediction, channel)
        else:
            ref = {
                "prediction_id": submitted.get("prediction_id"),
                "get_url": submitted.get("get_url"),
            }
            if prediction.get("status") == "succeeded":
                set_job(
                    job["id"],
                    status="running",
                    chosen_channel=channel,
                    started_at=time.time(),
                    upstream_ref=ref,
                )
                write_health(channel, True, "job_ok")
                return _format_success(job, prediction, channel)

        started = time.time()
        set_job(
            job["id"],
            status="running",
            chosen_channel=channel,
            started_at=started,
            upstream_ref=ref,
        )
        job = get_job(job["id"]) or {**job, "started_at": started, "upstream_ref": ref}
    else:
        if not job.get("started_at"):
            set_job(job["id"], status="running", chosen_channel=channel, started_at=time.time())
            job = get_job(job["id"]) or job

    started_at = float(job.get("started_at") or time.time())
    deadline = started_at + wait

    if channel == "fal":
        result = srv._fal_wait(ref.get("status_url"), ref.get("response_url"), deadline)
        if result.get("error") == "timeout":
            srv._fal_cancel(upstream, ref.get("request_id"))
    elif channel == "higgsfield":
        result = srv._higgsfield_wait(ref.get("request_id"), deadline)
        if result.get("error") == "timeout":
            srv._higgsfield_cancel(ref.get("request_id"))
    else:
        result = srv._replicate_wait(ref.get("get_url"), deadline)
        if result.get("error") == "timeout":
            srv._replicate_cancel(ref.get("prediction_id"))

    if not result.get("ok"):
        return _fail_from_result(job, channel, result)

    write_health(channel, True, "job_ok")
    return _format_success(job, result["prediction"], channel)


def recover_processing(channel: str) -> dict[str, int]:
    """On worker start: finish, resume, or requeue items left in processing:{ch}."""
    if channel not in PROCESSING_BY_CHANNEL:
        return {"terminal": 0, "resumed": 0, "requeued": 0}
    r = get_redis()
    processing = PROCESSING_BY_CHANNEL[channel]
    queue = QUEUE_BY_CHANNEL[channel]
    stats = {"terminal": 0, "resumed": 0, "requeued": 0}
    items = r.lrange(processing, 0, -1) or []
    for raw in items:
        meta = loads(raw) or {}
        job_id = meta.get("job_id")
        job = get_job(job_id) if job_id else None
        if not job:
            r.lrem(processing, 1, raw)
            stats["terminal"] += 1
            continue
        status = str(job.get("status") or "")
        if status in TERMINAL_STATUSES:
            r.lrem(processing, 1, raw)
            stats["terminal"] += 1
            continue
        if job.get("upstream_ref"):
            try:
                result = process_job(channel, job, resume=True)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "ok": False,
                    "error": "worker_error",
                    "detail": str(exc)[:300],
                    "status": 500,
                    "provider": channel,
                    "job_id": job_id,
                }
            publish_result(job_id, result)
            r.lrem(processing, 1, raw)
            stats["resumed"] += 1
            continue
        # Crashed before submit — put back at front of channel queue.
        r.lrem(processing, 1, raw)
        r.rpush(queue, raw)
        set_job(job_id, status="queued")
        stats["requeued"] += 1
    return stats


def _bump_inflight(channel: str, delta: int) -> None:
    global _active_inflight
    r = get_redis()
    key = inflight_key(channel)
    if delta > 0:
        r.incr(key)
        with _inflight_lock:
            _active_inflight += 1
    else:
        try:
            val = int(r.decr(key))
            if val < 0:
                r.set(key, 0)
        except Exception:  # noqa: BLE001
            pass
        with _inflight_lock:
            _active_inflight = max(0, _active_inflight - 1)


def _handle_raw_item(channel: str, raw: str, queued_at: float | None = None) -> None:
    r = get_redis()
    processing = PROCESSING_BY_CHANNEL[channel]
    meta = loads(raw) or {}
    job_id = meta.get("job_id")
    job = get_job(job_id) if job_id else None
    t0 = time.time()
    queue_wait = None
    if job and isinstance(job.get("created_at"), (int, float)):
        queue_wait = max(0.0, t0 - float(job["created_at"]))
    elif queued_at is not None:
        queue_wait = max(0.0, t0 - queued_at)

    _bump_inflight(channel, 1)
    outcome = "error"
    try:
        if not job:
            outcome = "missing"
            return
        print(
            f"[worker:{channel}] job={job_id} model={job.get('model_id')} "
            f"queue_wait_s={queue_wait if queue_wait is not None else '?'}",
            flush=True,
        )
        try:
            result = process_job(channel, job)
        except Exception as exc:  # noqa: BLE001
            print(f"[worker:{channel}] job={job_id} worker_error: {exc}", flush=True)
            result = {
                "ok": False,
                "error": "worker_error",
                "detail": str(exc)[:300],
                "status": 500,
                "provider": channel,
                "job_id": job_id,
            }
        publish_result(job_id, result)
        outcome = "succeeded" if result.get("ok") else (result.get("error") or "failed")
    finally:
        try:
            r.lrem(processing, 1, raw)
        except Exception as exc:  # noqa: BLE001
            print(f"[worker:{channel}] lrem error: {exc}", flush=True)
        _bump_inflight(channel, -1)
        elapsed = time.time() - t0
        print(
            f"[worker:{channel}] job={job_id} done outcome={outcome} "
            f"run_s={elapsed:.2f} queue_wait_s={queue_wait if queue_wait is not None else '?'}",
            flush=True,
        )


def run_channel_worker(channel: str) -> None:
    global _running, _active_inflight
    if channel not in QUEUE_BY_CHANNEL:
        raise SystemExit(f"unknown channel {channel}")
    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except ValueError:
        # Not on main thread (tests) — stop via _running flag.
        pass
    queue = QUEUE_BY_CHANNEL[channel]
    processing = PROCESSING_BY_CHANNEL[channel]
    n = worker_concurrency(channel)
    r = get_redis()
    _running = True
    _active_inflight = 0
    print(f"[worker:{channel}] started on {queue} concurrency={n}", flush=True)

    recovered = recover_processing(channel)
    print(f"[worker:{channel}] recover={recovered}", flush=True)

    slots = threading.BoundedSemaphore(n)
    futures = set()
    shutdown_started: float | None = None
    pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix=f"cw-{channel}")
    try:
        while True:
            # Reap completed futures
            done = {f for f in futures if f.done()}
            for f in done:
                futures.discard(f)
                try:
                    f.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"[worker:{channel}] future error: {exc}", flush=True)
                slots.release()

            if not _running:
                if shutdown_started is None:
                    shutdown_started = time.time()
                    print(
                        f"[worker:{channel}] shutting down; "
                        f"drain {len(futures)} jobs grace={WORKER_SHUTDOWN_GRACE_SEC}s",
                        flush=True,
                    )
                if not futures:
                    break
                if time.time() - shutdown_started >= WORKER_SHUTDOWN_GRACE_SEC:
                    print(
                        f"[worker:{channel}] grace elapsed with {len(futures)} still running; "
                        "leaving them in processing for recover",
                        flush=True,
                    )
                    break
                wait(futures, timeout=0.5)
                continue

            if not slots.acquire(blocking=False):
                time.sleep(0.2)
                continue

            try:
                # Reliable dequeue: move to processing list, then work.
                raw = r.blmove(queue, processing, 1, src="RIGHT", dest="LEFT")
            except Exception as exc:  # noqa: BLE001
                # Older redis without BLMOVE — fallback
                try:
                    item = r.brpop(queue, timeout=1)
                    raw = None
                    if item:
                        raw = item[1]
                        r.lpush(processing, raw)
                except Exception as exc2:  # noqa: BLE001
                    print(f"[worker:{channel}] dequeue error: {exc}/{exc2}", flush=True)
                    slots.release()
                    time.sleep(0.5)
                    continue

            if not raw:
                slots.release()
                continue

            fut = pool.submit(_handle_raw_item, channel, raw)
            futures.add(fut)
    finally:
        # Never block forever on exit — in-flight items remain in processing:{ch}.
        pool.shutdown(wait=False, cancel_futures=False)

    print(f"[worker:{channel}] stopped", flush=True)


if __name__ == "__main__":
    ch = sys.argv[1] if len(sys.argv) > 1 else ""
    if ch not in QUEUE_BY_CHANNEL:
        print("usage: python -m queue_runtime.channel_worker <replicate|fal|omniroute>")
        sys.exit(2)
    run_channel_worker(ch)
