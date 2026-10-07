"""Flask-адаптер: эндпоинт, совместимость с /api/chat, чистка контекста, env-провайдеры, health по каналам."""
import pytest

flask = pytest.importorskip("flask")

from assistant.flask_adapter import (build_from_env, clean_context, make_health_fn, providers_from_env,  # noqa: E402
                                     register_assistant)
from assistant_testkit import FakeTransport, ok_json, PRICES  # noqa: E402

MODELS = {mid: {"provider": "replicate"} for mid in PRICES}
MODELS["gen4-turbo"] = {"provider": "replicate", "listed": False}


@pytest.fixture()
def app():
    tr = FakeTransport(omniroute=[("ok", ok_json())])
    env = {"OMNIROUTE_API_KEY": "k", "OMNIROUTE_CHAT_MODEL": "free/x", "GROQ_API_KEY": "g"}
    a = build_from_env(models=MODELS, price_fn=PRICES.get, channel_healthy=lambda ch: True, env=env, transport=tr)
    app = flask.Flask("t")
    app.secret_key = "x"
    register_assistant(app, a)
    app.config["TR"] = tr
    return app


def test_endpoint_flow(app):
    c = app.test_client()
    r = c.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "сделай видео: кот в снегу"}]})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    d = r.get_json()
    assert d["model"] == "assistant" and d["channel"] == "rules" and d["reply"] and len(d["models"]) >= 2
    mid = d["models"][0]["id"]
    d2 = c.post("/api/assistant/chat", json={"action": {"type": "pick_model", "value": mid}, "context": {}}).get_json()
    assert d2["channel"] in {"omniroute", "groq"} and d2["generate_model"] == mid and d2["generate_prompt"]


def test_session_bound_to_cookie_not_body(app):
    c1, c2 = app.test_client(), app.test_client()
    c1.post("/api/assistant/chat", json={"message": "видео: кот"})
    d = c2.post("/api/assistant/chat", json={"action": {"type": "use_mine"}, "session_id": "steal"}).get_json()
    assert not d.get("generate_prompt")


def test_unlisted_model_never_recommended(app):
    c = app.test_client()
    d = c.post("/api/assistant/chat", json={"message": "оживи фото", "context": {"has_image": True}}).get_json()
    assert "gen4-turbo" not in {m["id"] for m in d["models"]}


def test_bad_requests(app):
    c = app.test_client()
    assert c.post("/api/assistant/chat", data="nope", content_type="application/json").status_code == 400
    assert c.post("/api/assistant/chat", json={"message": "x" * 40000}).status_code == 413


def test_clean_context():
    raw = {"selected_model_id": "a" * 500, "has_image": 1, "last_http_status": "402", "job_age_sec": -5,
           "evil": "x", "draft": None, "job_status": "running"}
    ctx = clean_context(raw)
    assert ctx == {"selected_model_id": "a" * 64, "has_image": True, "last_http_status": 402, "job_age_sec": 0.0,
                   "job_status": "running"}
    assert clean_context("str") == {}
    assert clean_context({"last_http_status": "abc"}) == {}


def test_providers_from_env_order_and_defaults():
    ps = providers_from_env({"OMNIROUTE_API_KEY": "k", "OMNIROUTE_BASE_URL": "http://h:20128/", "GROQ_API_KEY": "g",
                             "ASSIST_LLM_ORDER": "groq,omniroute", "ASSIST_OMNIROUTE_MODEL": "m"})
    assert [p.name for p in providers_from_env({"OMNIROUTE_API_KEY": "k", "GROQ_API_KEY": "g"})] == ["groq", "omniroute"]
    assert [p.name for p in ps] == ["groq", "omniroute"]
    assert ps[1].url == "http://h:20128/v1/chat/completions" and ps[1].model == "m"
    assert ps[0].model == "llama-3.1-8b-instant"


def test_no_keys_means_no_llm_and_degraded():
    a = build_from_env(models=MODELS, price_fn=PRICES.get, env={})
    assert a.d.llm is None
    a.handle("видео кот", {}, "s")
    r = a.handle("", {}, "s", action={"type": "pick_model", "value": "veo-3-1"})
    assert r["degraded"]


