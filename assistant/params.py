"""Параметры генерации — без LLM.

1. extract(text) — «сырые» пожелания: формат, длительность, качество, звук, инструментал.
2. fit(raw, card) — перевод в имена и значения конкретной модели (card.params = ключи payload builder-а):
   duration → duration | music_length_ms;  quality → resolution | quality | size;
   audio → generate_audio | generate_audio_switch;  instrumental → force_instrumental.
3. Значения по умолчанию (card.defaults) показываются выбранными — пользователь меняет кнопками.
"""
from __future__ import annotations

import re
from typing import Any

from .cards import Card

I = re.IGNORECASE

ASPECT_RULES: list[tuple[str, re.Pattern]] = [
    ("9:16", re.compile(r"\b9 ?[:x×/] ?16\b|вертикальн|reels?\b|рилс|сторис|stories|tiktok|тикток|шортс|shorts|vertical|portrait", I)),
    ("16:9", re.compile(r"\b16 ?[:x×/] ?9\b|горизонтальн|youtube|ютуб|широкоформат|widescreen|horizontal|landscape", I)),
    ("1:1", re.compile(r"\b1 ?[:x×/] ?1\b|квадрат|square|аватар|avatar", I)),
    ("4:3", re.compile(r"\b4 ?[:x×/] ?3\b", I)),
    ("3:4", re.compile(r"\b3 ?[:x×/] ?4\b|постер|poster|обложк", I)),
]
DURATION_RX = re.compile(r"\b(\d{1,3})\s*-?\s*(с|сек|секунд\w*|s|sec|secs|seconds?)\b", I)
MINUTE_RX = re.compile(r"\b(\d{1,2})\s*(мин\w*|min|minutes?)\b", I)
QUALITY_RULES = [("4k", re.compile(r"\b4\s?[kк]\b|2160p|максимальн\w* качеств|max quality", I)),
                 ("1080p", re.compile(r"1080p?|full ?hd|фулл ?хд|высок\w* качеств|high quality|для печати|print", I)),
                 ("720p", re.compile(r"720p?|\bhd\b", I)),
                 ("draft", re.compile(r"черновик|набросок|draft|побыстрее|дешевле", I))]
NO_AUDIO = re.compile(r"без звука|без аудио|беззвуч|no (sound|audio)|silent|mute", I)
WITH_AUDIO = re.compile(r"со звуком|с звуком|с озвучк|с диалог|with (sound|audio)|with dialog", I)
INSTRUMENTAL = re.compile(r"инструментал|без вокал|без слов|instrumental|no vocals", I)
WITH_VOCALS = re.compile(r"с вокал|с голос|песн|with vocals|\bsong\b", I)

# подписи групп параметров
NAME_LABEL = {
    "aspect_ratio": {"ru": "Формат", "en": "Aspect ratio"},
    "duration": {"ru": "Длительность", "en": "Duration"},
    "music_length_ms": {"ru": "Длительность", "en": "Duration"},
    "resolution": {"ru": "Качество", "en": "Quality"},
    "quality": {"ru": "Качество", "en": "Quality"},
    "size": {"ru": "Размер", "en": "Size"},
    "generate_audio": {"ru": "Звук", "en": "Audio"},
    "generate_audio_switch": {"ru": "Звук", "en": "Audio"},
    "force_instrumental": {"ru": "Вокал", "en": "Vocals"},
    "style_type": {"ru": "Стиль", "en": "Style"},
}
VALUE_LABEL = {
    "9:16": {"ru": "9:16 верт.", "en": "9:16 vertical"},
    "16:9": {"ru": "16:9 гориз.", "en": "16:9 wide"},
    "1:1": {"ru": "1:1 квадрат", "en": "1:1 square"},
    "3:4": {"ru": "3:4 портрет", "en": "3:4 portrait"},
    "4:3": {"ru": "4:3", "en": "4:3"},
    "2:3": {"ru": "2:3 портрет", "en": "2:3 portrait"},
    "3:2": {"ru": "3:2 альбом", "en": "3:2 landscape"},
    "low": {"ru": "черновик", "en": "draft"},
    "medium": {"ru": "обычное", "en": "standard"},
    "high": {"ru": "высокое", "en": "high"},
    "Auto": {"ru": "авто", "en": "auto"},
    "General": {"ru": "общий", "en": "general"},
    "Realistic": {"ru": "реализм", "en": "realistic"},
    "Design": {"ru": "дизайн", "en": "design"},
}
DURATION_NAMES = ("duration", "music_length_ms")
QUALITY_NAMES = ("resolution", "quality", "size")
AUDIO_NAMES = ("generate_audio", "generate_audio_switch")


def extract(text: str) -> dict[str, Any]:
    """Сырые пожелания из текста (в «общих» единицах: секунды, 4k/1080p/720p/draft, bool)."""
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
    for val, rx in QUALITY_RULES:
        if rx.search(t):
            out["quality"] = val
            break
    if NO_AUDIO.search(t):
        out["audio"] = False
    elif WITH_AUDIO.search(t):
        out["audio"] = True
    if INSTRUMENTAL.search(t):
        out["instrumental"] = True
    elif WITH_VOCALS.search(t):
        out["instrumental"] = False
    return out


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^(\d+)", str(v))
    return float(m.group(1)) if m else None


