"""Карточки моделей: загрузка, проверка, доступ.

Карточка — единственный источник знаний ассистента о модели. LLM не знает моделей «из памяти»:
всё, что она пишет о модели, берётся из карточки.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "model_cards.json")
KINDS = {"video", "image", "edit", "music", "sfx", "text"}
MODES = {"t2v", "i2v", "t2i", "i2i", "t2m", "t2t"}


@dataclass
class Card:
    id: str
    title: str
    kind: str
    modes: list[str]
    tags: list[str]
    strengths: dict[str, str]
    limits: dict[str, str]
    speed: dict[str, str]
    rank: int
    params: dict[str, list[Any]]
    ask_first: list[str]
    prompt_style: str
    avoid: str = ""
    defaults: dict[str, Any] = field(default_factory=dict)  # что сейчас ставит builder на сервере
    extra: dict[str, Any] = field(default_factory=dict)

    def text(self, key: str, lang: str) -> str:
        v = getattr(self, key)
        return (v.get(lang) or v.get("ru") or "") if isinstance(v, dict) else str(v)

    @property
    def needs_image(self) -> bool:
        return all(m in {"i2v", "i2i"} for m in self.modes)

    def supports(self, has_image: bool) -> bool:
        if has_image:
            return any(m in {"i2v", "i2i"} for m in self.modes) or self.kind in {"music", "sfx", "text"}
        return not self.needs_image


class CardError(ValueError):
    pass


def load_cards(path: str = DEFAULT_PATH) -> tuple[dict[str, Card], dict[str, list[str]]]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    cards: dict[str, Card] = {}
    for mid, c in (raw.get("models") or {}).items():
        known = {k: c[k] for k in Card.__dataclass_fields__ if k in c and k not in {"id", "extra"}}
        extra = {k: v for k, v in c.items() if k not in Card.__dataclass_fields__}
        try:
            cards[mid] = Card(id=mid, extra=extra, **known)
        except TypeError as exc:
            raise CardError(f"{mid}: {exc}") from exc
    validate(cards.values())
    return cards, raw.get("neighbors") or {}


def validate(cards: Iterable[Card], integrated_ids: Iterable[str] | None = None) -> list[str]:
    """Raise CardError on broken cards; return warnings (e.g. card for unknown model id)."""
    warnings: list[str] = []
    ids = set(integrated_ids) if integrated_ids is not None else None
    for c in cards:
        if c.kind not in KINDS:
            raise CardError(f"{c.id}: bad kind {c.kind}")
        if not c.modes or not set(c.modes) <= MODES:
            raise CardError(f"{c.id}: bad modes {c.modes}")
        for lang_field in ("strengths", "limits", "speed"):
            if not getattr(c, lang_field).get("ru"):
                raise CardError(f"{c.id}: {lang_field}.ru is empty")
        if not set(c.ask_first) <= set(c.params):
            raise CardError(f"{c.id}: ask_first not in params")
        for name, opts in c.params.items():
            if not isinstance(opts, list) or len(opts) < 2:
                raise CardError(f"{c.id}: param {name} needs >= 2 options")
        for name, val in c.defaults.items():
            if name not in c.params or val not in c.params[name]:
                raise CardError(f"{c.id}: default {name}={val!r} not in options")
        if not c.prompt_style:
            raise CardError(f"{c.id}: prompt_style is empty")
        if ids is not None and c.id not in ids:
            warnings.append(f"card {c.id} has no model in INTEGRATED_MODELS")
    return warnings


def mini(card: Card, lang: str) -> dict[str, Any]:
    """Сжатая карточка для LLM — только то, что нужно для промпта (экономия токенов)."""
    return {
        "id": card.id,
        "title": card.title,
        "strengths": card.text("strengths", "en"),
        "limits": card.text("limits", "en"),
        "prompt_style": card.prompt_style,
        "avoid": card.avoid,
    }
