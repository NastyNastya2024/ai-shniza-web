"""Rule-based assistant recommendations (no LLM when intent is clear)."""
from __future__ import annotations

import re
from typing import Any, Optional

from pricing import PRICING_SEED, list_pricing_public


def _detect(text: str, has_image: bool) -> dict[str, Any]:
    t = text.lower()
    category = None
    if has_image and re.search(r"видео|ожив|анимир|i2v|image.?to.?video", t):
        category = "video"
    elif re.search(r"видео|ролик|клип|seconds|сек", t):
        category = "video"
    elif re.search(r"картинк|изображ|постер|арт|фото", t):
        category = "image"
    elif re.search(r"музык|трек|бит|песн", t):
        category = "music"
    elif re.search(r"озвуч|голос|tts|speech", t):
        category = "voice"
    elif re.search(r"текст|напиши|эссе|перевод|чат", t):
        category = "text"

    duration = 5
    m = re.search(r"(\d+)\s*(?:с|сек|секунд)", t)
    if m:
        duration = max(1, min(15, int(m.group(1))))

    return {
        "category": category,
        "duration_sec": duration,
        "want_free": bool(re.search(r"бесплат|даром|очеред", t)),
        "want_cheap": bool(re.search(r"дёшев|дешев|бюджет|недорог", t)),
        "want_quality": bool(re.search(r"качеств|лучш|премиум|дорого", t)),
        "want_audio": bool(re.search(r"со звуком|со\s+звук|аудиодорож|voiceover", t)),
        "has_image": has_image,
        "clear": category is not None,
    }


def recommend(text: str, has_image: bool = False, free_left: int = 1, region: str = "RU") -> dict[str, Any]:
    intent = _detect(text, has_image)
    if not intent["clear"]:
        return {
            "used_llm": False,
            "reply": "Уточните, пожалуйста: нужно видео, картинка, музыка, озвучка или текст?",
            "options": [],
            "clarify": "Что именно создать?",
            "intent": intent,
        }

    items = [i for i in list_pricing_public(region) if i.get("category") == intent["category"] or (
        intent["category"] == "image" and i.get("category") == "tool"
    )]
    if intent["want_audio"]:
        audio_items = [i for i in items if i.get("has_audio") or i.get("is_free")]
        if audio_items:
            items = audio_items

    options: list[dict] = []
    free = next((i for i in items if i.get("is_free")), None)
    if free and free_left > 0 and intent["category"] == "video":
        options.append({
            "model_key": free["model_key"],
            "params": {"duration_sec": intent["duration_sec"]},
            "why": "Бесплатный вариант с очередью",
            "title": free.get("description_ru") or free["model_key"],
            "meta": f"Бесплатно · очередь ~40 мин · осталось сегодня {free_left}",
            "cta": "Бесплатно",
            "price_rub": 0,
            "is_free": True,
        })

    paid = [i for i in items if not i.get("is_free")]
    if intent["want_quality"]:
        paid_sorted = sorted(paid, key=lambda x: (-(x.get("quality_score") or 0), x.get("price_rub") or 0))
    else:
        paid_sorted = sorted(paid, key=lambda x: (x.get("example_rub_5s") or x.get("price_rub") or 10**9))

    for i, row in enumerate(paid_sorted[:2]):
        dur = intent["duration_sec"]
        if row.get("unit") == "per_second":
            price = int(row.get("price_rub") or 0) * dur
            label = row.get("price_label")
        else:
            price = int(row.get("price_rub") or 0)
            label = row.get("price_label")
        options.append({
            "model_key": row["model_key"],
            "params": {"duration_sec": dur},
            "why": "Лучше по цене" if i == 0 and not intent["want_quality"] else "Сильнее по качеству",
            "title": row.get("description_ru") or row["model_key"],
            "meta": f"{label} · ожидание обычно быстрее очереди",
            "cta": f"Создать за {price} ₽",
            "price_rub": price,
            "is_free": False,
        })

    options = options[:3]
    reply = "Подобрала варианты под запрос. Цены из каталога сервиса."
    if intent["want_free"] and not free:
        reply = "Бесплатного слота под эту задачу сейчас нет — вот платные варианты."

    return {
        "used_llm": False,
        "reply": reply,
        "options": options,
        "clarify": None,
        "intent": intent,
    }
