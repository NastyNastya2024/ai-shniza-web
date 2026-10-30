"""MCP-клиент {AI}-шницы: подключение к любому удалённому MCP-серверу по адресу (Streamable HTTP).

Без внешних SDK — только requests:
  * транспорт: JSON-RPC 2.0 по POST, ответ JSON или text/event-stream (SSE), заголовок Mcp-Session-Id;
  * вход: без входа, по токену (Bearer) или OAuth 2.1 по спецификации MCP —
    /.well-known/oauth-protected-resource → метаданные сервера авторизации → динамическая регистрация клиента →
    PKCE (S256) + resource (RFC 8707) → обмен кода и обновление токена;
  * защита: только https, адрес не должен вести во внутреннюю сеть (SSRF), без редиректов, лимиты размера и времени.

Env:
  MCP_ALLOW_HTTP=1     — разрешить http:// (только для локальной разработки)
  MCP_ALLOW_PRIVATE=1  — разрешить адреса внутренней сети (только для локальной разработки и тестов)
  MCP_TIMEOUT=30       — таймаут запроса к MCP-серверу, сек
  MCP_TOKEN_KEY        — ключ шифрования токенов (Fernet, 32 байта base64); если не задан — выводится из SECRET_KEY
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "aishnitsa", "title": "{AI}-шница", "version": "1.0"}
MAX_BYTES = 2_000_000          # потолок ответа MCP-сервера
MAX_URL = 500


class McpError(Exception):
    """code: bad_url | blocked_host | auth_required | http | protocol | timeout | unreachable | tool_error"""

    def __init__(self, code: str, detail: str = "", **extra: Any):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.extra = extra


def _flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes"}


def _timeout() -> float:
    try:
        return max(3.0, min(120.0, float(os.getenv("MCP_TIMEOUT") or 30)))
    except ValueError:
        return 30.0


# ─────────────────────────────────────────────────────────────── адреса и SSRF
def normalize_url(raw: str) -> str:
    """Чистит адрес сервера; бросает McpError('bad_url' | 'blocked_host')."""
    url = (raw or "").strip()
    if not url or len(url) > MAX_URL or any(c.isspace() for c in url):
        raise McpError("bad_url", "empty or too long")
    p = urlsplit(url)
    if p.scheme not in ("https", "http") or not p.hostname:
        raise McpError("bad_url", "need https://host/…")
    if p.scheme == "http" and not _flag("MCP_ALLOW_HTTP"):
        raise McpError("bad_url", "https only")
    if p.username or p.password:
        raise McpError("bad_url", "no credentials in url")
    host = p.hostname.lower()
    netloc = host if not p.port else f"{host}:{p.port}"
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]" + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path or "/", p.query, ""))


def _ip_blocked(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return not a.is_global or a.is_multicast


def check_host(url: str) -> None:
    """Адрес не должен вести во внутреннюю сеть (localhost, 10.x, 169.254.x — метаданные облака и т. п.)."""
    if _flag("MCP_ALLOW_PRIVATE"):
        return
    p = urlsplit(url)
    host = p.hostname or ""
    if host in {"localhost"} or host.endswith((".local", ".internal", ".localhost")):
        raise McpError("blocked_host", host)
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise McpError("unreachable", f"dns: {e}") from e
    if not infos:
        raise McpError("unreachable", "dns: no address")
    for info in infos:
        if _ip_blocked(info[4][0]):
            raise McpError("blocked_host", host)


def safe_url(raw: str) -> str:
    url = normalize_url(raw)
    check_host(url)
    return url


def origin(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "", "", ""))


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


# ─────────────────────────────────────────────────────────────── HTTP
def _read_limited(resp: requests.Response) -> bytes:
    buf = bytearray()
    for chunk in resp.iter_content(16384):
        buf += chunk
        if len(buf) > MAX_BYTES:
            resp.close()
            raise McpError("protocol", "response too large")
    return bytes(buf)


def _request(method: str, url: str, **kw: Any) -> requests.Response:
    safe_url(url)
    kw.setdefault("timeout", _timeout())
    try:
        return requests.request(method, url, allow_redirects=False, stream=True, **kw)
    except requests.Timeout as e:
        raise McpError("timeout", str(e)[:200]) from e
    except requests.RequestException as e:
        raise McpError("unreachable", str(e)[:200]) from e


def get_json(url: str) -> dict | None:
    """GET метаданных; None — если документа нет (404 и т. п.)."""
    r = _request("GET", url, headers={"Accept": "application/json", "MCP-Protocol-Version": PROTOCOL_VERSION})
    if r.status_code != 200:
        r.close()
        return None
    try:
        data = json.loads(_read_limited(r) or b"null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_sse(text: str) -> list[dict]:
    """События text/event-stream → список JSON-объектов из полей data."""
    out: list[dict] = []
    data: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n") + [""]:
        if line == "":
            if data:
                try:
                    obj = json.loads("\n".join(data))
                    if isinstance(obj, dict):
                        out.append(obj)
                    elif isinstance(obj, list):
                        out.extend(x for x in obj if isinstance(x, dict))
                except ValueError:
                    pass
                data = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    return out


def www_auth_param(header: str, key: str) -> str:
    m = re.search(key + r'\s*=\s*"([^"]*)"', header or "") or re.search(key + r"\s*=\s*([^,\s]+)", header or "")
    return m.group(1) if m else ""


class McpSession:
    """Один разговор с MCP-сервером: initialize → tools/list | tools/call."""

    def __init__(self, url: str, token: str = ""):
        self.url = safe_url(url)
        self.token = token or ""
        self.sid = ""
        self.server: dict = {}
        self._id = 0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        return h

    def _post(self, body: dict) -> requests.Response:
        r = _request("POST", self.url, headers=self._headers(), data=json.dumps(body, ensure_ascii=False).encode("utf-8"))
        if r.status_code == 401:
            hdr = r.headers.get("WWW-Authenticate", "")
            r.close()
            raise McpError("auth_required", "401", resource_metadata=www_auth_param(hdr, "resource_metadata"),
                           scope=www_auth_param(hdr, "scope"))
        if r.status_code == 403:
            r.close()
            raise McpError("auth_required", "403 forbidden", forbidden=True)
        if 300 <= r.status_code < 400:
            r.close()
            raise McpError("http", f"redirect {r.status_code} — укажите конечный адрес сервера")
        return r

    def rpc(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        rid = self._id
        body = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            body["params"] = params
        r = self._post(body)
        if r.status_code == 404 and self.sid:
            r.close()
            raise McpError("protocol", "session expired")
        if r.status_code >= 400:
            r.close()
            raise McpError("http", f"HTTP {r.status_code}")
        sid = r.headers.get("Mcp-Session-Id")
        if sid:
            self.sid = sid[:200]
        ctype = (r.headers.get("Content-Type") or "").lower()
        raw = _read_limited(r).decode("utf-8", "replace")
        msgs = parse_sse(raw) if "text/event-stream" in ctype else []
        if not msgs:
            try:
                obj = json.loads(raw)
            except ValueError as e:
                raise McpError("protocol", "not json") from e
            msgs = obj if isinstance(obj, list) else [obj]
        for m in msgs:
            if isinstance(m, dict) and m.get("id") == rid and ("result" in m or "error" in m):
                if m.get("error"):
                    err = m["error"] if isinstance(m["error"], dict) else {"message": str(m["error"])}
                    raise McpError("protocol", str(err.get("message") or "error")[:300], rpc_code=err.get("code"))
                return m.get("result")
        raise McpError("protocol", "no response for request")

    def notify(self, method: str) -> None:
        try:
            r = self._post({"jsonrpc": "2.0", "method": method})
            r.close()
        except McpError as e:
            if e.code == "auth_required":
                raise

    def initialize(self) -> dict:
        res = self.rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO})
        if not isinstance(res, dict):
            raise McpError("protocol", "bad initialize")
        self.server = res
        self.notify("notifications/initialized")
        return res

    def list_tools(self, pages: int = 5) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        for _ in range(pages):
            res = self.rpc("tools/list", {"cursor": cursor} if cursor else {}) or {}
            for t in res.get("tools") or []:
                if isinstance(t, dict) and t.get("name"):
                    tools.append(t)
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return tools[:200]

    def call_tool(self, name: str, args: dict) -> dict:
        res = self.rpc("tools/call", {"name": name, "arguments": args or {}})
        return res if isinstance(res, dict) else {"content": []}

    def close(self) -> None:
        if not self.sid:
            return
        try:
            _request("DELETE", self.url, headers=self._headers(), timeout=5).close()
        except McpError:
            pass


def compact_tool(t: dict) -> dict:
    """Инструмент для хранения и показа: имя, заголовок, описание, схема полей, подсказки."""
    ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
    schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {"type": "object", "properties": {}}
    return {
        "name": str(t.get("name"))[:120],
        "title": str(t.get("title") or ann.get("title") or t.get("name"))[:120],
        "description": str(t.get("description") or "")[:600],
        "inputSchema": schema,
        "readOnly": bool(ann.get("readOnlyHint")),
        "destructive": bool(ann.get("destructiveHint")) and not ann.get("readOnlyHint"),
    }


# ─────────────────────────────────────────────────────────────── OAuth 2.1 (MCP authorization)
def _well_known(base: str, doc: str) -> list[str]:
    p = urlsplit(base)
    path = (p.path or "").rstrip("/")
    root = urlunsplit((p.scheme, p.netloc, "", "", ""))
    if path:
        return [f"{root}/.well-known/{doc}{path}", f"{root}{path}/.well-known/{doc}", f"{root}/.well-known/{doc}"]
    return [f"{root}/.well-known/{doc}"]


def discover(mcp_url: str, resource_metadata: str = "") -> dict:
    """Эндпоинты OAuth для MCP-сервера. Порядок как в спецификации MCP 2025-06-18, с запасным путём 2025-03-26."""
    prm = None
    tried: list[str] = []
    for u in ([resource_metadata] if resource_metadata else []) + _well_known(mcp_url, "oauth-protected-resource"):
        if u in tried:
            continue
        tried.append(u)
        try:
            prm = get_json(u)
        except McpError:
            prm = None
        if prm and prm.get("authorization_servers"):
            break
        prm = None
    issuer = str((prm or {}).get("authorization_servers", [origin(mcp_url)])[0] or origin(mcp_url)).rstrip("/")
    resource = str((prm or {}).get("resource") or mcp_url)
    asm = None
    cands = _well_known(issuer, "oauth-authorization-server") + _well_known(issuer, "openid-configuration")
    seen: set[str] = set()
    for u in cands:
        if u in seen:
            continue
        seen.add(u)
        try:
            asm = get_json(u)
        except McpError:
            asm = None
        if asm and asm.get("authorization_endpoint") and asm.get("token_endpoint"):
            break
        asm = None
    if not asm:   # старые серверы без метаданных: эндпоинты по умолчанию от корня
        root = origin(issuer)
        asm = {"authorization_endpoint": root + "/authorize", "token_endpoint": root + "/token",
               "registration_endpoint": root + "/register"}
    methods = asm.get("code_challenge_methods_supported")
    if isinstance(methods, list) and methods and "S256" not in methods:
        raise McpError("protocol", "server has no PKCE S256")
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        if asm.get(k):
            safe_url(str(asm[k]))
    scopes = (prm or {}).get("scopes_supported") or asm.get("scopes_supported") or []
    return {
        "issuer": issuer,
        "resource": resource,
        "authorization_endpoint": str(asm["authorization_endpoint"]),
        "token_endpoint": str(asm["token_endpoint"]),
        "registration_endpoint": str(asm.get("registration_endpoint") or ""),
        "scope": " ".join(str(s) for s in scopes if isinstance(s, str))[:500] if isinstance(scopes, list) else "",
    }


def _post_form(url: str, data: dict) -> dict:
    r = _request("POST", url, data=data, headers={"Accept": "application/json"})
    raw = _read_limited(r)
    try:
        obj = json.loads(raw or b"{}")
    except ValueError:
        obj = {}
    if r.status_code >= 400 or not isinstance(obj, dict):
        raise McpError("auth_required" if r.status_code in (400, 401) else "http",
                       str((obj or {}).get("error_description") or (obj or {}).get("error") or r.status_code)[:200])
    return obj


def register_client(meta: dict, redirect_uri: str) -> dict:
    """Динамическая регистрация клиента (RFC 7591). Без неё — нужен client_id от владельца сервера."""
    reg = meta.get("registration_endpoint")
    if not reg:
        raise McpError("protocol", "no dynamic client registration")
    body = {"client_name": CLIENT_INFO["title"], "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "token_endpoint_auth_method": "none"}
    if meta.get("scope"):
        body["scope"] = meta["scope"]
    r = _request("POST", reg, json=body, headers={"Accept": "application/json"})
    raw = _read_limited(r)
    try:
        obj = json.loads(raw or b"{}")
    except ValueError:
        obj = {}
    if r.status_code >= 400 or not isinstance(obj, dict) or not obj.get("client_id"):
        raise McpError("protocol", f"client registration failed ({r.status_code})")
    return {"client_id": str(obj["client_id"]), "client_secret": str(obj.get("client_secret") or "")}


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(meta: dict, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", "resource": meta.get("resource") or ""}
    if meta.get("scope"):
        q["scope"] = meta["scope"]
    ep = meta["authorization_endpoint"]
    return ep + ("&" if "?" in ep else "?") + urlencode({k: v for k, v in q.items() if v})


def _tokens(obj: dict, old_refresh: str = "") -> dict:
    if not obj.get("access_token"):
        raise McpError("auth_required", "no access_token")
    exp = obj.get("expires_in")
    try:
        exp_at = int(time.time()) + int(exp) if exp else 0
    except (TypeError, ValueError):
        exp_at = 0
    return {"access_token": str(obj["access_token"]), "refresh_token": str(obj.get("refresh_token") or old_refresh or ""),
            "expires_at": exp_at}


def _client_fields(client: dict) -> dict:
    d = {"client_id": client.get("client_id", "")}
    if client.get("client_secret"):
        d["client_secret"] = client["client_secret"]
    return d


def exchange_code(meta: dict, client: dict, code: str, verifier: str, redirect_uri: str) -> dict:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier,
            "resource": meta.get("resource") or "", **_client_fields(client)}
    return _tokens(_post_form(meta["token_endpoint"], {k: v for k, v in data.items() if v}))


def refresh_tokens(meta: dict, client: dict, refresh_token: str) -> dict:
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "resource": meta.get("resource") or "",
            **_client_fields(client)}
    return _tokens(_post_form(meta["token_endpoint"], {k: v for k, v in data.items() if v}), refresh_token)


# ─────────────────────────────────────────────────────────────── шифрование секретов
def _fernet():
    from cryptography.fernet import Fernet

    key = (os.getenv("MCP_TOKEN_KEY") or "").strip()
    if not key:
        base = (os.getenv("SECRET_KEY") or "dev-only-secret").encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(b"aish-mcp:" + base).digest()).decode()
    return Fernet(key.encode())


def seal(obj: dict) -> str:
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def unseal(blob: str) -> dict:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except Exception:   # ключ сменили — секрет не читается, человек войдёт заново
        return {}


# ─────────────────────────────────────────────────────────────── форма кнопки и результат
_URL_RX = re.compile(r"(url|uri|link|href|src|source|file|image|img|photo|picture|video|media|audio|thumbnail|attachment)", re.I)
_PROMPT_RX = re.compile(r"(prompt|idea|query|topic)", re.I)
_TITLE_RX = re.compile(r"(title|name|subject|caption|headline|filename)", re.I)
_TEXT_RX = re.compile(r"(text|content|body|description|message|note|comment|script|summary)", re.I)


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _ptype(p: dict) -> str:
    """Тип поля схемы: type, список типов или anyOf/oneOf (Optional[...] из pydantic) — первый не null."""
    typ = p.get("type")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), None)
    if not typ:
        for alt in (p.get("anyOf") or p.get("oneOf") or []):
            if isinstance(alt, dict) and alt.get("type") and alt.get("type") != "null":
                typ = alt["type"] if isinstance(alt["type"], str) else None
                if typ:
                    break
    return typ if isinstance(typ, str) else "string"


def form_fields(schema: dict, ctx: dict) -> list[dict]:
    """Поля формы по inputSchema инструмента; подставляем результат генерации: ссылку, промпт, текст."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or []) if isinstance(schema.get("required"), list) else set()
    url = str(ctx.get("url") or "")
    prompt = str(ctx.get("prompt") or "")
    text = str(ctx.get("text") or "")
    out = []
    for name, p in list(props.items())[:30]:
        if not isinstance(p, dict):
            p = {}
        typ = _ptype(p)
        key = f"{name} {p.get('title') or ''}"
        f = {"name": str(name)[:80], "title": str(p.get("title") or name)[:80], "type": typ,
             "description": _short(str(p.get("description") or ""), 200), "required": name in required}
        if isinstance(p.get("enum"), list) and p["enum"]:
            f["enum"] = [x for x in p["enum"] if isinstance(x, (str, int, float, bool))][:50]
        value: Any = p.get("default")
        if typ == "string" and value in (None, ""):
            fmt = str(p.get("format") or "")
            if url and (fmt in ("uri", "url") or _URL_RX.search(key)) and not f.get("enum"):
                value = url
            elif _PROMPT_RX.search(key) and (prompt or text):
                value = prompt or _short(text, 2000)
            elif _TITLE_RX.search(key) and (prompt or text):
                value = _short(prompt or text, 100)
            elif _TEXT_RX.search(key) and (text or prompt):
                value = text or prompt
        if typ in ("object", "array"):
            f["widget"] = "json"
            value = json.dumps(value, ensure_ascii=False) if value is not None else ""
        elif typ == "boolean":
            f["widget"] = "check"
            value = bool(value)
        elif typ in ("integer", "number"):
            f["widget"] = "number"
        elif f.get("enum"):
            f["widget"] = "select"
        else:
            f["widget"] = "area" if (_TEXT_RX.search(key) or _PROMPT_RX.search(key)) and len(str(value or "")) > 60 else "text"
        f["value"] = "" if value is None else value
        out.append(f)
    return out


