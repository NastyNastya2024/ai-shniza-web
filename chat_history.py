"""История переписки в студии (/app): хранится в аккаунте, исходные файлы — нет.

Что храним: текст сообщений, имена прикреплённых файлов (тип + имя), ссылку на готовый результат,
карточки ответа помощника (без кнопок). Чего НЕ храним: сами файлы и их номера upl_… — файлы живут
24 часа (UPLOAD_TTL_SEC), а в истории остаётся только «Фото: cat.png».

API (только для вошедших, иначе 401 auth_required; CSRF — общий before_request из security.py):
  GET    /api/chats              → {items: [{id, title, n, updated_at}], days, max}
  POST   /api/chats              → {id, ...}   тело: {messages?: [...]} — новый чат (в т.ч. перенос гостевого)
  GET    /api/chats/<id>         → {id, title, messages, updated_at}
  PUT    /api/chats/<id>         → {ok, id, n}  тело: {messages: [...]} — снимок целиком
  DELETE /api/chats/<id>         → {ok}

Лимиты (env): CHAT_MAX_THREADS (100 чатов на человека, старые удаляются),
CHAT_HISTORY_DAYS (30 дней с последнего сообщения — потом чат удаляется), CHAT_MAX_MESSAGES (200 последних сообщений в чате).
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from assistant.files import clean_attachments

MAX_TEXT = 4000
MAX_ASSIST_JSON = 20_000
MAX_BODY = 600_000
ROLES = ("user", "bot")
MEDIA_KINDS = ("image", "video", "audio", "music")
BLOCK_TYPES = ("models", "prompt", "params", "summary", "brief", "variants")
_URL_RX = re.compile(r"^(https?://[^\s\"'<>]{1,1000}|/[^\s\"'<>]{0,1000})$")
_ID_RX = re.compile(r"^c_[0-9a-f]{20}$")


def _now() -> datetime:
    """UTC без tzinfo — как остальные DateTime-колонки в проекте."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.getenv(name) or default)
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def limits() -> dict[str, int]:
    return {
        "threads": _env_int("CHAT_MAX_THREADS", 100, 1, 1000),
        "days": _env_int("CHAT_HISTORY_DAYS", 30, 1, 3650),
        "messages": _env_int("CHAT_MAX_MESSAGES", 200, 10, 1000),
    }


def _text(v: Any, n: int = MAX_TEXT) -> str:
    s = v if isinstance(v, str) else ("" if v is None else str(v))
    s = s.replace("\x00", "")
    return s[:n]


def _url(v: Any) -> str:
    s = _text(v, 1000).strip()
    if not s or s.startswith("//") or not _URL_RX.match(s):
        return ""
    return s


