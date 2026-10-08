"""История переписки студии: хранится в аккаунте, исходные файлы — нет (только тип и имя)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    for k in ("CHAT_MAX_THREADS", "CHAT_HISTORY_DAYS", "CHAT_MAX_MESSAGES"):
        monkeypatch.delenv(k, raising=False)
    import server

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'chats.db'}"
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


def _ip(c):
    if not getattr(c, "_ip", None):
        c._ip = "10.9.%d.%d" % (id(c) % 250, id(c) // 250 % 250)
    return c._ip


def _h(c):
    tok = c.get("/api/csrf").get_json()["csrf_token"]
    return {"X-CSRF-Token": tok, "X-Forwarded-For": _ip(c)}


def _login(srv, c, email="u@t.local"):
    u = srv.User(email=email, provider="password", name="U")
    srv.db.session.add(u)
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id
    return u


MSGS = [
    {"role": "user", "text": "видео: кот прыгает в снег", "ts": 1760000000000,
     "files": [{"kind": "image", "name": "cat.png", "id": "upl_secret123", "url": "/media/u/x.png"},
               {"kind": "audio", "name": "voice.wav", "id": "upl_secret456"}]},
    {"role": "bot", "assistant": {"text": "Вижу фото «cat.png»", "lang": "ru",
                                  "blocks": [{"type": "models", "items": [{"id": "p-video", "title": "P-Video"}]}],
                                  "chips": [{"label": "Ещё", "action": "more"}]}},
    {"role": "bot", "text": "Готово", "result": True, "mediaUrl": "https://cdn.example/r.mp4", "mediaKind": "video",
     "workId": 42, "job": False, "files": [{"kind": "image", "name": "cat.png", "id": "upl_secret123"}]},
]


def test_guest_gets_401_everywhere(srv):
    c = srv.app.test_client()
    h = _h(c)
    assert c.get("/api/chats", headers=h).status_code == 401
    assert c.post("/api/chats", json={"messages": MSGS}, headers=h).status_code == 401
    assert c.get("/api/chats/c_" + "0" * 20, headers=h).status_code == 401


def test_csrf_required(srv):
    c = srv.app.test_client()
    _login(srv, c)
    r = c.post("/api/chats", json={}, headers={"X-Forwarded-For": _ip(c)})
    assert r.status_code == 403


def test_create_save_load_keeps_names_not_sources(srv):
    c = srv.app.test_client()
    _login(srv, c)
    h = _h(c)
    r = c.post("/api/chats", json={"messages": MSGS}, headers=h)
    assert r.status_code == 201
    cid = r.get_json()["id"]
    got = c.get(f"/api/chats/{cid}", headers=h).get_json()
    raw = json.dumps(got, ensure_ascii=False)
    assert "upl_" not in raw and "/media/u/x.png" not in raw          # номера и ссылки файлов не храним
    assert got["messages"][0]["files"] == [{"kind": "image", "name": "cat.png"}, {"kind": "audio", "name": "voice.wav"}]
    assert got["messages"][0]["ts"] == 1760000000000
    assert got["title"] == "видео: кот прыгает в снег"
    bot = got["messages"][1]
    assert bot["assistant"]["blocks"][0]["type"] == "models" and "chips" not in bot["assistant"]
    assert bot["text"] == "Вижу фото «cat.png»"
    res = got["messages"][2]
    assert res["mediaUrl"] == "https://cdn.example/r.mp4" and res["workId"] == "42" and "job" not in res

    # снимок целиком заменяет прежний
    more = MSGS + [{"role": "user", "text": "ещё раз"}]
    r = c.put(f"/api/chats/{cid}", json={"messages": more}, headers=h)
    assert r.get_json()["n"] == 4
    items = c.get("/api/chats", headers=h).get_json()["items"]
    assert [i["id"] for i in items] == [cid] and items[0]["n"] == 4


def test_other_user_cannot_read_or_change(srv):
    a, b = srv.app.test_client(), srv.app.test_client()
    _login(srv, a, "a@t.local")
    _login(srv, b, "b@t.local")
    cid = a.post("/api/chats", json={"messages": MSGS}, headers=_h(a)).get_json()["id"]
    hb = _h(b)
    assert b.get(f"/api/chats/{cid}", headers=hb).status_code == 404
    assert b.put(f"/api/chats/{cid}", json={"messages": []}, headers=hb).status_code == 404
    assert b.delete(f"/api/chats/{cid}", headers=hb).status_code == 404
    assert b.get("/api/chats", headers=hb).get_json()["items"] == []
    assert a.get(f"/api/chats/{cid}", headers=_h(a)).status_code == 200


def test_delete_and_bad_id(srv):
    c = srv.app.test_client()
    _login(srv, c)
    h = _h(c)
    cid = c.post("/api/chats", json={"messages": MSGS}, headers=h).get_json()["id"]
    assert c.delete(f"/api/chats/{cid}", headers=h).get_json() == {"ok": True}
    assert c.get(f"/api/chats/{cid}", headers=h).status_code == 404
    assert c.get("/api/chats/../../etc", headers=h).status_code == 404
    assert c.get("/api/chats/1", headers=h).status_code == 404


def test_junk_is_dropped(srv):
    from chat_history import clean_message, clean_messages
    assert clean_message({"role": "system", "text": "x"}) is None
    assert clean_message({"role": "user", "text": ""}) is None
    assert clean_message("x") is None
    m = clean_message({"role": "bot", "text": "a" * 9000, "result": True, "mediaUrl": "javascript:alert(1)",
                       "mediaKind": "exe", "workId": "<script>"})
    assert len(m["text"]) == 4000 and "mediaUrl" not in m and m["mediaKind"] == "image" and "workId" not in m
    assert clean_message({"role": "bot", "text": "x", "result": True, "mediaUrl": "//evil.example/x"}).get("mediaUrl") is None
    big = {"role": "bot", "assistant": {"text": "t", "blocks": [{"type": "prompt", "text": "x" * 30000}]}}
    assert "blocks" not in clean_message(big)["assistant"]                     # огромная карточка → только текст
    assert len(clean_messages([{"role": "user", "text": str(i)} for i in range(500)])) == 200
    assert clean_messages("nope") == []


def test_limits_purge_old_and_extra(srv, monkeypatch):
    monkeypatch.setenv("CHAT_MAX_THREADS", "2")
    c = srv.app.test_client()
    u = _login(srv, c)
    h = _h(c)
    ids = [c.post("/api/chats", json={"messages": [{"role": "user", "text": f"чат {i}"}]}, headers=h).get_json()["id"]
           for i in range(3)]
    Chat = srv.app.extensions["chat_history"]["model"]
    left = {r.id for r in Chat.query.filter_by(user_id=u.id).all()}
    assert len(left) == 2 and ids[0] not in left                               # самый старый удалён

    row = srv.db.session.get(Chat, ids[2])
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=400)                    # давно не открывали
    srv.db.session.commit()
    items = c.get("/api/chats", headers=h).get_json()["items"]
    assert [i["id"] for i in items] == [ids[1]]


def test_too_large_body(srv):
    c = srv.app.test_client()
    _login(srv, c)
    h = _h(c)
    cid = c.post("/api/chats", json={}, headers=h).get_json()["id"]
    r = c.put(f"/api/chats/{cid}", data="x" * 700_000, content_type="application/json", headers=h)
    assert r.status_code == 413
    # пустой чат в списке не показывается
    assert c.get("/api/chats", headers=h).get_json()["items"] == []


def test_assistant_reset_rotates_cookie(srv):
    c = srv.app.test_client()
    h = _h(c)
    r = c.post("/api/assistant/chat", json={"message": "видео: кот прыгает"}, headers=h)
    assert r.status_code == 200
    old = c.get_cookie("aish_assist").value
    r = c.post("/api/assistant/chat/reset", json={}, headers=h)
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    new = c.get_cookie("aish_assist")
    assert new.value != old and len(new.value) == 32
    assert c.post("/api/assistant/chat/reset", json={}, headers={"X-Forwarded-For": _ip(c)}).status_code == 403
