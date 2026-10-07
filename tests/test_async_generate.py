"""Async POST /api/generate (202 + poll) and queue_runtime job lifecycle."""
from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock

import pytest
import redis as redis_lib
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


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


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("GENERATE_USE_QUEUE", "1")
    monkeypatch.setenv("GENERATE_REQUIRE_AUTH", "0")  # здесь проверяем очередь; вход и баланс — в test_generate_gate.py
    monkeypatch.delenv("GENERATE_SYNC_WAIT", raising=False)
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-replicate-token")
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    import server

    db_file = tmp_path / "async_gen.db"
    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    server.app.config["TESTING"] = True
    with server.app.app_context():
        server.db.session.remove()
        try:
            server.db.engine.dispose()
        except Exception:
            pass
        server.db.drop_all()
        server.db.create_all()
        yield server
        server.db.session.remove()


@pytest.fixture()
def client(app_ctx):
    return app_ctx.app.test_client()


def _csrf(client):
    return client.get("/api/csrf").get_json()["csrf_token"]


def _post_generate(client, model="seedream-5-pro", prompt="egg"):
    csrf = _csrf(client)
    t0 = time.monotonic()
    r = client.post(
        "/api/generate",
        json={"model": model, "prompt": prompt},
        headers={"X-CSRF-Token": csrf},
    )
    elapsed = time.monotonic() - t0
    return r, elapsed


def test_post_generate_202_and_inbound_queue(client, redis_client):
    from queue_runtime import QUEUE_INBOUND, loads

    r, elapsed = _post_generate(client)
    assert r.status_code == 202, r.get_json()
    assert elapsed < 1.0
    data = r.get_json()
    assert data.get("job_id")
    assert data.get("poll_url") == f"/api/generate/jobs/{data['job_id']}"
    assert data.get("poll_after_ms") == 2000
    assert redis_client.llen(QUEUE_INBOUND) == 1
    raw = redis_client.lindex(QUEUE_INBOUND, 0)
    meta = loads(raw)
    assert meta.get("job_id") == data["job_id"]

    poll = client.get(data["poll_url"])
    assert poll.status_code == 200
    assert poll.get_json().get("status") == "queued"
    assert poll.headers.get("Cache-Control") == "no-store"


def test_publish_result_success_and_upstream_failure(client, redis_client):
    from queue_runtime.jobs import enqueue_inbound, generate_job_public, publish_result

    job_id = enqueue_inbound({"model_id": "seedream-5-pro", "kind": "image", "provider": "replicate"})
    publish_result(
        job_id,
        {
            "ok": True,
            "kind": "image",
            "urls": ["https://example.com/x.png"],
            "provider": "replicate",
        },
    )
    pub = generate_job_public(job_id)
    assert pub["status"] == "succeeded"
    assert pub.get("urls") == ["https://example.com/x.png"]
    assert pub.get("kind") == "image"

    job_id2 = enqueue_inbound({"model_id": "seedream-5-pro"})
    publish_result(
        job_id2,
        {"ok": False, "status": 502, "error": "upstream", "detail": "bad gateway"},
    )
    pub2 = generate_job_public(job_id2)
    assert pub2["status"] == "failed"
    assert pub2.get("http_status") == 502

    poll = client.get(f"/api/generate/jobs/{job_id2}")
    assert poll.get_json().get("http_status") == 502


def test_poll_not_found_and_owner(client, redis_client):
    assert client.get("/api/generate/jobs/not-valid-id").status_code == 404
    assert client.get("/api/generate/jobs/" + "a" * 15).status_code == 404

    from queue_runtime.jobs import enqueue_inbound

    job_id = enqueue_inbound({"model_id": "x", "owner_id": 424242})
    assert client.get(f"/api/generate/jobs/{job_id}").status_code == 404