def _assistant(raw: Any) -> dict | None:
    """Ответ помощника для перерисовки: текст + карточки. Кнопки (chips) не храним — в истории они не нажимаются."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {"text": _text(raw.get("text") or raw.get("reply") or "")}
    if raw.get("lang") in ("ru", "en"):
        out["lang"] = raw["lang"]
    blocks = [b for b in (raw.get("blocks") or []) if isinstance(b, dict) and b.get("type") in BLOCK_TYPES]
    if blocks:
        out["blocks"] = blocks[:8]
        if len(json.dumps(out, ensure_ascii=False)) > MAX_ASSIST_JSON:
            out.pop("blocks")   # слишком большая карточка — остаётся только текст
    return out


def clean_message(raw: Any) -> dict | None:
    """Одно сообщение с фронта → только безопасные поля. Номера файлов upl_… и прочее — отбрасываются."""
    if not isinstance(raw, dict):
        return None
    role = raw.get("role")
    if role not in ROLES:
        return None
    m: dict[str, Any] = {"role": role, "text": _text(raw.get("text"))}
    try:
        ts = int(raw.get("ts") or 0)
        if 1_500_000_000_000 < ts < 4_000_000_000_000:
            m["ts"] = ts
    except (TypeError, ValueError):
        pass
    files = clean_attachments(raw.get("files"))
    if files:
        m["files"] = files
    if role == "bot":
        a = _assistant(raw.get("assistant"))
        if a is not None:
            m["assistant"] = a
            if not m["text"]:
                m["text"] = a["text"]
        if raw.get("result"):
            m["result"] = True
            url = _url(raw.get("mediaUrl"))
            if url:
                m["mediaUrl"] = url
            mk = raw.get("mediaKind")
            m["mediaKind"] = mk if mk in MEDIA_KINDS else "image"
        wid = raw.get("workId")
        if isinstance(wid, (int, str)) and re.match(r"^[A-Za-z0-9_-]{1,64}$", str(wid)):
            m["workId"] = str(wid)
        for flag in ("job", "loginCta", "topup", "published"):
            if raw.get(flag):
                m[flag] = True
    if not m["text"] and not m.get("files") and not m.get("result") and "assistant" not in m:
        return None
    return m


def clean_messages(raw: Any, max_messages: int | None = None) -> list[dict]:
    if not isinstance(raw, list):
        return []
    n = max_messages or limits()["messages"]
    out = [m for m in (clean_message(x) for x in raw[-n * 2:]) if m]
    return out[-n:]


def title_of(messages: list[dict]) -> str:
    for m in messages:
        if m["role"] == "user" and m.get("text", "").strip():
            t = " ".join(m["text"].split())
            return t[:60] + ("…" if len(t) > 60 else "")
    for m in messages:
        if m.get("files"):
            return m["files"][0]["name"][:60]
    return ""


def register_chat_history(app: Any, db: Any, user_id_fn: Callable[[], Any] | None = None) -> dict:
    """Модель AssistantChat + маршруты /api/chats. Таблица assistant_chats создаётся обычным db.create_all()
    (wsgi.py и __main__ в server.py вызывают его при старте)."""
    from flask import jsonify, request, session

    class AssistantChat(db.Model):
        __tablename__ = "assistant_chats"
        id = db.Column(db.String(24), primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        title = db.Column(db.String(120), nullable=False, default="")
        messages = db.Column(db.Text, nullable=False, default="[]")
        n_messages = db.Column(db.Integer, nullable=False, default=0)
        created_at = db.Column(db.DateTime, nullable=False, default=_now)
        updated_at = db.Column(db.DateTime, nullable=False, default=_now, index=True)

    uid_fn = user_id_fn or (lambda: session.get("user_id"))

    def _uid():
        try:
            return uid_fn()
        except Exception:
            return None

    def _iso(dt: datetime | None) -> str:
        return (dt or _now()).replace(microsecond=0).isoformat() + "Z"

    def _purge(uid: Any) -> None:
        """Ленивая чистка: старше CHAT_HISTORY_DAYS и сверх CHAT_MAX_THREADS."""
        lim = limits()
        cutoff = _now() - timedelta(days=lim["days"])
        AssistantChat.query.filter(AssistantChat.user_id == uid, AssistantChat.updated_at < cutoff).delete(
            synchronize_session=False)
        extra = (AssistantChat.query.filter_by(user_id=uid).order_by(AssistantChat.updated_at.desc())
                 .offset(lim["threads"]).all())
        for row in extra:
            db.session.delete(row)
        db.session.commit()

    def _body_messages():
        if request.content_length and request.content_length > MAX_BODY:
            return None, (jsonify({"error": "too_large"}), 413)
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return None, (jsonify({"error": "bad_json"}), 400)
        return clean_messages(body.get("messages")), None

    def _own(chat_id: str):
        uid = _uid()
        if not uid:
            return None, (jsonify({"error": "auth_required"}), 401)
        if not _ID_RX.match(chat_id or ""):
            return None, (jsonify({"error": "not_found"}), 404)
        row = db.session.get(AssistantChat, chat_id)
        if not row or row.user_id != uid:
            return None, (jsonify({"error": "not_found"}), 404)
        return row, None

    def _nocache(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def chats_list():
        uid = _uid()
        if not uid:
            return jsonify({"error": "auth_required"}), 401
        _purge(uid)
        lim = limits()
        rows = (AssistantChat.query.filter_by(user_id=uid).order_by(AssistantChat.updated_at.desc())
                .limit(lim["threads"]).all())
        return _nocache(jsonify({
            "items": [{"id": r.id, "title": r.title, "n": r.n_messages, "updated_at": _iso(r.updated_at)}
                      for r in rows if r.n_messages > 0],
            "days": lim["days"], "max": lim["threads"],
        }))

    def chats_create():
        uid = _uid()
        if not uid:
            return jsonify({"error": "auth_required"}), 401
        msgs, err = _body_messages()
        if err:
            return err
        now = _now()
        row = AssistantChat(id="c_" + secrets.token_hex(10), user_id=uid, title=title_of(msgs),
                            messages=json.dumps(msgs, ensure_ascii=False), n_messages=len(msgs),
                            created_at=now, updated_at=now)
        db.session.add(row)
        db.session.commit()
        _purge(uid)
        return _nocache(jsonify({"ok": True, "id": row.id, "n": row.n_messages, "updated_at": _iso(row.updated_at)})), 201

    def chats_get(chat_id):
        row, err = _own(chat_id)
        if err:
            return err
        try:
            msgs = json.loads(row.messages or "[]")
        except ValueError:
            msgs = []
        return _nocache(jsonify({"id": row.id, "title": row.title, "messages": msgs, "updated_at": _iso(row.updated_at)}))

    def chats_put(chat_id):
        row, err = _own(chat_id)
        if err:
            return err
        msgs, err = _body_messages()
        if err:
            return err
        row.messages = json.dumps(msgs, ensure_ascii=False)
        row.n_messages = len(msgs)
        row.title = title_of(msgs) or row.title
        row.updated_at = _now()
        db.session.commit()
        return _nocache(jsonify({"ok": True, "id": row.id, "n": row.n_messages, "updated_at": _iso(row.updated_at)}))

    def chats_delete(chat_id):
        row, err = _own(chat_id)
        if err:
            return err
        db.session.delete(row)
        db.session.commit()
        return _nocache(jsonify({"ok": True}))

    views = {
        "api_chats_list": (chats_list, "/api/chats", ["GET"], (120, 60)),
        "api_chats_create": (chats_create, "/api/chats", ["POST"], (30, 60)),
        "api_chats_get": (chats_get, "/api/chats/<chat_id>", ["GET"], (120, 60)),
        "api_chats_put": (chats_put, "/api/chats/<chat_id>", ["PUT"], (120, 60)),
        "api_chats_delete": (chats_delete, "/api/chats/<chat_id>", ["DELETE"], (30, 60)),
    }
    limiter = getattr(app, "extensions", {}).get("rate_limit")
    for endpoint, (fn, url, methods, rate) in views.items():
        view = limiter(rate[0], rate[1], endpoint)(fn) if limiter else fn
        app.add_url_rule(url, endpoint=endpoint, view_func=view, methods=methods)

    ext = {"model": AssistantChat}
    app.extensions["chat_history"] = ext
    return ext
