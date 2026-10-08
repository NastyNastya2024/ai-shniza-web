"""Текстовые модели: разговор напрямую (без роли навигатора), понятная цена «за ответ», вход/баланс перед запуском."""
from __future__ import annotations

import os
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PRICES = {
    "deepseek-v3-1": "58 ₽ / млн входных токенов", "deepseek-v3-1__full": "58 ₽ / млн входных токенов · 174 ₽ / млн выходных токенов",
    "claude-sonnet-5": "173 ₽ / млн входных токенов", "claude-sonnet-5__full": "173 ₽ / млн входных токенов · 0,86 ₽ / тыс. выходных токенов",
    "omni-auto-free": "Бесплатно", "omni-auto-free__full": "Бесплатно",
}


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("GENERATE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "test-omni")
    import server

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'text.db'}"
    server.app.config["TESTING"] = True
    monkeypatch.setattr(server, "_integration_prices", lambda: dict(PRICES))
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


def test_token_prices_parsed(srv):
    assert srv._text_token_prices("deepseek-v3-1") == pytest.approx((58e-6, 174e-6))
    assert srv._text_token_prices("claude-sonnet-5") == pytest.approx((173e-6, 0.86e-3))
    assert srv._text_token_prices("omni-auto-free") == (0.0, 0.0)


def test_price_per_answer_is_human(srv):
    f = srv._text_price_fields("deepseek-v3-1")
    assert f["price_answer"] == "≈ 0,2 ₽ за ответ"          # 1500 вх × 58/млн + 600 вых × 174/млн
    assert srv._text_price_fields("claude-sonnet-5")["price_answer"] == "≈ 0,78 ₽ за ответ"
    assert srv._text_price_fields("omni-auto-free")["price_answer"] == "бесплатно"


def test_integrations_api_has_answer_price(srv):
    c = srv.app.test_client()
    items = {i["id"]: i for i in c.get("/api/integrations").get_json()["items"]}
    if "deepseek-v3-1" in items:
        assert items["deepseek-v3-1"]["price_answer"].endswith("за ответ")


def test_text_cost_is_per_answer_not_per_million(srv):
    assert srv._generate_cost_kop("deepseek-v3-1", {}) == 20          # ≈ 0,2 ₽, а не 58 ₽
    long = "слово " * 6000                                            # длинный контекст — дороже
    assert srv._generate_cost_kop("deepseek-v3-1", {}, long) > 20
    assert srv._generate_cost_kop("omni-auto-free", {}) == 0


def test_text_models_get_no_navigator_persona(srv):
    spec = srv.INTEGRATED_MODELS["deepseek-v3-1"]
    payload = srv._build_provider_input(spec, "Напиши стих про осень", None, None, None)
    assert payload["prompt"] == "Напиши стих про осень"
    nav = srv._build_provider_input(srv.INTEGRATED_MODELS["assistant"], "привет", None, None, None)
    assert "СИСТЕМНАЯ РОЛЬ" in nav["prompt"]


def _login(srv, c, kop):
    import billing
    u = srv.User(email=f"{uuid.uuid4().hex[:6]}@t.local", provider="password", name="U")
    srv.db.session.add(u)
    srv.db.session.commit()
    bal = billing.get_or_create_balance(srv.db, srv.app.extensions["product_models"]["Balance"], u.id)
    bal.balance_kop = kop
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id


def _gen(c, model):
    csrf = c.get("/api/csrf").get_json()["csrf_token"]
    ip = "10.6.%d.%d" % (uuid.uuid4().int % 250, uuid.uuid4().int % 250)
    return c.post("/api/generate", json={"model": model, "prompt": "Привет! Как дела?"},
                  headers={"X-CSRF-Token": csrf, "X-Forwarded-For": ip})


def test_text_chat_gate(srv, monkeypatch):
    import queue_runtime.jobs as jobs
    monkeypatch.setattr(jobs, "enqueue_inbound", lambda payload: "c" * 24)
    monkeypatch.setattr("queue_runtime.health.is_channel_healthy", lambda ch: True)
    c = srv.app.test_client()
    assert _gen(c, "deepseek-v3-1").status_code == 401                # сначала вход
    _login(srv, c, 10)                                                # 0,10 ₽ — мало
    r = _gen(c, "deepseek-v3-1")
    assert r.status_code == 402 and r.get_json()["need_kop"] == 20
    c2 = srv.app.test_client()
    _login(srv, c2, 100)                                              # 1 ₽ — хватает на несколько ответов
    assert _gen(c2, "deepseek-v3-1").status_code == 202
    c3 = srv.app.test_client()
    _login(srv, c3, 0)
    assert _gen(c3, "omni-auto-free").status_code == 202              # бесплатная — только вход
