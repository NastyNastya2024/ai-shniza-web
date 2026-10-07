"""Сборка ответа: короткий markdown + кнопки. Лимиты жёсткие — никаких «простыней».

Кнопка (chip) = {"label": str, "action": str, "value"?: any}. Фронт по action решает, что делать:
  pick_model(value=id) · more · choose_type(value=kind) · use_mine · edit_prompt · generate(value=id)
  param(value={"name","value"}) · send(value=text) · open_models · open_topup · open_vitrina(value=url)
  login · attach · retry · wait · support · similar · cheaper · faster · no_photo_model · rephrase
Действия pick_model/more/choose_type/use_mine/param/similar/cheaper/faster/no_photo_model/rephrase
фронт отправляет обратно в /api/assistant как {"action": {...}} — сервер обработает без LLM.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .cards import Card
from .texts import b, t

MAX_LINES = 12
MAX_CHARS = 1200
MAX_CHIPS = 5


def chip(label: str, action: str, value: Any = None) -> dict[str, Any]:
    c: dict[str, Any] = {"label": label, "action": action}
    if value is not None:
        c["value"] = value
    return c


def std_chip(key: str, action: str, lang: str, value: Any = None, **kw) -> dict[str, Any]:
    return chip(b(key, lang, **kw), action, value)


def vitrina_link(base: str, model_id: str, topic: str) -> str:
    url = f"{base}?model={quote(model_id)}"
    q = "+".join(re.findall(r"[\w-]+", topic or ""))  # кириллицу не кодируем в %D0… — короче ответ, браузер поймёт
    if q:
        url += f"&q={q}"
    return url


def model_line(card: Card, price: str | None, lang: str, vitrina_base: str, topic: str, idx: int) -> list[str]:
    price_s = price or t("price_unknown", lang)
    head = f"{idx}. **{card.title}** — {card.text('strengths', lang)} · {price_s} · {card.text('speed', lang)}"
    link = f"   [{t('vitrina', lang)}]({vitrina_link(vitrina_base, card.id, topic)})"
    return [head, link]


def limit(lines: list[str]) -> str:
    """≤12 непустых строк и ≤1200 символов; обрезаем по строкам, а не посреди слова."""
    out: list[str] = []
    n = 0
    total = 0
    for ln in lines:
        if ln is None:
            continue
        ln = ln.rstrip()
        add = len(ln) + 1
        if ln.strip():
            if n >= MAX_LINES or total + add > MAX_CHARS:
                break
            n += 1
        total += add
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def quote_prompt(prompt: str) -> str:
    return "> " + " ".join((prompt or "").split())


def response(lines: list[str], chips: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    seen: set[tuple] = set()
    uniq: list[dict[str, Any]] = []
    for c in chips or []:
        k = (c["action"], repr(c.get("value")))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    return {"reply": limit(lines), "chips": uniq[:MAX_CHIPS], **extra}