def test_health_fn_uses_channels():
    models = {"a": {"provider": "replicate"}, "b": {"provider": "fal", "fal_model": "x"}, "c": {"provider": "replicate", "fallback_provider": "fal"}}
    state = {"replicate": False, "fal": True}
    h = make_health_fn(models, lambda ch: state[ch])
    assert h("a") is False and h("b") is True and h("c") is True


def test_health_fn_redis_error_is_open():
    def boom(_):
        raise ConnectionError
    assert make_health_fn({"a": {"provider": "replicate"}}, boom)("a") is True


def test_redis_store_roundtrip_and_errors():
    from assistant.session import RedisStore

    class R:
        def __init__(self):
            self.d = {}

        def get(self, k):
            return self.d.get(k)

        def set(self, k, v, ex=None):
            assert ex == 6 * 3600
            self.d[k] = v

    s = RedisStore(R())
    s.set("x", {"a": 1})
    assert s.get("x") == {"a": 1}

    class Broken:
        def get(self, k):
            raise ConnectionError

        def set(self, *a, **k):
            raise ConnectionError

    b = RedisStore(Broken())
    b.set("x", {})
    assert b.get("x") is None


def test_metrics_hook():
    from assistant.flask_adapter import metrics_hook

    class Row:
        def __init__(self, day_key, total, without_llm):
            self.day_key, self.total, self.without_llm = day_key, total, without_llm

    rows = []

    class Q:
        def filter_by(self, day_key):
            class F:
                def first(_s):
                    return next((r for r in rows if r.day_key == day_key), None)
            return F()

    class Model(Row):
        query = Q()

    class Sess:
        def add(self, r):
            rows.append(r)

        def commit(self):
            pass

        def rollback(self):
            pass

    class DB:
        session = Sess()

    hook = metrics_hook(DB(), Model)
    hook({"llm_used": False})
    hook({"llm_used": True})
    assert rows[0].total == 2 and rows[0].without_llm == 1


def test_legacy_autostart_hides_generate_until_explicit():
    """Старый app.html запускает генерацию, как только видит generate_prompt. Без «запускай» его быть не должно."""
    from assistant.flask_adapter import handle_request
    a = build_from_env(models=MODELS, price_fn=PRICES.get, env={})
    sess = {}
    body = {"messages": [{"role": "user", "content": "видео: кот в снегу 9:16"}], "selected_model_id": "veo-3-1"}
    handle_request(a, body, sess, None, legacy_autostart=True)
    d = handle_request(a, {"action": {"type": "pick_model", "value": "veo-3-1"}}, sess, None, legacy_autostart=True)
    assert "generate_prompt" not in d and d["draft_prompt"] and d["draft_model"] == "veo-3-1"
    d2 = handle_request(a, {"messages": [{"role": "user", "content": "запускай"}]}, sess, None, legacy_autostart=True)
    assert d2["intent"] == "generate_now" and d2["generate_prompt"] and d2["generate_model"] == "veo-3-1"


def test_top_level_selected_model_id_is_used():
    from assistant.flask_adapter import handle_request
    a = build_from_env(models=MODELS, price_fn=PRICES.get, env={})
    d = handle_request(a, {"messages": [{"role": "user", "content": "почему ошибка"}], "selected_model_id": "veo-3-1",
                           "context": {"last_error": "channel_unavailable"}}, {}, None)
    assert "veo-3-1" not in {m["id"] for m in d["models"]} and d["models"]


def test_uses_app_rate_limiter():
    calls = []

    def rate_limit(limit, window, prefix):
        calls.append((limit, window, prefix))
        return lambda f: f

    a = build_from_env(models=MODELS, price_fn=PRICES.get, env={})
    app = flask.Flask("t2")
    app.secret_key = "x"
    app.extensions["rate_limit"] = rate_limit
    register_assistant(app, a)
    assert calls == [(30, 60, "assistant_chat")]
    assert "api_assistant_chat" in app.view_functions
