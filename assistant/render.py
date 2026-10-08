"""Сборка ответа: короткий текст + блоки для UI + кнопки.

Ответ:
  text    — 1–2 строки для пузыря ассистента (без markdown)
  blocks  — карточки для UI (рисует integration/assistant-ui.js):
              {"type":"models",  "items":[{id,title,price,estimate,badge,why,speed,vitrina_url}]}
              {"type":"prompt",  "model_id","title","text","note"}
              {"type":"params",  "model_id","groups":[{name,label,options:[{value,label,selected}]}]}
              {"type":"summary", "model_id","title","price","prompt","params":[str]}
              {"type":"camera",  "label","hint","items":[{id,title,preview,selected}]}
  chips   — кнопки действий [{label, action, value?, primary?}]
  reply   — тот же ответ ОДНИМ простым текстом (для старого фронта, который не умеет blocks)

Кнопка (chip) = {"label", "action", "value"?}. На сервер (как {"action":{type,value}}) уходят:
  pick_model · more · choose_type · use_mine · param · pick_camera · refine · improve · send · similar · cheaper · faster · no_photo_model · rephrase
Фронт сам: generate · edit_prompt · open_models · open_topup · open_vitrina · login · attach · retry · wait · support
"""
from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import quote

from .cards import Card
from .texts import b, t

MAX_LINES = 12
MAX_CHARS = 1200
MAX_CHIPS = 6


def chip(label: str, action: str, value: Any = None, primary: bool = False) -> dict[str, Any]:
    c: dict[str, Any] = {"label": label, "action": action}
    if value is not None:
        c["value"] = value
    if primary:
        c["primary"] = True
    return c


def std_chip(key: str, action: str, lang: str, value: Any = None, primary: bool = False, **kw) -> dict[str, Any]:
    return chip(b(key, lang, **kw), action, value, primary)


def vitrina_link(base: str, model_id: str, topic: str) -> str:
    url = f"{base}?model={quote(model_id)}"
    q = "+".join(re.findall(r"[\w-]+", topic or ""))
    if q:
        url += f"&q={q}"
    return url


_UNIT = [(re.compile(r"\s*/\s*изображени\w*", re.I), "/фото"), (re.compile(r"\s*/\s*картинк\w*", re.I), "/фото"),
         (re.compile(r"\s*/\s*сек\w*", re.I), "/сек"), (re.compile(r"\s*/\s*секунд\w*", re.I), "/сек"),
         (re.compile(r"\s*/\s*image", re.I), "/image"), (re.compile(r"\s*/\s*(sec|second)\w*", re.I), "/s"),
         (re.compile(r"\s*/\s*запуск\w*", re.I), "/запуск")]


def short_price(price: str | None) -> str | None:
    """«3,9 ₽ / изображение at 1K» → «3,9 ₽/фото». Технические хвосты (at 1K, at low) убираем."""
    if not price:
        return price
    raw = str(price).strip()
    s = re.sub(r"\s+(at|@|при)\s+\S+.*$", "", raw, flags=re.I)
    if s != raw and not re.match(r"^(от|from)\b", s, re.I):
        s = "от " + s  # «at low» — цена минимальной настройки
    for rx, rep in _UNIT:
        s = rx.sub(rep, s)
    return re.sub(r"\s{2,}", " ", s).strip()


def per_second(price: str | None) -> float | None:
    if not price or not re.search(r"/\s*(сек|s\b|sec)", price, re.I):
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", price.replace(" ", ""))
    return float(m.group(1).replace(",", ".")) if m else None


def estimate(price: str | None, sec: int | None, lang: str) -> str | None:
    ps = per_second(price)
    if ps is None or not sec:
        return None
    total = ps * sec
    kop = math.ceil(round(total * 100, 6))   # так же, как считает проверка баланса (вверх до копейки)
    num = str(kop // 100) if (kop % 100 == 0 or total >= 10) else f"{kop / 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    if total >= 10:
        num = f"{total:.0f}"
    return f"≈ {num} ₽ " + t("for_sec", lang, sec=sec)


def model_item(card: Card, price: str | None, lang: str, vitrina_base: str, topic: str,
               badge: str | None = None, sec: int | None = None) -> dict[str, Any]:
    sp = short_price(price)
    return {
        "id": card.id, "title": card.title, "price": sp or t("price_unknown", lang),
        "estimate": estimate(sp, sec, lang), "badge": badge,
        "why": card.text("strengths", lang), "speed": card.text("speed", lang),
        "needs_image": card.needs_image, "vitrina_url": vitrina_link(vitrina_base, card.id, topic),
    }


def plain_from(text: str, blocks: list[dict[str, Any]], lang: str) -> list[str]:
    """Простой текст из блоков — для фронта, который рисует только reply."""
    lines = [text] if text else []
    for bl in blocks:
        if bl["type"] == "models":
            for i, it in enumerate(bl["items"], 1):
                extra = f" · {it['badge']}" if it.get("badge") else ""
                lines.append(f"{i}. {it['title']} — {it['price']}{extra} · {it['why']}")
        elif bl["type"] == "prompt":
            lines.append("«" + " ".join(bl["text"].split()) + "»")
        elif bl["type"] == "params":
            for g in bl["groups"]:
                sel = next((o["label"] for o in g["options"] if o["selected"]), "—")
                lines.append(f"{g['label']}: {sel}")
        elif bl["type"] == "summary":
            lines.append(f"{bl['title']} · {bl.get('estimate') or bl['price']}")
        elif bl["type"] == "camera":
            sel = next((it["title"] for it in bl.get("items") or [] if it.get("selected")), None)
            if sel:
                lines.append(f"{bl.get('label') or 'Camera'}: {sel}")
    return lines


def limit(lines: list[str]) -> str:
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


def response(lines: list[str], chips: list[dict[str, Any]] | None = None, blocks: list[dict[str, Any]] | None = None,
             lang: str = "ru", **extra: Any) -> dict[str, Any]:
    seen: set[tuple] = set()
    uniq: list[dict[str, Any]] = []
    for c in chips or []:
        k = (c["action"], repr(c.get("value")))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    blocks = blocks or []
    text = limit(lines)
    reply = limit(plain_from(text, blocks, lang)) if blocks else text
    return {"text": text, "reply": reply, "blocks": blocks, "chips": uniq[:MAX_CHIPS], **extra}
