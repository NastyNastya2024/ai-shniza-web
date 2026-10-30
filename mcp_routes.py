"""Подключения MCP в аккаунте: каждый пользователь подключает свои MCP-серверы по адресу,
отмечает инструменты — и они появляются кнопками под результатом генерации в студии.

Маршруты (только для вошедших; POST/DELETE — с CSRF, как весь /api):
  GET    /api/mcp                         — мои подключения и их инструменты (без секретов)
  POST   /api/mcp                         — добавить {url, name?, token?} → ok | нужен вход через сервис (oauth_url)
  POST   /api/mcp/<id>                    — изменить {name?, token?}
  DELETE /api/mcp/<id>                    — удалить
  POST   /api/mcp/<id>/refresh            — перечитать инструменты
  POST   /api/mcp/<id>/oauth              — войти через сервис заново → {oauth_url}
  GET    /api/mcp/oauth/callback          — возврат из OAuth → /account?mcp=ok|err#mcp
  POST   /api/mcp/<id>/pins {tools:[…]}   — какие инструменты показывать кнопками в студии (до MCP_MAX_PINS)
  GET    /api/mcp/buttons                 — кнопки для студии
  POST   /api/mcp/form {cid, tool, ctx}   — поля формы инструмента, заполненные результатом генерации
  POST   /api/mcp/call {cid, tool, args}  — выполнить инструмент → {ok, text, links, images}

Каталог (PRESETS) — серверы, проверенные по документации сервисов; любой другой — по адресу.
Сервисы, которые не дают автоматическую регистрацию клиента (например Dropbox пускает только «доверенные»
клиенты), подключаются через приложение {AI}-шницы, зарегистрированное у сервиса владельцем сайта:
  MCP_CLIENTS='{"mcp.dropbox.com": {"client_id": "…", "client_secret": "…"}}'
redirect URI такого приложения: <BASE_URL>/api/mcp/oauth/callback. Можно и вручную в подключении (client_id/secret).

Env: MCP_CLIENTS, MCP_MAX_CONNECTIONS (10), MCP_MAX_PINS (6), BASE_URL / PUBLIC_BASE_URL (адрес сайта для OAuth и ссылок
на результат), MCP_TOKEN_KEY, MCP_ALLOW_HTTP, MCP_ALLOW_PRIVATE, MCP_TIMEOUT — см. mcp_client.py.
Таблица mcp_connections создаётся обычным db.create_all().
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any

import mcp_client as MC

log = logging.getLogger("mcp")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name) or default)))
    except ValueError:
        return default


ERR_TEXT = {
    "bad_url": "Адрес должен быть вида https://сервер/mcp",
    "blocked_host": "Этот адрес ведёт во внутреннюю сеть — такие подключать нельзя",
    "unreachable": "Сервер не отвечает. Проверьте адрес и что он доступен из интернета",
    "timeout": "Сервер не ответил вовремя",
    "http": "Сервер ответил ошибкой",
    "protocol": "Сервер ответил не по протоколу MCP (нужен Streamable HTTP)",
    "auth_required": "Нужно войти через сервис",
    "bad_args": "Проверьте поле",
    "tool_error": "Инструмент вернул ошибку",
    "no_registration": "Сервер не даёт войти автоматически — вставьте токен доступа",
}


PRESETS = [
    # cats: viral | reels | edit | 3d | video | voice | storage ;  auth: oauth (по адресу) | bridge (локально, через мост)
    {"id": "vidiq", "name": "vidIQ", "url": "https://mcp.vidiq.com/mcp", "auth": "oauth", "official": True,
     "cats": ["reels", "viral"], "docs": "https://support.vidiq.com/en/articles/15082430-vidiq-mcp",
     "note": "Reels и YouTube: оценка заголовка и обложки, «выстрелившие» ролики ниши, тренды, публикация. Публиковать — только со входом."},
    {"id": "higgsfield", "name": "Higgsfield", "url": "https://mcp.higgsfield.ai/mcp", "auth": "oauth", "official": True,
     "cats": ["viral", "video"],
     "note": "Virality Predictor: прогноз виральности ролика до 15 с — общий балл 0–100, сила хука, удержание, тепловая карта. "
             "Плюс видео и картинки Higgsfield. Нужна платная подписка Higgsfield."},
    {"id": "viraldecoder", "name": "ViralDecoder", "url": "https://viraldecoder.online/mcp", "auth": "oauth", "official": False,
     "cats": ["viral"], "docs": "https://glama.ai/mcp/connectors/online.viraldecoder/viraldecoder",
     "note": "Разбор чужого Reels / Shorts / TikTok по ссылке: почему залетел, оценка хука, сценарий по той же структуре, "
             "тренды ниши. Не прогноз для своего ролика. Бесплатно 3 разбора в месяц; сервис пока работает нестабильно."},
    {"id": "dropbox", "name": "Dropbox", "url": "https://mcp.dropbox.com/mcp", "auth": "oauth", "official": True,
     "app_required": True, "cats": ["storage"], "docs": "https://help.dropbox.com/integrations/connect-dropbox-mcp-server",
     "note": "Исходники и рендеры: сохранить результат, взять футаж. Нужна регистрация приложения сайта (MCP_CLIENTS)."},
    {"id": "meshy", "name": "Meshy", "url": "", "auth": "bridge", "official": True, "cats": ["3d"],
     "cmd": "npx -y @meshy-ai/meshy-mcp-server", "env": "MESHY_API_KEY", "docs": "https://docs.meshy.ai/en/api/ai",
     "note": "3D-модель из текста или картинки, текстуры. Связка: картинка → Meshy → Blender."},
    {"id": "tripo", "name": "Tripo", "url": "", "auth": "bridge", "official": True, "cats": ["3d"],
     "cmd": "uvx tripo-mcp", "docs": "https://github.com/VAST-AI-Research/tripo-mcp",
     "note": "3D-модель из текста или картинки, сразу в сцену Blender (работает в паре с Blender MCP)."},
    {"id": "davinci", "name": "DaVinci Resolve", "url": "", "auth": "bridge", "official": False, "cats": ["edit"],
     "cmd": "", "docs": "https://github.com/samuelgursky/davinci-resolve-mcp",
     "note": "Таймлайн, монтаж, цветокоррекция, рендер. Resolve должен быть запущен; команда запуска — в инструкции проекта."},
    {"id": "ffmpeg", "name": "Видеоредактор FFmpeg", "url": "", "auth": "bridge", "official": False, "cats": ["edit", "reels"],
     "cmd": "", "docs": "https://playbooks.com/mcp/kush36agrawal-video-editor",
     "note": "Нарезка, склейка, вертикальный кроп, субтитры — без открытого редактора."},
    {"id": "elevenlabs", "name": "ElevenLabs", "url": "", "auth": "bridge", "official": True, "cats": ["voice"],
     "cmd": "uvx elevenlabs-mcp", "env": "ELEVENLABS_API_KEY", "docs": "https://github.com/elevenlabs/elevenlabs-mcp",
     "note": "Озвучка, клонирование голоса, расшифровка — на ключе пользователя. В студии ElevenLabs уже есть без MCP."},
]


def _env_clients() -> dict:
    try:
        v = json.loads(os.getenv("MCP_CLIENTS") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def register_mcp(app: Any, db: Any) -> dict:
    from flask import jsonify, redirect, request, session, url_for

    from security import rate_limit

    class McpConnection(db.Model):
        __tablename__ = "mcp_connections"
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        name = db.Column(db.String(80), nullable=False, default="")
        url = db.Column(db.String(512), nullable=False)
        auth = db.Column(db.String(8), nullable=False, default="none")      # none | token | oauth
        secret = db.Column(db.Text, nullable=False, default="")             # зашифровано: токен / OAuth-токены / клиент
        meta = db.Column(db.Text, nullable=False, default="{}")             # эндпоинты OAuth, сервер (без секретов)
        tools = db.Column(db.Text, nullable=False, default="[]")
        pinned = db.Column(db.Text, nullable=False, default="[]")
        status = db.Column(db.String(8), nullable=False, default="new")     # ok | auth | error | new
        error = db.Column(db.String(300), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=_now)
        updated_at = db.Column(db.DateTime, nullable=False, default=_now)

    def _uid():
        return session.get("user_id")

    def _j(s: str, d: Any) -> Any:
        try:
            v = json.loads(s or "")
            return v if isinstance(v, type(d)) else d
        except ValueError:
            return d

    def _site() -> str:
        base = (os.getenv("BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        return base or request.host_url.rstrip("/")

    def _redirect_uri() -> str:
        base = (os.getenv("BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        return f"{base}/api/mcp/oauth/callback" if base else url_for("mcp_oauth_callback", _external=True)

    def _err(code: str, status: int = 400, **extra: Any):
        return jsonify({"error": code, "message": ERR_TEXT.get(code, "Не получилось"), **extra}), status

    def _view(c: McpConnection) -> dict:
        pins = set(_j(c.pinned, []))
        return {
            "id": c.id, "name": c.name or MC.host_of(c.url), "url": c.url, "host": MC.host_of(c.url), "auth": c.auth,
            "status": c.status, "error": c.error,
            "server": _j(c.meta, {}).get("server", ""),
            "tools": [{"name": t["name"], "title": t.get("title") or t["name"], "description": t.get("description", ""),
                       "readOnly": t.get("readOnly", False), "destructive": t.get("destructive", False),
                       "pinned": t["name"] in pins} for t in _j(c.tools, [])],
        }

    def _own(cid: Any) -> McpConnection | None:
        uid = _uid()
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None
        c = db.session.get(McpConnection, cid)
        return c if c and uid and c.user_id == uid else None

    # ── токены
    def _access_token(c: McpConnection, force_refresh: bool = False) -> str:
        sec = MC.unseal(c.secret)
        if c.auth == "token":
            return sec.get("token", "")
        if c.auth != "oauth":
            return ""
        tok = sec.get("tokens") or {}
        if not tok.get("access_token"):
            raise MC.McpError("auth_required", "no token")
        exp = int(tok.get("expires_at") or 0)
        if force_refresh or (exp and exp < time.time() + 60):
            if not tok.get("refresh_token"):
                raise MC.McpError("auth_required", "expired")
            meta = _j(c.meta, {}).get("oauth") or {}
            tok = MC.refresh_tokens(meta, sec.get("client") or {}, tok["refresh_token"])
            sec["tokens"] = tok
            c.secret = MC.seal(sec)
            db.session.commit()
        return tok["access_token"]

    def _with_session(c: McpConnection, fn):
        """Открыть сессию, выполнить fn(ses); при 401 с OAuth — обновить токен и повторить один раз."""
        for attempt in (0, 1):
            ses = MC.McpSession(c.url, _access_token(c, force_refresh=attempt == 1))
            try:
                ses.initialize()
                return fn(ses)
            except MC.McpError as e:
                if e.code == "auth_required" and attempt == 0 and c.auth == "oauth":
                    continue
                raise
            finally:
                ses.close()

    def _sync_tools(c: McpConnection) -> None:
        def go(ses):
            return ses.server, ses.list_tools()
        info, tools = _with_session(c, go)
        meta = _j(c.meta, {})
        si = info.get("serverInfo") if isinstance(info.get("serverInfo"), dict) else {}
        meta["server"] = str(si.get("title") or si.get("name") or "")[:80]
        c.meta = json.dumps(meta)
        c.tools = json.dumps([MC.compact_tool(t) for t in tools], ensure_ascii=False)
        names = {t["name"] for t in tools}
        c.pinned = json.dumps([p for p in _j(c.pinned, []) if p in names])
        if not c.name:
            c.name = meta["server"] or MC.host_of(c.url)
        c.status, c.error = "ok", ""
        c.updated_at = _now()

    def _start_oauth(c: McpConnection, hint: dict | None = None, back: str = "") -> str:
        meta = _j(c.meta, {})
        oauth = MC.discover(c.url, (hint or {}).get("resource_metadata", ""))
        if (hint or {}).get("scope") and not oauth.get("scope"):
            oauth["scope"] = str(hint["scope"])[:500]
        sec = MC.unseal(c.secret)
        redirect_uri = _redirect_uri()
        client = sec.get("client") or {}
        fixed = sec.get("own_client") or _env_clients().get(MC.host_of(c.url)) or {}
        if isinstance(fixed, dict) and fixed.get("client_id"):    # приложение, зарегистрированное у сервиса вручную
            client = {"client_id": str(fixed["client_id"]), "client_secret": str(fixed.get("client_secret") or ""),
                      "redirect_uri": redirect_uri, "fixed": True}
        elif not client.get("client_id") or client.get("fixed") or meta.get("oauth", {}).get("token_endpoint") != oauth["token_endpoint"] \
                or client.get("redirect_uri") != redirect_uri:
            if not oauth.get("registration_endpoint"):
                raise MC.McpError("no_registration")
            client = MC.register_client(oauth, redirect_uri)
            client["redirect_uri"] = redirect_uri
        verifier, challenge = MC.pkce_pair()
        state = secrets.token_urlsafe(24)
        sec["client"] = client
        sec["pending"] = {"state": state, "verifier": verifier, "ts": int(time.time())}
        meta["oauth"] = oauth
        c.secret, c.meta, c.auth, c.status, c.error = MC.seal(sec), json.dumps(meta), "oauth", "auth", ""
        db.session.commit()
        st = dict(session.get("mcp_oauth") or {})
        st = dict(sorted(st.items(), key=lambda kv: kv[1].get("ts", 0))[-4:])
        st[state] = {"cid": c.id, "ts": int(time.time()), "back": "app" if back == "app" else ""}
        session["mcp_oauth"] = st
        return MC.authorize_url(oauth, client["client_id"], redirect_uri, state, challenge)

    def _connect(c: McpConnection, back: str = "") -> dict:
        """Пробуем подключиться; нужен вход — отдаём ссылку на OAuth."""
        try:
            _sync_tools(c)
            db.session.commit()
            return {"connection": _view(c)}
        except MC.McpError as e:
            if e.code == "auth_required" and c.auth != "token":
                try:
                    url = _start_oauth(c, e.extra, back)
                    return {"connection": _view(c), "oauth_url": url}
                except MC.McpError as e2:
                    code = "no_registration" if e2.code in ("no_registration",) or "registration" in e2.detail else e2.code
                    c.status, c.error = "auth", ERR_TEXT.get(code, "")
                    db.session.commit()
                    return {"connection": _view(c), "need_token": True}
            c.status = "auth" if e.code == "auth_required" else "error"
            c.error = ERR_TEXT.get(e.code, "Не получилось")
            if e.code == "auth_required" and c.auth == "token":
                c.error = "Токен не подошёл"
            db.session.commit()
            return {"connection": _view(c)}

    # ── маршруты
    @app.get("/download/mcp_bridge.py")
    def mcp_bridge_download():
        """Мост для локальных MCP-серверов (Blender и т. п.) — scripts/mcp_bridge.py, скачать файлом."""
        from flask import send_from_directory

        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
        return send_from_directory(root, "mcp_bridge.py", as_attachment=True, mimetype="text/x-python")

    @app.get("/api/mcp")
    def mcp_list():
        uid = _uid()
        if not uid:
            return _err("auth_required", 401)
        rows = McpConnection.query.filter_by(user_id=uid).order_by(McpConnection.id.asc()).all()
        apps = _env_clients()
        presets = [dict(p, ready=not p.get("app_required") or MC.host_of(p["url"]) in apps) for p in PRESETS]
        return jsonify({"connections": [_view(c) for c in rows], "presets": presets,
                        "redirect_uri": _redirect_uri(), "max": _env_int("MCP_MAX_CONNECTIONS", 10, 1, 100),
                        "max_pins": _env_int("MCP_MAX_PINS", 6, 1, 20)})

    @app.post("/api/mcp")
    @rate_limit(20, 60, "mcp_add")
    def mcp_add():
        uid = _uid()
        if not uid:
            return _err("auth_required", 401)
        body = request.get_json(silent=True) or {}
        try:
            url = MC.safe_url(str(body.get("url") or ""))
        except MC.McpError as e:
            return _err(e.code)
        if McpConnection.query.filter_by(user_id=uid).count() >= _env_int("MCP_MAX_CONNECTIONS", 10, 1, 100):
            return _err("too_many", 400)
        if McpConnection.query.filter_by(user_id=uid, url=url).first():
            return _err("exists", 409)
        token = str(body.get("token") or "").strip()[:4000]
        sec: dict = {"token": token} if token else {}
        cid_own = str(body.get("client_id") or "").strip()[:300]
        if cid_own and not token:
            sec["own_client"] = {"client_id": cid_own, "client_secret": str(body.get("client_secret") or "").strip()[:500]}
        c = McpConnection(user_id=uid, url=url, name=str(body.get("name") or "").strip()[:80],
                          auth="token" if token else "none", secret=MC.seal(sec) if sec else "")
        db.session.add(c)
        db.session.commit()
        return jsonify(_connect(c, str(body.get("back") or "")))

    @app.post("/api/mcp/<int:cid>")
    def mcp_update(cid: int):
        c = _own(cid)
        if not c:
            return _err("not_found", 404)
        body = request.get_json(silent=True) or {}
        if "name" in body:
            c.name = str(body.get("name") or "").strip()[:80]
        if "token" in body:
            token = str(body.get("token") or "").strip()[:4000]
            c.auth, c.secret = ("token", MC.seal({"token": token})) if token else ("none", "")
            db.session.commit()
            return jsonify(_connect(c))
        db.session.commit()
        return jsonify({"connection": _view(c)})

    @app.delete("/api/mcp/<int:cid>")
    def mcp_delete(cid: int):
        c = _own(cid)
        if not c:
            return _err("not_found", 404)
        db.session.delete(c)
        db.session.commit()
        return jsonify({"ok": True})

    @app.post("/api/mcp/<int:cid>/refresh")
    @rate_limit(30, 60, "mcp_refresh")
    def mcp_refresh(cid: int):
        c = _own(cid)
        if not c:
            return _err("not_found", 404)
        return jsonify(_connect(c))

    @app.post("/api/mcp/<int:cid>/oauth")
    @rate_limit(20, 60, "mcp_oauth")
    def mcp_oauth_start(cid: int):
        c = _own(cid)
        if not c:
            return _err("not_found", 404)
        try:
            return jsonify({"oauth_url": _start_oauth(c, back=str((request.get_json(silent=True) or {}).get("back") or ""))})
        except MC.McpError as e:
            return _err(e.code if e.code in ERR_TEXT else "protocol")

    @app.get("/api/mcp/oauth/callback", endpoint="mcp_oauth_callback")
    def mcp_oauth_callback():
        state = request.args.get("state") or ""
        st = dict(session.get("mcp_oauth") or {})
        pend = st.pop(state, None) if state else None
        session["mcp_oauth"] = st
        c = _own(pend.get("cid")) if pend else None
        page = "/app" if pend and pend.get("back") == "app" else "/account"
        if not c:
            return redirect("/account?mcp=err#mcp")
        sec = MC.unseal(c.secret)
        p = sec.get("pending") or {}
        if not p or not secrets.compare_digest(str(p.get("state")), state) or time.time() - p.get("ts", 0) > 900 \
                or request.args.get("error") or not request.args.get("code"):
            c.status, c.error = "auth", "Вход не завершён — попробуйте ещё раз"
            db.session.commit()
            return redirect(f"{page}?mcp=err&id={c.id}#mcp")
        meta = _j(c.meta, {}).get("oauth") or {}
        try:
            tok = MC.exchange_code(meta, sec.get("client") or {}, request.args["code"], p["verifier"],
                                   (sec.get("client") or {}).get("redirect_uri") or _redirect_uri())
        except MC.McpError as e:
            log.warning("mcp oauth exchange failed: %s", e)
            c.status, c.error = "auth", "Сервис не выдал доступ — попробуйте войти ещё раз"
            db.session.commit()
            return redirect(f"{page}?mcp=err&id={c.id}#mcp")
        sec.pop("pending", None)
        sec["tokens"] = tok
        c.secret = MC.seal(sec)
        db.session.commit()
        res = _connect(c)
        ok = res["connection"]["status"] == "ok"
        return redirect(f"{page}?mcp={'ok' if ok else 'err'}&id={c.id}#mcp")

    @app.post("/api/mcp/<int:cid>/pins")
    def mcp_pins(cid: int):
        c = _own(cid)
        if not c:
            return _err("not_found", 404)
        want = (request.get_json(silent=True) or {}).get("tools") or []
        names = {t["name"] for t in _j(c.tools, [])}
        pins = [str(x) for x in want if isinstance(x, str) and x in names][: _env_int("MCP_MAX_PINS", 6, 1, 20)]
        c.pinned = json.dumps(pins)
        db.session.commit()
        return jsonify({"connection": _view(c)})

    @app.get("/api/mcp/buttons")
    def mcp_buttons():
        uid = _uid()
        if not uid:
            return jsonify({"buttons": []})
        out = []
        for c in McpConnection.query.filter_by(user_id=uid).order_by(McpConnection.id.asc()).all():
            tools = {t["name"]: t for t in _j(c.tools, [])}
            for name in _j(c.pinned, []):
                t = tools.get(name)
                if t:
                    out.append({"cid": c.id, "tool": name, "title": t.get("title") or name,
                                "conn": c.name or MC.host_of(c.url), "status": c.status})
        return jsonify({"buttons": out})

    def _tool(c: McpConnection, name: str) -> dict | None:
        return next((t for t in _j(c.tools, []) if t["name"] == name), None)

    def _abs(u: str) -> str:
        u = (u or "").strip()
        if u.startswith("/") and not u.startswith("//"):
            return _site() + u
        return u if u.startswith(("https://", "http://")) else ""

    @app.post("/api/mcp/form")
    def mcp_form():
        body = request.get_json(silent=True) or {}
        c = _own(body.get("cid"))
        t = c and _tool(c, str(body.get("tool") or ""))
        if not t:
            return _err("not_found", 404)
        ctx = body.get("ctx") if isinstance(body.get("ctx"), dict) else {}
        ctx = {"url": _abs(str(ctx.get("url") or "")), "prompt": str(ctx.get("prompt") or "")[:4000],
               "text": str(ctx.get("text") or "")[:8000]}
        return jsonify({"cid": c.id, "tool": t["name"], "title": t.get("title") or t["name"],
                        "description": t.get("description", ""), "conn": c.name or MC.host_of(c.url),
                        "destructive": t.get("destructive", False), "status": c.status,
                        "fields": MC.form_fields(t.get("inputSchema") or {}, ctx)})

    @app.post("/api/mcp/call")
    @rate_limit(30, 60, "mcp_call")
    def mcp_call():
        body = request.get_json(silent=True) or {}
        c = _own(body.get("cid"))
        t = c and _tool(c, str(body.get("tool") or ""))
        if not t:
            return _err("not_found", 404)
        try:
            args = MC.coerce_args(t.get("inputSchema") or {}, body.get("args") if isinstance(body.get("args"), dict) else {})
        except MC.McpError as e:
            return _err("bad_args", 400, field=e.detail)
        try:
            res = _with_session(c, lambda ses: ses.call_tool(t["name"], args))
        except MC.McpError as e:
            if e.code == "auth_required":
                c.status, c.error = "auth", "Нужно войти через сервис заново" if c.auth == "oauth" else "Токен не подошёл"
                db.session.commit()
                return _err("auth_required", 401, cid=c.id)
            log.info("mcp call %s/%s failed: %s", MC.host_of(c.url), t["name"], e)
            if e.code == "protocol" and e.detail:
                return _err("tool_error", 502, detail=e.detail[:300])
            return _err(e.code if e.code in ERR_TEXT else "http", 502)
        view = MC.result_view(res)
        return jsonify({"tool": t["name"], "title": t.get("title") or t["name"], "conn": c.name or MC.host_of(c.url), **view})

    return {"McpConnection": McpConnection}
