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
    ip = "10.8.%d.%d" % (id(client) % 250, id(client) // 250 % 250)   # свой «IP»: не упираться в rate-limit
    return client.post("/api/assistant/chat", json=body, headers={"X-CSRF-Token": csrf, "X-Forwarded-For": ip})


def test_cards_match_integrated_models(server):
    from assistant.cards import load_cards

    cards, _ = load_cards()
    missing = set(cards) - set(server.INTEGRATED_MODELS)
    assert not missing, f"карточки без модели в INTEGRATED_MODELS: {missing}"


def test_card_params_match_real_builder(server):
    """Имена params в карточках = ключи payload builder-а; defaults = то, что builder ставит сейчас (без фото)."""
    from assistant.cards import load_cards

    cards, _ = load_cards()
    for mid, card in cards.items():
        if card.needs_image:
            continue  # i2v-only builder без фото кидает ValueError — проверяем ниже с фото
        payload = server._build_provider_input(server.INTEGRATED_MODELS[mid], "x", None, None, None)
        for name in card.params:
            assert name in payload, f"{mid}: параметра {name} нет в payload builder-а {sorted(payload)}"
        for name, val in card.defaults.items():
            if name == "aspect_ratio" and payload.get(name) in ("adaptive", "auto", "match_input_image"):
                continue
            assert payload[name] == val, f"{mid}: default {name}={val!r}, а builder ставит {payload[name]!r}"
    for mid in ("gen4-turbo", "grok-imagine-video-1-5"):
        payload = server._build_provider_input(server.INTEGRATED_MODELS[mid], "x", "data:image/png;base64,AA==", None, None)
        for name in cards[mid].params:
            assert name in payload, (mid, name)


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
    assert d["intent"] == "brief" and d["blocks"][0]["type"] == "brief"
    v = _post(client, {"action": {"type": "variants"}}).get_json()
    assert v["intent"] == "variants" and len(v["blocks"][0]["items"]) >= 2 and v["degraded"] is True
    assert "по шаблону" in v["text"]
    d2 = _post(client, {"action": {"type": "use_variant", "value": "v1"}}).get_json()
    assert d2["intent"] == "use_variant" and len(d2["models"]) >= 2 and d2["blocks"][0]["type"] == "prompt"
    assert d2["blocks"][0]["text"].startswith("Кот в снегу")
    mid = d2["models"][0]["id"]
    assert mid == "seedance-2-5"
    setup = _post(client, {"action": {"type": "pick_model", "value": mid}}).get_json()
    assert setup["generate_model"] == mid and setup["generate_prompt"].startswith("Кот в снегу")
    assert "job_id" not in setup


def test_prices_come_from_catalog(client, server):
    from assistant.render import short_price

    prices = server._integration_prices()
    d = _post(client, {"message": "сделай картинку: логотип кофейни"}).get_json()
    assert d["intent"] in ("brief", "variants")
    _post(client, {"action": {"type": "variants"}})
    d = _post(client, {"action": {"type": "use_variant", "value": "v1"}}).get_json()
    for m in d["models"]:
        assert m["price"] == (short_price(prices.get(m["id"])) or "цена уточняется")


def test_csrf_required(client):
    r = client.post("/api/assistant/chat", json={"message": "привет"})
    assert r.status_code in (400, 403)


def test_assistant_does_not_enqueue(client, monkeypatch):
    import queue_runtime.jobs as jobs

    monkeypatch.setattr(jobs, "enqueue_inbound", lambda *a, **k: (_ for _ in ()).throw(AssertionError("enqueue")))
    _post(client, {"message": "видео: кот"})
    _post(client, {"action": {"type": "variants"}})
    _post(client, {"action": {"type": "use_variant", "value": "v1"}})
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
