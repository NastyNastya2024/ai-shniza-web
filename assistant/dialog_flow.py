"""Диалог v2: сначала промпт идеи, потом путь, модели только перед запуском.

Помощник не показывает стартовое меню и не спрашивает «собрать или улучшить промпт».
Генерацию по-прежнему запускает только кнопка на итоговой карточке.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from . import params as P
from .recommend import advise
from .render import chip, model_item, response

_CAPS = os.path.join(os.path.dirname(__file__), "data", "model_capabilities.json")
_KW = os.path.join(os.path.dirname(__file__), "data", "dialog_keywords.json")

ACTIONS = {
    "flow_slot", "idea_next", "idea_alt", "path_photos", "path_board", "path_direct",
    "flow_next", "flow_show", "flow_skip", "flow_polish",
}

SKIP_RX = re.compile(r"сразу\s+видео|пропусти\s+раскадров|давай\s+сразу", re.I)
ADVISE_RX = re.compile(r"посоветуй|какая\s+лучше|какой\s+посовету|что\s+взять", re.I)
COMPARE_RX = re.compile(r"чем\s+отлича", re.I)

# Слова самой просьбы — не название товара.
_STOP = {
    "мне", "нужно", "надо", "сделай", "сделать", "хочу", "давай", "для", "про", "это",
    "карточку", "карточка", "карточки", "маркетплейса", "маркетплейс", "вайлдберриз",
    "озон", "ozon", "видео", "ролик", "рилс", "reels", "картинку", "картинка", "фото",
    "который", "которая", "которое", "залетит", "инфографика", "инфографику", "белый",
    "белом", "фоне", "фон", "сразу",
}

_SLOTS = {
    "COM.CARD": [
        ("product", "Что за товар?", [
            ("Есть фото — прикреплю", "photo"),
            ("Опишу словами", "words"),
            ("Фото нет", "none"),
        ]),
        ("look", "Как должна выглядеть карточка?", [
            ("Белый фон", "white"),
            ("Инфографика", "info"),
            ("В жизни", "life"),
        ]),
    ],
    "VID.REELS": [
        ("goal", "Для чего ролик?", [
            ("Продажа", "sale"),
            ("Охват", "reach"),
            ("Личное", "personal"),
        ]),
        ("own", "Есть свои фото или видео?", [
            ("Да, прикреплю", "yes"),
            ("Нет, сгенерируем", "no"),
        ]),
    ],
}

_STAGE_LEFT = {
    "slots": "осталось уточнить",
    "idea": "дорабатываем промпт",
    "refine": "дорабатываем промпт",
    "path": "осталось выбрать путь",
    "cast": "осталось собрать кадры",
    "board": "идёт раскадровка",
    "advise": "осталось выбрать модель",
    "card": "осталось запустить",
    "type": "осталось выбрать тип",
    "redo": "дописываем промпт",
    "fresh": "уточняем новую генерацию",
    "fresh_desc": "уточняем, что сделать",
}


@lru_cache(maxsize=1)
def capabilities() -> dict:
    try:
        with open(_CAPS, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _keywords() -> dict[str, list[str]]:
    try:
        with open(_KW, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return {}
    out = {}
    for sid, row in (raw or {}).items():
        words = row.get("keywords") if isinstance(row, dict) else row
        out[sid] = [str(w).lower() for w in (words or [])]
    return out


def meta(ses: dict) -> dict:
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else {}
    return {
        "task": f.get("kind") or ses.get("kind") or "",
        "story": f.get("story") or "",
        "stage": f.get("stage") or "",
        "slots": f.get("slots") or {},
        "missing": list(f.get("missing") or []),
        "next": f.get("next") or "",
    }


def guess_story(msg: str, tree: Any = None) -> str:
    if tree is not None and hasattr(tree, "match_sub"):
        hit = tree.match_sub(msg)
        if hit:
            return hit
    low = (msg or "").lower()
    best, nbest = "", 0
    for sid, words in _keywords().items():
        n = sum(1 for w in words if w and w in low)
        if n > nbest:
            best, nbest = sid, n
    return best


def active(ses: dict) -> bool:
    return isinstance(ses.get("flow"), dict) and bool(ses["flow"].get("stage"))


def back_chip(ses: dict) -> dict | None:
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not f or not f.get("stage"):
        return None
    title = (f.get("idea") or f.get("source") or "задаче").strip().split("\n")[0][:32]
    left = _STAGE_LEFT.get(f.get("stage") or "", "продолжаем")
    return chip(f"↩ {title}: {left}", "flow_show")


def start(engine: Any, msg: str, it: Any, ctx: dict, ses: dict, lang: str) -> dict | None:
    if engine._is_guest(ctx):
        return None
    kind = getattr(it, "kind", None) or None
    story = guess_story(msg, engine.d.tree)
    kind = _kind_of(story, kind)
    from . import model_lock as ML
    lock = ML.lock_of(engine, ctx, ses)
    if lock and lock["kind"] in ("image", "edit"):
        kind = "image"
    if not kind:
        return ask_type(engine, msg, ctx, ses, lang)
    _park(ses, msg)
    _open(ses, kind, story, msg, ctx)
    if engine.d.tree_log and not story:
        try:
            engine.d.tree_log({"kind": "new_story", "text": (msg or "")[:200]})
        except Exception:
            pass
    return advance(engine, ctx, ses, lang)


def start_saved(engine: Any, ctx: dict, ses: dict, lang: str) -> dict | None:
    """После входа: идея уже лежит в сессии, диалог ещё не открыт."""
    msg = (ses.get("idea") or "").strip()
    if not msg:
        return None
    story = guess_story(msg, engine.d.tree)
    kind = _kind_of(story, ses.get("kind"))
    if not kind:
        return None
    _open(ses, kind, story, msg, ctx)
    return advance(engine, ctx, ses, lang)


def from_handoff(engine: Any, prompt: str, kind: str, from_name: str, took: bool,
                 ctx: dict, ses: dict, lang: str, stay: dict) -> dict:
    """После команды «сгенери видео по этому»: идея на правку, не сетка моделей."""
    text = (prompt or "").strip()
    story = guess_story(text, engine.d.tree)
    kind = _kind_of(story, kind)
    _park(ses, text)
    _open(ses, kind or "video", story, text, ctx)
    f = ses["flow"]
    f["missing"] = []
    f["idea"] = _compose(f)
    ses["idea"] = f["idea"]
    word = {"video": "видео", "image": "картинку", "music": "музыку"}.get(f["kind"], "это")
    if took:
        head = f"Сделаем {word}. Беру текст из ответа {from_name} — вот варианты промпта."
    else:
        head = f"Сделаем {word}. Вот варианты промпта."
    out = open_prompts(engine, ctx, ses, lang, "idea")
    ses["flow"]["polished"] = True
    if out.get("intent") in ("look_photo", "look_photo_wait"):
        ses.pop("_just_parked", None)
        if out.get("intent") == "look_photo_wait":
            return {"text": "", "reply": "", "blocks": [], "chips": [], "silent": True,
                    "intent": "look_photo_wait", "lang": lang}
        return out
    out["text"] = head + "\n" + (out.get("text") or "")
    out["reply"] = out["text"]
    out["chips"] = list(out.get("chips") or []) + [stay]
    out["intent"] = "model_switch"
    return out


def ask_type(engine: Any, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
    _park(ses, msg)
    ses["idea"] = (msg or "").strip()
    ses["flow"] = {
        "stage": "type", "kind": "", "story": "", "slots": {}, "missing": ["kind"],
        "idea": "", "idea_user": (msg or "").strip(), "path": "", "next": "type",
        "source": (msg or "").strip()[:500],
    }
    low = (msg or "").lower()
    chips = [
        chip("Видео", "choose_type", "video", primary=True),
        chip("Картинка", "choose_type", "image"),
    ]
    if re.search(r"песн|трек|музык", low):
        chips.append(chip("Музыка", "choose_type", "music"))
    return response(
        ["Это видео, картинка или что-то ещё?" if lang != "en" else "Is this a video, an image, or something else?"],
        chips, lang=lang, intent="ask_type",
    )


def on_message(engine: Any, msg: str, ctx: dict, ses: dict, lang: str) -> dict | None:
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not f:
        return None
    if COMPARE_RX.search(msg or ""):
        return compare_from_text(engine, msg, lang)
    other = guess_story(msg, engine.d.tree)
    if other and other != (f.get("story") or "") and other in _SLOTS and _fresh_task(msg):
        return start(engine, msg, _Kind(other), ctx, ses, lang)
    if SKIP_RX.search(msg or "") and (f.get("kind") == "video" or not f.get("kind")):
        f["kind"] = "video"
        return _go_direct(engine, ctx, ses, lang)
    if ADVISE_RX.search(msg or ""):
        return _advise(engine, ctx, ses, lang, again=True)
    stage = f.get("stage")
    if stage == "slots":
        _absorb(f, msg, ctx)
        return advance(engine, ctx, ses, lang)
    if stage == "fresh":
        return start(engine, _carry_prior(ses, msg), _Kind(guess_story(msg, engine.d.tree)), ctx, ses, lang)
    if stage == "fresh_desc":
        carried = _carry_prior(ses, msg)
        f["idea_user"] = carried
        f["source"] = carried[:500]
        f["idea"] = ""
        f["missing"] = []
        return advance(engine, ctx, ses, lang)
    if stage == "redo":
        _apply_edit(f, _carry_prior(ses, msg))
        text = (f.get("idea") or "").strip()
        ses["idea"] = ses["prompt"] = ses["prompt_base"] = text
        return _redo_card(ses, lang, "Дописала в промпт." if lang != "en" else "Added to the prompt.")
    if stage in ("idea", "path", "advise", "card", "cast", "refine", "variants"):
        _apply_edit(f, _carry_prior(ses, msg))
        ses["idea"] = f.get("idea") or ses.get("idea") or ""
        if stage == "card" and ses.get("picked"):
            ses["prompt"] = f.get("idea") or ses.get("prompt") or ""
            ses["prompt_base"] = ses["prompt"]
            card = engine.d.cards.get(ses.get("picked") or "")
            if card:
                return engine._setup_reply(card, ses, ctx, lang, "edit_prompt", "Обновила промпт.")
        if stage == "variants":
            _apply_edit(f, msg)
            ses["idea"] = f.get("idea") or ses.get("idea") or ""
            return open_prompts(engine, ctx, ses, lang, str(f.get("prompt_for") or "idea"))
        if stage == "refine":
            return _refine(ses, lang, str(f.get("refine") or "photos"), "Поправила промпт.")
        if stage == "idea":
            return _idea_card(ses, lang, "Поправила промпт.")
        return show(engine, ctx, ses, lang)
    return None


def on_action(engine: Any, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict | None:
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if kind in ACTIONS or (kind == "choose_type" and f and f.get("stage") in ("type", "fresh")):
        pass
    elif kind == "use_mine" and f and f.get("stage") == "idea":
        pass
    elif kind == "pick_model" and f and f.get("stage") in ("advise", "card"):
        pass
    elif kind == "media_add" and f:
        pass
    elif kind == "make" and f:
        pass
    elif kind == "back" and f:
        pass
    else:
        return None
    if kind == "flow_next" and not isinstance(f, dict):
        return _next(engine, value, ctx, ses, lang)
    if not isinstance(f, dict):
        return response(["Сначала опишите задачу."], [], lang=lang, intent="flow")
    if kind == "flow_slot":
        slot, val = _pair(value)
        if slot:
            f["slots"][slot] = val
        return advance(engine, ctx, ses, lang)
    if kind == "idea_next":
        if (f.get("kind") or ses.get("kind")) == "video":
            return _paths(engine, ses, lang)
        return _advise(engine, ctx, ses, lang)
    if kind == "idea_alt":
        ses["var_round"] = int(ses.get("var_round") or 0) + 1
        return open_prompts(engine, ctx, ses, lang, str(f.get("prompt_for") or "idea"))
    if kind == "use_mine":
        f["idea"] = f.get("idea_user") or f.get("idea") or ""
        ses["idea"] = f["idea"]
        return _idea_card(ses, lang, "Вернула ваш текст.")
    if kind == "flow_polish":
        if not (ses.get("prompt") or ses.get("prompt_base")):
            items = ses.get("variants") or []
            if items:
                ses["prompt"] = ses["prompt_base"] = items[0].get("text") or ""
                f["idea"] = ses["prompt"]
                ses["idea"] = ses["prompt"]
        f["stage"] = "polish"
        f["next"] = "polish"
        return engine._offer_polish(ses, ctx, lang, "flow_polish",
                                    head="Доработать этот промпт в Claude, GPT или другой текстовой модели.")
    if kind == "path_photos":
        return open_prompts(engine, ctx, ses, lang, "photos")
    if kind == "path_board":
        return open_prompts(engine, ctx, ses, lang, "board")
    if kind == "path_direct" or kind == "flow_skip":
        return _go_direct(engine, ctx, ses, lang)
    if kind == "back":
        return step_back(engine, ctx, ses, lang)
    if kind == "flow_show":
        return show(engine, ctx, ses, lang)
    if kind == "flow_next":
        return _next(engine, value, ctx, ses, lang)
    if kind == "choose_type":
        if f.get("stage") == "fresh":
            return _ask_fresh_detail(ses, str(value or "video"), lang)
        story = f.get("story") or ""
        _open(ses, str(value or "image"), story, f.get("idea_user") or ses.get("idea") or "", ctx)
        return advance(engine, ctx, ses, lang)
    if kind == "pick_model":
        return _launch(engine, str(value or ""), ctx, ses, lang)
    if kind == "media_add":
        from . import dialog as DG
        if isinstance(value, dict) and (value.get("url") or value.get("work_id")):
            DG.add_result(ses, value)
        return _after_media(value if isinstance(value, dict) else {}, ses, lang)
    if kind == "make":
        return from_prompt(engine, value, ctx, ses, lang)
    return None


def step_back(engine: Any, ctx: dict, ses: dict, lang: str) -> dict | None:
    """Назад — предыдущий шаг диалога. Список моделей не подменяет возврат к промпту."""
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not f or not f.get("stage"):
        return None
    stage = f.get("stage") or ""
    kind = f.get("kind") or ses.get("kind") or ""
    which = str(f.get("prompt_for") or "idea")
    shown = [x for x in (f.get("shown_models") or []) if x]
    if stage == "card" and len(shown) > 1:
        return _advise(engine, ctx, ses, lang, again=True)
    if stage in ("card", "advise", "polish", "path", "variants"):
        if kind == "video" and stage in ("card", "advise"):
            return _paths(engine, ses, lang)
        return open_prompts(engine, ctx, ses, lang, which)
    if stage in ("board", "cast", "refine"):
        return _paths(engine, ses, lang)
    return None


def show(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    f = ses.get("flow") or {}
    stage = f.get("stage")
    if stage == "type":
        return ask_type(engine, f.get("idea_user") or "", ctx, ses, lang)
    if stage == "slots":
        return advance(engine, ctx, ses, lang)
    if stage == "path":
        return _paths(engine, ses, lang)
    if stage == "variants":
        return open_prompts(engine, ctx, ses, lang, str(f.get("prompt_for") or "idea"))
    if stage == "polish":
        return engine._offer_polish(ses, ctx, lang, "use_variant")
    if stage == "refine":
        return _refine(ses, lang, str(f.get("refine") or "photos"))
    if stage == "cast":
        return _cast(ses, lang)
    if stage == "board":
        return _board(engine, ctx, ses, lang)
    if stage == "advise":
        return _advise(engine, ctx, ses, lang, again=True)
    if stage == "card":
        card = engine.d.cards.get(ses.get("picked") or "")
        if card:
            return engine._setup_reply(card, ses, ctx, lang, "summary", "Проверьте и запускайте.")
    if stage == "redo":
        return _redo_card(ses, lang)
    if stage == "fresh":
        return _fresh_generation(engine, ctx, ses, lang)
    if stage == "fresh_desc":
        word = {"video": "видео", "image": "картинку", "music": "музыку"}.get(f.get("kind") or "", "это")
        ask = (f"What should it do? Describe {word}." if lang == "en" else f"Что нужно сделать? Опишите {word}.")
        return response([ask], [], lang=lang, intent="flow_fresh")
    return _idea_card(ses, lang)


def advance(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    f = ses["flow"]
    _absorb(f, f.get("source") or "", ctx)
    # картинка: промпт как у видео — сразу варианты, без опросника карточки
    if (f.get("kind") or "") == "image":
        if not f.get("idea"):
            f["idea"] = _compose(f)
            ses["idea"] = f["idea"]
        return open_prompts(engine, ctx, ses, lang, "idea")
    missing = _missing(f)
    f["missing"] = missing
    if missing:
        f["stage"] = "slots"
        f["next"] = missing[0]
        return _ask_slots(f, missing[:1], lang)
    if not f.get("idea"):
        f["idea"] = _compose(f)
        ses["idea"] = f["idea"]
    return open_prompts(engine, ctx, ses, lang, "idea")


def compare_from_text(engine: Any, msg: str, lang: str) -> dict:
    low = (msg or "").lower()
    found = []
    for c in engine.d.cards.values():
        title = (c.title or "").lower()
        if title and title in low:
            found.append(c)
    if len(found) < 2:
        for key, c in engine.d.cards.items():
            token = key.split("-")[0]
            if len(token) >= 3 and token in low and c not in found:
                found.append(c)
    return compare_cards(engine, found[:2], lang)


def compare_cards(engine: Any, cards: list, lang: str) -> dict:
    caps = capabilities()
    if len(cards) < 2:
        return response(["Назовите две модели — коротко сравню их."], [], lang=lang, intent="compare")
    lines = ["Чем отличаются:"]
    for c in cards[:2]:
        cap = caps.get(c.id) or {}
        bits = [c.title]
        if cap.get("audio"):
            bits.append("звук: " + str(cap["audio"]))
        else:
            bits.append("звук: не указан")
        if cap.get("max_sec"):
            bits.append(f"до {cap['max_sec']} с")
        if isinstance(cap.get("text_render"), (int, float)):
            bits.append(f"текст {cap['text_render']}")
        note = (cap.get("note_ru") or "")[:90]
        lines.append(" · ".join(bits) + ((" — " + note) if note else ""))
    lines.append(f"Для задачи из диалога ближе {cards[0].title}.")
    return response(lines, [], lang=lang, intent="compare")


# ---------------------------------------------------------------- internals


class _Kind:
    def __init__(self, story: str):
        self.kind = _kind_of(story, None)
        self.name = "generate_task"


def _kind_of(story: str, kind: str | None) -> str | None:
    if story in ("COM.CARD", "IMG.COVER", "IMG.BRAND", "DSN.INTER", "MKT.PERF"):
        return "image"
    if story in ("VID.REELS", "VID.ANIM", "VID.PROMO", "COM.PVIDEO", "STO.SERIES"):
        return "video"
    if story == "AUD.SONG":
        return "music"
    return kind if kind in ("image", "video", "music", "text") else None


def _open(ses: dict, kind: str, story: str, msg: str, ctx: dict) -> None:
    text = (msg or "").strip()
    flow = {
        "stage": "slots",
        "kind": kind,
        "story": story or "",
        "slots": {},
        "missing": [],
        "idea": "",
        "idea_user": text,
        "path": "",
        "next": "slots",
        "source": text[:500],
        "shown_models": [],
    }
    ses["flow"] = flow
    ses["kind"] = kind
    ses["idea"] = text
    ses["picked"] = None
    ses["prompt"] = ""
    ses["prompt_base"] = ""
    _absorb(flow, text, ctx)


def _park(ses: dict, new_text: str) -> None:
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not f or not (f.get("idea") or f.get("source")):
        return
    if (f.get("source") or "")[:80] == (new_text or "")[:80]:
        return
    ses["parked"] = {
        "idea": f.get("idea") or f.get("source") or "",
        "kind": f.get("kind"),
        "topic": (f.get("idea") or f.get("source") or "")[:40],
        "prompt": ses.get("prompt") or "",
        "prompt_base": ses.get("prompt_base") or "",
        "picked": ses.get("picked"),
        "params": dict(ses.get("params") or {}),
        "camera": ses.get("camera"),
        "needs": list(ses.get("needs") or []),
        "flow": dict(f),
    }
    ses["_just_parked"] = True


def _fresh_task(msg: str) -> bool:
    return bool(re.search(r"сделай|хочу|нужно|давай|собери", msg or "", re.I))


def _absorb(flow: dict, text: str, ctx: dict) -> None:
    low = (text or "").lower()
    slots = flow.setdefault("slots", {})
    story = flow.get("story") or ""
    if story == "COM.CARD":
        if ctx.get("has_image") or re.search(r"прикреп|есть фото", low):
            slots["product"] = "photo"
        elif re.search(r"без фото|фото нет|нет фото", low):
            slots["product"] = "none"
        elif _subject_words(low):
            slots.setdefault("product", "words")
        if re.search(r"инфографик", low):
            slots["look"] = "info"
        elif re.search(r"лайфстайл|в жизни|в руках", low):
            slots["look"] = "life"
        elif re.search(r"бел\w*\s+фон", low):
            slots["look"] = "white"
    elif story == "VID.REELS":
        if re.search(r"продаж|реклам", low):
            slots["goal"] = "sale"
        elif re.search(r"залетит|охват|вирус", low):
            slots["goal"] = "reach"
        elif re.search(r"личн|для себя", low):
            slots["goal"] = "personal"
        if re.search(r"есть фото|есть видео|своё фото|свое фото|прикреп", low) or ctx.get("has_image"):
            slots["own"] = "yes"
        elif re.search(r"нет фото|без фото|сгенерир", low):
            slots["own"] = "no"
    elif story == "IMG.COVER" and re.search(r"youtube|ютуб", low):
        slots["format"] = "16:9"


def _subject_words(low: str) -> list[str]:
    return [w for w in re.findall(r"[a-zа-яё0-9]{3,}", low) if w not in _STOP]


def _missing(flow: dict) -> list[str]:
    need = [sid for sid, _q, _opts in _SLOTS.get(flow.get("story") or "", [])]
    return [sid for sid in need if not (flow.get("slots") or {}).get(sid)]


def _ask_slots(flow: dict, ids: list[str], lang: str) -> dict:
    spec = {sid: (q, opts) for sid, q, opts in _SLOTS.get(flow.get("story") or "", [])}
    lines, chips = [], []
    for sid in ids:
        q, opts = spec[sid]
        lines.append(q)
        for label, val in opts:
            chips.append(chip(label, "flow_slot", {"slot": sid, "value": val}))
    return response(lines, chips[:8], lang=lang, intent="flow_slots")


def _compose(flow: dict) -> str:
    src = (flow.get("idea_user") or "").strip()
    bits = [src] if src else []
    look = (flow.get("slots") or {}).get("look")
    low = src.lower()
    if look == "white" and "бел" not in low:
        bits.append("Чистый белый фон, мягкий свет, товар по центру.")
    if look == "info" and "инфографик" not in low:
        bits.append("Инфографика: крупный товар и короткие подписи.")
    if look == "life":
        bits.append("Товар в жизни, как им пользуются.")
    if flow.get("story") == "COM.CARD":
        bits.append("Формат 3:4.")
    if flow.get("story") == "VID.REELS":
        bits.append("Вертикальное видео 9:16, около 15 секунд, со звуком.")
    if flow.get("story") == "IMG.COVER" and (flow.get("slots") or {}).get("format") == "16:9":
        bits.append("Обложка 16:9.")
    text = " ".join(b for b in bits if b).strip()
    return re.sub(r"([A-Za-zА-Яа-яЁё])\1{2,}", r"\1\1", text)


def _apply_edit(flow: dict, msg: str) -> None:
    low = (msg or "").lower()
    if re.search(r"ноч", low):
        extra = "Ночная сцена."
    elif re.search(r"вечер", low):
        extra = "Вечерний свет."
    elif re.search(r"без людей", low):
        extra = "Без людей."
    else:
        extra = (msg or "").strip()
    if not extra:
        return
    base = (flow.get("idea") or flow.get("idea_user") or "").strip()
    if extra.lower() in base.lower():
        flow["idea"] = base
        return
    flow["idea"] = (base + " " + extra).strip()


def _idea_card(ses: dict, lang: str, head: str | None = None) -> dict:
    f = ses["flow"]
    if not f.get("idea"):
        f["idea"] = _compose(f)
    ses["idea"] = f["idea"]
    f["stage"] = "idea"
    f["next"] = "idea"
    video = (f.get("kind") or ses.get("kind")) == "video"
    if video:
        text = head or ("Сначала доработаем промпт основной идеи. "
                        "Поправьте текст ниже. Когда он готов — выберем, как делать видео.")
        ok = "Промпт готов" if lang != "en" else "Prompt is ready"
    else:
        text = head or "Вот идея. Дальше — как это делать."
        ok = "Дальше" if lang != "en" else "Next"
    block = {"type": "prompt", "label": True, "title": "Промпт" if lang != "en" else "Prompt",
             "text": f["idea"], "note": ""}
    chips = [
        chip(ok, "idea_next", None, primary=True),
        chip("Ещё вариант" if lang != "en" else "Another version", "idea_alt"),
        chip("Вернуть мой текст" if lang != "en" else "Restore my text", "use_mine"),
    ]
    return response([text], chips, [block], lang=lang, intent="idea")


def _paths(engine: Any, ses: dict, lang: str) -> dict:
    f = ses["flow"]
    f["stage"] = "path"
    f["next"] = "path"
    lines = [
        "Промпт основной идеи готов. Дальше можно так:",
        "• Добавить фото персонажей и сцены — потом из них соберём ролик.",
        "• Раскадровка — кадры сценария по порядку, потом видео.",
        "• Доработать общий промпт в Claude, GPT или другой текстовой модели.",
        "• Сразу видео — один ролик из идеи.",
    ]
    media = [m for m in (ses.get("media") or []) if isinstance(m, dict) and m.get("kind") == "image"]
    if media or any(isinstance(a, dict) and a.get("kind") == "image" for a in (ses.get("arts") or [])):
        lines.append("Фото уже есть — они будут добавлены автоматически.")
    chips = [
        chip("Фото персонажей и сцены", "path_photos"),
        chip("Раскадровка сценария", "path_board"),
        chip("Доработать в Claude или GPT", "flow_polish"),
        chip("Сразу видео", "path_direct", primary=True),
    ]
    return response(lines, chips, lang=lang, intent="flow_path")


def open_prompts(engine: Any, ctx: dict, ses: dict, lang: str, which: str = "idea", change: str = "") -> dict:
    """Несколько вариантов одного промпта. Дальше — доработка в Claude или GPT, либо «использовать этот»."""
    f = ses["flow"]
    f["stage"] = "variants"
    f["prompt_for"] = which
    f["next"] = "variants"
    if which == "photos":
        f["path"] = "photos"
    elif which == "board":
        f["path"] = "board"
    if not f.get("idea"):
        f["idea"] = _compose(f)
    guide_kind = "image" if which == "photos" else (f.get("kind") or ses.get("kind") or "image")
    ses["kind"] = guide_kind if guide_kind in ("image", "video", "music") else "image"
    ses["idea"] = f["idea"]
    ses["brief"] = {"q": [], "a": {}, "extra": [change] if change else [], "summary": "", "src": "flow", "phase": "done"}
    ses["brief_for_model"] = None
    ses["picked"] = None
    ses["gen_model"] = None
    from . import model_lock as ML
    lock = ML.lock_of(engine, ctx, ses)
    if lock and (
        (lock["kind"] in ("image", "edit") and guide_kind == "image")
        or (lock["kind"] == "video" and guide_kind == "video")
    ):
        ses["brief_guide"] = lock["id"]
    else:
        ses["brief_guide"] = None
    card = engine._brief_guide(ses, ctx)
    if not card:
        return _idea_card(ses, lang)
    out = engine._variants(card, ses, ctx, lang, change)
    if out.get("intent") in ("look_photo", "look_photo_wait"):
        return out
    if which == "idea" and (f.get("kind") or "") in ("video", "image"):
        out["chips"] = [chip("Доработать в Claude или GPT", "flow_polish")] + list(out.get("chips") or [])
    return out


def _refine(ses: dict, lang: str, which: str, head: str | None = None) -> dict:
    """Один и тот же промпт дорабатываем под выбранный шаг, модели — только после «промпт готов»."""
    f = ses["flow"]
    f["stage"] = "refine"
    f["path"] = which
    f["refine"] = which
    f["next"] = "refine"
    if not f.get("idea"):
        f["idea"] = _compose(f)
    ses["idea"] = f["idea"]
    if which == "photos":
        title = "Промпт для фото" if lang != "en" else "Prompt for the photos"
        lines = [head or ("Фото персонажей и сцены. Доработайте тот же промпт — по нему сделаем картинки."
                          if lang != "en" else "Photos of the characters and the place. Refine the same prompt.")]
        lines.append("Герой — по описанию из идеи." if lang != "en" else "Hero — from the idea.")
        lines.append("Сцена — место из идеи." if lang != "en" else "Scene — the place from the idea.")
        ok, val = ("Промпт готов — к картинке", "photos_go")
    else:
        title = "Промпт для раскадровки" if lang != "en" else "Prompt for the storyboard"
        lines = [head or ("Раскадровка. Доработайте тот же промпт — по нему разложу кадры."
                          if lang != "en" else "Storyboard. Refine the same prompt — the frames follow it.")]
        ok, val = ("Промпт готов — к кадрам", "board_go")
    block = {"type": "prompt", "label": True, "title": title, "text": f["idea"], "note": ""}
    chips = [
        chip(ok if lang != "en" else "Prompt is ready", "flow_next", val, primary=True),
        chip("Ещё вариант" if lang != "en" else "Another version", "idea_alt"),
    ]
    return response(lines, chips, [block], lang=lang, intent="flow_refine")


def _cast(ses: dict, lang: str) -> dict:
    f = ses["flow"]
    f["stage"] = "cast"
    f["path"] = "photos"
    f["next"] = "cast"
    f["cast"] = [
        {"id": "hero", "title": "Герой", "on": True},
        {"id": "scene", "title": "Сцена", "on": True},
    ]
    lines = [
        "Сначала фото.",
        "Герой — по описанию из идеи.",
        "Сцена — место из идеи.",
    ]
    chips = [chip("Дальше: картинки героев", "flow_next", "cast_images", primary=True)]
    return response(lines, chips, lang=lang, intent="flow_cast")


def _board(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    from . import storyboard as SB
    f = ses["flow"]
    f["stage"] = "board"
    f["path"] = "board"
    f["next"] = "board"
    ses["idea"] = f.get("idea") or ses.get("idea") or ""
    return SB.start(engine, ses, ctx, lang, text=ses["idea"])


def _go_direct(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    f = ses["flow"]
    f["path"] = "direct"
    f["kind"] = f.get("kind") or "video"
    ses["kind"] = f["kind"]
    if not f.get("idea"):
        f["idea"] = _compose(f)
        ses["idea"] = f["idea"]
    return _advise(engine, ctx, ses, lang)


def _profile(engine: Any, ses: dict, ctx: dict) -> dict:
    f = ses.get("flow") or {}
    kind = f.get("kind") or ses.get("kind") or "image"
    story = f.get("story") or ""
    aspect = None
    if story == "COM.CARD":
        aspect = "3:4"
    elif story == "VID.REELS" or (kind == "video" and f.get("path")):
        aspect = "9:16"
    elif story == "IMG.COVER" and (f.get("slots") or {}).get("format") == "16:9":
        aspect = "16:9"
    return {
        "kind": "image" if f.get("stage") == "cast" or f.get("next") == "cast_images" else kind,
        "text": story == "COM.CARD" or (f.get("slots") or {}).get("look") == "info",
        "aspect": aspect,
        "audio": kind == "video",
        "needs_image": bool(ctx.get("has_image")) or any(
            isinstance(m, dict) and m.get("kind") == "image" for m in (ses.get("media") or [])
        ),
        "current": str(ctx.get("selected_model_id") or ""),
    }


def _advise(engine: Any, ctx: dict, ses: dict, lang: str, again: bool = False) -> dict:
    f = ses["flow"]
    if f.get("next") == "cast_images":
        prof_kind = "image"
    else:
        prof_kind = f.get("kind") or "image"
    if not again and prof_kind in ("image", "video"):
        from . import model_lock as ML
        jumped = ML.parameters_if_locked(engine, ctx, ses, lang, prof_kind)
        if jumped is not None:
            f["stage"] = "card"
            f["next"] = "card"
            f["shown_models"] = [str(ctx.get("selected_model_id") or "")]
            return jumped
    profile = _profile(engine, ses, ctx)
    profile["kind"] = prof_kind
    caps = capabilities()
    cards = advise(engine.d.cards, caps, profile, engine._price, engine.d.health_fn, engine.d.catalog_fn,
                   n=None, price_order=True)
    ids = [c.id for c in cards]
    if again and ids and ids == list(f.get("shown_models") or []):
        title = cards[0].title if cards else ""
        return response(
            [f"Оставляю тот же совет: {title}. Можно взять её или написать, что важнее — цена, текст или качество."],
            [chip("Взять " + title, "pick_model", cards[0].id, primary=True)] if cards else [],
            lang=lang, intent="advise",
        )
    f["shown_models"] = ids
    f["stage"] = "advise"
    f["next"] = "advise"
    ses["kind"] = prof_kind
    sec = 5 if prof_kind == "video" else None
    def fit(c: Card) -> float:
        cap = caps.get(c.id) or {}
        s = c.rank / 100.0
        tr = cap.get("text_render")
        if profile.get("text") and isinstance(tr, (int, float)):
            s += float(tr) * 4
        if profile.get("audio") and cap.get("audio") in ("native", "lipsync", "music"):
            s += 6
        return s

    best = max(cards, key=fit) if cards else None
    items = []
    for c in cards:
        cap = caps.get(c.id) or {}
        reason = (cap.get("note_ru") or c.text("strengths", lang) or "")[:90]
        it = model_item(c, engine._price(c.id), lang, engine.d.vitrina_url, ses.get("topic") or "",
                        "Советую" if best and c.id == best.id else None, sec)
        it["why"] = reason
        if profile.get("needs_image") and "i2v" not in (c.modes or []) and "i2i" not in (c.modes or []):
            it["note"] = "Фото в эту модель не уйдёт" if lang != "en" else "The photo will not be sent to this model"
        items.append(it)
    cur = str(ctx.get("selected_model_id") or "")
    cur_card = engine.d.cards.get(cur)
    if cards and cur and best and best.id == cur:
        head = f"Делаем на {best.title}."
    elif cur_card and cards and cur not in ids:
        head = f"{cur_card.title} сюда слабее подходит. Ближе {best.title}." if best else f"{cur_card.title} сюда слабее подходит."
    elif best:
        head = f"Советую {best.title}. Сначала самые дешёвые, остальные — следующими партиями."
    else:
        head = "Сейчас нет подходящей модели в студии."
    if prof_kind == "video" and cards:
        head += " Оценка — за ролик 5 с."
    chips = []
    blocks = [{"type": "models", "items": items}] if items else []
    return response([head], chips, blocks, lang=lang, intent="advise",
                    models=[{"id": it["id"], "title": it["title"], "price": it["price"]} for it in items])


def _launch(engine: Any, mid: str, ctx: dict, ses: dict, lang: str) -> dict:
    card = engine.d.cards.get(mid)
    if not card:
        return _advise(engine, ctx, ses, lang)
    f = ses["flow"]
    if not f.get("idea"):
        f["idea"] = _compose(f)
    prompt = f.get("idea") or ses.get("idea") or ""
    ses["picked"] = card.id
    ses["kind"] = card.kind if card.kind != "edit" else (f.get("kind") or "image")
    ses["idea"] = prompt
    ses["prompt_base"] = prompt
    ses["prompt"] = prompt
    params: dict[str, Any] = {}
    aspects = card.params.get("aspect_ratio") or []
    want = _profile(engine, ses, ctx).get("aspect")
    if want and want in aspects:
        params["aspect_ratio"] = want
    if (f.get("kind") == "video" or card.kind == "video") and f.get("story") == "VID.REELS":
        dur = _closest_duration(card, 15)
        if dur is not None:
            params["duration"] = dur
    ses["params"] = P.with_defaults(card, params)
    f["stage"] = "card"
    f["next"] = "generate"
    return engine._setup_reply(card, ses, ctx, lang, "summary", "Проверьте и запускайте.")


def _closest_duration(card: Any, target: int) -> int | None:
    nums = []
    for o in card.params.get("duration") or []:
        if isinstance(o, (int, float)):
            nums.append(int(o))
        elif isinstance(o, str) and o.strip().isdigit():
            nums.append(int(o.strip()))
        elif isinstance(o, dict) and str(o.get("value", "")).isdigit():
            nums.append(int(o["value"]))
    if not nums:
        return None
    return min(nums, key=lambda n: (abs(n - target), n))


def _after_media(value: dict, ses: dict, lang: str) -> dict:
    kind = str(value.get("kind") or "")
    f = ses.get("flow") or {}
    story = f.get("story") or ""
    path = f.get("path") or ""
    if kind == "image" and path == "board":
        chips = [chip("Дальше: видео по раскадровке", "path_direct", primary=True)]
    elif kind == "image" and (story == "VID.REELS" or path in ("photos", "board")):
        chips = [
            chip("Дальше: раскадровка", "path_board"),
            chip("Дальше: видео из этой картинки", "path_direct"),
        ]
    elif kind == "video":
        en = lang == "en"
        chips = [
            chip("Redo" if en else "Переделать", "flow_next", "redo", primary=True),
            chip("Continue" if en else "Сделать продолжение", "flow_next", "continue"),
            chip("New generation" if en else "Новая генерация", "flow_next", "fresh"),
        ]
        _remember_prior(ses, "video", _current_prompt(ses))
    elif kind == "text":
        en = lang == "en"
        prompt = str(value.get("reply") or "")[:4000]
        def pack(k: str) -> dict:
            return {"kind": k, "text": prompt}
        chips = [
            chip("Make a video from this" if en else "Сделать видео по этому", "make", pack("video"), primary=True),
            chip("Image" if en else "Картинку", "make", pack("image")),
            chip("Storyboard" if en else "Раскадровку", "make", pack("storyboard")),
        ]
    elif kind == "image":
        return {"text": "", "reply": "", "blocks": [], "chips": [], "silent": True, "intent": "image_done", "lang": lang}
    else:
        chips = [
            chip("Ещё слайды инфографики", "flow_next", "more_slides"),
            chip("Главное фото", "flow_next", "hero"),
            chip("Видео товара", "flow_next", "video"),
        ]
    return response([], chips, lang=lang, intent="flow_next")


def from_prompt(engine: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Кнопка под готовым текстом: этот промпт сразу идёт в видео, картинку или раскадровку."""
    if isinstance(value, dict):
        kind = str(value.get("kind") or "video")
        text = str(value.get("text") or "").strip()
    else:
        kind = str(value or "video")
        text = ""
    if not text:
        for row in reversed(ses.get("texts") or []):
            if isinstance(row, dict) and str(row.get("text") or "").strip():
                text = str(row["text"]).strip()
                break
    text = text[:4000]
    task = "image" if kind == "image" else "video"
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not f:
        _open(ses, task, "", text, ctx)
        f = ses["flow"]
    if text and text != (f.get("idea") or ""):
        f["shown_models"] = []
    if text:
        f["idea"] = text
        ses["idea"] = text
        ses["prompt"] = text
        ses["prompt_base"] = text
    f["polished"] = True
    if kind == "storyboard":
        from . import storyboard as SB
        f["kind"] = "video"
        ses["kind"] = "video"
        return SB.start(engine, ses, ctx, lang, text=text or f.get("idea") or "")
    if kind == "image":
        f["kind"] = "image"
        ses["kind"] = "image"
        f["path"] = "direct"
        return _advise(engine, ctx, ses, lang)
    f["kind"] = "video"
    ses["kind"] = "video"
    return _go_direct(engine, ctx, ses, lang)


