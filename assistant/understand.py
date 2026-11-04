"""Понимание свободного текста — слой над router.py.

Свежий запрос сначала читает языковая модель и сама выбирает процесс: текст, видео, картинка,
музыка, озвучка, вопрос, смена модели. router.py — запасной путь, если модель не ответила.

  1. fast()  — правила, 0 ₽: переключить модель, вопрос-совет, действие в интерфейсе, запуск режима.
  2. ask_llm() — разбор нейросетью (цепочка помощника).
     Возвращает JSON {intent, model, kind, mode, ui, value, question}; всё сверяется со списками — нейросеть
     не может придумать модель, режим или действие.
  3. Решение — в engine.py (_understood): запустить выбранный процесс.

Намерения: switch_model | question | ui_do | start_mode | generate | other.
"""
from __future__ import annotations

import re
from typing import Any

I = re.IGNORECASE

# ─────────────────────────────────────────── модели: как люди их называют
FAMILY_RX: list[tuple[str, re.Pattern]] = [
    ("claude", re.compile(r"\bклод\w*|\bклауд\w*|\bclaude\b|\bантропик|\banthropic", I)),
    ("deepseek", re.compile(r"дип\s?сик\w*|\bdeep\s?seek\b", I)),
    ("gpt", re.compile(r"\bgpt\b|\bгпт\b|чат\s?гпт|chat\s?gpt|\bджипити|\bopenai\b|\bопенаи", I)),
    ("gemini", re.compile(r"\bgemini\b|\bгемини\b|\bджемини\b|\bgoogle ai\b", I)),
]
# какая модель семейства по умолчанию (дешевле) и по просьбе «умнее»
FAMILY_MODELS = {"claude": ("claude-4-5-haiku", "claude-sonnet-5"), "deepseek": ("deepseek-v3-1",),
                 "gpt": ("gpt-5-4",), "gemini": ("gemini-3-5-flash",)}
SMART_RX = re.compile(r"умн|мощн|лучш|сильн|sonnet|сонет|opus|опус|smart|strong", I)
SWITCH_VERB = re.compile(r"\b(включи|включить|подключи|запусти|переключи\w*|выбери|поставь|дай|давай|хочу|можно|открой|"
                         r"смени|перейди|пусть|switch|use|turn on|enable)\b", I)
TALK_WITH = re.compile(r"(поговор\w*|пообща\w*|спрос\w*|чат|переписк\w*|работать|talk|chat)\s+(с|со|with)\b", I)

# ─────────────────────────────────────────── вопрос-совет
QUESTION_START = re.compile(
    r"^\s*(а\s+)?(какая|какой|какое|какие|каким|какую|что\s+лучше|что\s+выбрать|что\s+посовету\w*|посоветуй\w*|подскаж\w*|"
    r"чем\s+(отличается|отличаются|лучше|хуже)|в\s+ч[её]м\s+разница|почему|зачем|сколько|можно\s+ли|"
    r"есть\s+ли|что\s+такое|кто\s+лучше|which|what\s+is|what's|why|how\s+much|is\s+there|should\s+i)\b", I)
HOWTO = re.compile(r"^\s*(а\s+)?(как|how)\s+(мне\s+|лучше\s+|можно\s+)?(выбрать|настроить|поменять|сменить|включить|выключить|"
                   r"убрать|вернуть|сохранить|скачать|найти|пользоваться|работает|сделать\s+так|choose|change|set|use)\b", I)
MAKE_VERB = re.compile(r"\b(сделай|создай|нарисуй|сгенерируй|сними|напиши|оживи|анимируй|make|create|draw|generate)\b", I)