def test_stale_jobs(client, redis_client, monkeypatch):
    import queue_runtime.jobs as jobs

    monkeypatch.setattr(jobs, "RUNNING_STALE_SEC", 30)
    monkeypatch.setattr(jobs, "QUEUE_STALE_SEC", 30)

    from queue_runtime.jobs import enqueue_inbound, generate_job_public, set_job

    old = time.time() - 9999
    running_id = enqueue_inbound({"model_id": "seedream-5-pro"})
    set_job(running_id, status="running", started_at=old)
    pub = generate_job_public(running_id)
    assert pub["status"] == "failed"
    assert pub.get("error") == "timeout"

    queued_id = enqueue_inbound({"model_id": "seedream-5-pro"})
    set_job(queued_id, status="queued", created_at=old)
    assert generate_job_public(queued_id)["status"] == "failed"

    free_id = enqueue_inbound({"model_id": "seedream-5-pro"})
    set_job(free_id, status="queued_free", created_at=old)
    assert generate_job_public(free_id)["status"] == "queued_free"

    fresh_id = enqueue_inbound({"model_id": "seedream-5-pro"})
    set_job(fresh_id, status="running", started_at=time.time())
    assert generate_job_public(fresh_id)["status"] == "running"


def test_worker_process_job_exception(redis_client, monkeypatch):
    from queue_runtime import QUEUE_BY_CHANNEL, dumps
    from queue_runtime.jobs import enqueue_inbound, get_job
    import queue_runtime.channel_worker as cw

    job_id = enqueue_inbound(
        {
            "model_id": "seedream-5-pro",
            "provider": "replicate",
            "kind": "image",
            "upstream_model": "bytedance/seedream-5-pro",
            "input_payload": {"prompt": "egg"},
        }
    )
    redis_client.lpush(QUEUE_BY_CHANNEL["replicate"], dumps({"job_id": job_id}))

    def boom(_channel, _job):
        cw._running = False
        raise RuntimeError("boom")

    monkeypatch.setattr(cw, "process_job", boom)
    cw._running = True
    cw.run_channel_worker("replicate")

    job = get_job(job_id)
    assert job["status"] == "failed"
    assert job.get("error") == "worker_error"


def test_generate_job_fields_helper(app_ctx):
    fn = app_ctx.app.config.get("GENERATE_JOB_FIELDS")
    assert callable(fn)
    fields = fn("seedream-5-pro", "egg")
    assert fields["kind"] == "image"
    assert fields["upstream_model"] == "bytedance/seedream-5-pro"
    assert fields["input_payload"]["prompt"] == "egg"


def test_chat_respects_deadline_no_deepseek(app_ctx, client, monkeypatch):
    monkeypatch.setenv("CHAT_DEADLINE_SEC", "6")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GROQ_CHAT_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setenv("CHAT_PREFER_GROQ", "1")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-replicate-token")
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)

    timeouts_seen = []

    class FakeHttp:
        trust_env = False

        def post(self, *args, **kwargs):
            timeouts_seen.append(kwargs.get("timeout"))
            raise requests.ConnectionError("slow fail")

    deepseek = MagicMock(side_effect=AssertionError("DeepSeek fallback must not run"))
    monkeypatch.setattr(app_ctx, "load_env", lambda *_a, **_k: None)
    monkeypatch.setattr(app_ctx, "_chat_session", lambda: FakeHttp())
    monkeypatch.setattr(app_ctx, "_run_replicate_prediction", deepseek)
    monkeypatch.setattr(app_ctx, "_omniroute_key", lambda: "")
    # Prompt assembly can be slow on cold FS; isolate deadline logic from I/O.
    monkeypatch.setattr(app_ctx, "_build_chat_system_prompt", lambda: "test system")
    monkeypatch.setattr(app_ctx, "_ui_model_context", lambda _data: "")

    csrf = _csrf(client)
    t0 = time.monotonic()
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-CSRF-Token": csrf},
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 8.0, f"chat exceeded deadline window: {elapsed:.2f}s"
    assert r.status_code == 502
    assert timeouts_seen
    assert all(t <= 6.0 for t in timeouts_seen if t is not None)
    deepseek.assert_not_called()
