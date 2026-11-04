"""Начальный интент, когда запрос не попал в обычный сценарий.

Алгоритм тот же, что в intent-router/src/intentRouter.ts: сначала языковая модель,
если она не ответила — ключевые слова. Файлы пакета не меняются.
Решение: запустить существующий процесс, задать один вопрос или отказаться.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable

log = logging.getLogger("assistant.intent_route")

_PROMPT = os.path.join(os.path.dirname(__file__), "..", "intent-router", "prompts", "router-system-prompt.md")

TYPES = ("image", "video", "text", "mixed", "unclear", "out_of_scope")
TEMPLATES = ("image", "video", "text")
MIN_CONFIDENCE = 0.7

DEFAULT_CLARIFY = {
    "question": "Уточните, пожалуйста, что именно нужно?",
    "options": ["Тексты для постов", "Баннер или картинка", "Видео / reels", "Комплект для запуска", "Другое"],
}
FALLBACK_NOTICE = "Редактор сейчас отвечает медленно, поэтому уточню вручную. "
OUT_OF_SCOPE_MESSAGE = (
    "С этим я помочь не могу. Я умею: промпты для изображений и видео, "
    "а также маркетинговые тексты (посты, описания, слоганы). Что из этого вам нужно?"
)
MISSING_QUESTIONS = {
    "subject": "Что должно быть в кадре или о чём материал?",
    "product": "Что продаём? Опишите продукт или услугу в паре слов.",
}
KEYWORDS = {
    "image": re.compile(
        r"фото|картин|изображ|иллюстрац|баннер|обложк|постер|плакат|визуал|аватар|"
        r"карточк[уиа]? товар|кадр|снимок|снимк|image|picture|photo|banner",
        re.I,
    ),
    "video": re.compile(r"видео|ролик|рилс|reels?|shorts?|клип|анимац|тикток|tiktok|video|сторис", re.I),
    "text": re.compile(
        r"текст|пост(?!ер)|описани|слоган|заголов|статья|стать[юи]|письм|рассылк|сценари|"
        r"контент[- ]план|подпис|caption|copy|лендинг",
        re.I,
    ),
}
OUT_OF_SCOPE_HINTS = re.compile(r"погод|курс валют|рецепт|код на|программ|юрист|оплат|возврат денег|пароль", re.I)
FREE_TEXT = re.compile(r"^\s*(другое|опишу сам(?:\(а\))?|other)\s*\.?\s*$", re.I)


def system_prompt() -> str:
    with open(_PROMPT, encoding="utf-8") as f:
        return f.read()


def is_free_text(label: str) -> bool:
    return bool(FREE_TEXT.match(label or ""))


def classify_by_keywords(text: str) -> dict:
    raw = (text or "").strip()
    base = {
        "summary": raw[:120],
        "critical_missing": [],
        "nice_to_have": [],
        "source": "keywords",
    }
    matched = [name for name, rx in KEYWORDS.items() if rx.search(raw)]
    if len(matched) == 1:
        return {**base, "type": matched[0], "confidence": 0.75, "clarify_question": None, "options": []}
    if len(matched) > 1:
        return {
            **base, "type": "mixed", "confidence": 0.6,
            "clarify_question": "С чего начнём?",
            "options": ["Сначала текст", "Сначала визуал", "Сразу всё"],
        }
    if OUT_OF_SCOPE_HINTS.search(raw):
        return {**base, "type": "out_of_scope", "confidence": 0.6, "clarify_question": None, "options": []}
    return {
        **base, "type": "unclear", "confidence": 0.3,
        "clarify_question": DEFAULT_CLARIFY["question"],
        "options": list(DEFAULT_CLARIFY["options"]),
    }


def parse_llm_response(raw: str) -> dict | None:
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("type") not in TYPES:
        return None
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        return None
    if confidence != confidence:  # NaN
        return None

    def strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [x for x in value if isinstance(x, str)]

    question = data.get("clarify_question")
    return {
        "type": data["type"],
        "confidence": min(1.0, max(0.0, confidence)),
        "summary": data.get("summary") if isinstance(data.get("summary"), str) else "",
        "critical_missing": strings(data.get("critical_missing")),
        "nice_to_have": strings(data.get("nice_to_have")),
        "clarify_question": question.strip() if isinstance(question, str) and question.strip() else None,
        "options": strings(data.get("options"))[:5],
        "source": "llm",
    }


def decide(intent: dict, min_confidence: float = MIN_CONFIDENCE) -> dict:
    notice = FALLBACK_NOTICE if intent.get("source") == "keywords" else ""
    if intent.get("type") == "out_of_scope":
        return {"action": "out_of_scope", "message": OUT_OF_SCOPE_MESSAGE, "intent": intent}
    if intent.get("type") in ("unclear", "mixed") or float(intent.get("confidence") or 0) < min_confidence:
        options = intent.get("options") or []
        return {
            "action": "clarify",
            "message": notice + (intent.get("clarify_question") or DEFAULT_CLARIFY["question"]),
            "options": options if len(options) >= 2 else list(DEFAULT_CLARIFY["options"]),
            "intent": intent,
        }
    missing = next((m for m in (intent.get("critical_missing") or []) if m in MISSING_QUESTIONS), None)
    if missing:
        return {
            "action": "clarify",
            "message": intent.get("clarify_question") or MISSING_QUESTIONS[missing],
            "options": list(intent.get("options") or []),
            "intent": intent,
        }
    return {"action": "build_prompt", "template": intent["type"], "intent": intent}


def route_request(text: str, call_llm: Callable[[str, str], str] | None = None, timeout_note: str = "") -> dict:
    """call_llm(system, user) -> сырой текст. Исключение или пустой ответ — ключевые слова."""
    raw = (text or "").strip()
    if not raw:
        intent = classify_by_keywords("")
        intent["type"] = "unclear"
        return decide(intent)
    if call_llm is not None:
        try:
            parsed = parse_llm_response(call_llm(system_prompt(), raw))
            if parsed:
                decision = decide(parsed)
                _log_unusual(raw, decision)
                return decision
            log.warning("intent router: модель вернула не JSON, беру ключевые слова")
        except Exception as exc:
            log.warning("intent router: модель недоступна (%s), беру ключевые слова", exc)
    decision = decide(classify_by_keywords(raw))
    if timeout_note:
        decision["message"] = timeout_note + (decision.get("message") or "")
    _log_unusual(raw, decision)
    return decision


def _log_unusual(text: str, decision: dict) -> None:
    if decision.get("action") == "build_prompt":
        return
    intent = decision.get("intent") or {}
    log.info("intent router unusual type=%s action=%s source=%s text=%s",
             intent.get("type"), decision.get("action"), intent.get("source"), (text or "")[:160])