def _same_video_card(engine: Any, ses: dict):
    for mid in (ses.get("picked"), ses.get("gen_model"), ses.get("route_model")):
        card = engine.d.cards.get(mid or "")
        if card and card.kind == "video":
            return card
    return None


def _current_prompt(ses: dict) -> str:
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else {}
    return (ses.get("prompt_base") or ses.get("prompt") or f.get("idea") or ses.get("idea") or "").strip()


def _remember_prior(ses: dict, kind: str, prompt: str) -> None:
    text = (prompt or "").strip()
    if not text:
        return
    bag = [row for row in (ses.get("prior") or []) if isinstance(row, dict)]
    row = {"kind": kind or "", "prompt": text[:2000]}
    if bag and bag[-1].get("prompt") == row["prompt"] and bag[-1].get("kind") == row["kind"]:
        ses["prior"] = bag[-8:]
        return
    bag.append(row)
    ses["prior"] = bag[-8:]


_CARRY_RX = re.compile(
    r"прошл|предыдущ|тот же|та же|те же|того же|той же|тех же|как там|по этому|из этого|the same|last one|previous",
    re.I,
)


def _carry_prior(ses: dict, msg: str) -> str:
    text = (msg or "").strip()
    bag = [r for r in (ses.get("prior") or []) if isinstance(r, dict) and r.get("prompt")]
    if not text or not bag or not _CARRY_RX.search(text):
        return text
    prev = str(bag[-1]["prompt"]).strip()[:1500]
    note = "Контекст прошлой генерации: " + prev
    if note.lower() in text.lower():
        return text
    return (text + "\n" + note).strip()


