"""Правило «выбранная модель главнее»: если человек сам выбрал модель в панели (или в списке у поля ввода),
сообщение работает с этой моделью, а не со стандартным процессом генерации.

  * текстовая модель (DeepSeek, Claude, GPT…) — сообщение уходит в неё как есть (фронт отправляет в чат модели);
    помощник НЕ запускает поток генерации. Только если человек явно просит сделать медиа («сгенерируй видео») —
    вопрос: остаться с DeepSeek или подобрать видео-модель. По умолчанию — выбранная модель.
  * генеративная модель (Kling, GPT Image…) — помощник ведёт задачу сразу с ней: без списка моделей,
    промпт и поля — под неё. Если просят другой тип («видео», а выбрана картинка) — вопрос, а не молчаливая подмена.
  * модель не выбрана человеком (стоит по умолчанию) — обычный процесс.

Подключение в engine.Assistant.handle():
    from . import model_lock as ML
    ...
    if action and action.get("type") in ML.ACTIONS:
        out = ML.action(self, action["type"], action.get("value"), ctx, ses, lang)
    else:
        out = ML.before_message(self, msg, ctx, ses, lang) if msg else None
        if out is None:
            out = self._message(msg, ctx, ses, lang)

Фронт присылает в context: selected_model_id, selected_model_kind, model_locked (true — выбрал человек).
"""
from __future__ import annotations

import re
from typing import Any

ACTIONS = ("lock_keep", "lock_switch")

KIND_WORDS = {
    "video": r"видео|ролик|рилс|клип|анимац|оживи|оживить|video|reels?|clip",
    "image": r"картинк|изображен|фото|обложк|постер|баннер|логотип|арт\b|нарисуй|image|picture|photo|logo",
    "music": r"музык|трек|песн|бит\b|джингл|music|song|track",
    "sfx": r"звуков\w* эффект|sfx",
    "voice": r"озвуч|голос\w* (?:озвуч|начитк)|tts|voice ?over",
    "3d": r"\b3d\b|3д|трёхмерн|трехмерн",
}
GEN_VERB = re.compile(r"\b(сгенер\w*|генерир\w*|сгенерируй|создай|сделай|нарисуй|оживи|сними|смонтируй|озвучь|"
                      r"generate|create|make|draw|render|animate)\b", re.I)
# объект — текст («сделай промпт / сценарий / подпись для видео») — это задача текстовой модели, не генерация
TEXT_OBJ = re.compile(r"промпт|сценари|текст|пост\b|подпис|стать|описани|идею|план|prompt|script|caption|text|article", re.I)
KIND_RU = {"video": "видео", "image": "картинки", "music": "музыку", "sfx": "звуки", "voice": "озвучку",
           "3d": "3D", "text": "текст", "edit": "правку картинок"}


def asked_kind(msg: str) -> str | None:
    """Какой тип результата человек явно просит СДЕЛАТЬ, а не написать текст про него.
    «сгенерируй видео по этому сценарию» → video; «напиши / сделай промпт для видео» → None; «оживи фото» → video."""
    low = (msg or "").lower()
    for m in GEN_VERB.finditer(low):
        if re.match(r"оживи|animate", m.group(1)):
            return "video"
        tail = low[m.end(): m.end() + 60]
        best: tuple[int, str] | None = None
        for kind, rx in KIND_WORDS.items():
            k = re.search(rx, tail)
            if k and (best is None or k.start() < best[0]):
                best = (k.start(), kind)
        if not best:
            continue
        t = TEXT_OBJ.search(tail)
        if t and t.start() < best[0]:          # «сделай промпт для видео»: сначала текст, потом тип
            continue
        return best[1]
    return None


def lock_of(a: Any, ctx: dict, ses: dict) -> dict | None:
    """Выбранная человеком модель или None. Модель должна быть в каталоге помощника и открыта в студии."""
    if not ctx.get("model_locked"):
        return None
    mid = str(ctx.get("selected_model_id") or "")
    card = (a.d.cards or {}).get(mid)
    if card is None:
        return None
    if getattr(a.d, "catalog_fn", None) and not a.d.catalog_fn(mid):
        return None
    kind = str(getattr(card, "kind", "") or ctx.get("selected_model_kind") or "")
    return {"id": mid, "kind": kind, "title": getattr(card, "title", mid), "card": card}


def _compatible(model_kind: str, want: str | None) -> bool:
    if not want:
        return True
    if model_kind == want:
        return True
    return (model_kind, want) in {("edit", "image"), ("image", "edit"), ("music", "sfx"), ("sfx", "music"),
                                  ("voice", "music")}


