#!/usr/bin/env python3
"""Мост {AI}-шницы: локальный MCP-сервер (stdio) → адрес по HTTP с токеном, чтобы подключить его в «Подключениях».

Нужен для серверов, которые работают на вашем компьютере: Blender MCP, файлы, локальные утилиты.
Только стандартная библиотека Python 3.9+, работает в Windows, macOS и Linux.

  1) Запустите мост рядом с программой (пример — Blender MCP; в Blender включён аддон и нажато «Connect»):
       python mcp_bridge.py --port 8765 -- uvx blender-mcp
     Мост напечатает токен (или задайте свой: --token …).
  2) Дайте мосту https-адрес из интернета, например туннелем Cloudflare:
       cloudflared tunnel --url http://127.0.0.1:8765
     → https://что-то.trycloudflare.com
  3) В {AI}-шнице: Кабинет → Подключения → адрес https://что-то.trycloudflare.com/mcp и токен из шага 1.

Мост слушает только 127.0.0.1 и пускает запросы лишь с правильным токеном (Authorization: Bearer).
Пока мост и туннель запущены, сайт может вызывать инструменты сервера — от вашего имени и только по вашей кнопке.
Закройте мост (Ctrl+C) — доступ пропадёт.
"""
from __future__ import annotations

import argparse
import hmac
import itertools
import json
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StdioServer:
    """Один процесс MCP-сервера; запросы разных клиентов получают свои id, ответы раздаются по ожидающим."""

    def __init__(self, cmd: list[str], timeout: float):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)
        self.timeout = timeout
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.waiting: dict[int, dict] = {}
        self.init_result = None
        self.init_lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _send(self, obj: dict) -> None:
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "method" in msg and "id" in msg:      # запрос от сервера (sampling, roots…) — мост их не поддерживает
                self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported by bridge"}})
                continue
            w = self.waiting.get(msg.get("id")) if "id" in msg else None
            if w is not None:
                w["msg"] = msg
                w["ev"].set()
        for w in list(self.waiting.values()):
            w["ev"].set()

    def request(self, method: str, params) -> dict:
        rid = next(self.ids)
        w = {"ev": threading.Event(), "msg": None}
        self.waiting[rid] = w
        try:
            body = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                body["params"] = params
            self._send(body)
            if not w["ev"].wait(self.timeout) or w["msg"] is None:
                return {"error": {"code": -32000, "message": "local server timeout or exit"}}
            return w["msg"]
        finally:
            self.waiting.pop(rid, None)

    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method")
        if "id" not in msg:                          # уведомление
            if method != "notifications/initialized":   # initialized уже отправлен при первом initialize
                self._send(msg)
            return None
        if method == "initialize":                   # stdio-сервер принимает initialize один раз — дальше отдаём сохранённый
            with self.init_lock:
                if self.init_result is None:
                    res = self.request("initialize", msg.get("params"))
                    if "error" in res:
                        return {"jsonrpc": "2.0", "id": msg["id"], "error": res["error"]}
                    self.init_result = res.get("result")
                    self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            return {"jsonrpc": "2.0", "id": msg["id"], "result": self.init_result}
        res = self.request(method, msg.get("params"))
        out = {"jsonrpc": "2.0", "id": msg["id"]}
        out.update({k: res[k] for k in ("result", "error") if k in res})
        return out


def make_handler(server: StdioServer, token: str, path: str):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("[bridge] " + fmt % args + "\n")

        def _reply(self, code: int, obj=None, headers=None):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8") if obj is not None else b""
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if obj is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            got = self.headers.get("Authorization", "")
            return got.startswith("Bearer ") and hmac.compare_digest(got[7:].strip(), token)

        def do_POST(self):
            if self.path.split("?")[0].rstrip("/") != path:
                return self._reply(404, {"error": "not found"})
            if not self._authed():
                return self._reply(401, {"error": "token required"}, {"WWW-Authenticate": "Bearer"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 5_000_000:
                return self._reply(400, {"error": "bad body"})
            try:
                msg = json.loads(self.rfile.read(n))
            except ValueError:
                return self._reply(400, {"error": "bad json"})
            msgs = msg if isinstance(msg, list) else [msg]
            outs = [o for o in (server.handle(m) for m in msgs if isinstance(m, dict)) if o is not None]
            if not outs:
                return self._reply(202)
            return self._reply(200, outs if isinstance(msg, list) else outs[0], {"Mcp-Session-Id": "bridge"})

        def do_GET(self):          # поток событий от сервера мост не держит
            self._reply(405, {"error": "use POST"}, {"Allow": "POST"})

        def do_DELETE(self):
            self._reply(200 if self._authed() else 401)

    return H


def main() -> None:
    ap = argparse.ArgumentParser(description="stdio MCP-сервер → HTTP с токеном для {AI}-шницы")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="по умолчанию только этот компьютер; наружу — через туннель")
    ap.add_argument("--token", default="", help="свой токен (иначе будет создан случайный)")
    ap.add_argument("--path", default="/mcp")
    ap.add_argument("--timeout", type=float, default=120.0, help="сколько ждать ответа инструмента, сек")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="команда сервера после --, например: -- uvx blender-mcp")
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("укажите команду MCP-сервера после --, например: -- uvx blender-mcp")
    token = a.token or secrets.token_urlsafe(24)
    if len(token) < 16:
        ap.error("токен короче 16 символов — слишком простой")
    srv = StdioServer(cmd, a.timeout)
    http = ThreadingHTTPServer((a.host, a.port), make_handler(srv, token, "/" + a.path.strip("/")))
    print(f"Мост запущен: http://{a.host}:{a.port}/{a.path.strip('/')}")
    print(f"Токен для «Подключений»: {token}")
    print("Дальше: cloudflared tunnel --url http://127.0.0.1:%d  → адрес https://…/%s" % (a.port, a.path.strip("/")))
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.proc.terminate()


if __name__ == "__main__":
    main()
