"""Подключения MCP: клиент (Streamable HTTP, SSE, OAuth 2.1 + PKCE), защита адресов, маршруты /api/mcp.

Поддельный MCP-сервер поднимается в потоке на 127.0.0.1 (поэтому в тестах MCP_ALLOW_HTTP / MCP_ALLOW_PRIVATE)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mcp_client as MC  # noqa: E402

TOOLS = [
    {"name": "echo", "title": "Эхо", "description": "Повторяет текст", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "publish_video", "description": "Опубликовать видео",
     "inputSchema": {"type": "object", "required": ["video_url", "title"], "properties": {
         "video_url": {"type": "string", "format": "uri"}, "title": {"type": "string"},
         "private": {"type": "boolean", "default": True}, "tags": {"type": "array", "items": {"type": "string"}},
         "count": {"type": "integer"}, "visibility": {"type": "string", "enum": ["public", "unlisted"], "default": "unlisted"}}}},
]


class FakeMcp:
    """Мини-сервер: /mcp (JSON-RPC, ответы JSON и SSE), OAuth-метаданные, регистрация, authorize, token."""

    def __init__(self, oauth: bool = True, static_token: str = "tok-static", expires_in: int = 3600, dcr: bool = True):
        self.oauth, self.static_token, self.expires_in, self.dcr = oauth, static_token, expires_in, dcr
        self.token_clients: list = []
        self.codes: dict = {}
        self.access: set = set()
        self.refresh: dict = {}
        self.calls: list = []
        self.refreshed = 0
        self.srv = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()

    def _json(self, obj, status=200, **headers):
        return Response(json.dumps(obj), status=status, content_type="application/json", headers=headers)

    def app(self, environ, start_response):
        req = Request(environ)
        return self.route(req)(environ, start_response)

    def route(self, req: Request) -> Response:
        p = req.path
        if p == "/.well-known/oauth-protected-resource/mcp" and self.oauth:
            return self._json({"resource": self.base + "/mcp", "authorization_servers": [self.base]})
        if p == "/.well-known/oauth-authorization-server" and self.oauth:
            return self._json({"issuer": self.base, "authorization_endpoint": self.base + "/authorize",
                               "token_endpoint": self.base + "/token", "registration_endpoint": self.base + "/register",
                               "code_challenge_methods_supported": ["S256"]})
        if p == "/register" and req.method == "POST" and self.oauth and self.dcr:
            body = req.get_json()
            assert body["token_endpoint_auth_method"] == "none" and body["redirect_uris"]
            return self._json({"client_id": "cl-" + secrets.token_hex(4)}, 201)
        if p == "/authorize":
            a = req.args
            assert a["code_challenge_method"] == "S256" and a["resource"] == self.base + "/mcp"
            code = secrets.token_hex(6)
            self.codes[code] = a["code_challenge"]
            return Response(status=302, headers={"Location": a["redirect_uri"] + "?" + urlencode({"code": code, "state": a["state"]})})
        if p == "/token" and req.method == "POST":
            f = req.form
            self.token_clients.append((f.get("client_id"), f.get("client_secret")))
            if f["grant_type"] == "authorization_code":
                ch = self.codes.pop(f["code"], None)
                calc = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if ch != calc:
                    return self._json({"error": "invalid_grant"}, 400)
            elif f["grant_type"] == "refresh_token":
                if f["refresh_token"] not in self.refresh:
                    return self._json({"error": "invalid_grant"}, 400)
                self.refreshed += 1
            at, rt = "at-" + secrets.token_hex(6), "rt-" + secrets.token_hex(6)
            self.access.add(at)
            self.refresh[rt] = at
            return self._json({"access_token": at, "refresh_token": rt, "token_type": "Bearer", "expires_in": self.expires_in})
        if p == "/mcp" and req.method == "POST":
            auth = req.headers.get("Authorization", "")
            tok = auth[7:] if auth.startswith("Bearer ") else ""
            if tok != self.static_token and tok not in self.access:
                return Response(status=401, headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{self.base}/.well-known/oauth-protected-resource/mcp"'})
            msg = req.get_json()
            if "id" not in msg:
                return Response(status=202)
            m = msg["method"]
            if m == "initialize":
                assert "text/event-stream" in req.headers["Accept"]
                return self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {
                    "protocolVersion": MC.PROTOCOL_VERSION, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "title": "Fake Studio"}}}, **{"Mcp-Session-Id": "sess-1"})
            assert req.headers.get("Mcp-Session-Id") == "sess-1"
            if m == "tools/list":
                return self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": TOOLS}})
            if m == "tools/call":
                self.calls.append(msg["params"])
                args = msg["params"]["arguments"]
                if msg["params"]["name"] == "echo":
                    return self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": "эхо: " + args["text"]}]}})
                body = (": ping\n\n"
                        + "data: " + json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}) + "\n\n"
                        + "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [
                            {"type": "text", "text": "Опубликовано: https://video.example/v/1"},
                            {"type": "resource_link", "uri": "https://video.example/v/1", "name": "Ролик"}]}}) + "\n\n")
                return Response(body, content_type="text/event-stream")
        if p == "/mcp" and req.method == "DELETE":
            return Response(status=200)
        return Response(status=404)


# ───────────────────────────────────────────── чистые функции
def test_url_guard(monkeypatch):
    monkeypatch.delenv("MCP_ALLOW_HTTP", raising=False)
    monkeypatch.delenv("MCP_ALLOW_PRIVATE", raising=False)
    for bad, code in [("http://example.com/mcp", "bad_url"), ("ftp://x.y/", "bad_url"), ("https://u:p@example.com/", "bad_url"),
                      ("https://127.0.0.1/mcp", "blocked_host"), ("https://169.254.169.254/latest", "blocked_host"),
                      ("https://10.1.2.3/mcp", "blocked_host"), ("https://[::1]/mcp", "blocked_host"),
                      ("https://localhost/mcp", "blocked_host"), ("https://db.internal/mcp", "blocked_host")]:
        with pytest.raises(MC.McpError) as e:
            MC.safe_url(bad)
        assert e.value.code == code, bad
    assert MC.normalize_url(" https://Mcp.Example.com/mcp#x ") == "https://mcp.example.com/mcp"


def test_sse_and_www_authenticate():
    msgs = MC.parse_sse(': hi\r\n\r\nevent: message\r\ndata: {"id": 1,\r\ndata: "result": {}}\r\n\r\ndata: not json\n\n')
    assert msgs == [{"id": 1, "result": {}}]
    h = 'Bearer error="invalid_token", resource_metadata="https://a.b/.well-known/oauth-protected-resource", scope="read write"'
    assert MC.www_auth_param(h, "resource_metadata") == "https://a.b/.well-known/oauth-protected-resource"
    assert MC.www_auth_param(h, "scope") == "read write"


def test_form_prefill_and_coerce():
    schema = TOOLS[1]["inputSchema"]
    f = {x["name"]: x for x in MC.form_fields(schema, {"url": "https://s/m/1.mp4", "prompt": "Кот на скейте"})}
    assert f["video_url"]["value"] == "https://s/m/1.mp4" and f["video_url"]["required"]
    assert f["title"]["value"] == "Кот на скейте"
    assert f["private"]["widget"] == "check" and f["private"]["value"] is True
    assert f["tags"]["widget"] == "json" and f["visibility"]["widget"] == "select" and f["visibility"]["value"] == "unlisted"
    args = MC.coerce_args(schema, {"video_url": "https://s/m/1.mp4", "title": "T", "private": "false", "tags": '["a"]',
                                   "count": "3", "visibility": "public", "junk": 1})
    assert args == {"video_url": "https://s/m/1.mp4", "title": "T", "private": False, "tags": ["a"], "count": 3, "visibility": "public"}
    for bad in ({"title": "T"}, {"video_url": "u", "title": "T", "count": "x"}, {"video_url": "u", "title": "T", "visibility": "secret"}):
        with pytest.raises(MC.McpError):
            MC.coerce_args(schema, bad)


def test_optional_anyof_types():
    schema = {"type": "object", "properties": {"tags": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}], "default": None},
                                               "n": {"type": ["integer", "null"]}}}
    f = {x["name"]: x for x in MC.form_fields(schema, {})}
    assert f["tags"]["widget"] == "json" and f["n"]["widget"] == "number"
    assert MC.coerce_args(schema, {"tags": '["a"]', "n": "2"}) == {"tags": ["a"], "n": 2}
    assert MC.coerce_args(schema, {"tags": "", "n": ""}) == {}


def test_result_view():
    v = MC.result_view({"isError": False, "content": [{"type": "text", "text": "см. https://x.y/1"},
                                                       {"type": "image", "data": "AAAA", "mimeType": "image/png"},
                                                       {"type": "image", "data": "AAAA", "mimeType": "image/svg+xml"}]})
    assert v["ok"] and v["links"][0]["url"] == "https://x.y/1" and v["images"] == ["data:image/png;base64,AAAA"]
    assert MC.result_view({"isError": True, "content": []})["ok"] is False


def test_seal_roundtrip(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k1")
    blob = MC.seal({"token": "secret-value"})
    assert "secret-value" not in blob and MC.unseal(blob) == {"token": "secret-value"}
    monkeypatch.setenv("SECRET_KEY", "k2")
    assert MC.unseal(blob) == {}


# ───────────────────────────────────────────── маршруты
@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("MCP_ALLOW_HTTP", "1")
    monkeypatch.setenv("MCP_ALLOW_PRIVATE", "1")
    monkeypatch.setenv("BASE_URL", "http://localhost")
    import server

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'mcp.db'}"
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


@pytest.fixture()
def fake():
    f = FakeMcp()
    yield f
    f.stop()


def _h(c):
    if not getattr(c, "_ip", None):
        c._ip = "10.8.%d.%d" % (id(c) % 250, id(c) // 250 % 250)
    tok = c.get("/api/csrf").get_json()["csrf_token"]
    return {"X-CSRF-Token": tok, "X-Forwarded-For": c._ip}


def _login(srv, c, email="u@t.local"):
    u = srv.User(email=email, provider="password", name="U")
    srv.db.session.add(u)
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id
    return u


def test_guest_and_validation(srv, fake):
    c = srv.app.test_client()
    dl = c.get("/download/mcp_bridge.py")
    assert dl.status_code == 200 and b"StdioServer" in dl.data and "attachment" in dl.headers["Content-Disposition"]
    assert c.get("/api/mcp").status_code == 401
    assert c.post("/api/mcp", json={"url": fake.base + "/mcp"}, headers=_h(c)).status_code == 401
    assert c.get("/api/mcp/buttons").get_json() == {"buttons": []}
    _login(srv, c)
    r = c.post("/api/mcp", json={"url": "ftp://nope"}, headers=_h(c))
    assert r.status_code == 400 and r.get_json()["error"] == "bad_url"


def test_token_connection_pins_form_call(srv, fake):
    c = srv.app.test_client()
    _login(srv, c)
    r = c.post("/api/mcp", json={"url": fake.base + "/mcp", "token": "tok-static"}, headers=_h(c)).get_json()
    conn = r["connection"]
    assert conn["status"] == "ok" and conn["name"] == "Fake Studio" and conn["auth"] == "token"
    assert [t["name"] for t in conn["tools"]] == ["echo", "publish_video"] and conn["tools"][0]["readOnly"]
    assert "tok-static" not in json.dumps(c.get("/api/mcp").get_json())
    from sqlalchemy import text

    secret = srv.db.session.execute(text("select secret from mcp_connections where id=:i"), {"i": conn["id"]}).scalar()
    assert secret and "tok-static" not in secret
    assert c.post("/api/mcp", json={"url": fake.base + "/mcp"}, headers=_h(c)).status_code == 409

    c.post(f"/api/mcp/{conn['id']}/pins", json={"tools": ["publish_video", "ghost"]}, headers=_h(c))
    btn = c.get("/api/mcp/buttons").get_json()["buttons"]
    assert btn == [{"cid": conn["id"], "tool": "publish_video", "title": "publish_video", "conn": "Fake Studio", "status": "ok"}]

    form = c.post("/api/mcp/form", json={"cid": conn["id"], "tool": "publish_video",
                                         "ctx": {"url": "/media/works/1.mp4", "prompt": "Кот на скейте"}}, headers=_h(c)).get_json()
    vals = {f["name"]: f["value"] for f in form["fields"]}
    assert vals["video_url"] == "http://localhost/media/works/1.mp4" and vals["title"] == "Кот на скейте"

    bad = c.post("/api/mcp/call", json={"cid": conn["id"], "tool": "publish_video", "args": {"title": "x"}}, headers=_h(c))
    assert bad.status_code == 400 and bad.get_json()["field"] == "video_url"
    res = c.post("/api/mcp/call", json={"cid": conn["id"], "tool": "publish_video",
                                        "args": {"video_url": vals["video_url"], "title": "Кот", "private": False}}, headers=_h(c)).get_json()
    assert res["ok"] and "Опубликовано" in res["text"] and res["links"][0]["url"] == "https://video.example/v/1"
    assert fake.calls[-1]["arguments"] == {"video_url": "http://localhost/media/works/1.mp4", "title": "Кот", "private": False}

    # чужой человек не видит и не вызывает
    c2 = srv.app.test_client()
    _login(srv, c2, "other@t.local")
    assert c2.get("/api/mcp").get_json()["connections"] == []
    assert c2.post("/api/mcp/call", json={"cid": conn["id"], "tool": "echo", "args": {"text": "a"}}, headers=_h(c2)).status_code == 404
    assert c2.delete(f"/api/mcp/{conn['id']}", headers=_h(c2)).status_code == 404
    assert c.delete(f"/api/mcp/{conn['id']}", headers=_h(c)).get_json() == {"ok": True}


def test_wrong_token(srv, fake):
    c = srv.app.test_client()
    _login(srv, c)
    conn = c.post("/api/mcp", json={"url": fake.base + "/mcp", "token": "nope"}, headers=_h(c)).get_json()["connection"]
    assert conn["status"] == "auth" and conn["error"] == "Токен не подошёл"
    conn = c.post(f"/api/mcp/{conn['id']}", json={"token": "tok-static"}, headers=_h(c)).get_json()["connection"]
    assert conn["status"] == "ok"


def _oauth_roundtrip(c, oauth_url):
    import requests

    r = requests.get(oauth_url, allow_redirects=False, timeout=5)
    loc = urlsplit(r.headers["Location"])
    assert loc.path == "/api/mcp/oauth/callback"
    return c.get(loc.path + "?" + loc.query)


def test_oauth_flow_and_refresh(srv, fake):
    c = srv.app.test_client()
    _login(srv, c)
    r = c.post("/api/mcp", json={"url": fake.base + "/mcp"}, headers=_h(c)).get_json()
    assert r["connection"]["status"] == "auth" and r["oauth_url"].startswith(fake.base + "/authorize?")
    q = parse_qs(urlsplit(r["oauth_url"]).query)
    assert q["redirect_uri"] == ["http://localhost/api/mcp/oauth/callback"] and q["code_challenge_method"] == ["S256"]
    back = _oauth_roundtrip(c, r["oauth_url"])
    assert back.status_code == 302 and "/account?mcp=ok" in back.headers["Location"]
    conn = c.get("/api/mcp").get_json()["connections"][0]
    assert conn["status"] == "ok" and conn["auth"] == "oauth" and len(conn["tools"]) == 2
    res = c.post("/api/mcp/call", json={"cid": conn["id"], "tool": "echo", "args": {"text": "привет"}}, headers=_h(c)).get_json()
    assert res["text"] == "эхо: привет"
    # сервер забыл токен → клиент сам обновляет его refresh-токеном и повторяет
    fake.access.clear()
    res = c.post("/api/mcp/call", json={"cid": conn["id"], "tool": "echo", "args": {"text": "ещё"}}, headers=_h(c)).get_json()
    assert res["text"] == "эхо: ещё" and fake.refreshed == 1
    # и refresh не помог → просим войти заново
    fake.access.clear()
    fake.refresh.clear()
    bad = c.post("/api/mcp/call", json={"cid": conn["id"], "tool": "echo", "args": {"text": "x"}}, headers=_h(c))
    assert bad.status_code == 401 and c.get("/api/mcp").get_json()["connections"][0]["status"] == "auth"
    again = c.post(f"/api/mcp/{conn['id']}/oauth", headers=_h(c)).get_json()
    assert _oauth_roundtrip(c, again["oauth_url"]).headers["Location"].startswith("/account?mcp=ok")
    # вход начат из студии — возвращаемся в студию
    again = c.post(f"/api/mcp/{conn['id']}/oauth", json={"back": "app"}, headers=_h(c)).get_json()
    assert _oauth_roundtrip(c, again["oauth_url"]).headers["Location"].startswith("/app?mcp=ok")


def test_oauth_callback_rejects_foreign_state(srv, fake):
    c = srv.app.test_client()
    _login(srv, c)
    r = c.post("/api/mcp", json={"url": fake.base + "/mcp"}, headers=_h(c)).get_json()
    other = srv.app.test_client()
    _login(srv, other, "x@t.local")
    import requests

    loc = urlsplit(requests.get(r["oauth_url"], allow_redirects=False, timeout=5).headers["Location"])
    assert other.get(loc.path + "?" + loc.query).headers["Location"] == "/account?mcp=err#mcp"
    bad_state = c.get("/api/mcp/oauth/callback?code=1&state=forged")
    assert bad_state.headers["Location"] == "/account?mcp=err#mcp"


def test_server_without_oauth_needs_token(srv):
    f = FakeMcp(oauth=False)
    try:
        c = srv.app.test_client()
        _login(srv, c)
        r = c.post("/api/mcp", json={"url": f.base + "/mcp"}, headers=_h(c)).get_json()
        assert r.get("need_token") and r["connection"]["status"] == "auth" and "oauth_url" not in r
    finally:
        f.stop()


def test_presets_and_registered_app(srv, monkeypatch):
    f = FakeMcp(dcr=False)
    try:
        c = srv.app.test_client()
        _login(srv, c)
        lst = c.get("/api/mcp").get_json()
        assert {p["id"] for p in lst["presets"]} >= {"higgsfield", "vidiq", "dropbox", "meshy", "davinci"}
        assert "blender" not in {p["id"] for p in lst["presets"]}
        assert all(p["auth"] in ("oauth", "bridge") and p["cats"] for p in lst["presets"])
        assert next(p for p in lst["presets"] if p["id"] == "dropbox")["ready"] is False
        assert lst["redirect_uri"] == "http://localhost/api/mcp/oauth/callback"
        # без регистрации клиента и без приложения — просим токен
        r = c.post("/api/mcp", json={"url": f.base + "/mcp"}, headers=_h(c)).get_json()
        assert r.get("need_token")
        c.delete(f"/api/mcp/{r['connection']['id']}", headers=_h(c))
        # приложение сайта из MCP_CLIENTS — вход через сервис работает
        monkeypatch.setenv("MCP_CLIENTS", json.dumps({"127.0.0.1": {"client_id": "aish-app", "client_secret": "s3"}}))
        r = c.post("/api/mcp", json={"url": f.base + "/mcp"}, headers=_h(c)).get_json()
        assert "client_id=aish-app" in r["oauth_url"]
        assert _oauth_roundtrip(c, r["oauth_url"]).headers["Location"].startswith("/account?mcp=ok")
        assert f.token_clients[-1] == ("aish-app", "s3")
        # своё приложение в подключении
        monkeypatch.delenv("MCP_CLIENTS")
        c.delete(f"/api/mcp/{r['connection']['id']}", headers=_h(c))
        r = c.post("/api/mcp", json={"url": f.base + "/mcp", "client_id": "mine"}, headers=_h(c)).get_json()
        assert "client_id=mine" in r["oauth_url"]
    finally:
        f.stop()


def test_bridge_wraps_stdio_server(tmp_path):
    """scripts/mcp_bridge.py: stdio-сервер → HTTP с токеном; повторный initialize отдаётся из памяти."""
    import socket
    import subprocess
    import time

    srv_py = tmp_path / "stdio_srv.py"
    srv_py.write_text("""
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m: continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "local"}}
        if getattr(sys, "_inited", False): r = None
        sys._inited = True
    elif m["method"] == "tools/list":
        r = {"tools": [{"name": "add", "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}}}}]}
    else:
        r = {"content": [{"type": "text", "text": "sum=" + str(m["params"]["arguments"]["a"] + 1)}]}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r} if r else {"jsonrpc": "2.0", "id": m["id"], "error": {"code": 1, "message": "twice"}}), flush=True)
""")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    br = subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "mcp_bridge.py"), "--port", str(port), "--token",
                           "bridge-token-123456", "--", sys.executable, str(srv_py)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.2)
        os.environ["MCP_ALLOW_HTTP"] = os.environ["MCP_ALLOW_PRIVATE"] = "1"
        url = f"http://127.0.0.1:{port}/mcp"
        with pytest.raises(MC.McpError) as e:
            MC.McpSession(url, "wrong").initialize()
        assert e.value.code == "auth_required"
        for _ in range(2):
            ses = MC.McpSession(url, "bridge-token-123456")
            assert ses.initialize()["serverInfo"]["name"] == "local"
            assert ses.list_tools()[0]["name"] == "add"
            assert MC.result_view(ses.call_tool("add", {"a": 2}))["text"] == "sum=3"
    finally:
        os.environ.pop("MCP_ALLOW_HTTP", None); os.environ.pop("MCP_ALLOW_PRIVATE", None)
        br.terminate()
