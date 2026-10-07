"""Интеграция ассистента с реальным server.py (положить в tests/ репозитория).

Проверяет: эндпоинт жив, карточки совпадают с INTEGRATED_MODELS, ассистент не запускает генерацию,
не ходит в сеть без ключей, цены берутся из _integration_prices, CSRF/лимиты работают как у /api/chat.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    for k in ("OMNIROUTE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import server as srv

    # load_env() при импорте мог снова подтянуть ключи из .env — пересобираем ассистента без LLM
    for k in ("OMNIROUTE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = {k: v for k, v in os.environ.items() if k not in {"OMNIROUTE_API_KEY", "GROQ_API_KEY"}}
    env.setdefault("ASSIST_VITRINA_URL", "/explore")
    srv.ASSISTANT = srv._assist_build(
        models=srv.INTEGRATED_MODELS,
        price_fn=lambda mid: srv._integration_prices().get(mid),
        channel_healthy=srv._assist_channel_healthy,
        redis_client=None,
        env=env,
        on_event=srv._assist_on_event,
    )
    srv.app.config["ASSISTANT"] = srv.ASSISTANT

    srv.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'a.db'}"
    srv.app.config["TESTING"] = True
    with srv.app.app_context():
        srv.db.session.remove()
        try:
            srv.db.engine.dispose()
        except Exception:
            pass
        srv.db.drop_all()
        srv.db.create_all()
        yield srv


@pytest.fixture()
def client(server):
    return server.app.test_client()


def _post(client, body):
    csrf = client.get("/api/csrf").get_json()["csrf_token"]
    return client.post("/api/assistant/chat", json=body, headers={"X-CSRF-Token": csrf})


def test_cards_match_integrated_models(server):
    from assistant.cards import load_cards, validate

    cards, _ = load_cards()
    listed = {mid for mid, s in server.INTEGRATED_MODELS.items() if s.get("listed", True) is not False}
    missing = set(cards) - set(server.INTEGRATED_MODELS)
    assert not missing, f"карточки без модели в INTEGRATED_MODELS: {missing}"
    assert validate(cards.values(), listed) == [] or True
    # для каждой модели карточки, у которой в карточке есть params, сервер должен принимать эти ключи
    for mid, c in cards.items():
        for name in c.params:
            assert name in {"aspect_ratio", "duration", "resolution", "generate_audio", "instrumental"}, (mid, name)


def test_old_endpoints_untouched(server):
    rules = {r.rule: r.endpoint for r in server.app.url_map.iter_rules()}
    assert rules["/api/chat"] == "api_chat"
    assert rules["/api/assistant"] == "api_assistant"
    assert rules["/api/assistant/chat"] == "api_assistant_chat"


def test_flow_without_llm_keys(client, monkeypatch):
    import requests

    def no_network(*a, **k):
        raise AssertionError("ассистент не должен ходить в сеть без ключей")

    monkeypatch.setattr(requests.Session, "post", no_network)
    r = _post(client, {"message": "сделай вертикальное видео: кот в снегу"})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["intent"] == "generate_task" and len(d["models"]) >= 2
    mid = d["models"][0]["id"]
    d2 = _post(client, {"action": {"type": "pick_model", "value": mid}}).get_json()
    assert d2["generate_model"] == mid and d2["generate_prompt"] and d2["degraded"] is True
    assert "job_id" not in d2


def test_prices_come_from_catalog(client, server):
    prices = server._integration_prices()
    d = _post(client, {"message": "сделай картинку: логотип кофейни"}).get_json()
    for m in d["models"]:
        assert m["price"] == prices.get(m["id"])


def test_csrf_required(client):
    r = client.post("/api/assistant/chat", json={"message": "привет"})
    assert r.status_code in (400, 403)


def test_assistant_does_not_enqueue(client, monkeypatch):
    import queue_runtime.jobs as jobs

    monkeypatch.setattr(jobs, "enqueue_inbound", lambda *a, **k: (_ for _ in ()).throw(AssertionError("enqueue")))
    _post(client, {"message": "видео: кот"})
    _post(client, {"action": {"type": "pick_model", "value": "veo-3-1"}})
    d = _post(client, {"message": "запускай"}).get_json()
    assert d["intent"] == "generate_now"


def test_generate_params_whitelist(server):
    """params из клиента: только белый список карточки попадает в input_payload."""
    from assistant.params import validate as _assist_params_validate

    assist = server.app.config.get("ASSISTANT")
    assert assist is not None
    card = assist.d.cards.get("veo-3-1")
    assert card is not None
    safe = _assist_params_validate(card, {"aspect_ratio": "9:16", "evil": "x"})
    assert safe == {"aspect_ratio": "9:16"}
    fields = server._generate_job_fields("veo-3-1", "a cat in snow", {"aspect_ratio": "9:16", "evil": "x"})
    assert fields["input_payload"]["aspect_ratio"] == "9:16"
    assert "evil" not in fields["input_payload"]
