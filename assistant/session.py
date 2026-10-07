"""Память диалога. Redis (TTL 6 ч) в проде, словарь в тестах.

Храним только состояние подбора — не историю переписки: так дешевле и LLM не нужен контекст.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

TTL_SEC = 6 * 3600
KEY = "assist:sess:{sid}"
MAX_SESSION_ID = 128


def empty_session() -> dict[str, Any]:
    return {
        "lang": None,
        "kind": None,        # тип задачи
        "topic": "",         # 1–3 слова для ссылки на витрину
        "needs": [],
        "idea": "",          # исходный текст пользователя (для «вернуть мой текст»)
        "shown": [],         # какие модели уже показывали
        "picked": None,      # выбранная модель
        "prompt": "",        # текущий адаптированный промпт
        "params": {},
        "tokens": 0,         # потрачено LLM-токенов за сессию
        "llm_calls": 0,
        "turns": 0,
        "await": None,       # чего ждём от пользователя: type | model | params | refine | idea
        "last_chips": [],    # кнопки прошлого ответа — чтобы понять, если их label пришёл текстом
        "owner": None,       # id пользователя: анонимный разговор продолжается после входа
        "degraded_told": False,
        "brief": None,       # {q: вопросы, a: ответы, extra: детали своими словами, summary}
        "brief_done": False,
        "variants": [],      # последние варианты промпта
        "var_round": 0,
    }


class MemoryStore:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._d: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self.clock = clock

    def get(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._d.get(sid)
            if not row:
                return None
            exp, raw = row
            if exp < self.clock():
                self._d.pop(sid, None)
                return None
            return json.loads(raw)

    def set(self, sid: str, data: dict[str, Any], ttl: int = TTL_SEC) -> None:
        with self._lock:
            self._d[sid] = (self.clock() + ttl, json.dumps(data, ensure_ascii=False))


class RedisStore:
    """redis-py клиент с decode_responses=True (как в queue_runtime). Ошибки Redis не валят чат."""

    def __init__(self, client: Any, ttl: int = TTL_SEC):
        self.r = client
        self.ttl = ttl

    def get(self, sid: str) -> dict[str, Any] | None:
        try:
            raw = self.r.get(KEY.format(sid=sid))
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def set(self, sid: str, data: dict[str, Any], ttl: int | None = None) -> None:
        try:
            self.r.set(KEY.format(sid=sid), json.dumps(data, ensure_ascii=False), ex=ttl or self.ttl)
        except Exception:
            pass


def load(store: Any, sid: str) -> dict[str, Any]:
    base = empty_session()
    got = store.get(sid) if sid else None
    if isinstance(got, dict):
        base.update({k: v for k, v in got.items() if k in base})
    return base
