"""Перед генерацией: сначала вход, потом баланс — и в /api/generate, и в вопросах ассистента."""
from __future__ import annotations

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
    # ключи могли подтянуться из .env при import server — убираем и пересобираем ASSISTANT
    for k in ("OMNIROUTE_API_KEY", "GROQ_API_KEY", "ASSIST_GROQ_API_KEY", "ASSIST_OMNIROUTE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import server

    for k in ("OMNIROUTE_API_KEY", "GROQ_API_KEY", "ASSIST_GROQ_API_KEY", "ASSIST_OMNIROUTE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    server.ASSISTANT = server._assist_build(
        models=server.INTEGRATED_MODELS,
        price_fn=lambda mid: server._integration_prices().get(mid),
        channel_healthy=server._assist_channel_healthy,
        redis_client=None,
        on_event=server._assist_on_event,
        cost_fn=server._generate_cost_kop,
    )
    server.app.config["ASSISTANT"] = server.ASSISTANT

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'gate.db'}"
    server.app.config["TESTING"] = True
    monkeypatch.setattr(server, "_integration_prices", lambda: {
        "veo-3-1": "17 ₽ / секунда", "seedream-5-pro": "3,9 ₽ / изображение at 1K", "kling-v2-5-turbo-pro": "6 ₽ / секунда",
        "ideogram-v3-turbo": "бесплатно"})
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


def _login(srv, c, balance_kop=0):
    import billing

    u = srv.User(email=f"u{balance_kop}@t.local", provider="password", name="U")
    srv.db.session.add(u)
    srv.db.session.commit()
    bal = billing.get_or_create_balance(srv.db, srv.app.extensions["product_models"]["Balance"], u.id)
    bal.balance_kop = balance_kop
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id
    return u


def _gen(c, model="veo-3-1", params=None):
    body = {"model": model, "prompt": "a cat"}
    if params:
        body["params"] = params
    import uuid
    ip = "10.7.%d.%d" % (uuid.uuid4().int % 250, uuid.uuid4().int % 250)   # свой «IP»: не упираться в общий rate-limit
    return c.post("/api/generate", json=body, headers={"X-CSRF-Token": _csrf(c), "X-Forwarded-For": ip})


