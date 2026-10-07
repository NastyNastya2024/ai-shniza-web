"""LLM-цепочка для адаптации промпта: OmniRoute → Groq → (нет) → шаблон.

Почему так:
* LLM нужна ровно в одном месте — переписать идею пользователя под стиль конкретной модели.
  Всё остальное (тип, подбор, параметры, ошибки, UI) — правила, 0 токенов.
* Ответ — строго JSON-контракт. Разметку и кнопки рисует сервер, не модель.
* Общий дедлайн на всю цепочку (по умолчанию 12 с) — чат не должен держать gthread-поток gunicorn 45 с.
* Circuit breaker на провайдера: 2 ошибки подряд → 60 с не трогаем (бесплатные маршруты OmniRoute часто 429/висят).
* DeepSeek-на-Replicate сюда сознательно НЕ входит: это тот же домен отказа, что и генерация
  (упал Replicate → упали и генерации, и чат). Вместо него — шаблонный промпт (degraded).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

Transport = Callable[[str, dict, dict, float], "tuple[int, Any]"]


class TransportTimeout(Exception):
    pass


class TransportError(Exception):
    pass


class LLMUnavailable(Exception):
    """Ни один провайдер не дал валидный ответ в пределах дедлайна."""

    def __init__(self, reason: str, attempts: list[dict] | None = None, tokens: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts or []
        self.tokens = tokens  # потрачено на неудачные попытки — тоже учитываем в бюджете


@dataclass
class LLMProvider:
    name: str
    base_url: str  # OpenAI-compatible, напр. http://127.0.0.1:20128/v1
    api_key: str
    model: str
    timeout: float = 8.0
    json_mode: bool = True  # response_format={"type":"json_object"}; отключается сам, если провайдер его не умеет
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    attempts: list[dict]

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class CircuitBreaker:
    def __init__(self, threshold: int = 2, cooldown: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, name: str) -> bool:
        with self._lock:
            until = self._open_until.get(name, 0.0)
            if until and self.clock() < until:
                return False
            if until:  # half-open: одна пробная попытка
                self._open_until.pop(name, None)
                self._fails[name] = self.threshold - 1
            return True

    def success(self, name: str) -> None:
        with self._lock:
            self._fails[name] = 0
            self._open_until.pop(name, None)

    def failure(self, name: str) -> None:
        with self._lock:
            n = self._fails.get(name, 0) + 1
            self._fails[name] = n
            if n >= self.threshold:
                self._open_until[name] = self.clock() + self.cooldown

    def state(self) -> dict[str, str]:
        now = self.clock()
        with self._lock:
            names = set(self._fails) | set(self._open_until)
            return {n: ("open" if self._open_until.get(n, 0) > now else "closed") for n in names}


def requests_transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, Any]:
    import requests  # ленивый импорт: тестам сеть не нужна

    sess = requests.Session()
    sess.trust_env = False  # локальный OmniRoute не должен идти через HTTP(S)_PROXY
    try:
        r = sess.post(url, headers=headers, json=payload, timeout=(min(3.0, timeout), timeout))
    except requests.Timeout as exc:
        raise TransportTimeout(str(exc)) from exc
    except requests.ConnectionError as exc:
        raise TransportError("connection_refused (провайдер не запущен или недоступен)") from exc
    except requests.RequestException as exc:
        raise TransportError(type(exc).__name__) from exc
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:500]


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json_object(text: str) -> dict[str, Any]:
    """Достаёт первый JSON-объект из ответа модели (снимает <think>, ```json, текст вокруг)."""
    if not isinstance(text, str):
        raise ValueError("not text")
    s = _FENCE.sub("", _THINK.sub("", text).strip()).strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except ValueError:
                        break
                    break
        start = s.find("{", start + 1)
    raise ValueError("no json object")


# «думающие» модели тратят max_tokens на рассуждение и могут вернуть пустой content
REASONING_RX = re.compile(r"gpt-oss|qwen3|qwq|deepseek-r1|reason|\bo[134](-|$)", re.I)


def _http_error(status: int, body: Any) -> str:
    msg = ""
    if isinstance(body, dict):
        err = body.get("error")
        msg = (err.get("message") if isinstance(err, dict) else err) or body.get("detail") or ""
    elif isinstance(body, str):
        msg = body
    msg = re.sub(r"\s+", " ", str(msg or "")).strip()[:100]
    return f"http_{status}" + (f": {msg}" if msg else "")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


class LLMChain:
    def __init__(self, providers: list[LLMProvider], transport: Transport | None = None, deadline_sec: float = 12.0,
                 breaker: CircuitBreaker | None = None, clock: Callable[[], float] = time.monotonic,
                 max_tokens: int = 220, temperature: float = 0.2, min_attempt_sec: float = 1.0):
        self.providers = [p for p in providers if p.api_key and p.base_url and p.model]
        self.transport = transport or requests_transport
        self.deadline_sec = deadline_sec
        self.clock = clock
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.min_attempt_sec = min_attempt_sec
        self.last: dict[str, dict] = {}  # последний результат по провайдеру — для /api/assistant/status
        self._all = list(providers)       # включая те, у кого нет ключа (для диагностики)

    def _note(self, name: str, ok: bool, error: str = "", ms: int = 0) -> None:
        self.last[name] = {"ok": ok, "error": error, "ms": ms, "at": int(time.time())}

    def status(self) -> list[dict]:
        """Диагностика без секретов: какие провайдеры есть, есть ли ключ, состояние breaker, последняя ошибка."""
        states = self.breaker.state()
        out = []
        for p in self._all:
            out.append({
                "name": p.name, "model": p.model or None, "url": p.url,
                "key_set": bool(p.api_key), "enabled": p in self.providers,
                "breaker": states.get(p.name, "closed"), "last": self.last.get(p.name),
                "why_disabled": None if p in self.providers else ("нет ключа" if not p.api_key else "не задана модель"),
            })
        return out

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def _call(self, p: LLMProvider, messages: list[dict], timeout: float, max_tokens: int) -> tuple[str, dict]:
        if REASONING_RX.search(p.model or ""):
            max_tokens = max(max_tokens, 1200)
        payload: dict[str, Any] = {"model": p.model, "messages": messages, "temperature": self.temperature,
                                   "max_tokens": max_tokens, "stream": False}
        if p.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {p.api_key}", "Content-Type": "application/json", **p.extra_headers}
        status, body = self.transport(p.url, headers, payload, timeout)
        if status == 400 and p.json_mode:
            # Groq: unsupported response_format или json_validate_failed на части моделей
            p.json_mode = False
            payload.pop("response_format", None)
            status, body = self.transport(p.url, headers, payload, timeout)
        if status == 429:
            raise TransportError("rate_limited")
        if status >= 400 or not isinstance(body, dict):
            raise TransportError(_http_error(status, body))
        try:
            msg = body["choices"][0]["message"]
            content = msg.get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise TransportError("bad_shape") from exc
        if not content.strip() and (msg.get("reasoning") or msg.get("reasoning_content")):
            content = "<empty: reasoning model spent max_tokens on thinking>"
        return content, body.get("usage") or {}

    def complete_json(self, system: str, user: str, validate: Callable[[dict], dict] | None = None,
                      max_tokens: int | None = None, deadline_sec: float | None = None) -> LLMResult:
        if not self.providers:
            raise LLMUnavailable("no_providers")
        # circuit_open у всех — тоже отметим, чтобы в статусе было видно, почему шаблон
        t0 = self.clock()
        deadline = t0 + (deadline_sec or self.deadline_sec)
        mt = max_tokens or self.max_tokens
        attempts: list[dict] = []
        tin = tout = 0
        for p in self.providers:
            if not self.breaker.allow(p.name):
                attempts.append({"provider": p.name, "error": "circuit_open"})
                continue
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            for try_no in (1, 2):  # 2-я попытка — только при невалидном JSON
                remaining = deadline - self.clock()
                if remaining < self.min_attempt_sec:
                    attempts.append({"provider": p.name, "error": "deadline"})
                    raise LLMUnavailable("deadline", attempts, tin + tout)
                a0 = self.clock()
                try:
                    content, usage = self._call(p, messages, min(p.timeout, remaining), mt)
                except TransportTimeout:
                    self.breaker.failure(p.name)
                    attempts.append({"provider": p.name, "error": "timeout"})
                    self._note(p.name, False, f"timeout > {min(p.timeout, remaining):.1f} с")
                    break
                except TransportError as exc:
                    self.breaker.failure(p.name)
                    attempts.append({"provider": p.name, "error": str(exc)})
                    self._note(p.name, False, str(exc))
                    break
                tin += int(usage.get("prompt_tokens") or _estimate_tokens(system + user))
                tout += int(usage.get("completion_tokens") or _estimate_tokens(content))
                try:
                    data = parse_json_object(content)
                    if validate:
                        data = validate(data)
                except (ValueError, TypeError) as exc:
                    attempts.append({"provider": p.name, "error": f"bad_json:{exc}"[:80]})
                    if try_no == 1:
                        messages = messages + [{"role": "assistant", "content": content[:400]},
                                               {"role": "user", "content": "Invalid. Reply with ONLY the JSON object."}]
                        continue
                    self.breaker.failure(p.name)
                    self._note(p.name, False, f"ответ не JSON: {content[:60]!r}")
                    break
                self.breaker.success(p.name)
                self._note(p.name, True, ms=int((self.clock() - a0) * 1000))
                attempts.append({"provider": p.name, "ok": True, "ms": int((self.clock() - a0) * 1000)})
                return LLMResult(data, p.name, tin, tout, int((self.clock() - t0) * 1000), attempts)
        raise LLMUnavailable("all_failed", attempts, tin + tout)