def _prior_line(ses: dict, lang: str) -> str:
    bag = [r for r in (ses.get("prior") or []) if isinstance(r, dict) and r.get("prompt")]
    if not bag:
        return ""
    text = str(bag[-1]["prompt"]).replace("\n", " ").strip()
    short = text[:90] + ("…" if len(text) > 90 else "")
    if lang == "en":
        return "The previous generation stays in memory: " + short
    return "Прошлое остаётся в памяти: " + short


def _redo_card(ses: dict, lang: str, head: str | None = None) -> dict:
    f = ses["flow"]
    prompt = _current_prompt(ses)
    if prompt:
        f["idea"] = ses["idea"] = ses["prompt"] = ses["prompt_base"] = prompt
    f["kind"] = ses["kind"] = "video"
    f["stage"] = "redo"
    f["next"] = "redo"
    en = lang == "en"
    if not head:
        head = ("Same prompt. Add to it below, or refine it in Claude or GPT."
                if en else
                "Тот же промпт. Допишите его в поле ниже или доработайте в Claude или GPT.")
    block = {"type": "prompt", "label": True, "extend": True,
             "title": "Prompt" if en else "Промпт", "text": prompt, "note": ""}
    chips = [
        chip("Refine in Claude or GPT" if en else "Доработать в Claude или GPT", "flow_polish"),
        chip("Prompt is ready" if en else "Промпт готов", "idea_next", None, primary=True),
    ]
    return response([head], chips, [block], lang=lang, intent="idea")