def _chat(c, body):
    # свой «IP» на клиента: тесты не упираются в общий rate-limit
    ip = getattr(c, "_ip", None) or setattr(c, "_ip", "10.9.%d.%d" % (id(c) % 250, id(c) // 250 % 250)) or c._ip
    return c.post("/api/assistant/chat", json=body, headers={"X-CSRF-Token": _csrf(c), "X-Forwarded-For": ip}).get_json()


# ---------------- /api/generate: сервер не пускает без входа и денег
def test_generate_anonymous_is_401(srv):
    r = _gen(srv.app.test_client())
    assert r.status_code == 401 and r.get_json()["error"] == "auth_required"


def test_generate_low_balance_is_402_with_amounts(srv):
    c = srv.app.test_client()
    _login(srv, c, balance_kop=1000)                    # 10 ₽, а Veo 8 с × 17 ₽ = 136 ₽
    r = _gen(c)
    d = r.get_json()
    assert r.status_code == 402 and d["error"] == "insufficient_funds"
    assert d["need_kop"] == 13600 and d["available_kop"] == 1000


def test_generate_duration_param_changes_need(srv, monkeypatch):
    monkeypatch.setenv("ASSIST_BILLING_USE_PARAMS", "1")
    c = srv.app.test_client()
    _login(srv, c, balance_kop=1000)
    d = _gen(c, params={"duration": 4}).get_json()
    assert d["need_kop"] == 6800


def test_generate_enough_balance_passes_gate(srv, monkeypatch):
    c = srv.app.test_client()
    _login(srv, c, balance_kop=50000)
    import queue_runtime.jobs as jobs
    monkeypatch.setattr(jobs, "enqueue_inbound", lambda payload: "a" * 24)
    monkeypatch.setattr("queue_runtime.health.is_channel_healthy", lambda ch: True)
    r = _gen(c)
    assert r.status_code == 202, r.get_json()


def test_free_model_needs_login_only(srv, monkeypatch):
    c = srv.app.test_client()
    assert _gen(c, model="ideogram-v3-turbo").status_code == 401
    _login(srv, c, balance_kop=0)
    import queue_runtime.jobs as jobs
    monkeypatch.setattr(jobs, "enqueue_inbound", lambda payload: "b" * 24)
    monkeypatch.setattr("queue_runtime.health.is_channel_healthy", lambda ch: True)
    assert _gen(c, model="ideogram-v3-turbo").status_code == 202


# ---------------- ассистент: тот же порядок вопросов
def test_assistant_asks_login_then_topup_then_generate(srv):
    c = srv.app.test_client()
    d = _chat(c, {"message": "видео: кот жарит яичницу"})
    assert d["intent"] == "brief"                      # сначала уточняем детали, потом модель
    d = _chat(c, {"action": {"type": "variants"}})
    assert d["intent"] == "variants" and len(d["blocks"][0]["items"]) >= 2
    d = _chat(c, {"action": {"type": "use_variant", "value": "v1"}})
    assert d["intent"] == "use_variant" and len(d["models"]) >= 2
    d = _chat(c, {"action": {"type": "pick_model", "value": "veo-3-1"}})
    assert d["gate"] == "login" and d["ready"] is False
    assert d["chips"][0]["action"] == "login" and not any(x["action"] == "generate" for x in d["chips"])
    assert "войдите" in d["text"]

    u = _login(srv, c, balance_kop=1000)               # вошли (session.clear в реальном входе не мешает: своя cookie)
    with c.session_transaction() as s:
        s.clear()
        s["user_id"] = u.id
    d = _chat(c, {"action": {"type": "resume"}})
    assert d["intent"] == "resume" and d["gate"] == "topup"
    assert d["chips"][0]["action"] == "open_topup" and any(x["action"] == "resume" for x in d["chips"])
    assert "10 ₽" in d["text"] and "136 ₽" in d["text"]
    assert d["generate_prompt"]                        # промпт и параметры не потерялись после входа

    bal = __import__("billing").get_or_create_balance(srv.db, srv.app.extensions["product_models"]["Balance"], u.id)
    bal.balance_kop = 20000
    srv.db.session.commit()
    d = _chat(c, {"action": {"type": "resume"}})
    assert d["gate"] == "ok" and d["ready"] is True and d["chips"][0]["action"] == "generate"
    assert "136 ₽" in d["text"]


def test_assistant_cookie_survives_session_clear(srv):
    c = srv.app.test_client()
    _chat(c, {"message": "картинка: логотип кофейни"})
    _chat(c, {"action": {"type": "variants"}})
    _chat(c, {"action": {"type": "use_variant", "value": "v1"}})
    _chat(c, {"action": {"type": "pick_model", "value": "seedream-5-pro"}})
    with c.session_transaction() as s:
        s.clear()                                      # так делает вход в auth.py
    d = _chat(c, {"action": {"type": "resume"}})
    assert d["intent"] == "resume" and d["generate_model"] == "seedream-5-pro"


def test_client_cannot_fake_account(srv):
    c = srv.app.test_client()
    _chat(c, {"message": "видео: кот"})
    _chat(c, {"action": {"type": "variants"}})
    _chat(c, {"action": {"type": "use_variant", "value": "v1"}})
    d = _chat(c, {"action": {"type": "pick_model", "value": "veo-3-1"},
                  "context": {"_account": {"authed": True, "available_kop": 10 ** 9}}})
    assert d["gate"] == "login"


def test_status_endpoint_explains_template_mode(srv):
    c = srv.app.test_client()
    d = c.get("/api/assistant/chat/status").get_json()
    assert d["llm_enabled"] is False and "GROQ_API_KEY" in d["hint"]
    assert {p["name"] for p in d["llm_providers"]} == {"gigachat", "groq", "openrouter", "omniroute"}
    assert all(p["why_disabled"] == "нет ключа" for p in d["llm_providers"])
    assert d["account_check"] == "on"
    assert "test-token" not in str(d)
