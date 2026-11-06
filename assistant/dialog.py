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


def open_kinds(ses: dict, lang: str) -> list[dict]:
    """Первый вопрос, если языковая модель не выбрала процесс: все пути, не только видео и картинка."""
    ru = lang != "en"
    idea = (ses.get("idea") or ses.get("topic") or "").strip()
    return [
        chip("Промпт" if ru else "Prompt", "choose_type", "prompt"),
        chip("Рилс" if ru else "Reels", "mode_start", {"id": "reels", "text": idea}),
        chip("Видео" if ru else "Video", "choose_type", "video"),
        chip("Картинка" if ru else "Image", "choose_type", "image"),
        chip("Раскадровка" if ru else "Storyboard", "sb_start", idea),
        chip("Музыка" if ru else "Music", "choose_type", "music"),
        chip("Озвучка" if ru else "Voiceover", "choose_type", "voice"),
    ]


def type_question(ses: dict, lang: str) -> dict:
    from .render import response
    line = "What should we make?" if lang == "en" else "Что с этим сделать?"
    return response([line], open_kinds(ses, lang), lang=lang, intent="ask_type")


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


def add_upload(ses: dict, kind: str, name: str, upload_id: str = "", preview: str = "") -> dict:
    for item in ses.get("media") or []:
        if item.get("source") == "upload" and item.get("upload_id") == upload_id and upload_id:
            item["alive"] = True
            item["name"] = name or item.get("name")
            if preview and not item.get("url"):
                item["url"] = preview
            return item
        if item.get("source") == "upload" and not upload_id and item.get("name") == name and item.get("kind") == kind:
            item["alive"] = True
            if preview and not item.get("url"):
                item["url"] = preview
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
        "url": preview or "",
        "alive": True,
    }
    ses.setdefault("media", []).append(item)
    return item


def ingest_uploads(ses: dict, files: list[dict]) -> None:
    for f in files or []:
        add_upload(ses, str(f.get("kind") or ""), str(f.get("name") or ""), str(f.get("id") or ""), str(f.get("preview") or ""))


def files_from_uploads(ses: dict) -> list[dict]:
    """Загрузки этого диалога, которые ещё можно отправить. Пустая скрепка в новом сообщении их не стирает."""
    out = []
    seen = set()
    for m in alive_media(ses):
        if m.get("source") != "upload":
            continue
        fid = str(m.get("upload_id") or "")
        if not fid or fid in seen:
            continue
        seen.add(fid)
        row = {"kind": str(m.get("kind") or "image"), "name": str(m.get("name") or "файл"), "id": fid}
        prev = str(m.get("url") or "")
        if prev:
            row["preview"] = prev
        out.append(row)
    return out


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


def _preview(item: dict) -> str:
    """Миниатюра: своя копия работы, иначе адрес файла. Загрузка без адреса добирается на клиенте по номеру upl_."""
    wid = str(item.get("work_id") or "")
    if wid.isdigit():
        return f"/api/works/{wid}/media"
    return str(item.get("url") or "")


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
            "id": m.get("upload_id") or m.get("id"),
            "kind": m.get("kind"),
            "name": _label(m, lang),
            "file": m.get("name") or "",
            "preview": _preview(m),
            "work_id": str(m.get("work_id") or ""),
            "origin": _origin(m, lang),
            "role": _role_for(m.get("kind") or "", card.kind, lang),
            "checked": bool(checked),
        })
    need = len(items) > 1 and not ses.get("files_ok") and _uploaded_photo(items) is None
    title = "Что отправляем" if lang != "en" else "What we send"
    return {"type": "files", "title": title, "items": rows, "need_confirm": need}


def _uploaded_photo(items: list[dict]) -> dict | None:
    """Одно загруженное фото. Старые результаты рядом не заменяют его."""
    photos = [m for m in items if m.get("kind") == "image" and str(m.get("upload_id") or "").startswith("upl_")]
    return photos[0] if len(photos) == 1 else None


def generate_files(ses: dict) -> list[dict]:
    focus = set(ses.get("focus") or [])
    items = alive_media(ses)
    if len(items) == 1 and not focus:
        focus = {items[0].get("id")}
    photo = _uploaded_photo(items)
    out = []
    for m in items:
        sent = m.get("upload_id") or m.get("id")
        if focus and m.get("id") not in focus and sent not in focus:
            continue
        if not ses.get("files_ok") and len(items) > 1 and m is not photo:
            continue
        out.append({"id": sent, "role": _role_for(m.get("kind") or "", "video", "ru"),
                    "kind": m.get("kind"), "name": m.get("name") or ""})
    return out


def drop(ses: dict, mid: str) -> None:
    """Убрать файл из того, что уйдёт в генерацию. Повторный запрос его не возвращает."""
    mid = str(mid or "")
    if not mid:
        return
    for item in ses.get("media") or []:
        if item.get("id") == mid or item.get("upload_id") == mid:
            item["alive"] = False
    ses["focus"] = [i for i in (ses.get("focus") or []) if i != mid]
    ses["files"] = [f for f in (ses.get("files") or []) if str(f.get("id") or "") != mid]
    ses["files_ok"] = True