def _redo_video(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Тот же промпт — поле, куда можно дописать, и доработка в Claude или GPT."""
    _remember_prior(ses, "video", _current_prompt(ses))
    return _redo_card(ses, lang)


def _continue_video(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Как в начале: несколько сценариев продолжения, любой можно доработать в Claude или GPT."""
    f = ses["flow"]
    base = _current_prompt(ses)
    _remember_prior(ses, "video", base)
    extra = ("Continuation of the previous video: the next moment, same person, clothes, place and light. "
             "Three different scenarios of what happens next."
             if lang == "en" else
             "Продолжение предыдущего ролика: следующий момент, те же герой, одежда, место и свет. "
             "Три разных сценария того, что происходит дальше.")
    f["idea"] = ses["idea"] = base or extra
    f["idea_user"] = base or extra
    f["kind"] = ses["kind"] = "video"
    f["polished"] = False
    f["shown_models"] = []
    f["path"] = ""
    out = open_prompts(engine, ctx, ses, lang, "idea", extra)
    # Смотрение фото не создало запрос — сразу те же карточки и кнопки, что у первого промпта.
    if out.get("intent") in ("look_photo", "look_photo_wait"):
        out = engine._look_skip(ctx, ses, lang)
    head = ("Continuation. Here are different scenarios for the next moment. "
            "Any of them can be refined in Claude or GPT."
            if lang == "en" else
            "Продолжение. Вот разные сценарии следующего момента. "
            "Любой можно доработать в Claude или GPT.")
    out["text"] = head + "\n" + (out.get("text") or "")
    out["reply"] = out["text"]
    if not any(c.get("action") == "flow_polish" for c in out.get("chips") or []):
        out["chips"] = [chip("Доработать в Claude или GPT" if lang != "en" else "Refine in Claude or GPT", "flow_polish")] + list(out.get("chips") or [])
    return out


def _fresh_generation(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Любой новый тип. Прошлые промпты остаются в памяти чата."""
    _remember_prior(ses, str((ses.get("flow") or {}).get("kind") or ses.get("kind") or ""), _current_prompt(ses))
    ses["flow"] = {
        "stage": "fresh", "kind": "", "story": "", "slots": {}, "missing": ["kind"],
        "idea": "", "idea_user": "", "path": "", "next": "fresh", "source": "", "shown_models": [],
    }
    ses["picked"] = None
    ses["prompt"] = ""
    ses["prompt_base"] = ""
    en = lang == "en"
    lines = ["New generation. What should we make — a video, an image, or describe it in your own words?"
             if en else
             "Новая генерация. Что делаем — видео, картинка или опишите своими словами?"]
    remembered = _prior_line(ses, lang)
    if remembered:
        lines.append(remembered)
    chips = [
        chip("Video" if en else "Видео", "choose_type", "video", primary=True),
        chip("Image" if en else "Картинка", "choose_type", "image"),
    ]
    return response(lines, chips, lang=lang, intent="flow_fresh")


def _ask_fresh_detail(ses: dict, kind: str, lang: str) -> dict:
    kind = kind if kind in ("video", "image", "music") else "video"
    _open(ses, kind, "", "", {})
    f = ses["flow"]
    f["stage"] = "fresh_desc"
    f["next"] = "fresh_desc"
    f["kind"] = ses["kind"] = kind
    word = {"video": ("видео", "the video"), "image": ("картинку", "the image"),
            "music": ("музыку", "the music")}.get(kind, ("это", "it"))
    ask = (f"What should it do? Describe {word[1]}." if lang == "en" else f"Что нужно сделать? Опишите {word[0]}.")
    lines = [ask]
    remembered = _prior_line(ses, lang)
    if remembered:
        lines.append(remembered)
    return response(lines, [], lang=lang, intent="flow_fresh")


def _start_from_picture(ses: dict, ctx: dict, prompt: str, kind: str) -> None:
    """Кнопки под готовой картинкой: тот же промпт, новый шаг (картинка или видео)."""
    text = (prompt or _current_prompt(ses) or "").strip()
    _open(ses, kind, "", text, ctx)
    f = ses["flow"]
    f["idea"] = ses["idea"] = ses["prompt"] = ses["prompt_base"] = text
    f["idea_user"] = text
    f["kind"] = ses["kind"] = kind
    f["polished"] = False
    f["shown_models"] = []
    f["path"] = ""


def _image_redo(engine: Any, ctx: dict, ses: dict, lang: str, prompt: str) -> dict:
    """Тот же промпт картинки — снова варианты, как в начале."""
    ses["need_ref"] = False
    _start_from_picture(ses, ctx, prompt, "image")
    return open_prompts(engine, ctx, ses, lang, "idea")


def _image_to_video(engine: Any, ctx: dict, ses: dict, lang: str, prompt: str) -> dict:
    """Видео по этой картинке: обычный видеопроцесс и полный список видеомоделей."""
    ses["need_ref"] = False
    _start_from_picture(ses, ctx, prompt, "video")
    out = open_prompts(engine, ctx, ses, lang, "idea")
    head = ("A video from this picture. First the prompt, then every video model."
            if lang == "en" else
            "Видео по этой картинке. Сначала промпт, потом все видеомодели.")
    out["text"] = head + ("\n" + out["text"] if out.get("text") else "")
    out["reply"] = out["text"]
    return out


def _image_angles(engine: Any, ctx: dict, ses: dict, lang: str, prompt: str) -> dict:
    """Тот же персонаж с прикреплённого кадра, другие ракурсы."""
    base = (prompt or _current_prompt(ses) or "").strip()
    extra = ("Другие ракурсы того же персонажа с прикреплённой фотографии: лицо, одежда и место не меняй. "
             "Крупный план, профиль, три четверти и вид со спины."
             if lang != "en" else
             "Other angles of the same person from the attached photo: keep the face, clothes and place. "
             "Close-up, profile, three-quarter and from behind.")
    ses["need_ref"] = True
    _start_from_picture(ses, ctx, base, "image")
    f = ses["flow"]
    f["need_ref"] = True
    f["idea"] = ses["idea"] = (base + "\n" + extra).strip()
    out = open_prompts(engine, ctx, ses, lang, "idea", extra)
    head = ("The photo stays attached. Here are prompts for other angles of the same person."
            if lang == "en" else
            "Фото остаётся в закрепе. Вот промпты с другими ракурсами того же персонажа.")
    out["text"] = head + ("\n" + out["text"] if out.get("text") else "")
    out["reply"] = out["text"]
    return out


def _adopt_result(ses: dict, ctx: dict, prompt: str) -> None:
    """Кнопки под готовым роликом работают и без открытого диалога: берём промпт результата."""
    text = (prompt or _current_prompt(ses) or "").strip()
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not f:
        _open(ses, "video", "", text, ctx)
        f = ses["flow"]
    if text and not _current_prompt(ses):
        f["idea"] = ses["idea"] = ses["prompt"] = ses["prompt_base"] = text
        f["kind"] = ses["kind"] = "video"


def _next(engine: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    prompt = ""
    if isinstance(value, dict):
        step = str(value.get("step") or "")
        prompt = str(value.get("prompt") or "").strip()[:4000]
    else:
        step = value if isinstance(value, str) else ""
    if step in ("image_redo", "image_video", "image_angles"):
        if step == "image_video":
            return _image_to_video(engine, ctx, ses, lang, prompt)
        if step == "image_angles":
            return _image_angles(engine, ctx, ses, lang, prompt)
        return _image_redo(engine, ctx, ses, lang, prompt)
    if step in ("redo", "continue", "fresh"):
        _adopt_result(ses, ctx, prompt)
    f = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
    if not isinstance(f, dict):
        return response(["Сначала опишите задачу."], [], lang=lang, intent="flow")
    if step in ("cast_images", "photos_go"):
        f["next"] = "cast_images"
        f["path"] = "photos"
        return _advise(engine, ctx, ses, lang)
    if step == "board_go":
        return _board(engine, ctx, ses, lang)
    if step == "redo":
        return _redo_video(engine, ctx, ses, lang)
    if step == "continue":
        return _continue_video(engine, ctx, ses, lang)
    if step == "fresh":
        return _fresh_generation(engine, ctx, ses, lang)
    if step == "reprompt":
        f["path"] = ""
        f["refine"] = ""
        f["prompt_for"] = "idea"
        return open_prompts(engine, ctx, ses, lang, "idea")
    if step in ("video", "cover"):
        f["kind"] = "video" if step == "video" else "image"
        f["story"] = "VID.REELS" if step == "video" else "IMG.COVER"
        if not f.get("idea"):
            f["idea"] = _compose(f)
        if step == "video":
            return _paths(engine, ses, lang)
        return _advise(engine, ctx, ses, lang)
    return _idea_card(ses, lang, "Продолжаем ту же задачу.")


def _pair(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        return str(value.get("slot") or ""), str(value.get("value") or "")
    return "", ""
