"""Parallel channel workers, processing-list recovery, run_all restarts."""
from __future__ import annotations

import os
import sys
import threading
import time

import pytest
import redis as redis_lib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
_FLAKY_FLAG_ENV = "TEST_RUN_ALL_FLAKY_FLAG"


@pytest.fixture(scope="module")
def redis_available():
    try:
        r = redis_lib.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
        r.ping()
    except Exception:
        pytest.skip("Redis unavailable (set TEST_REDIS_URL or start redis)")
    return TEST_REDIS_URL


@pytest.fixture()
def redis_client(redis_available, monkeypatch):
    monkeypatch.setenv("REDIS_URL", redis_available)
    r = redis_lib.Redis.from_url(redis_available, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()


def _seed_job(model_id="seedream-5-pro"):
    from queue_runtime.jobs import enqueue_inbound

    return enqueue_inbound(
        {
            "model_id": model_id,
            "provider": "replicate",
            "kind": "image",
            "upstream_model": "bytedance/seedream-5-pro",
            "input_payload": {"prompt": "egg"},
        }
    )


def test_parallel_workers_cap_and_speed(redis_client, monkeypatch):
    monkeypatch.setenv("WORKER_CONCURRENCY_REPLICATE", "5")
    import queue_runtime.channel_worker as cw
    import server as srv
    from queue_runtime import QUEUE_BY_CHANNEL, QUEUE_INBOUND, dumps, loads
    from queue_runtime.jobs import get_job, set_job

    monkeypatch.setattr(cw, "is_channel_healthy", lambda _ch: True)
    monkeypatch.setattr(cw, "recover_processing", lambda _ch: {"terminal": 0, "resumed": 0, "requeued": 0})

    peaks = {"cur": 0, "max": 0}
    lock = threading.Lock()
    submit_n = {"n": 0}

    def fake_submit(model, payload):
        submit_n["n"] += 1
        return {
            "ok": True,
            "prediction_id": f"p-{submit_n['n']}",
            "get_url": f"https://example.test/p-{submit_n['n']}",
            "prediction": {"status": "starting", "id": f"p-{submit_n['n']}"},
            "phase": "submit",
        }

    def fake_wait(get_url, deadline):
        with lock:
            peaks["cur"] += 1
            peaks["max"] = max(peaks["max"], peaks["cur"])
        time.sleep(1.0)
        with lock:
            peaks["cur"] -= 1
        return {
            "ok": True,
            "prediction": {
                "status": "succeeded",
                "id": "px",
                "output": "https://example.com/out.png",
            },
            "phase": "run",
        }

    monkeypatch.setattr(srv, "_replicate_submit", fake_submit)
    monkeypatch.setattr(srv, "_replicate_wait", fake_wait)
    monkeypatch.setattr(srv, "_replicate_cancel", lambda *_a, **_k: None)

    job_ids = [_seed_job() for _ in range(10)]
    while True:
        item = redis_client.rpop(QUEUE_INBOUND)
        if not item:
            break
        meta = loads(item)
        jid = meta["job_id"]
        set_job(jid, status="dispatched", chosen_channel="replicate")
        redis_client.lpush(QUEUE_BY_CHANNEL["replicate"], dumps({"job_id": jid}))

    cw._running = True
    t = threading.Thread(target=lambda: cw.run_channel_worker("replicate"), daemon=True)
    t0 = time.time()
    t.start()

    deadline = time.time() + 8
    while time.time() < deadline:
        done = sum(1 for jid in job_ids if (get_job(jid) or {}).get("status") == "succeeded")
        if done == 10:
            break
        time.sleep(0.1)
    cw._running = False
    t.join(timeout=6)
    elapsed = time.time() - t0

    assert all((get_job(jid) or {}).get("status") == "succeeded" for jid in job_ids)
    assert elapsed < 4.5, f"expected ~2s with concurrency 5, got {elapsed:.2f}s"
    assert peaks["max"] <= 5
    assert peaks["max"] >= 2


def test_recover_with_upstream_ref_does_not_resubmit(redis_client, monkeypatch):
    import queue_runtime.channel_worker as cw
    import server as srv
    from queue_runtime import PROCESSING_BY_CHANNEL, dumps
    from queue_runtime.jobs import get_job, set_job

    monkeypatch.setattr(cw, "is_channel_healthy", lambda _ch: True)
    job_id = _seed_job()
    set_job(
        job_id,
        status="running",
        started_at=time.time(),
        upstream_ref={"prediction_id": "abc", "get_url": "https://example.test/abc"},
    )
    redis_client.lpush(PROCESSING_BY_CHANNEL["replicate"], dumps({"job_id": job_id}))

    submits = []

    def fake_submit(*_a, **_k):
        submits.append(1)
        raise AssertionError("submit must not be called on resume")

    def fake_wait(get_url, deadline):
        return {
            "ok": True,
            "prediction": {"status": "succeeded", "id": "abc", "output": "https://example.com/x.png"},
            "phase": "run",
        }

    monkeypatch.setattr(srv, "_replicate_submit", fake_submit)
    monkeypatch.setattr(srv, "_replicate_wait", fake_wait)
    monkeypatch.setattr(srv, "_replicate_cancel", lambda *_a, **_k: None)

    stats = cw.recover_processing("replicate")
    assert stats["resumed"] == 1
    assert submits == []
    assert (get_job(job_id) or {}).get("status") == "succeeded"
    assert redis_client.llen(PROCESSING_BY_CHANNEL["replicate"]) == 0


def test_recover_without_upstream_ref_requeues(redis_client, monkeypatch):
    import queue_runtime.channel_worker as cw
    from queue_runtime import PROCESSING_BY_CHANNEL, QUEUE_BY_CHANNEL, dumps, loads
    from queue_runtime.jobs import get_job, set_job

    job_id = _seed_job()
    set_job(job_id, status="running", started_at=time.time())
    raw = dumps({"job_id": job_id})
    redis_client.lpush(PROCESSING_BY_CHANNEL["replicate"], raw)

    stats = cw.recover_processing("replicate")
    assert stats["requeued"] == 1
    assert redis_client.llen(PROCESSING_BY_CHANNEL["replicate"]) == 0
    assert redis_client.llen(QUEUE_BY_CHANNEL["replicate"]) == 1
    assert loads(redis_client.lindex(QUEUE_BY_CHANNEL["replicate"], 0))["job_id"] == job_id
    assert (get_job(job_id) or {}).get("status") == "queued"


def test_wait_timeout_cancels(redis_client, monkeypatch):
    import queue_runtime.channel_worker as cw
    import server as srv
    from queue_runtime.jobs import get_job, publish_result

    monkeypatch.setattr(cw, "is_channel_healthy", lambda _ch: True)
    job_id = _seed_job()
    job = get_job(job_id)

    cancels = []

    def fake_submit(model, payload):
        return {
            "ok": True,
            "prediction_id": "to-cancel",
            "get_url": "https://example.test/to-cancel",
            "prediction": {"status": "starting", "id": "to-cancel"},
            "phase": "submit",
        }

    def fake_wait(get_url, deadline):
        return {"ok": False, "error": "timeout", "detail": "still", "status": 504, "phase": "run"}

    monkeypatch.setattr(srv, "_replicate_submit", fake_submit)
    monkeypatch.setattr(srv, "_replicate_wait", fake_wait)
    monkeypatch.setattr(srv, "_replicate_cancel", lambda pid: cancels.append(pid))
    monkeypatch.setattr(cw, "_wait_seconds", lambda *_a, **_k: 1)

    result = cw.process_job("replicate", job)
    assert result.get("error") == "timeout"
    assert cancels == ["to-cancel"]
    publish_result(job_id, result)
    assert (get_job(job_id) or {}).get("status") == "failed"


def _test_flaky_child():
    path = os.environ[_FLAKY_FLAG_ENV]
    if not os.path.exists(path):
        open(path, "w").write("died")
        raise SystemExit(7)
    while True:
        time.sleep(0.2)


def _test_ok_child():
    while True:
        time.sleep(0.2)


def test_run_all_restarts_one_child(tmp_path, monkeypatch):
    import multiprocessing as mp
    import queue_runtime.run_all as run_all

    flag = tmp_path / "flaky.flag"
    monkeypatch.setenv(_FLAKY_FLAG_ENV, str(flag))
    monkeypatch.setattr(run_all, "WORKER_SHUTDOWN_GRACE_SEC", 2)

    roles = [
        ("flaky", _test_flaky_child),
        ("ok", _test_ok_child),
    ]

    try:
        mp.set_start_method("fork", force=True)
    except RuntimeError:
        pass

    procs_box: dict[str, list] = {}
    original_start = run_all._start_child

    def tracking_start(name, target):
        p = original_start(name, target)
        procs_box.setdefault(name, []).append(p)
        return p

    monkeypatch.setattr(run_all, "_start_child", tracking_start)
    stop_event = threading.Event()

    t = threading.Thread(
        target=lambda: run_all.main(roles=roles, stop_event=stop_event),
        daemon=True,
    )
    t.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        flaky_list = procs_box.get("flaky") or []
        ok_list = procs_box.get("ok") or []
        if (
            len(flaky_list) >= 2
            and ok_list
            and ok_list[0].is_alive()
            and flaky_list[-1].is_alive()
        ):
            break
        time.sleep(0.1)
    else:
        stop_event.set()
        t.join(timeout=5)
        pytest.fail(
            f"restart did not happen: "
            f"{ {k: [(p.pid, p.is_alive(), p.exitcode) for p in v] for k, v in procs_box.items()} }"
        )

    assert len(procs_box["flaky"]) >= 2
    assert procs_box["ok"][0].is_alive()
    assert procs_box["flaky"][-1].is_alive()

    stop_event.set()
    t.join(timeout=5)
    # Ensure no leftover non-daemon children keep the pytest process alive.
    for plist in procs_box.values():
        for p in plist:
            if p.is_alive():
                p.terminate()
                p.join(timeout=2)
            if p.is_alive():
                p.kill()
                p.join(timeout=1)