def adopt_message_files(ses: dict, files: list[dict]) -> None:
    """Новое сообщение пришло со своими файлами: в генерацию берём только их, не кадры прошлого чата."""
    ids = {str(f.get("id") or "") for f in files or [] if f.get("id")}
    for item in ses.get("media") or []:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("upload_id") or "")
        if item.get("source") == "upload":
            item["alive"] = bool(fid and fid in ids)
        elif item.get("source") == "result":
            item["alive"] = False
    ses["files"] = list(files or [])
    ses["focus"] = []
    ses["files_ok"] = len(ids) <= 1
    ingest_uploads(ses, files or [])


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


# ---------------------------------------------------------------- подключения MCP
_MCP_RX = re.compile(r"\bmcp\b|мсп", re.I)
_MCP_NAME = re.compile(r"vidiq|dropbox|meshy|tripo|elevenlabs", re.I)
_MCP_ASK = re.compile(r"подключ|зачем|какой|какие|как\b|нужен|выбра", re.I)
_CLAUDE_MCP = re.compile(r"(клод|claude).{0,48}(mcp|мсп|подключ)|(mcp|мсп|подключ).{0,48}(клод|claude)", re.I)

_GOALS = (
    ("Тренды и ключевые слова", "trends", "vidiq"),
    ("Прогноз виральности", "viral", "higgsfield"),
    ("Хранить и отправлять файлы", "files", "dropbox"),
    ("3D-модели", "3d", "meshy"),
)


def mcp_about(msg: str) -> bool:
    """Вопрос про подключение сервиса, а не про генерацию и не про тему оформления."""
    t = msg or ""
    if _CLAUDE_MCP.search(t) or _MCP_RX.search(t):
        return True
    if _MCP_NAME.search(t) and _MCP_ASK.search(t):
        return True
    if re.search(r"higgsfield", t, re.I) and re.search(r"mcp|мсп|подключ|виральн|прогноз", t, re.I):
        return True
    return False


def _presets() -> list[dict]:
    try:
        from mcp_routes import PRESETS
        return list(PRESETS)
    except Exception:
        return []


def _preset(pid: str) -> dict | None:
    for p in _presets():
        if p.get("id") == pid:
            return p
    return None


def _service_for(goal: str) -> str:
    for _label, gid, pid in _GOALS:
        if gid == goal:
            return pid
    return "vidiq"


def _task_known(ses: dict) -> str:
    """Уже ясно, что человек делает — не спрашивать заново. Пусто, если неясно."""
    flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else {}
    blob = " ".join(str(x or "") for x in (ses.get("idea"), ses.get("kind"), flow.get("story"), flow.get("source"))).lower()
    if re.search(r"рилс|reels|шортс|видео", blob):
        return "trends"
    if re.search(r"3d|меш|трипо", blob):
        return "3d"
    if re.search(r"dropbox|хранилищ|файл", blob) and "mcp" not in blob:
        return ""
    return ""


def _advice(pid: str, lang: str) -> str:
    if pid == "vidiq":
        return ("Для рилса советую vidIQ: покажет популярные темы и ключевые слова, "
                "а под готовым видео появится кнопка «Проверить по трендам».")
    if pid == "higgsfield":
        return "Для прогноза, залетит ли ролик, советую Higgsfield: балл, сила начала и удержание."
    if pid == "dropbox":
        return "Чтобы хранить и забирать файлы, советую Dropbox: результат можно сохранить и взять футаж обратно."
    if pid == "meshy":
        return "Для 3D-модели советую Meshy: из текста или картинки получится модель."
    p = _preset(pid)
    name = (p or {}).get("name") or pid
    return f"Для этой задачи советую {name}."


def _steps_line(pid: str) -> str:
    p = _preset(pid) or {}
    if p.get("auth") == "oauth":
        return "Нажмите «Подключить» → войдите в аккаунт сервиса → разрешите доступ."
    return "Вставьте ключ из личного кабинета сервиса."


def _mcp_state(ses: dict) -> dict:
    m = ses.get("mcp")
    return m if isinstance(m, dict) else {}


def mcp_turn(engine: Any, msg: str, ctx: dict, ses: dict, lang: str) -> dict | None:
    if not mcp_about(msg):
        return None
    if _CLAUDE_MCP.search(msg or ""):
        from .render import response
        return response(
            ["Не нужно. Подключения работают в студии отдельно и подходят к любым моделям."],
            [], lang=lang, intent="mcp")
    if engine._is_guest(ctx):
        ses["mcp"] = {"stage": "ask", "goal": _task_known(ses), "service": ""}
        return engine._ask_login(ses, lang, "mcp")
    known = _task_known(ses)
    if known:
        return mcp_advise(engine, known, ctx, ses, lang)
    return mcp_ask(ses, lang)


def mcp_ask(ses: dict, lang: str) -> dict:
    from .render import chip, response
    ses["mcp"] = {"stage": "ask", "goal": "", "service": ""}
    chips = [chip(label, "mcp_goal", gid) for label, gid, _pid in _GOALS]
    return response(["Для какой задачи подключение?"], chips, lang=lang, intent="mcp")