# ─────────────────────────────────────────── действия в интерфейсе (безопасные и обратимые)
THEME_RX: list[tuple[str, re.Pattern]] = [
    ("black", re.compile(r"(т[её]мн|ч[её]рн|ночн|dark|black)\w*\s+(тем|фон|режим|оформлен|интерфейс|theme|mode|background)|"
                         r"(тем|фон|режим|оформлен|интерфейс|theme|mode)\w*(?:\s+\S+){0,2}\s+(т[её]мн|ч[её]рн|ночн|dark|black)|\bсделай\s+темнее|темн(ая|ую) тема", I)),
    ("white", re.compile(r"(светл|бел|дневн|light|white)\w*\s+(тем|фон|режим|оформлен|интерфейс|theme|mode|background)|"
                         r"(тем|фон|режим|оформлен|интерфейс|theme|mode)\w*(?:\s+\S+){0,2}\s+(светл|бел|light|white)|\bсделай\s+светлее", I)),
    ("violet", re.compile(r"фиолет\w*\s+(тем|фон|оформлен)|(тем|фон)\w*\s+фиолет|violet|purple theme", I)),
]
PANEL_RX: list[tuple[str, re.Pattern]] = [
    ("mcp", re.compile(r"(открой|покажи|где)\s+(мои\s+)?(подключени|mcp|мсп|интеграци)", I)),
    ("models", re.compile(r"(открой|покажи)\s+((все\s+|список\s+)?(нейросет|модел)|список)", I)),
    ("vit", re.compile(r"(открой|покажи)\s+(витрин|примеры работ|чужие работы)", I)),
]
NEW_CHAT_RX = re.compile(r"^\s*(начн(и|ём|ем)\s+(заново|сначала)|новый\s+чат|очисти\s+чат|start\s+over|new\s+chat)\s*$", I)

# ─────────────────────────────────────────── режимы
SERIES_RX = re.compile(r"\bсериал\w*|\bсерии\b|\bэпизод\w*|\bweb[- ]?series\b|\bseries\b|мини-?сериал|многосерийн", I)
REELS_MODE_RX = re.compile(r"(режим\w*|по\s+шагам|под\s+ключ|полн\w+\s+цикл\w*|целиком|от\s+идеи\s+до\s+публикац\w*|step by step)"
                           r".{0,30}(рилс|reels?|шортс|shorts|тикток|tiktok)|"
                           r"(рилс|reels?|шортс|shorts)\w*.{0,20}(по\s+шагам|под\s+ключ|целиком|полн\w+\s+цикл\w*|режим|от\s+идеи)|"
                           r"(придума\w*|помоги\w*|нет)\s+(с\s+)?иде\w*.{0,20}(рилс|reels?|шортс|shorts)", I)
REELS_WORD = re.compile(r"\bрилс\w*|\breels?\b|\bшортс\w*|\bshorts\b|\bтикток\w*|\btiktok\b", I)

# router-намерения, которые важнее этого слоя (безопасность, ошибки, точные справки)
PROTECTED = {"crisis", "safety", "safety_person", "injection", "error_help", "ui_help", "compare", "price", "generate_now",
             "prompt_improve"}
INTENTS = ("switch_model", "question", "ui_do", "start_mode", "other")
MODES = ("reels", "series")
UI_DO = ("theme", "panel", "new_chat")
THEMES = ("white", "black", "light", "violet")
PANELS = ("models", "mcp", "vit")


def family(text: str) -> str | None:
    for fam, rx in FAMILY_RX:
        if rx.search(text or ""):
            return fam
    return None


def model_for(fam: str, text: str, cards: dict) -> str | None:
    if fam == "claude" and re.search(r"\bopus\b|опус", text or "", I) and "claude-opus-4-7" in cards:
        return "claude-opus-4-7"
    ids = [m for m in FAMILY_MODELS.get(fam, ()) if m in cards]
    if not ids:
        return None
    return ids[-1] if SMART_RX.search(text or "") and len(ids) > 1 else ids[0]


def is_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if QUESTION_START.search(t) or HOWTO.search(t):
        return not (MAKE_VERB.search(t) and not re.search(r"\?\s*$", t) and not QUESTION_START.search(t))
    # «…?» без глагола «сделай» — тоже вопрос («seedance лучше kling?»)
    return bool(re.search(r"\?\s*$", t)) and not MAKE_VERB.search(t) and len(t.split()) <= 14


