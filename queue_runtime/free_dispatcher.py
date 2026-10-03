"""Dispatch free video jobs to OmniRoute veoaifree at ≤1 / 10 minutes."""

from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auth import load_env  # noqa: E402

load_env(_ROOT)

import free_quota  # noqa: E402
from queue_runtime import get_redis  # noqa: E402
from queue_runtime.jobs import enqueue_inbound, set_job, publish_result  # noqa: E402


STUB_URL = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=80"


def _dispatch_one(r, payload: dict) -> bool:
    job_id = payload.get("job_id")
    if not job_id:
        return False
    allow_stub = (os.getenv("ALLOW_STUB_GEN") or "1").strip().lower() in {"1", "true", "yes"}
    omni_model = os.getenv("FREE_VIDEO_MODEL") or "veo-free/seedance"
    try:
        set_job(
            job_id,
            status="running",
            user_id=payload.get("user_id"),
            model_key=payload.get("model_key"),
            prompt=payload.get("prompt"),
            is_free=True,
        )
        # Prefer enqueue into omniroute channel; stub if no workers / stub mode
        if allow_stub and (os.getenv("FREE_STUB") or "1").strip().lower() in {"1", "true", "yes"}:
            publish_result(
                job_id,
                {
                    "ok": True,
                    "status": "succeeded",
                    "output": STUB_URL,
                    "kind": "video",
                    "is_free": True,
                },
            )
            free_quota.mark_dispatched(r)
            free_quota.clear_errors(r)
            _mark_db_success(payload, STUB_URL)
            return True

        inbound_id = enqueue_inbound(
            {
                "model_id": omni_model,
                "provider": "omniroute",
                "prompt": payload.get("prompt") or "",
                "user_id": payload.get("user_id"),
                "price_kop": 0,
                "billing_job_id": job_id,
                "is_free": True,
                "params": payload.get("params") or {},
            }
        )
        set_job(job_id, status="queued", upstream_job_id=inbound_id, is_free=True)
        free_quota.mark_dispatched(r)
        free_quota.clear_errors(r)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[free_dispatcher] error: {exc}", flush=True)
        free_quota.record_error(r)
        set_job(job_id, status="failed", error=str(exc), is_free=True)
        # re-queue? no — failure must not burn quota (consume only on success)
        return False


def _mark_db_success(payload: dict, url: str) -> None:
    """Update Work + FreeQuota when stub succeeds."""
    try:
        from server import app, db, User  # late
        from product_models import init_product_models

        with app.app_context():
            models = app.extensions.get("product_models") or init_product_models(db)
            Work = models["Work"]
            FreeQuota = models["FreeQuota"]
            job_id = payload.get("job_id")
            user_id = payload.get("user_id")
            work = Work.query.filter_by(job_id=job_id).first()
            if work:
                work.original_url = url
                work.thumb_url = url
                work.status = "draft"
                db.session.commit()
            if user_id:
                fq = free_quota.get_quota(db, FreeQuota, int(user_id))
                free_quota.consume_success(db, fq)
    except Exception as exc:  # noqa: BLE001
        print(f"[free_dispatcher] db update failed: {exc}", flush=True)


def run_free_dispatcher(poll_sec: float = 5.0) -> None:
    print("[free_dispatcher] started", flush=True)
    while True:
        try:
            r = get_redis()
            if free_quota.can_dispatch(r) and free_quota.queue_len(r) > 0:
                payload = free_quota.pop_free(r)
                if payload:
                    print(f"[free_dispatcher] dispatching {payload.get('job_id')}", flush=True)
                    _dispatch_one(r, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[free_dispatcher] loop error: {exc}", flush=True)
        time.sleep(poll_sec)


if __name__ == "__main__":
    run_free_dispatcher()