def mcp_goal(engine: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    return mcp_advise(engine, str(value or "trends"), ctx, ses, lang)


def mcp_advise(engine: Any, goal: str, ctx: dict, ses: dict, lang: str) -> dict:
    from .render import chip, response
    pid = _service_for(goal)
    alt = "higgsfield" if pid == "vidiq" else "vidiq"
    ses["mcp"] = {"stage": "advise", "goal": goal, "service": pid}
    p = _preset(pid) or {}
    name = p.get("name") or pid
    other = (_preset(alt) or {}).get("name") or alt
    chips = [
        chip(f"Подключить {name}", "open_mcp", pid, primary=True),
        chip(f"Подключить {other}", "open_mcp", alt),
        chip("Чем они отличаются", "mcp_compare"),
    ]
    return response([_advice(pid, lang)], chips, lang=lang, intent="mcp")


def mcp_compare(ses: dict, lang: str) -> dict:
    from .render import chip, response
    pid = str(_mcp_state(ses).get("service") or "vidiq")
    text = ("vidIQ — темы и ключевые слова для ролика. Higgsfield — прогноз, залетит ли уже снятый ролик. "
            "Для рилса обычно начинают с vidIQ.")
    return response([text], [chip("Подключить vidIQ", "open_mcp", "vidiq", primary=True),
                             chip("Подключить Higgsfield", "open_mcp", "higgsfield")],
                    lang=lang, intent="mcp")


def mcp_open(engine: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    from .render import chip, response
    pid = str(value or _mcp_state(ses).get("service") or "vidiq")
    ses["mcp"] = {"stage": "steps", "goal": _mcp_state(ses).get("goal") or "", "service": pid}
    if engine._is_guest(ctx):
        return engine._ask_login(ses, lang, "mcp")
    p = _preset(pid) or {}
    name = p.get("name") or pid
    return response(
        [f"Открыла {name}. {_steps_line(pid)}"],
        [chip("Проверить подключение", "mcp_try"), chip("Повторить подключение", "open_mcp", pid)],
        lang=lang, intent="mcp_steps",
        ui_do={"action": "open_mcp", "value": pid})


def mcp_try(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    from .render import chip, response
    pid = str(_mcp_state(ses).get("service") or "vidiq")
    name = (_preset(pid) or {}).get("name") or pid
    last = next((m for m in reversed(alive_media(ses)) if m.get("kind") in ("video", "image")), None)
    if last:
        return response(
            [f"{name} подключён. Попробуем на вашем последнем видео?"],
            [chip("Проверить по трендам", "open_mcp", pid, primary=True)],
            lang=lang, intent="mcp_connected")
    return response(
        [f"{name} подключён. Найти тренды по теме?"],
        [chip("Найти тренды по теме", "mcp_topic")],
        lang=lang, intent="mcp_connected")


def mcp_connected(engine: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    from .render import response
    if isinstance(value, dict) and value.get("id"):
        st = _mcp_state(ses)
        st["service"] = str(value.get("id"))
        st["stage"] = "steps"
        ses["mcp"] = st
    return mcp_try(engine, ctx, ses, lang)


def mcp_failed(ses: dict, lang: str) -> dict:
    from .render import chip, response
    pid = str(_mcp_state(ses).get("service") or "vidiq")
    return response(
        ["Подключение не прошло: доступ не выдан."],
        [chip("Повторить подключение", "open_mcp", pid, primary=True),
         chip("Написать в поддержку", "mcp_support")],
        lang=lang, intent="mcp")


def mcp_support(lang: str) -> dict:
    from .render import response
    return response(["Напишите в поддержку из кабинета — там же видны ваши подключения."], [], lang=lang, intent="mcp")


def mcp_show(engine: Any, ctx: dict, ses: dict, lang: str) -> dict:
    st = _mcp_state(ses)
    if st.get("stage") == "steps" and st.get("service"):
        return mcp_open(engine, st["service"], ctx, ses, lang)
    if st.get("stage") == "advise" and st.get("goal"):
        return mcp_advise(engine, st["goal"], ctx, ses, lang)
    if st.get("goal"):
        return mcp_advise(engine, st["goal"], ctx, ses, lang)
    return mcp_ask(ses, lang)


def ui_more(lang: str) -> dict:
    from .render import chip, response
    return response(
        ["Можно сменить тему или открыть панель."],
        [chip("Тёмная тема", "set_theme", "black"),
         chip("Светлая тема", "set_theme", "white"),
         chip("Панель моделей", "open_panel", "models")],
        lang=lang, intent="ui_help")


def limit_question(ses: dict, lang: str, kind: str = "video") -> dict:
    from .render import response
    items = [m for m in alive_media(ses) if m.get("kind") == kind]
    line = ("Модель берёт 1 видео — какое оставить?" if lang != "en" else "The model takes 1 video — which one should stay?")
    chips = [chip(_label(m, lang), "media_pick", m.get("id")) for m in items[:6]]
    return response([line], chips, lang=lang, intent="ask_file")