def before_message(a: Any, msg: str, ctx: dict, ses: dict, lang: str) -> dict | None:
    """None — обычный процесс. Иначе — готовый ответ под выбранную модель."""
    from .render import chip, response

    lock = lock_of(a, ctx, ses)
    if lock is None:
        ses.pop("lock", None)
        return None
    if ses.get("lock_off") == lock["id"]:          # человек уже выбрал «подобрать другую» для этой модели
        return None
    ses["lock"] = lock["id"]
    want = asked_kind(msg)
    en = str(lang).startswith("en")

    if lock["kind"] == "text":
        if want and want != "text":
            ses["lock_pending"] = {"text": msg[:2000], "kind": want}
            head = (f"Selected model is {lock['title']} (text). Make {want} instead?" if en else
                    f"Сейчас выбрана {lock['title']} — она пишет текст. Сделать {KIND_RU.get(want, want)}?")
            return response([head], [
                chip((f"Ask {lock['title']}" if en else f"Спросить {lock['title']}"), "lock_keep", None, primary=True),
                chip(("Pick a model for it" if en else f"Подобрать модель для: {KIND_RU.get(want, want)}"), "lock_switch", want),
            ], [], lang, intent="lock_ask")
        # главное правило: текстовая модель отвечает сама, помощник поток генерации не запускает
        return response([], [], [], lang, intent="route_text_model", silent=True,
                        route={"to": "text_model", "model_id": lock["id"], "text": msg})

    # генеративная модель: задача ведётся сразу с ней
    if not _compatible(lock["kind"], want):
        ses["lock_pending"] = {"text": msg[:2000], "kind": want}
        head = (f"{lock['title']} makes {lock['kind']}. Do it with {lock['title']} or pick a {want} model?" if en else
                f"Выбрана {lock['title']} — она делает {KIND_RU.get(lock['kind'], lock['kind'])}. "
                f"Сделать на ней или подобрать модель для: {KIND_RU.get(want, want)}?")
        return response([head], [
            chip((f"Do it with {lock['title']}" if en else f"Сделать на {lock['title']}"), "lock_keep", None, primary=True),
            chip(("Pick another model" if en else f"Подобрать модель для: {KIND_RU.get(want, want)}"), "lock_switch", want),
        ], [], lang, intent="lock_ask")
    # картинка и видео: сначала обычный промпт (и для видео — раскадровка). Список моделей пропускается в конце.
    if lock["kind"] in ("image", "edit", "video"):
        ses["lock"] = lock["id"]
        return None
    if ses.get("picked") != lock["id"] or ses.get("kind") != lock["kind"]:
        _pin(ses, lock, msg)
        return a._pick(lock["id"], ctx, ses, lang, "locked_model")
    return None                                       # та же модель уже ведётся — обычные шаги (правки, параметры)


def _composer_pick(a: Any, ctx: dict) -> dict | None:
    """Модель в поле ввода. Подсветка в панели — это выбор, даже если флаг закрепления потерялся."""
    mid = str(ctx.get("selected_model_id") or "")
    if not mid:
        return None
    card = (a.d.cards or {}).get(mid)
    if card is None:
        return None
    if getattr(a.d, "catalog_fn", None) and not a.d.catalog_fn(mid):
        return None
    kind = str(getattr(card, "kind", "") or ctx.get("selected_model_kind") or "")
    if kind not in ("image", "edit", "video"):
        return None
    return {"id": mid, "kind": kind, "title": getattr(card, "title", mid), "card": card}


def parameters_if_locked(a: Any, ctx: dict, ses: dict, lang: str, kind: str) -> dict | None:
    """Модель уже выбрана человеком: не показывать список, открыть параметры этой модели."""
    lock = lock_of(a, ctx, ses) or _composer_pick(a, ctx)
    if lock is None:
        return None
    flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else {}
    if flow.get("need_ref") or ses.get("need_ref"):
        from . import files as F
        if not F.accepts(lock["card"], "image", getattr(a.d, "inputs_fn", None)):
            return None
    if kind == "image":
        if lock["kind"] not in ("image", "edit"):
            return None
    elif not _compatible(lock["kind"], kind):
        return None
    prompt = (ses.get("prompt") or ses.get("prompt_base") or ses.get("idea") or "").strip()
    if not prompt:
        return None
    ses["idea"] = prompt
    ses["prompt"] = ses["prompt_base"] = prompt
    ses["brief_done"] = True
    ses["picked"] = lock["id"]
    ses["gen_model"] = lock["id"]
    ses["kind"] = "image" if lock["kind"] == "edit" else lock["kind"]
    ses["gen_kind"] = ses["kind"]
    if hasattr(a, "_setup_from_idea"):
        return a._setup_from_idea(lock["card"], ctx, ses, lang, "locked_model")
    return a._pick(lock["id"], ctx, ses, lang, "locked_model")


def _pin(ses: dict, lock: dict, msg: str) -> None:
    """Закрепить модель в задаче помощника: без выбора моделей, сразу её путь (идея → промпт → карточка)."""
    from . import router as R
    ses.update(picked=lock["id"], kind=lock["kind"], gen_kind=lock["kind"], gen_model=lock["id"],
               assist_mode=ses.get("assist_mode") or "direct", shown=[lock["id"]])
    if msg and msg.strip():
        ses.update(idea=msg.strip()[:500], topic=R.topic_of(msg) or ses.get("topic") or "",
                   needs=R.detect_needs(msg) or ses.get("needs") or [], prompt="", brief=None, brief_done=False)


def action(a: Any, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Ответ на вопрос «остаться с выбранной моделью или подобрать другую»."""
    from .render import response
    pend = ses.pop("lock_pending", None) or {}
    text = str(pend.get("text") or "")
    lock = lock_of(a, ctx, ses)
    if kind == "lock_keep" and lock:
        if lock["kind"] == "text":
            return response([], [], [], lang, intent="route_text_model", silent=True,
                            route={"to": "text_model", "model_id": lock["id"], "text": text})
        _pin(ses, lock, text)
        return a._pick(lock["id"], ctx, ses, lang, "locked_model")
    # lock_switch: снимаем закрепление для этой модели и идём обычным процессом с нужным типом
    if lock:
        ses["lock_off"] = lock["id"]
    ses.update(picked=None, gen_model=None, kind=None, shown=[])
    ctx = dict(ctx)
    ctx["model_locked"] = False
    out = a._message(text, ctx, ses, lang) if text else response(
        ["Опишите, что сделать" if not str(lang).startswith("en") else "Describe what to make"], [], [], lang,
        intent="lock_switch")
    out["ui_do"] = {"action": "unlock_model", "value": None}
    return out
