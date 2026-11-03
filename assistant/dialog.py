"""Память диалога, реестр файлов и подтверждение того, что уйдёт в генерацию.

Помощник не запускает генерацию сам: здесь только текст, кнопки и карточка.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .render import chip
from .texts import t

MAX_LOG = 12
MAX_TURN = 300
MEDIA_TTL = 24 * 3600

_REF = re.compile(
    r"этим же|этот же|это же|тою же|ту же|то же самое|\bто же\b|"
    r"последн\w*|предыдущ\w*|втор(ое|ую|ой|ая)\b|№\s*\d+|видео\s*№|картинк\w*\s*№|"
    r"с этой картинк|с этим видео|с этим фото|из прошлого видео|"
    r"\bрезультат\b|моё фото|мое фото|мой ролик|это видео|эту картинк|этим видео",
    re.I,
)
_VAGUE = re.compile(
    r"что-нибудь|что нибудь|что-то|красив\w*|классн\w*|крут\w*|интересн\w*|любое|любую|any(thing)?|something nice",
    re.I,
)


def remember(ses: dict, role: str, text: str) -> None:
    text = (text or "").strip()
    if not text or role not in ("user", "bot"):
        return
    log = list(ses.get("log") or [])
    log.append({"role": role, "text": text[:MAX_TURN]})
    ses["log"] = log[-MAX_LOG:]


def llm_preface(ses: dict) -> str:
    """Короткая сводка для нейросети помощника: задача, выбор и последние реплики."""
    bits = []
    if ses.get("kind"):
        bits.append("task=" + str(ses.get("kind")))
    if ses.get("picked"):
        bits.append("model=" + str(ses.get("picked")))
    if ses.get("idea"):
        bits.append("idea=" + str(ses.get("idea"))[:180])
    if ses.get("prompt"):
        bits.append("prompt=" + str(ses.get("prompt"))[:220])
    if ses.get("params"):
        bits.append("params=" + str(ses.get("params"))[:160])
    if ses.get("camera"):
        bits.append("camera=" + str(ses.get("camera")))
    lines = [f"{x['role']}: {x['text']}" for x in (ses.get("log") or [])[-6:]]
    head = "DIALOG: " + "; ".join(bits) if bits else "DIALOG:"
    if lines:
        head += "\n" + "\n".join(lines)
    return head[:900]


def greet(lang: str, intent: str = "smalltalk") -> dict:
    from .render import response
    return response([t("hello", lang)], [], lang=lang, intent=intent)


def capabilities(lang: str) -> dict:
    from .render import response
    return response([t("capabilities", lang)], [], lang=lang, intent="smalltalk")


def open_question(lang: str, intent: str = "ask_type") -> dict:
    from .render import response
    return response([t("ask_open", lang)], [], lang=lang, intent=intent)


def vague_question(lang: str) -> dict:
    from .render import response
    return response([t("ask_vague", lang)], [], lang=lang, intent="need_subject")


def is_vague(text: str) -> bool:
    from . import brief as BR
    if BR.has_subject(text) and not _VAGUE.search(text or ""):
        return False
    return not BR.has_subject(text) or bool(_VAGUE.search(text or "") and BR.detail_level(text) <= 2)


def narrow_types(ses: dict, lang: str) -> list[dict]:
    """2–3 кнопки типа под конкретный запрос, не всё меню."""
    idea = ((ses.get("idea") or "") + " " + (ses.get("topic") or "")).lower()
    ru = lang != "en"
    out = [
        chip("Видео" if ru else "Video", "choose_type", "video"),
        chip("Картинка" if ru else "Image", "choose_type", "image"),
    ]
    if re.search(r"музык|трек|песн|звук|music|song|track", idea, re.I):
        out.append(chip("Музыка" if ru else "Music", "choose_type", "music"))
    return out[:3]


def type_question(ses: dict, lang: str) -> dict:
    from .render import response
    topic = (ses.get("topic") or ses.get("idea") or "").strip()
    if lang == "en":
        line = f"“{topic}” — a video or an image?" if topic else "A video or an image?"
    else:
        line = f"«{topic}» — это видео или картинка?" if topic else "Это видео или картинка?"
    return response([line], narrow_types(ses, lang), lang=lang, intent="ask_type")


def tree_guesses(engine: Any, msg: str, lang: str, limit: int = 3) -> list[dict]:
    tree = getattr(engine.d, "tree", None)
    if tree is None or not (msg or "").strip():
        return []
    from .tree import _stems
    stems = _stems(msg)
    if not stems:
        return []
    scored = []
    for sid, kw in getattr(tree, "_kw", {}).items():
        hit = len(stems & kw)
        if hit:
            scored.append((hit, sid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chips = []
    for _hit, sid in scored[:limit]:
        story = (tree.stories.get(sid) or {})
        title = str(story.get("title") or sid)[:60]
        chips.append(chip(title, "tree_hint", {"s": sid, "t": 0, "i": 0, "label": title}))
    return chips


def unclear(engine: Any, msg: str, lang: str, intent: str = "junk") -> dict:
    from .render import response
    return response([t("ask_open", lang)], tree_guesses(engine, msg, lang), lang=lang, intent=intent)


def park_snapshot(ses: dict) -> dict:
    return {
        "idea": ses.get("idea") or "",
        "kind": ses.get("kind"),
        "picked": ses.get("picked"),
        "prompt": ses.get("prompt") or "",
        "prompt_base": ses.get("prompt_base") or "",
        "params": dict(ses.get("params") or {}),
        "camera": ses.get("camera"),
        "topic": ses.get("topic") or "",
        "needs": list(ses.get("needs") or []),
    }


def maybe_park(ses: dict, new_idea: str) -> bool:
    prev = (ses.get("idea") or "").strip()
    new_idea = (new_idea or "").strip()
    if not prev or not new_idea or prev == new_idea:
        return False
    if not (ses.get("prompt") or ses.get("picked")):
        return False
    ses["parked"] = park_snapshot(ses)
    return True


def return_chip(ses: dict, lang: str) -> dict | None:
    parked = ses.get("parked") if isinstance(ses.get("parked"), dict) else None
    if not parked:
        return None
    title = (parked.get("topic") or parked.get("idea") or "").strip()[:40]
    if not title:
        title = "прошлой задаче" if lang != "en" else "the previous task"
    label = ("↩ Вернуться к " if lang != "en" else "↩ Back to ") + title
    return chip(label, "resume_task")


def _topic_words(text: str) -> str:
    from .router import topic_of
    return topic_of(text or "", 3)


def _touch_alive(item: dict, now: float | None = None) -> None:
    now = now if now is not None else time.time()
    created = float(item.get("created_ts") or now)
    if now - created > MEDIA_TTL:
        item["alive"] = False


def alive_media(ses: dict) -> list[dict]:
    now = time.time()
    out = []
    for item in ses.get("media") or []:
        if not isinstance(item, dict):
            continue
        _touch_alive(item, now)
        if item.get("alive") is not False:
            out.append(item)
    return out


def _next_n(ses: dict, kind: str) -> int:
    nums = [int(m.get("n") or 0) for m in (ses.get("media") or []) if m.get("kind") == kind]
    return (max(nums) if nums else 0) + 1


def add_upload(ses: dict, kind: str, name: str, upload_id: str = "") -> dict:
    for item in ses.get("media") or []:
        if item.get("source") == "upload" and item.get("upload_id") == upload_id and upload_id:
            item["alive"] = True
            item["name"] = name or item.get("name")
            return item
        if item.get("source") == "upload" and not upload_id and item.get("name") == name and item.get("kind") == kind:
            item["alive"] = True
            return item
    item = {
        "id": upload_id or f"up-{kind}-{_next_n(ses, kind)}",
        "source": "upload",
        "kind": kind,
        "name": name or kind,
        "n": _next_n(ses, kind),
        "model": "",
        "topic": _topic_words(name),
        "created_ts": time.time(),
        "upload_id": upload_id,
        "work_id": "",
        "url": "",
        "alive": True,
    }
    ses.setdefault("media", []).append(item)
    return item


def ingest_uploads(ses: dict, files: list[dict]) -> None:
    for f in files or []:
        add_upload(ses, str(f.get("kind") or ""), str(f.get("name") or ""), str(f.get("id") or ""))


def add_result(ses: dict, value: dict) -> dict:
    kind = str(value.get("kind") or "image")
    if kind == "music":
        kind = "audio"
    prompt = str(value.get("prompt") or "")
    item = {
        "id": "rs-" + str(int(time.time() * 1000))[-10:],
        "source": "result",
        "kind": kind if kind in ("image", "video", "audio", "text") else "image",
        "name": str(value.get("name") or "")[:60],
        "n": _next_n(ses, kind),
        "model": str(value.get("model") or "")[:80],
        "topic": _topic_words(prompt) or _topic_words(str(value.get("name") or "")),
        "created_ts": time.time(),
        "upload_id": "",
        "work_id": str(value.get("work_id") or "")[:40],
        "url": str(value.get("url") or "")[:500],
        "alive": True,
    }
    ses.setdefault("media", []).append(item)
    ses["files_ok"] = False
    return item


def _kind_word(kind: str, lang: str) -> str:
    ru = {"image": "картинка", "video": "видео", "audio": "аудио", "text": "текст"}
    en = {"image": "image", "video": "video", "audio": "audio", "text": "text"}
    table = en if lang == "en" else ru
    return table.get(kind, kind)


def _label(item: dict, lang: str) -> str:
    topic = item.get("topic") or item.get("name") or ""
    word = _kind_word(item.get("kind") or "", lang)
    n = item.get("n") or 1
    if lang == "en":
        return f"{word} #{n}" + (f" ({topic})" if topic else "")
    return f"{word} №{n}" + (f" ({topic})" if topic else "")


def refer(msg: str, ses: dict) -> tuple[str, list[dict]]:
    """('skip', []) | ('one', [item]) | ('many', items) | ('none', []) | ('dead', [item])."""
    if not _REF.search(msg or ""):
        return "skip", []
    items = alive_media(ses)
    dead = [m for m in (ses.get("media") or []) if isinstance(m, dict) and m.get("alive") is False]
    low = (msg or "").lower()
    kind = None
    if re.search(r"видео|ролик", low):
        kind = "video"
    elif re.search(r"картин|фото|изображен", low):
        kind = "image"
    elif re.search(r"аудио|музык|трек|голос", low):
        kind = "audio"
    pool = [m for m in items if m.get("kind") == kind] if kind else list(items)
    if not pool and dead and not items:
        return "dead", dead[:1]
    if not pool:
        # «анимируй моё фото» без файла в диалоге — обычная задача, не вопрос «какое фото»
        if not items and not re.search(r"этим же|последн|предыдущ|втор|№|результат|с этой|с этим|из прошлого", low):
            return "skip", []
        return "none", []
    num = None
    mnum = re.search(r"№\s*(\d+)|втор", low)
    if mnum:
        num = 2 if mnum.group(0).startswith("втор") else int(mnum.group(1))
    if num is not None:
        hit = [m for m in pool if int(m.get("n") or 0) == num]
        if len(hit) == 1:
            return "one", hit
        if not hit:
            return "none", []
        pool = hit
    topic_m = re.search(r"где\s+([а-яёa-z0-9\-]{3,})", low)
    if topic_m:
        word = topic_m.group(1)
        hit = [m for m in pool if word in (str(m.get("topic") or "") + " " + str(m.get("name") or "")).lower()]
        if len(hit) == 1:
            return "one", hit
        if len(hit) > 1:
            return "many", hit
    if len(pool) == 1:
        return "one", pool
    return "many", pool


def take_line(item: dict, lang: str) -> str:
    if lang == "en":
        return "Using " + _label(item, lang) + "."
    return "Беру " + _label(item, lang) + "."


def ask_which(items: list[dict], lang: str) -> dict:
    from .render import response
    kind = items[0].get("kind") if items else "video"
    word = _kind_word(kind or "video", lang)
    if lang == "en":
        line = f"Which {word}?"
    else:
        line = f"С каким { 'видео' if kind == 'video' else 'файлом' }: " + " · ".join(_label(m, lang) for m in items[:4]) + "?"
    chips = [chip(_label(m, lang), "media_pick", m.get("id")) for m in items[:6]]
    return response([line], chips, lang=lang, intent="ask_file")


def ask_attach(lang: str, dead: bool = False) -> dict:
    from .render import response
    if dead:
        line = ("Этот файл уже удалён — прикрепите его ещё раз." if lang != "en"
                else "That file is already gone — please attach it again.")
    else:
        line = ("Такого файла в разговоре нет. Прикрепите его." if lang != "en"
                else "That file is not in this chat. Please attach it.")
    return response([line], [chip("Прикрепить" if lang != "en" else "Attach", "attach")], lang=lang, intent="need_file")


def _accepts(engine: Any, card: Any, kind: str) -> bool:
    from . import files as F
    return F.accepts(card, kind, engine.d.inputs_fn)


def incompatible(engine: Any, card: Any, ses: dict, ctx: dict, lang: str) -> dict | None:
    """Выбранная модель не берёт тип файла — предложить другие, с ценой."""
    ids = list(ses.get("focus") or [])
    items = [m for m in alive_media(ses) if not ids or m.get("id") in ids]
    if not items:
        return None
    bad = [m for m in items if not _accepts(engine, card, m.get("kind") or "")]
    if not bad:
        return None
    kind = bad[0].get("kind") or "video"
    alts = []
    for c in engine.d.cards.values():
        if c.kind == card.kind and c.id != card.id and _accepts(engine, c, kind):
            if engine.d.catalog_fn and not engine.d.catalog_fn(c.id):
                continue
            alts.append(c)
    if not alts:
        from .render import response
        line = (f"{card.title} не принимает {_kind_word(kind, lang)}. Прикрепите другой файл или выберите другую модель."
                if lang != "en" else
                f"{card.title} does not take a {_kind_word(kind, lang)}. Attach another file or pick another model.")
        return response([line], [], lang=lang, intent="need_file")
    from .recommend import Pick
    head = (f"{card.title} не принимает {_kind_word(kind, lang)}. Вот модели, которые принимают, с ценой:"
            if lang != "en" else
            f"{card.title} does not take a {_kind_word(kind, lang)}. These models do, with the price:")
    return engine._show_models(Pick(alts[:6], True), ses, lang, "need_file", head=head)


def _origin(item: dict, lang: str) -> str:
    if item.get("source") == "result":
        model = item.get("model") or ""
        if lang == "en":
            return f"result #{item.get('n') or 1}" + (f", {model}" if model else "")
        return f"результат №{item.get('n') or 1}" + (f", {model}" if model else "")
    hh = time.strftime("%H:%M", time.localtime(float(item.get("created_ts") or time.time())))
    return (f"загружено {hh}" if lang != "en" else f"uploaded {hh}")


def _role_for(kind: str, model_kind: str, lang: str) -> str:
    ru = {
        ("image", "video"): "первый кадр",
        ("image", "image"): "референс стиля",
        ("video", "video"): "основа",
        ("audio", "video"): "голос",
        ("audio", "music"): "основа",
    }
    en = {
        ("image", "video"): "first frame",
        ("image", "image"): "style reference",
        ("video", "video"): "source",
        ("audio", "video"): "voice",
        ("audio", "music"): "source",
    }
    table = en if lang == "en" else ru
    return table.get((kind, model_kind), "основа" if lang != "en" else "source")


def files_block(card: Any, ses: dict, lang: str) -> dict | None:
    items = alive_media(ses)
    if not items:
        return None
    focus = set(ses.get("focus") or [])
    pointed = bool(focus)
    rows = []
    for m in items:
        checked = (m.get("id") in focus) if pointed else (len(items) == 1)
        rows.append({
            "id": m.get("id"),
            "kind": m.get("kind"),
            "name": _label(m, lang),
            "preview": m.get("url") or "",
            "origin": _origin(m, lang),
            "role": _role_for(m.get("kind") or "", card.kind, lang),
            "checked": bool(checked),
        })
    need = len(items) > 1 and not ses.get("files_ok")
    title = "Что отправляем" if lang != "en" else "What we send"
    return {"type": "files", "title": title, "items": rows, "need_confirm": need}


def generate_files(ses: dict) -> list[dict]:
    focus = set(ses.get("focus") or [])
    items = alive_media(ses)
    if len(items) == 1 and not focus:
        focus = {items[0].get("id")}
    out = []
    for m in items:
        if focus and m.get("id") not in focus:
            continue
        if not ses.get("files_ok") and len(items) > 1:
            continue
        out.append({"id": m.get("id"), "role": _role_for(m.get("kind") or "", "video", "ru"),
                    "kind": m.get("kind"), "name": m.get("name") or ""})
    return out


def confirm(ses: dict, value: Any, card_kind: str) -> str | None:
    """Вернуть текст вопроса, если набор не проходит лимит. Иначе отметить files_ok."""
    raw = value.get("items") if isinstance(value, dict) else value
    if not isinstance(raw, list):
        raw = []
    ids = []
    for it in raw:
        if isinstance(it, dict) and it.get("id"):
            ids.append(str(it["id"]))
        elif isinstance(it, str):
            ids.append(it)
    by_kind: dict[str, list[str]] = {}
    known = {m.get("id"): m for m in alive_media(ses)}
    for i in ids:
        m = known.get(i)
        if not m:
            continue
        by_kind.setdefault(m.get("kind") or "", []).append(i)
    if card_kind == "video" and len(by_kind.get("video") or []) > 1:
        return "limit-video"
    ses["focus"] = [i for i in ids if i in known]
    ses["files_ok"] = True
    return None


def limit_question(ses: dict, lang: str, kind: str = "video") -> dict:
    from .render import response
    items = [m for m in alive_media(ses) if m.get("kind") == kind]
    line = ("Модель берёт 1 видео — какое оставить?" if lang != "en" else "The model takes 1 video — which one should stay?")
    chips = [chip(_label(m, lang), "media_pick", m.get("id")) for m in items[:6]]
    return response([line], chips, lang=lang, intent="ask_file")
