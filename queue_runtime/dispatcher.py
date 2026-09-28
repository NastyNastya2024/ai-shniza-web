"""Dispatcher worker: inbound queue → channel queue (health-gated)."""

from __future__ import annotations

import os
import signal
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auth import load_env  # noqa: E402

load_env(_ROOT)

from queue_runtime import (  # noqa: E402
    HEALTH_INTERVAL_SEC,
    QUEUE_BY_CHANNEL,
    QUEUE_INBOUND,
    dumps,
    get_redis,
    loads,
)
from queue_runtime.health import is_channel_healthy, probe_all  # noqa: E402
from queue_runtime.jobs import get_job, publish_result, set_job  # noqa: E402

_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


def _route_once(r) -> bool:
    item = r.brpop(QUEUE_INBOUND, timeout=1)
    if not item:
        return False
    _key, raw = item
    meta = loads(raw) or {}
    job_id = meta.get("job_id")
    if not job_id:
        return True
    job = get_job(job_id)
    if not job:
        return True

    channel = job.get("provider")
    if channel not in QUEUE_BY_CHANNEL:
        publish_result(
            job_id,
            {
                "ok": False,
                "error": "unsupported_provider",
                "status": 400,
                "detail": channel,
                "job_id": job_id,
            },
        )
        return True

    if not is_channel_healthy(channel):
        publish_result(
            job_id,
            {
                "ok": False,
                "error": "channel_unavailable",
                "status": 503,
                "detail": f"{channel} is down; not routing",
                "provider": channel,
                "job_id": job_id,
            },
        )
        return True

    set_job(job_id, status="dispatched", chosen_channel=channel)
    r.lpush(QUEUE_BY_CHANNEL[channel], dumps({"job_id": job_id}))
    return True


def run_dispatcher() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    r = get_redis()
    print(f"[dispatcher] started; health every {HEALTH_INTERVAL_SEC}s", flush=True)
    last_probe = 0.0
    try:
        probe_all()
        last_probe = time.time()
        print("[dispatcher] initial health probe done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[dispatcher] initial probe failed: {exc}", flush=True)

    while _running:
        now = time.time()
        if now - last_probe >= HEALTH_INTERVAL_SEC:
            try:
                states = probe_all()
                summary = {ch: v.get("state") for ch, v in states.items()}
                print(f"[dispatcher] health={summary}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[dispatcher] probe error: {exc}", flush=True)
            last_probe = now
        try:
            _route_once(r)
        except Exception as exc:  # noqa: BLE001
            print(f"[dispatcher] route error: {exc}", flush=True)
            time.sleep(0.5)
    print("[dispatcher] stopped", flush=True)


if __name__ == "__main__":
    run_dispatcher()
    sys.exit(0)
