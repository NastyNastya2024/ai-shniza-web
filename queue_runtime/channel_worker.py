"""Channel workers: consume per-provider queues and call upstream APIs."""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Any

# Ensure project root on path when run as script
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auth import load_env  # noqa: E402

load_env(_ROOT)

from queue_runtime import QUEUE_BY_CHANNEL, get_redis, loads  # noqa: E402
from queue_runtime.health import is_channel_healthy, write_health  # noqa: E402
from queue_runtime.jobs import get_job, publish_result, set_job  # noqa: E402

_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


def _wait_seconds(model_id: str, kind: str) -> int:
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
        "ltx-2-3-t2v-fal",
        "ltx-2-3-t2v-fast-fal",
        "ltx-2-3-i2v-fal",
        "ltx-2-3-i2v-fast-fal",
        "ltx-2-3-a2v-fal",
        "pixverse-v6-t2v-fal",
        "pixverse-v6-i2v-fal",
        "minimax-music-2-5",
        "dreamactor-m2",
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


def _run_omniroute(job: dict[str, Any]) -> dict[str, Any]:
    import server as srv

    wait = _wait_seconds(job["model_id"], job.get("kind") or "llm")
    upstream = job.get("upstream_model") or "auto/chat"
    payload = job.get("input_payload") or {}
    set_job(job["id"], status="running", chosen_channel="omniroute")
    result = srv._run_omniroute_prediction(upstream, payload, wait_seconds=wait)
    if not result.get("ok"):
        write_health("omniroute", False, str(result.get("detail") or result.get("error") or "upstream"))
        return {
            "ok": False,
            "error": result.get("error") or "upstream",
            "detail": result.get("detail"),
            "status": int(result.get("status") or 502),
            "model": job.get("model_id"),
            "provider": "omniroute",
            "upstream_model": upstream,
            "job_id": job.get("id"),
        }
    write_health("omniroute", True, "job_ok")
    return _format_success(job, result["prediction"], "omniroute")


def process_job(channel: str, job: dict[str, Any]) -> dict[str, Any]:
    if not is_channel_healthy(channel):
        return {
            "ok": False,
            "error": "channel_unavailable",
            "status": 503,
            "detail": f"{channel} became unhealthy before run",
            "provider": channel,
            "job_id": job.get("id"),
        }

    if channel == "omniroute":
        return _run_omniroute(job)

    import server as srv

    wait = _wait_seconds(job["model_id"], job["kind"])
    upstream = job["upstream_model"]
    payload = job["input_payload"]
    set_job(job["id"], status="running", chosen_channel=channel)

    if channel == "fal":
        result = srv._run_fal_prediction(upstream, payload, wait_seconds=wait)
    else:
        result = srv._run_replicate_prediction(upstream, payload, wait_seconds=wait)

    if not result.get("ok"):
        # Soft health signal: upstream failure increments streak without full probe.
        write_health(channel, False, str(result.get("detail") or result.get("error") or "upstream"))
        return {
            "ok": False,
            "error": result.get("error") or "upstream",
            "detail": result.get("detail"),
            "status": int(result.get("status") or 502),
            "model": job["model_id"],
            "provider": channel,
            "upstream_model": upstream,
            "job_id": job["id"],
        }

    write_health(channel, True, "job_ok")
    return _format_success(job, result["prediction"], channel)


def run_channel_worker(channel: str) -> None:
    if channel not in QUEUE_BY_CHANNEL:
        raise SystemExit(f"unknown channel {channel}")
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    queue = QUEUE_BY_CHANNEL[channel]
    r = get_redis()
    print(f"[worker:{channel}] started on {queue}", flush=True)

    while _running:
        try:
            item = r.brpop(queue, timeout=1)
            if not item:
                continue
            _key, raw = item
            meta = loads(raw) or {}
            job_id = meta.get("job_id")
            job = get_job(job_id) if job_id else None
            if not job:
                continue
            print(f"[worker:{channel}] job={job_id} model={job.get('model_id')}", flush=True)
            result = process_job(channel, job)
            publish_result(job_id, result)
        except Exception as exc:  # noqa: BLE001
            print(f"[worker:{channel}] error: {exc}", flush=True)
            time.sleep(0.5)

    print(f"[worker:{channel}] stopped", flush=True)


if __name__ == "__main__":
    ch = sys.argv[1] if len(sys.argv) > 1 else ""
    if ch not in QUEUE_BY_CHANNEL:
        print("usage: python -m queue_runtime.channel_worker <replicate|fal|omniroute>")
        sys.exit(2)
    run_channel_worker(ch)
