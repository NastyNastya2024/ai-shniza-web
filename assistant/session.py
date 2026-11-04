"""Память диалога. Redis (TTL 24 ч, ASSIST_SESSION_TTL_SEC) в проде, словарь в тестах.

Состояние подбора и короткая история реплик (последние 12, по 300 символов) — чтобы правка вроде «а теперь вечером» относилась к текущей задаче.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable



def _ttl_from_env() -> int:
    """Сколько помощник помнит разговор. По умолчанию 24 ч — столько же живут прикреплённые файлы
    и гостевая история в браузере, чтобы «вернулся вечером — продолжили с того же места» было правдой."""
    try:
        v = int(os.getenv("ASSIST_SESSION_TTL_SEC") or 24 * 3600)
    except ValueError:
        v = 24 * 3600
    return max(600, min(7 * 24 * 3600, v))


TTL_SEC = _ttl_from_env()
KEY = "assist:sess:{sid}"
MAX_SESSION_ID = 128


def empty_session() -> dict[str, Any]:
    return {
        "lang": None,
        "kind": None,        # тип задачи
        "assist_mode": None, # prompt — собираем промпт; direct — сразу к моделям
        "topic": "",         # 1–3 слова для ссылки на витрину
        "needs": [],
        "idea": "",          # исходный текст пользователя (для «вернуть мой текст»)
        "shown": [],         # какие модели уже показывали
        "picked": None,      # выбранная модель
        "prompt": "",        # текущий адаптированный промпт (с движением камеры для видео)
        "prompt_base": "",   # промпт без инструкции камеры
        "camera": None,      # id движения камеры (static / dolly-in / …)
        "camera_cleared": False,  # пользователь явно снял движение («Без движения»)
        "params": {},
        "tokens": 0,         # потрачено LLM-токенов за сессию
        "llm_calls": 0,
        "turns": 0,
        "await": None,       # type | gen_type | has_prompt | model | params | refine | idea | …
        "last_chips": [],    # кнопки прошлого ответа — чтобы понять, если их label пришёл текстом
        "owner": None,       # id пользователя: анонимный разговор продолжается после входа
        "degraded_told": False,
        "brief": None,       # {q: вопросы, a: ответы, extra: детали своими словами, summary}
        "brief_done": False,
        "brief_guide": None, # id модели-ориентира для брифа (промпт ещё без выбора модели)
        "brief_for_model": None,  # id модели, под которую уточняем (профиль clarify/structure)
        "variants": [],      # последние варианты промпта
        "var_round": 0,
        "junk_count": 0,     # сколько непонятных сообщений подряд — чтобы не повторять один и тот же ответ
        "files": [],         # скрепка: [{kind, name}] — чтобы называть файлы по имени
        "files_told": False, # уже сказали «Вижу фото «cat.png»» для этого набора файлов
        "gen_kind": None,    # тип генерации (video/image…), пока kind временно = text на шаге доработки
        "gen_model": None,   # id модели генерации, выбранной до брифа — после polish не спрашивать снова
        "polish_draft": "",  # промпт на шаге «доработать / использовать» — не терять при чате с Claude/GPT
        "tree": None,        # дерево подсказок: {story, step, shown, ign, off, trail, ts, prof, pc} — см. tree.state()
        "polish_model": None,
        "prompt_gate": False,  # показывали ли «нужен промпт?» — для кнопки «Назад» с брифа
        "from_polish": False,  # список моделей после «Использовать этот промпт» (если модель ещё не была выбрана)
        "sb": None,          # режим «Раскадровка»: {step, source, script, idea, frames, format, aspect, style, model}
        "reel": None,        # режим «Рилс»: {step, idea, style, refs, characters, script, frames, model, final}
        "pipe": None,        # флоу помощника и ожидание результата: {on, stage, sub, await, expect, chat}; раскадровка ставит expect=sb_frames
        "mode": None,        # режимы «Рилс» / «Сериал» (modes.py): {id, step, data, paused}
        "arts": [],          # артефакты флоу этой сессии (промпты, картинки, ролики). «Новый чат» и TTL сессии их стирают
        "log": [],           # последние реплики: [{role, text}] — до 12, текст до 300 символов
        "parked": None,      # прошлый черновик, если человек явно начал другую задачу
        "media": [],         # реестр загрузок и результатов этого диалога
        "focus": [],         # id файлов, на которые указала фраза
        "files_ok": False,   # набор для запуска подтверждён
        "texts": [],         # ответы текстовых моделей: [{model, name, text}]
        "switch_from": "",   # имя модели, с которой уходим — строка «Claude → Seedance»
        "switch_from_id": "",
        "switch_cands": [],  # несколько промптов — ждём, какой взять
        "switch_kind": "",
        "switch_text": "",
        "text_ask": "",      # фраза, которую отправить в текстовую модель после выбора
        "photo_look": "",    # id фото и круг вариантов: сетка уже смотрела этот кадр через Opus
        "alt_of": {},        # запасной id → основная карточка (та же модель, другая площадка)
        "route_model": "",   # id, который реально уйдёт в генерацию
        "flow": None,        # диалог v2: {stage, kind, story, slots, idea, path, next}
        "prior": [],         # прошлые генерации этого чата: [{kind, prompt}] — новая задача их не стирает
        "mcp": None,         # помощь с подключением: {stage, goal, service}
        "lock": "",          # id модели, которую человек закрепил
        "lock_off": "",      # id, для которой уже выбрали «подобрать другую»
        "lock_pending": None,  # {text, kind} — вопрос «остаться или подобрать» ждёт кнопку
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