def fast(text: str, cards: dict | None = None) -> dict | None:
    """Правила (0 ₽). None — правила не уверены."""
    t = (text or "").strip()
    if not t or len(t) > 400:
        return None
    cards = cards or {}
    fam = family(t)
    if fam and (SWITCH_VERB.search(t) or TALK_WITH.search(t) or len(t.split()) <= 2):
        mid = model_for(fam, t, cards)
        if mid and (not is_question(t) or len(t.split()) <= 3):   # «можно claude?» — тоже просьба включить
            return {"intent": "switch_model", "model": mid, "family": fam, "src": "rules"}
    if NEW_CHAT_RX.search(t):
        return {"intent": "ui_do", "ui": "new_chat", "src": "rules"}
    for theme, rx in THEME_RX:
        if rx.search(t):
            # «кружка на белом фоне» — описание кадра, не смена темы
            if re.search(r"карточк|картин|фото|маркетплейс|инфографик|\bвб\b|вайлд|озон|ozon|кроссов|товар|на\s+(бел|ч[её]рн)\w*\s+фон", t, I) and not re.search(
                    r"тем[аыуе]|режим|оформлен|интерфейс|theme", t, I):
                continue
            return {"intent": "ui_do", "ui": "theme", "value": theme, "src": "rules"}
    for panel, rx in PANEL_RX:
        if rx.search(t):
            return {"intent": "ui_do", "ui": "panel", "value": panel, "src": "rules"}
    if SERIES_RX.search(t) and not is_question(t):
        return {"intent": "start_mode", "mode": "series", "src": "rules"}
    if REELS_MODE_RX.search(t) and not is_question(t):
        return {"intent": "start_mode", "mode": "reels", "src": "rules"}
    if is_question(t):
        return {"intent": "question", "question": t, "src": "rules"}
    return None


# ─────────────────────────────────────────── слой 2: нейросеть
UNDERSTAND_SYSTEM = (
    "You are the dispatcher for {AI}-shnitsa, a studio of generative models. Read the user's message and choose "
    "which process to start. Return JSON only:\n"
    '{"intent": one of "switch_model" | "question" | "ui_do" | "start_mode" | "generate" | "other",\n'
    ' "model": model id from MODELS or "", "kind": "video"|"image"|"music"|"voice"|"text"|"", '
    '"mode": "reels"|"series"|"",\n'
    ' "ui": "theme"|"panel"|"new_chat"|"", "value": theme white|black|light|violet or panel models|mcp|vit or "",\n'
    ' "confidence": 0..1}\n'
    "generate — the user wants something made. Set kind to the result, not to the verb:\n"
    " text — anything to write or tell: a story, tale, poem, article, letter, script, explanation, advice. "
    "The words generate/сделай/сгенерируй do not make it a picture or a video.\n"
    " image — a still picture, photo, poster or product card.\n"
    " video — a moving clip. voice — spoken narration or voiceover, even if the sentence also says video.\n"
    " music — a track or song.\n"
    "If the user names the medium, use that kind. If they do not, decide from what they asked to receive.\n"
    "switch_model — chat with a named model. question — advice. ui_do — theme, panel, new chat.\n"
    "start_mode — a reels project or a series. other — greetings and anything else.\n"
    "Use ONLY ids from MODELS. Never invent models, modes or actions."
)


def _v_understand(cards: dict):
    def v(d: Any) -> dict:
        if not isinstance(d, dict):
            raise ValueError("not an object")
        intent = str(d.get("intent") or "other")
        if intent not in INTENTS + ("generate",):
            raise ValueError("bad intent")
        out = {"intent": intent, "src": "llm", "confidence": float(d.get("confidence") or 0)}
        mid = str(d.get("model") or "")
        if mid in cards:
            out["model"] = mid
        kind = str(d.get("kind") or "")
        if kind in ("video", "image", "music", "voice", "text"):
            out["kind"] = kind
        mode = str(d.get("mode") or "")
        if mode in MODES:
            out["mode"] = mode
        ui = str(d.get("ui") or "")
        val = str(d.get("value") or "")
        if ui in UI_DO:
            out["ui"] = ui
            if (ui == "theme" and val in THEMES) or (ui == "panel" and val in PANELS):
                out["value"] = val
        # несогласованный ответ — считаем «не понял»
        if intent == "switch_model" and "model" not in out:
            out["intent"] = "other"
        if intent == "start_mode" and "mode" not in out:
            out["intent"] = "other"
        if intent == "ui_do" and ("ui" not in out or (out["ui"] != "new_chat" and "value" not in out)):
            out["intent"] = "other"
        return out
    return v