def coerce_args(schema: dict, raw: dict) -> dict:
    """Значения формы → аргументы по схеме. Бросает McpError('bad_args', поле)."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    props = props if isinstance(props, dict) else {}
    required = set(schema.get("required") or []) if isinstance(schema.get("required"), list) else set()
    out: dict = {}
    for name, p in props.items():
        p = p if isinstance(p, dict) else {}
        typ = _ptype(p)
        v = (raw or {}).get(name)
        if v is None or (isinstance(v, str) and v.strip() == "" and typ != "string"):
            if name in required:
                raise McpError("bad_args", name)
            continue
        if isinstance(v, str) and v == "" and name not in required:
            continue
        try:
            if typ == "integer":
                v = int(v)
            elif typ == "number":
                v = float(v)
            elif typ == "boolean":
                v = v if isinstance(v, bool) else str(v).lower() in {"1", "true", "on", "yes"}
            elif typ in ("object", "array"):
                v = json.loads(v) if isinstance(v, str) else v
                if typ == "object" and not isinstance(v, dict) or typ == "array" and not isinstance(v, list):
                    raise ValueError
            else:
                v = str(v)[:20000]
        except (TypeError, ValueError) as e:
            raise McpError("bad_args", name) from e
        if isinstance(p.get("enum"), list) and p["enum"] and v not in p["enum"]:
            raise McpError("bad_args", name)
        out[name] = v
    for name in required:
        if name not in out:
            raise McpError("bad_args", name)
    return out


_LINK_RX = re.compile(r"https?://[^\s<>\"')\]]+")


def result_view(res: dict) -> dict:
    """Ответ tools/call → текст, ссылки и маленькие картинки для показа в чате."""
    texts: list[str] = []
    links: list[dict] = []
    images: list[str] = []
    for c in (res.get("content") or [])[:30]:
        if not isinstance(c, dict):
            continue
        t = c.get("type")
        if t == "text":
            texts.append(str(c.get("text") or ""))
        elif t == "resource_link" and c.get("uri"):
            links.append({"url": str(c["uri"])[:800], "title": str(c.get("title") or c.get("name") or c["uri"])[:120]})
        elif t == "resource" and isinstance(c.get("resource"), dict):
            r = c["resource"]
            if r.get("text"):
                texts.append(str(r["text"]))
            elif r.get("uri"):
                links.append({"url": str(r["uri"])[:800], "title": str(r.get("uri"))[:120]})
        elif t == "image" and c.get("data") and len(str(c["data"])) < 400_000:
            mime = str(c.get("mimeType") or "image/png")
            if re.fullmatch(r"image/(png|jpeg|webp|gif)", mime):
                images.append(f"data:{mime};base64,{c['data']}")
    if not texts and isinstance(res.get("structuredContent"), (dict, list)):
        texts.append(json.dumps(res["structuredContent"], ensure_ascii=False, indent=1))
    text = "\n\n".join(x.strip() for x in texts if x and x.strip())
    for u in _LINK_RX.findall(text)[:10]:
        if not any(l["url"] == u for l in links):
            links.append({"url": u, "title": u})
    links = [l for l in links if l["url"].startswith(("https://", "http://"))][:10]
    return {"ok": not res.get("isError"), "text": text[:6000], "links": links, "images": images[:4]}
