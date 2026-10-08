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
import re
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
    """Провайдеры LLM по порядку ASSIST_LLM_ORDER. Без ключа провайдер просто пропускается.

    Бесплатные варианты:
      gigachat   — Сбер, работает из РФ; Freemium физлица: GIGACHAT_AUTH_KEY (ключ авторизации из личного кабинета)
      groq       — бесплатный тариф с лимитами; GROQ_API_KEY
      openrouter — бесплатные модели «:free» (мало запросов в день); OPENROUTER_API_KEY
      omniroute  — свой шлюз; OMNIROUTE_API_KEY
    """
    from .llm import GigaChatAuth

    e = env if env is not None else os.environ
    order = [x.strip() for x in (e.get("ASSIST_LLM_ORDER") or "gigachat,groq,openrouter,omniroute").split(",") if x.strip()]
    omni_base = (e.get("OMNIROUTE_BASE_URL") or "http://127.0.0.1:20128").rstrip("/")
    if not omni_base.endswith("/v1"):
        omni_base += "/v1"
    giga_key = (e.get("GIGACHAT_AUTH_KEY") or e.get("GIGACHAT_CREDENTIALS") or "").strip()
    giga_ca = (e.get("GIGACHAT_CA_BUNDLE") or "").strip() or None
    table = {
        "gigachat": LLMProvider(
            name="gigachat", base_url=e.get("GIGACHAT_BASE_URL") or "https://gigachat.devices.sberbank.ru/api/v1",
            api_key=giga_key, model=e.get("ASSIST_GIGACHAT_MODEL") or "GigaChat-2-Pro",
            timeout=float(e.get("ASSIST_GIGACHAT_TIMEOUT") or 10), json_mode=False, ca_bundle=giga_ca,
            auth=GigaChatAuth(giga_key, scope=e.get("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS", ca_bundle=giga_ca)
            if giga_key else None),
        "omniroute": LLMProvider(
            name="omniroute", base_url=omni_base, api_key=(e.get("OMNIROUTE_API_KEY") or "").strip(),
            model=e.get("ASSIST_OMNIROUTE_MODEL") or e.get("OMNIROUTE_CHAT_MODEL") or "",
            timeout=float(e.get("ASSIST_OMNIROUTE_TIMEOUT") or 7)),
        "groq": LLMProvider(
            name="groq", base_url=e.get("GROQ_BASE_URL") or "https://api.groq.com/openai/v1",
            api_key=(e.get("GROQ_API_KEY") or "").strip(),
            # НЕ наследуем GROQ_CHAT_MODEL/GROQ_MODEL от /api/chat: там часто «думающая» gpt-oss —
            # она медленная и тратит лимит токенов на рассуждения → варианты промпта не успевают → шаблон.
            model=e.get("ASSIST_GROQ_MODEL") or "llama-3.3-70b-versatile",
            timeout=float(e.get("ASSIST_GROQ_TIMEOUT") or 8)),
        "openrouter": LLMProvider(
            name="openrouter", base_url=e.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
            api_key=(e.get("OPENROUTER_API_KEY") or "").strip(),
            model=e.get("ASSIST_OPENROUTER_MODEL") or "meta-llama/llama-3.3-70b-instruct:free",
            timeout=float(e.get("ASSIST_OPENROUTER_TIMEOUT") or 12),
            extra_headers={"X-Title": "AI-shnitsa assistant"}),
    }
    return [table[n] for n in order if n in table]


def build_from_env(models: dict[str, dict] | None = None, price_fn: Callable[[str], Any] | None = None,
                   channel_healthy: Callable[[str], bool] | None = None, redis_client: Any = None,
                   env: dict[str, str] | None = None, transport: Any = None,
                   on_event: Callable[[dict], None] | None = None,
                   cost_fn: Callable[[str, dict], "int | None"] | None = None) -> Assistant:
    """cost_fn(model_id, params) → цена запуска в копейках (как будет считать биллинг). None — посчитаем из price_fn."""
    e = env if env is not None else os.environ
    cards, neighbors = load_cards(e.get("ASSIST_CARDS_PATH") or os.path.join(os.path.dirname(__file__), "data", "model_cards.json"))
    if models is not None:
        listed = {mid for mid, spec in models.items() if spec.get("listed", True) is not False}
        for w in validate(cards.values(), listed):
            log.warning("assistant: %s", w)
        cards = {mid: c for mid, c in cards.items() if mid in listed}  # не советуем то, чего нет в студии
    llm = LLMChain(providers_from_env(e), transport=transport,
                   deadline_sec=float(e.get("ASSIST_LLM_DEADLINE_SEC") or 25),
                   max_tokens=int(e.get("ASSIST_LLM_MAX_TOKENS") or 220))
    deps = AssistantDeps(
        cards=cards, neighbors=neighbors,
        price_fn=price_fn or (lambda _m: None),
        health_fn=make_health_fn(models, channel_healthy) if (models is not None and channel_healthy) else None,
        llm=llm if llm.available else None,
        llm_diag=llm,
        store=RedisStore(redis_client) if redis_client is not None else MemoryStore(),
        vitrina_url=e.get("ASSIST_VITRINA_URL") or "/vitrina.html",
        token_budget=int(e.get("ASSIST_SESSION_TOKEN_BUDGET") or 6000),
        on_event=on_event,
        cost_fn=cost_fn,
        brief=(e.get("ASSIST_BRIEF") or "1").strip().lower() not in {"0", "false", "no"},
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


COOKIE = "aish_assist"
_SID_RX = re.compile(r"^[0-9a-f]{32}$")


def session_key(flask_session: Any, user_id: Any = None, sid: str | None = None) -> str:
    """Ключ памяти — только серверный, не из тела запроса.
    Отдельная cookie `aish_assist` (а не flask session): вход в аккаунт делает session.clear(),
    а разговор должен продолжиться после входа и после пополнения баланса."""
    if sid and _SID_RX.match(sid):
        return sid
    sid = flask_session.get("assist_sid") if hasattr(flask_session, "get") else None
    if not sid:
        sid = uuid.uuid4().hex
        try:
            flask_session["assist_sid"] = sid
        except Exception:
            pass
    return sid


def handle_request(assistant: Assistant, body: Any, flask_session: Any, user_id: Any = None,
                   legacy_autostart: bool = False, sid: str | None = None,
                   account: dict | None = None) -> dict[str, Any]:
    """account — {authed, available_kop, free_left} с СЕРВЕРА (не из тела запроса): по нему ассистент
    перед запуском спрашивает сначала вход, потом пополнение. None — проверка выключена.

    legacy_autostart=True — для старого фронта, который сам запускает генерацию, увидев generate_prompt."""
    body = body if isinstance(body, dict) else {}
    action = body.get("action") if isinstance(body.get("action"), dict) else None
    raw_ctx = dict(body.get("context") or {}) if isinstance(body.get("context"), dict) else {}
    if body.get("selected_model_id") and "selected_model_id" not in raw_ctx:  # формат текущего /api/chat
        raw_ctx["selected_model_id"] = body.get("selected_model_id")
    ctx = clean_context(raw_ctx)          # клиент не может подложить _account/_uid: их нет в CTX_SCHEMA
    if account is not None:
        ctx["_account"] = account
    if user_id is not None:
        ctx["_uid"] = str(user_id)
    out = assistant.handle(_last_user_text(body), ctx, session_key(flask_session, user_id, sid), action)
    out["model"] = "assistant"
    out["channel"] = out["llm"].get("provider") or "rules"
    if legacy_autostart and not (out.get("intent") == "generate_now" and out.get("ready")):
        for k in ("generate_prompt", "generate_model", "generate_params"):
            if k in out:
                out["draft_" + k.split("_", 1)[1]] = out.pop(k)
    return out


def status(assistant: Assistant, account_check: bool | None = None) -> dict[str, Any]:
    """Почему ассистент отвечает шаблоном: провайдеры LLM, ключи, breaker, последняя ошибка, хранилище."""
    d = assistant.d
    chain = d.llm or d.llm_diag
    store = type(d.store).__name__
    redis_ok = None
    if store == "RedisStore":
        try:
            redis_ok = bool(d.store.r.ping())
        except Exception as exc:
            redis_ok = f"error: {exc}"[:120]
    return {
        "llm_enabled": bool(d.llm and d.llm.available),
        "llm_providers": chain.status() if chain else [],
        "deadline_sec": chain.deadline_sec if chain else None,
        "session_store": store, "redis": redis_ok,
        "cards": len(d.cards),
        "account_check": "on" if (d.account_check if account_check is None else account_check) else "off",
        "hint": None if (d.llm and d.llm.available) else
        "LLM выключена: нет ни одного провайдера с ключом и моделью → промпты собираются по шаблону. "
        "Бесплатно: GIGACHAT_AUTH_KEY (Сбер, работает из РФ), GROQ_API_KEY, OPENROUTER_API_KEY или OMNIROUTE_API_KEY. "
        "Проверка вживую: python -m assistant.selfcheck",
    }


def register_assistant(app: Any, assistant: Assistant, url: str = "/api/assistant/chat",
                       user_id_fn: Callable[[], Any] | None = None, decorators: list[Callable] | None = None,
                       legacy_autostart: bool = False, rate: tuple[int, int] | None = (60, 60),
                       account_fn: Callable[[Any], dict | None] | None = None,
                       status_allowed: Callable[[], bool] | None = None) -> None:
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
        asst = app.config.get("ASSISTANT") or assistant
        account = None
        if account_fn:
            try:
                account = account_fn(uid)
            except Exception:
                log.exception("assistant account_fn failed")
                account = None
        sid = request.cookies.get(COOKIE) or ""
        if not _SID_RX.match(sid):
            sid = uuid.uuid4().hex
        resp = jsonify(handle_request(asst, body, session, uid, legacy_autostart, sid=sid, account=account))
        resp.headers["Cache-Control"] = "no-store"
        resp.set_cookie(COOKIE, sid, max_age=6 * 3600, httponly=True, samesite="Lax", secure=request.is_secure)
        return resp

    def status_view():
        allowed = status_allowed() if status_allowed else (os.getenv("FLASK_ENV") or "").lower() != "production"
        if not allowed:
            return jsonify({"error": "forbidden"}), 403
        resp = jsonify(status(app.config.get("ASSISTANT") or assistant, account_check=bool(account_fn)))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    for dec in decorators or []:
        view = dec(view)
    limiter = getattr(app, "extensions", {}).get("rate_limit")
    if limiter and rate:
        view = limiter(rate[0], rate[1], "assistant_chat")(view)
    app.add_url_rule(url, endpoint="api_assistant_chat", view_func=view, methods=["POST"])
    app.add_url_rule(url + "/status", endpoint="api_assistant_status", view_func=status_view, methods=["GET"])
    app.config["ASSISTANT"] = assistant
    assistant.d.account_check = bool(account_fn)