def ask_llm(a: Any, text: str, ses: dict, ctx: dict) -> dict | None:
    cards = a.d.cards
    vis = [c for c in cards.values() if not a.d.catalog_fn or a.d.catalog_fn(c.id)]
    models = "; ".join(f"{c.id} ({c.title}, {c.kind})" for c in vis)[:3000]
    mode = ses.get("mode") if isinstance(ses.get("mode"), dict) else {}
    user = (f"MODELS: {models}\nCURRENT: mode={mode.get('id') or 'none'} step={mode.get('step', '')} "
            f"selected_model={ctx.get('selected_model_id') or ses.get('picked') or 'none'}\nMESSAGE: {text[:600]}")
    res = a._llm_json(UNDERSTAND_SYSTEM, user, _v_understand(cards), ses, max_tokens=160, task="understand")
    if not res or res.get("confidence", 1) < 0.5:
        return None
    if res["intent"] == "question":
        res["question"] = text
    if res["intent"] == "generate" and res.get("kind"):
        return res
    return res if res["intent"] in INTENTS and res["intent"] != "other" else None


# ─────────────────────────────────────────── ответы на вопросы
ANSWER_SYSTEM = (
    "You are the friendly assistant of {AI}-shnitsa, a studio of generative AI models. Answer the user's question in "
    "{lang}, 1-4 short sentences, concrete and practical. Use ONLY the facts below (models with prices, interface "
    "help, modes). If the facts do not cover it, say so briefly and suggest the closest thing the studio can do. "
    "If CONTEXT names the user's current story and step, keep the answer consistent with it and end on that step. "
    "Never name the studio's internal architecture, API suppliers or routing services; talk about models and prices only. "
    "Return JSON only: {\"answer\": text, \"models\": [up to 3 model ids from FACTS that fit the question, or []]}."
)


def _v_answer(cards: dict):
    def v(d: Any) -> dict:
        if not isinstance(d, dict) or not str(d.get("answer") or "").strip():
            raise ValueError("no answer")
        ids = [str(x) for x in (d.get("models") or []) if str(x) in cards][:3]
        return {"answer": str(d["answer"]).strip()[:900], "models": ids}
    return v


def facts(a: Any, lang: str) -> str:
    from .ui_help import HELP

    vis = [c for c in a.d.cards.values() if not a.d.catalog_fn or a.d.catalog_fn(c.id)]
    lines = []
    for c in vis:
        price = a._price(c.id) or ""
        lines.append(f"- {c.id}: {c.title} ({c.kind}{', ' + price if price else ''})")
    ui = [f"- {k}: " + " ".join(v.get("ru") or []) for k, v in HELP.items()]
    ui += ["- themes: кружок справа внизу — Белая, Чёрная, Светлая, Фиолетовая; помощник может переключить сам.",
           "- panel: справа вкладки Витрина, Модели (каталог нейросетей), MCP (подключения сервисов: vidIQ, Higgsfield — прогноз виральности, Dropbox, 3D)."]
    modes = ["- режим «Рилс»: идея → сценарий с хуком → раскадровка → видео → озвучка/музыка → монтаж → прогноз виральности → публикация.",
             "- режим «Сериал»: мир и герои → портреты героев → сценарий серии → раскадровка → видео → следующая серия с теми же героями."]
    return "MODELS:\n" + "\n".join(lines)[:3500] + "\nINTERFACE:\n" + "\n".join(ui)[:2500] + "\nMODES:\n" + "\n".join(modes)


def answer_llm(a: Any, question: str, ses: dict, lang: str) -> dict | None:
    system = ANSWER_SYSTEM.replace("{lang}", "Russian" if lang == "ru" else "English")
    from .tree import context_text
    tctx = context_text(ses, getattr(a.d, "tree", None))
    return a._llm_json(system, facts(a, lang) + ("\n\n" + tctx if tctx else "") + "\n\nQUESTION: " + question[:600],
                       _v_answer(a.d.cards), ses, max_tokens=320, task="answer")
