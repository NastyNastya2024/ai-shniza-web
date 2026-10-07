"""Подключение ассистента к Flask-приложению {AI}-шницы.

    from assistant.flask_adapter import build_from_env, register_assistant
    assistant = build_from_env(
        models=INTEGRATED_MODELS,                       # dict id → spec (provider, fal_model, listed…)
        price_fn=lambda mid: _integration_prices().get(mid),
        channel_healthy=queue_runtime.health.is_channel_healthy,
        redis_client=get_redis(),                       # тот же клиент, что у очередей (decode_responses=True)
    )
    register_assistant(app, assistant)                  # POST /api/assistant/chat

Эндпоинт синхронный, но короткий: правила — миллисекунды, LLM — не дольше ASSIST_LLM_DEADLINE_SEC (12 с).
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import uuid
from typing import Any, Callable

from .cards import load_cards, validate
from .engine import Assistant, AssistantDeps
from .llm import LLMChain, LLMProvider
from .session import MemoryStore, RedisStore

log = logging.getLogger("assistant")

CTX_SCHEMA: dict[str, tuple[type, int]] = {
    "selected_model_id": (str, 64),
    "has_image": (bool, 0),
    "last_error": (str, 40),
    "last_http_status": (int, 0),
    "job_status": (str, 20),
    "job_age_sec": (float, 0),
    "job_failover": (bool, 0),
    "draft": (str, 1000),
    "lang": (str, 2),
}


def clean_context(raw: Any) -> dict[str, Any]:
    """Контекст приходит с фронта — доверять нельзя: только известные ключи, типы и длины."""
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, (typ, max_len) in CTX_SCHEMA.items():
        v = raw.get(key)
        if v is None:
            continue
        try:
            if typ is bool:
                out[key] = bool(v)
            elif typ is int:
                out[key] = int(v)
            elif typ is float:
                out[key] = max(0.0, float(v))
            else:
                out[key] = str(v)[:max_len]
        except (TypeError, ValueError):
            continue
    return out


def make_health_fn(models: dict[str, dict], channel_healthy: Callable[[str], bool]) -> Callable[[str], bool]:
    """Модель доступна, если жив её основной канал ИЛИ резерв (fal_model → канал fal)."""

    def health(mid: str) -> bool:
        spec = models.get(mid) or {}
        chans = [spec.get("provider") or "replicate"]
        if spec.get("fal_model") or spec.get("fallback_provider") == "fal":
            chans.append("fal")
        for ch in chans:
            try:
                if channel_healthy(ch):
                    return True
            except Exception:
                return True
        return False

    return health


def providers_from_env(env: dict[str, str] | None = None) -> list[LLMProvider]:
    e = env if env is not None else os.environ
    order = [x.strip() for x in (e.get("ASSIST_LLM_ORDER") or "groq,omniroute").split(",") if x.strip()]
    omni_base = (e.get("OMNIROUTE_BASE_URL") or "http://127.0.0.1:20128").rstrip("/")
    if not omni_base.endswith("/v1"):
        omni_base += "/v1"
    table = {
        "omniroute": LLMProvider(
            name="omniroute", base_url=omni_base, api_key=(e.get("OMNIROUTE_API_KEY") or "").strip(),
            model=e.get("ASSIST_OMNIROUTE_MODEL") or e.get("OMNIROUTE_CHAT_MODEL") or "",
            timeout=float(e.get("ASSIST_OMNIROUTE_TIMEOUT") or 7)),
        "groq": LLMProvider(
            name="groq", base_url=e.get("GROQ_BASE_URL") or "https://api.groq.com/openai/v1",
            api_key=(e.get("GROQ_API_KEY") or "").strip(),
            model=e.get("ASSIST_GROQ_MODEL") or e.get("GROQ_CHAT_MODEL") or "llama-3.1-8b-instant",
            timeout=float(e.get("ASSIST_GROQ_TIMEOUT") or 5)),
    }
    return [table[n] for n in order if n in table]


def build_from_env(models: dict[str, dict] | None = None, price_fn: Callable[[str], Any] | None = None,
                   channel_healthy: Callable[[str], bool] | None = None, redis_client: Any = None,
                   env: dict[str, str] | None = None, transport: Any = None,
                   on_event: Callable[[dict], None] | None = None) -> Assistant:
    e = env if env is not None else os.environ
    cards, neighbors = load_cards(e.get("ASSIST_CARDS_PATH") or os.path.join(os.path.dirname(__file__), "data", "model_cards.json"))
    if models is not None:
        listed = {mid for mid, spec in models.items() if spec.get("listed", True) is not False}
        for w in validate(cards.values(), listed):
            log.warning("assistant: %s", w)
        cards = {mid: c for mid, c in cards.items() if mid in listed}  # не советуем то, чего нет в студии
    llm = LLMChain(providers_from_env(e), transport=transport,
                   deadline_sec=float(e.get("ASSIST_LLM_DEADLINE_SEC") or 12),
                   max_tokens=int(e.get("ASSIST_LLM_MAX_TOKENS") or 220))
    deps = AssistantDeps(
        cards=cards, neighbors=neighbors,
        price_fn=price_fn or (lambda _m: None),
        health_fn=make_health_fn(models, channel_healthy) if (models is not None and channel_healthy) else None,
        llm=llm if llm.available else None,
        store=RedisStore(redis_client) if redis_client is not None else MemoryStore(),
        vitrina_url=e.get("ASSIST_VITRINA_URL") or "/vitrina.html",
        token_budget=int(e.get("ASSIST_SESSION_TOKEN_BUDGET") or 6000),
        on_event=on_event,
    )
    return Assistant(deps)


def metrics_hook(db: Any, metric_model: Any) -> Callable[[dict], None]:
    """Инкремент assistant_metrics (total, without_llm) за день. Вызывается внутри запроса."""

    def hook(ev: dict) -> None:
        day = _dt.date.today().isoformat()
        row = metric_model.query.filter_by(day_key=day).first()
        if row is None:
            row = metric_model(day_key=day, total=0, without_llm=0)
            db.session.add(row)
        row.total = (row.total or 0) + 1
        if not ev.get("llm_used"):
            row.without_llm = (row.without_llm or 0) + 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return hook


def _last_user_text(body: dict) -> str:
    if isinstance(body.get("message"), str):
        return body["message"]
    for m in reversed(body.get("messages") or []):
        if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def session_key(flask_session: Any, user_id: Any = None) -> str:
    """Ключ памяти — только серверный (cookie-сессия + пользователь), не из тела запроса."""
    sid = flask_session.get("assist_sid")
    if not sid:
        sid = uuid.uuid4().hex
        flask_session["assist_sid"] = sid
    return f"{user_id or 'anon'}:{sid}"


def handle_request(assistant: Assistant, body: Any, flask_session: Any, user_id: Any = None,
                   legacy_autostart: bool = False) -> dict[str, Any]:
    """legacy_autostart=True — для СТАРОГО фронта (app.html/generate.js), который запускает генерацию,
    как только видит generate_prompt в ответе. Тогда отдаём generate_* только на явное «запускай»
    (intent=generate_now и всё уточнено), а в остальных ответах кладём их в draft_* — фронт их игнорирует,
    и деньги без подтверждения не тратятся. Новый фронт с кнопками: legacy_autostart=False.
    """
    body = body if isinstance(body, dict) else {}
    action = body.get("action") if isinstance(body.get("action"), dict) else None
    raw_ctx = dict(body.get("context") or {}) if isinstance(body.get("context"), dict) else {}
    if body.get("selected_model_id") and "selected_model_id" not in raw_ctx:  # формат текущего /api/chat
        raw_ctx["selected_model_id"] = body.get("selected_model_id")
    out = assistant.handle(_last_user_text(body), clean_context(raw_ctx), session_key(flask_session, user_id), action)
    # совместимость с текущим фронтом /api/chat: reply, model, channel, generate_prompt?, generate_model?
    out["model"] = "assistant"
    out["channel"] = out["llm"].get("provider") or "rules"
    if legacy_autostart and not (out.get("intent") == "generate_now" and out.get("ready")):
        for k in ("generate_prompt", "generate_model", "generate_params"):
            if k in out:
                out["draft_" + k.split("_", 1)[1]] = out.pop(k)
    return out


def register_assistant(app: Any, assistant: Assistant, url: str = "/api/assistant/chat",
                       user_id_fn: Callable[[], Any] | None = None, decorators: list[Callable] | None = None,
                       legacy_autostart: bool = False, rate: tuple[int, int] | None = (30, 60)) -> None:
    """Регистрирует POST {url}. ВНИМАНИЕ: /api/assistant уже занят старым studio.js — поэтому по умолчанию /api/assistant/chat.
    Если в app.extensions есть rate_limit (security.apply_rate_limits) — оборачиваем им же: rate=(лимит, окно сек)."""
    from flask import jsonify, request, session

    def view():
        if request.content_length and request.content_length > 32_000:
            return jsonify({"error": "too_large"}), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "bad_json"}), 400
        uid = None
        if user_id_fn:
            try:
                uid = user_id_fn()
            except Exception:
                uid = None
        # app.config["ASSISTANT"] — чтобы тесты/горячая пересборка могли подменить инстанс
        active = app.config.get("ASSISTANT") or assistant
        resp = jsonify(handle_request(active, body, session, uid, legacy_autostart))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    for dec in decorators or []:
        view = dec(view)
    limiter = getattr(app, "extensions", {}).get("rate_limit")
    if limiter and rate:
        view = limiter(rate[0], rate[1], "assistant_chat")(view)
    app.add_url_rule(url, endpoint="api_assistant_chat", view_func=view, methods=["POST"])
    app.config["ASSISTANT"] = assistant
