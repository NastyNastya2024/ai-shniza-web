"""Скрепка в настоящем приложении: /api/uploads → номер файла → /api/generate → payload провайдера."""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("GENERATE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("FAL_KEY", "test-key")
    for k in ("PUBLIC_BASE_URL", "BASE_URL", "UPLOAD_ALLOW_REMOTE_URLS"):
        monkeypatch.delenv(k, raising=False)
    import server
    import uploads

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'upl.db'}"
    server.app.config["TESTING"] = True
    monkeypatch.setattr(server, "_integration_prices", lambda: {"seedream-5-pro": "3,9 ₽ / изображение at 1K"})

    # файлы — во временную папку, а не в media/ репозитория; записи — в память
    def save(key, data, mime):
        p = tmp_path / "media" / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return "/media/" + key

    def read_local(stored):
        p = tmp_path / stored.lstrip("/")
        return p.read_bytes() if p.exists() else None

    ext = server.app.extensions["uploads"]
    monkeypatch.setitem(ext, "store", uploads.MetaStore())
    monkeypatch.setitem(ext, "storage", uploads.Storage(save=save, presign=lambda s, e: s, read_local=read_local,
                                                        delete_local=lambda s: None))

    import queue_runtime.jobs as jobs
    captured = {}

    def fake_enqueue(payload):
        captured["payload"] = payload
        return "c" * 24

    monkeypatch.setattr(jobs, "enqueue_inbound", fake_enqueue)
    monkeypatch.setattr("queue_runtime.health.is_channel_healthy", lambda ch: True)
    server._captured = captured

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


def _csrf(c):
    return c.get("/api/csrf").get_json()["csrf_token"]


def _ip(c):
    if not getattr(c, "_ip", None):
        c._ip = "10.7.%d.%d" % (id(c) % 250, id(c) // 250 % 250)
    return c._ip


def _login(srv, c, email="u@t.local", balance_kop=100000):
    import billing

    u = srv.User(email=email, provider="password", name="U")
    srv.db.session.add(u)
    srv.db.session.commit()
    bal = billing.get_or_create_balance(srv.db, srv.app.extensions["product_models"]["Balance"], u.id)
    bal.balance_kop = balance_kop
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id
    return u


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (16, 9), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


def _upload(c, data=None, name="cat.png", mime="image/png", csrf=True):
    headers = {"X-Forwarded-For": _ip(c)}
    if csrf:
        headers["X-CSRF-Token"] = _csrf(c)
    return c.post("/api/uploads", data={"file": (io.BytesIO(data or _png()), name, mime)},
                  content_type="multipart/form-data", headers=headers)


def _gen(c, model, **media):
    body = {"model": model, "prompt": "оживи фото"}
    body.update(media)
    return c.post("/api/generate", json=body, headers={"X-CSRF-Token": _csrf(c), "X-Forwarded-For": _ip(c)})


def test_upload_requires_csrf(srv):
    c = srv.app.test_client()
    assert _upload(c, csrf=False).status_code in (400, 403)
    assert _upload(c).status_code == 201


def test_attached_image_reaches_provider_payload(srv):
    c = srv.app.test_client()
    _login(srv, c)
    upl = _upload(c).get_json()["id"]
    r = _gen(c, "seedream-5-pro", image=upl)
    assert r.status_code == 202, r.get_json()
    payload = json.dumps(srv._captured["payload"]["input_payload"])
    assert "data:image/png;base64," in payload          # локально без PUBLIC_BASE_URL — data URL


def test_public_base_url_gives_provider_a_link(srv, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://ai-shniza.ru")
    c = srv.app.test_client()
    _login(srv, c)
    upl = _upload(c).get_json()["id"]
    assert _gen(c, "seedream-5-pro", image=upl).status_code == 202
    payload = json.dumps(srv._captured["payload"]["input_payload"])
    assert "https://ai-shniza.ru/media/uploads/" in payload and "base64" not in payload


def test_guest_attaches_then_logs_in(srv):
    c = srv.app.test_client()
    upl = _upload(c).get_json()["id"]                    # прикрепил до входа
    assert _gen(c, "seedream-5-pro", image=upl).status_code == 401
    _login(srv, c)
    assert _gen(c, "seedream-5-pro", image=upl).status_code == 202


def test_foreign_upload_is_refused(srv):
    a, b = srv.app.test_client(), srv.app.test_client()
    _login(srv, a, email="a@t.local")
    _login(srv, b, email="b@t.local")
    upl = _upload(a).get_json()["id"]
    r = _gen(b, "seedream-5-pro", image=upl)
    assert r.status_code == 404 and r.get_json()["error"] == "upload_not_found"


def test_expired_upload_explained(srv):
    c = srv.app.test_client()
    _login(srv, c)
    r = _gen(c, "seedream-5-pro", image="upl_" + "0" * 24)
    assert r.status_code == 410 and r.get_json()["error"] == "upload_expired"


def test_text_only_model_ignores_attachment(srv):
    c = srv.app.test_client()
    _login(srv, c)
    upl = _upload(c).get_json()["id"]
    srv._captured.clear()
    r = _gen(c, "elevenlabs-music", image=upl)
    assert r.status_code == 202, r.get_json()
    assert "base64" not in json.dumps(srv._captured["payload"]["input_payload"])


def test_integrations_expose_inputs_for_attach_button(srv):
    items = srv.app.test_client().get("/api/integrations").get_json()["items"]
    by_id = {it["id"]: it for it in items}
    if "seedream-5-pro" in by_id:
        assert "image" in by_id["seedream-5-pro"]["inputs"]


def test_studio_page_loads_attach_module(srv):
    html = srv.app.test_client().get("/app").get_data(as_text=True)
    assert '/attach.js' in html and '/attach.css' in html and 'data-attach' in html
    assert srv.app.test_client().get("/attach.js").status_code == 200
