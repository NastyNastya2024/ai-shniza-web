"""Генерация → «Мои работы»; неопубликованные хранятся 24 часа, опубликованные — пока их не удалят."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

JOB = "a" * 24


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("WORKS_COPY_RESULTS", "0")
    monkeypatch.delenv("WORKS_UNPUBLISHED_TTL_HOURS", raising=False)
    import server

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'works.db'}"
    server.app.config["TESTING"] = True
    jobs = {}
    import queue_runtime.jobs as qj

    monkeypatch.setattr(qj, "get_job", lambda jid: jobs.get(jid))
    monkeypatch.setattr(qj, "generate_job_public", lambda jid: dict(jobs[jid]["public"]) if jid in jobs else None)
    server._jobs = jobs
    server.app.extensions["generation_works"]["_state"]["last_purge"] = 0.0
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


def _login(srv, c, email="w@t.local"):
    u = srv.User(email=email, provider="password", name="W")
    srv.db.session.add(u)
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id
    return u


def _job(srv, owner, kind="video", urls=("https://cdn.example/out.mp4",), status="succeeded", jid=JOB):
    srv._jobs[jid] = {"owner_id": owner, "prompt": "кот прыгает в снег", "params": {"duration": 5},
                      "public": {"job_id": jid, "status": status, "kind": kind, "model": "p-video", "urls": list(urls)}}


def _Work(srv):
    return srv.app.extensions["product_models"]["Work"]


def test_finished_generation_becomes_draft_work_once(srv):
    c = srv.app.test_client()
    u = _login(srv, c)
    _job(srv, u.id)
    r = c.get(f"/api/generate/jobs/{JOB}").get_json()
    assert r["work_id"] and r["published"] is False and r["expires_at"].endswith("Z")
    w = srv.db.session.get(_Work(srv), r["work_id"])
    assert w.status == "draft" and w.prompt == "кот прыгает в снег" and w.original_url == "https://cdn.example/out.mp4"
    again = c.get(f"/api/generate/jobs/{JOB}").get_json()
    assert again["work_id"] == r["work_id"] and _Work(srv).query.count() == 1


def test_no_work_for_text_running_or_guest(srv):
    c = srv.app.test_client()
    u = _login(srv, c)
    _job(srv, u.id, kind="text", urls=(), jid="b" * 24)
    assert "work_id" not in c.get("/api/generate/jobs/" + "b" * 24).get_json()
    _job(srv, u.id, status="running", jid="c" * 24)
    assert "work_id" not in c.get("/api/generate/jobs/" + "c" * 24).get_json()
    g = srv.app.test_client()
    _job(srv, None, jid="d" * 24)
    assert "work_id" not in g.get("/api/generate/jobs/" + "d" * 24).get_json()
    assert _Work(srv).query.count() == 0


def test_purge_deletes_only_unpublished_older_than_24h(srv, tmp_path, monkeypatch):
    c = srv.app.test_client()
    u = _login(srv, c)
    W = _Work(srv)
    import media_store
    media_dir = os.path.join(os.path.dirname(media_store.__file__), "media", "works", "test-purge")
    os.makedirs(media_dir, exist_ok=True)
    f = os.path.join(media_dir, "old.mp4")
    open(f, "wb").write(b"x")
    old = _now() - timedelta(hours=25)
    rows = {
        "old_draft": W(owner_id=u.id, kind="video", model_key="m", prompt="", status="draft", created_at=old,
                       original_url="/media/works/test-purge/old.mp4"),
        "old_saved": W(owner_id=u.id, kind="image", model_key="m", prompt="", status="saved", created_at=old),
        "fresh": W(owner_id=u.id, kind="image", model_key="m", prompt="", status="draft", created_at=_now()),
        "published": W(owner_id=u.id, kind="image", model_key="m", prompt="", status="published", created_at=old,
                       published_at=old),
        "hidden_after_publish": W(owner_id=u.id, kind="image", model_key="m", prompt="", status="saved",
                                  created_at=old, published_at=old),
    }
    for w in rows.values():
        srv.db.session.add(w)
    srv.db.session.commit()
    ids = {k: w.id for k, w in rows.items()}
    gw = srv.app.extensions["generation_works"]
    assert gw["purge"](dry_run=True) == 2
    assert gw["purge"]() == 2
    left = {w.id for w in W.query.all()}
    assert left == {ids["fresh"], ids["published"], ids["hidden_after_publish"]}
    assert not os.path.exists(f)
    os.rmdir(media_dir)


def test_works_mine_shows_expiry_and_purges(srv):
    c = srv.app.test_client()
    u = _login(srv, c)
    W = _Work(srv)
    srv.db.session.add(W(owner_id=u.id, kind="image", model_key="m", prompt="", status="draft",
                         created_at=_now() - timedelta(hours=30)))
    fresh = W(owner_id=u.id, kind="image", model_key="m", prompt="", status="draft", created_at=_now(),
              original_url="https://cdn.example/a.png")
    pub = W(owner_id=u.id, kind="image", model_key="m", prompt="", status="published", created_at=_now(),
            published_at=_now())
    srv.db.session.add_all([fresh, pub])
    srv.db.session.commit()
    items = {i["id"]: i for i in c.get("/api/works/mine").get_json()["items"]}
    assert set(items) == {fresh.id, pub.id}                      # старый черновик удалён при открытии списка
    assert items[fresh.id]["expires_at"] and items[pub.id]["expires_at"] is None


def test_ttl_from_env(srv, monkeypatch):
    monkeypatch.setenv("WORKS_UNPUBLISHED_TTL_HOURS", "48")
    c = srv.app.test_client()
    u = _login(srv, c)
    W = _Work(srv)
    srv.db.session.add(W(owner_id=u.id, kind="image", model_key="m", prompt="", status="draft",
                         created_at=_now() - timedelta(hours=30)))
    srv.db.session.commit()
    assert srv.app.extensions["generation_works"]["purge"]() == 0


def test_copy_result_to_own_storage(srv, monkeypatch):
    c = srv.app.test_client()
    u = _login(srv, c)
    _job(srv, u.id, kind="image", urls=("https://replicate.delivery/x/out.webp",))
    wid = c.get(f"/api/generate/jobs/{JOB}").get_json()["work_id"]
    import media_store
    saved = {}
    monkeypatch.setattr(media_store, "download_url_to_bytes", lambda url: b"img")
    monkeypatch.setattr(media_store, "upload_bytes", lambda key, data, mime: saved.setdefault("k", "s3://b/" + key))
    srv.app.extensions["generation_works"]["copy"](wid)
    w = srv.db.session.get(_Work(srv), wid)
    srv.db.session.refresh(w)
    assert w.original_url == f"s3://b/works/{u.id}/{wid}.webp" and w.thumb_url == w.original_url


def test_cli_dry_run(srv):
    r = srv.app.test_cli_runner().invoke(args=["purge-unpublished-works", "--dry-run"])
    assert "would delete 0" in r.output


def test_local_uploads_older_than_24h_are_deleted(tmp_path):
    import time as _t
    from generation_works import purge_local_uploads
    old = tmp_path / "2026" / "10" / "01" / "upl_old.png"
    new = tmp_path / "2026" / "10" / "08" / "upl_new.png"
    for p in (old, new):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    past = _t.time() - 25 * 3600
    os.utime(old, (past, past))
    assert purge_local_uploads(str(tmp_path), dry_run=True) == 1 and old.exists()
    assert purge_local_uploads(str(tmp_path)) == 1
    assert not old.exists() and new.exists() and not old.parent.exists()
