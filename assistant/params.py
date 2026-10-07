"""Параметры генерации из текста пользователя — без LLM.

Извлекаем «сырые» пожелания (9:16, 10 секунд, 4k, без звука, инструментал),
затем подгоняем под схему конкретной модели (card.params). Всё, чего нет в схеме, не отправляем:
сервер принимает только параметры из белого списка карточки.
"""
from __future__ import annotations

import re
from typing import Any

from .cards import Card

I = re.IGNORECASE

ASPECT_RULES: list[tuple[str, re.Pattern]] = [
    ("9:16", re.compile(r"\b9 ?[:x×/] ?16\b|вертикальн|reels?\b|рилс|сторис|stories|tiktok|тикток|шортс|shorts|vertical|portrait", I)),
    ("16:9", re.compile(r"\b16 ?[:x×/] ?9\b|горизонтальн|youtube|ютуб|широкоформат|widescreen|horizontal|landscape", I)),
    ("1:1", re.compile(r"\b1 ?[:x×/] ?1\b|квадрат|square", I)),
    ("4:3", re.compile(r"\b4 ?[:x×/] ?3\b", I)),
    ("3:4", re.compile(r"\b3 ?[:x×/] ?4\b", I)),
]
DURATION_RX = re.compile(r"\b(\d{1,3})\s*(?:-?\s*)(с|сек|секунд\w*|s|sec|secs|seconds?)\b", I)
MINUTE_RX = re.compile(r"\b(\d{1,2})\s*(мин\w*|min|minutes?)\b", I)
RES_RX = [("4k", re.compile(r"\b4\s?[kк]\b|2160p", I)), ("1080p", re.compile(r"1080p?|full ?hd|фулл ?хд", I)),
          ("720p", re.compile(r"720p?", I))]
NO_AUDIO = re.compile(r"без звука|без аудио|беззвуч|no (sound|audio)|silent|mute", I)
WITH_AUDIO = re.compile(r"со звуком|с звуком|с озвучк|с диалог|with (sound|audio)|with dialog", I)
INSTRUMENTAL = re.compile(r"инструментал|без вокал|без слов|instrumental|no vocals", I)

LABELS = {
    "aspect_ratio": {"ru": "формат {v}", "en": "aspect {v}"},
    "duration": {"ru": "{v} с", "en": "{v}s"},
    "resolution": {"ru": "качество {v}", "en": "quality {v}"},
    "generate_audio": {"ru": "звук: {v}", "en": "audio: {v}"},
    "instrumental": {"ru": "инструментал: {v}", "en": "instrumental: {v}"},
}
YESNO = {True: {"ru": "да", "en": "yes"}, False: {"ru": "нет", "en": "no"}}


def extract(text: str) -> dict[str, Any]:
    """Сырые пожелания из текста. Значения — в формате схемы модели."""
    t = text or ""
    out: dict[str, Any] = {}
    for val, rx in ASPECT_RULES:
        if rx.search(t):
            out["aspect_ratio"] = val
            break
    m = DURATION_RX.search(t)
    if m:
        out["duration"] = int(m.group(1))
    else:
        m = MINUTE_RX.search(t)
        if m:
            out["duration"] = int(m.group(1)) * 60
    for val, rx in RES_RX:
        if rx.search(t):
            out["resolution"] = val
            break
    if NO_AUDIO.search(t):
        out["generate_audio"] = False
    elif WITH_AUDIO.search(t):
        out["generate_audio"] = True
    if INSTRUMENTAL.search(t):
        out["instrumental"] = True
    return out


def _nearest(value: Any, options: list[Any]) -> Any:
    nums = [o for o in options if isinstance(o, (int, float)) and not isinstance(o, bool)]
    if isinstance(value, (int, float)) and nums:
        return min(nums, key=lambda o: (abs(o - value), -o))
    return None


def fit(raw: dict[str, Any], card: Card) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Подогнать пожелания под схему модели.

    Возвращает (params, adjustments). params — только ключи из card.params и только допустимые значения.
    adjustments — что пришлось поменять (для честного сообщения пользователю).
    """
    params: dict[str, Any] = {}
    adjustments: list[dict[str, Any]] = []
    for name, value in raw.items():
        options = card.params.get(name)
        if not options:
            continue  # модель не даёт выбирать этот параметр — молча не отправляем
        if value in options:
            params[name] = value
            continue
        near = _nearest(value, options)
        if near is not None:
            params[name] = near
            adjustments.append({"param": name, "asked": value, "got": near})
    return params, adjustments


def missing(card: Card, params: dict[str, Any]) -> list[str]:
    """Параметры, которые модель просит уточнить до генерации (ask_first) и которых ещё нет."""
    return [p for p in card.ask_first if p not in params]


def validate(card: Card, params: dict[str, Any] | None) -> dict[str, Any]:
    """Фильтр для пришедших от клиента параметров: только белый список карточки."""
    clean: dict[str, Any] = {}
    for name, value in (params or {}).items():
        opts = card.params.get(name)
        if opts and value in opts:
            clean[name] = value
    return clean


def label(name: str, value: Any, lang: str) -> str:
    row = LABELS.get(name, {"ru": name + " {v}", "en": name + " {v}"})
    v = YESNO[value][lang if lang in ("ru", "en") else "ru"] if isinstance(value, bool) else value
    return (row.get(lang) or row["ru"]).format(v=v)