def _nearest(value: float, options: list[Any]) -> Any:
    nums = [(o, _num(o)) for o in options if _num(o) is not None]
    if not nums:
        return None
    return min(nums, key=lambda p: (abs(p[1] - value), -p[1]))[0]


def _quality_pick(want: str, options: list[Any]) -> Any:
    low = {str(o).lower(): o for o in options}
    if want in low:
        return low[want]
    if want == "4k":
        return low.get("4k") or options[-1]           # максимум из доступного
    if want == "draft":
        return low.get("low") or options[0]           # минимум из доступного
    if want == "1080p":
        return low.get("1080p") or low.get("high") or low.get("2k") or options[-1]
    if want == "720p":
        return low.get("720p") or low.get("768p") or low.get("medium") or low.get("1k")
    return None


def fit(raw: dict[str, Any], card: Card) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Пожелания → параметры модели. Только ключи card.params и только допустимые значения.
    adjustments — где пришлось подогнать (честно сообщаем пользователю)."""
    params: dict[str, Any] = {}
    adj: list[dict[str, Any]] = []
    for name, options in card.params.items():
        if name == "aspect_ratio" and "aspect_ratio" in raw:
            v = raw["aspect_ratio"]
            if v in options:
                params[name] = v
            elif v in ("3:4", "2:3") and ("2:3" in options or "3:4" in options):
                params[name] = "2:3" if "2:3" in options else "3:4"
            elif v in ("4:3", "3:2") and ("3:2" in options or "4:3" in options):
                params[name] = "3:2" if "3:2" in options else "4:3"
            elif v == "9:16" and "2:3" in options:
                params[name] = "2:3"
                adj.append({"param": name, "asked": v, "got": "2:3"})
            elif v == "16:9" and "3:2" in options:
                params[name] = "3:2"
                adj.append({"param": name, "asked": v, "got": "3:2"})
        elif name in DURATION_NAMES and "duration" in raw:
            sec = raw["duration"]
            want = sec * 1000 if name == "music_length_ms" else sec
            got = want if want in options else _nearest(want, options)
            if got is not None:
                params[name] = got
                if got != want:
                    adj.append({"param": name, "asked": sec, "got": got // 1000 if name == "music_length_ms" else got})
        elif name in QUALITY_NAMES and "quality" in raw:
            got = _quality_pick(raw["quality"], options)
            if got is not None:
                params[name] = got
        elif name in AUDIO_NAMES and "audio" in raw:
            params[name] = raw["audio"]
        elif name == "force_instrumental" and "instrumental" in raw:
            params[name] = raw["instrumental"]
    return params, adj


def with_defaults(card: Card, params: dict[str, Any]) -> dict[str, Any]:
    return {**{k: v for k, v in card.defaults.items() if k in card.params}, **params}


def missing(card: Card, params: dict[str, Any]) -> list[str]:
    return [p for p in card.ask_first if p not in params]


def validate(card: Card, params: dict[str, Any] | None) -> dict[str, Any]:
    """Фильтр параметров с клиента: только белый список карточки."""
    clean: dict[str, Any] = {}
    for name, value in (params or {}).items():
        opts = card.params.get(name)
        if opts and value in opts and not (isinstance(value, bool) != any(isinstance(o, bool) for o in opts)):
            clean[name] = value
    return clean


def value_label(name: str, value: Any, lang: str) -> str:
    L = "en" if lang == "en" else "ru"
    if isinstance(value, bool):
        if name == "force_instrumental":
            return {"ru": ("без вокала", "с вокалом"), "en": ("instrumental", "with vocals")}[L][0 if value else 1]
        return {"ru": ("есть", "без звука"), "en": ("on", "off")}[L][0 if value else 1]
    if name == "music_length_ms":
        return f"{int(value) // 1000} с" if L == "ru" else f"{int(value) // 1000}s"
    if name == "duration":
        return f"{value} с" if L == "ru" else f"{value}s"
    row = VALUE_LABEL.get(str(value))
    return row[L] if row else str(value)


def name_label(name: str, lang: str) -> str:
    row = NAME_LABEL.get(name)
    return (row.get(lang) or row["ru"]) if row else name


def label(name: str, value: Any, lang: str) -> str:
    return f"{name_label(name, lang).lower()} {value_label(name, value, lang)}"


def seconds(card: Card, params: dict[str, Any]) -> int | None:
    if "duration" in params:
        return int(params["duration"])
    if "music_length_ms" in params:
        return int(params["music_length_ms"]) // 1000
    return None


PARAM_ORDER = ("aspect_ratio", "duration", "music_length_ms", "resolution", "quality", "size",
               "generate_audio", "generate_audio_switch", "force_instrumental", "style_type")


def groups(card: Card, params: dict[str, Any], lang: str, has_image: bool = False) -> list[dict[str, Any]]:
    """Блок параметров для UI: группы кнопок, выбранное значение отмечено."""
    out = []
    for name in sorted(card.params, key=lambda n: PARAM_ORDER.index(n) if n in PARAM_ORDER else 99):
        if name == "aspect_ratio" and has_image and card.kind in {"video", "edit"}:
            continue  # с фото формат берётся из фото (builder убирает aspect_ratio)
        out.append({
            "name": name,
            "label": name_label(name, lang),
            "options": [{"value": v, "label": value_label(name, v, lang), "selected": params.get(name) == v}
                        for v in card.params[name]],
        })
    return out
