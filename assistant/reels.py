"""Режим «Рилс»: вирусный ролик по шагам — идея → персонаж → сценарий → раскадровка → общий промпт → генерация.

Как в Virale (персонажи → сценарий → раскадровка → промпт) с аккуратными уточняющими окнами как в Buzzy:
каждый вопрос — карточка «choice»: пронумерованные варианты (первый раскрыт), 4-й пункт — свой текст,
кнопка «Продолжить». На каждом шаге можно поправить текст руками или попросить словами.

Шаги (ses["reel"]["step"]):
  idea       — какую историю снимаем (3 идеи + своя)
  refs       — проверка референсов перед персонажем (фото героя / стиль / не использовать)
  character  — карточка персонажа на светло-сером фоне + «что поправить?»; лист персонажа можно сгенерировать
  script     — общее описание: хук, развитие, финал, настроение + «что поправить?»
  storyboard — кадры: время, план, действие, движение камеры, промпт кадра; любой кадр правится отдельно
  final      — общий промпт для видеомодели, выбор модели, «Сгенерировать»

LLM пишет тексты; без неё — аккуратные шаблоны (режим работает и без ключей).
Модуль без Flask: всё внешнее — через объект помощника `a` (Assistant): _llm_json, _price, d.cards, d.inputs_fn.
"""
from __future__ import annotations

import re
from typing import Any

from . import camera as CAM
from . import files as F
from . import params as P
from .render import chip, response, short_price

STEPS = ("character", "script", "storyboard", "final")
STEP_TITLES = {"ru": {"idea": "Идея", "refs": "Референсы", "character": "Персонаж", "script": "Сценарий",
                      "storyboard": "Раскадровка", "final": "Промпт"},
               "en": {"idea": "Idea", "refs": "References", "character": "Character", "script": "Script",
                      "storyboard": "Storyboard", "final": "Prompt"}}
PREV = {"refs": "idea", "character": "refs", "script": "character", "storyboard": "script", "final": "storyboard"}
MAX_FRAMES = 6
SHEET_BG = "seamless light grey studio background (#E6E6E8)"
# видеомодели для итогового ролика — в порядке предпочтения (кто держит персонажа и вертикаль)
FINAL_MODELS = ("seedance-2-5", "kling-v3-0-hf", "veo-3-1", "minimax-h3", "kling-v2-5-turbo-pro", "veo-3-1-fast",
                "pixverse-v6", "wan-3-0")
SHEET_MODELS = ("nano-banana-pro", "nano-banana-2", "seedream-5-pro", "gpt-image-2")
STYLES = {
    "ru": [("ugc", "UGC — как снято на телефон", "живой ролик от первого лица, естественный свет, ручная камера"),
           ("cinema", "Кино", "кинематографичный свет, плёночное зерно, плавные движения камеры"),
           ("cartoon", "Мультик 3D", "стилизованный 3D, как в анимационном кино, яркая палитра"),
           ("ad", "Реклама продукта", "чистый свет, крупные планы продукта, динамичный монтаж")],
    "en": [("ugc", "UGC — shot on a phone", "first-person, natural light, handheld"),
           ("cinema", "Cinematic", "cinematic lighting, film grain, smooth camera moves"),
           ("cartoon", "3D cartoon", "stylized 3D animation look, vivid palette"),
           ("ad", "Product ad", "clean light, product close-ups, punchy editing")],
}
STYLE_EN = {"ugc": "authentic UGC smartphone footage, natural light, handheld feel",
            "cinema": "cinematic look, soft contrast, subtle film grain, smooth camera moves",
            "cartoon": "stylized 3D animated film look, vivid palette, soft global illumination",
            "ad": "clean commercial look, crisp product lighting, punchy pacing"}


def L(lang: str) -> str:
    return "en" if lang == "en" else "ru"


def tr(lang: str, ru: str, en: str) -> str:
    return en if L(lang) == "en" else ru


def state(ses: dict) -> dict:
    st = ses.get("reel")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("step", "idea")
    st.setdefault("idea", "")
    st.setdefault("style", "")
    st.setdefault("characters", [])
    st.setdefault("script", None)
    st.setdefault("frames", [])
    st.setdefault("model", "")
    st.setdefault("final", "")
    st.setdefault("refs", [])
    ses["reel"] = st
    return st


def active(ses: dict) -> bool:
    return isinstance(ses.get("reel"), dict) and ses.get("assist_mode") == "reel"


# ════════════════════════════════════════════════════════════ блоки
def stepper(step: str, lang: str) -> dict:
    names = STEP_TITLES[L(lang)]
    if step in ("idea", "refs"):
        return {"type": "reel_steps", "current": 0, "total": len(STEPS), "label": names[step], "steps": []}
    n = STEPS.index(step) + 1
    return {"type": "reel_steps", "current": n, "total": len(STEPS), "label": names[step],
            "steps": [{"id": s, "title": names[s], "state": "done" if i + 1 < n else ("current" if i + 1 == n else "todo")}
                      for i, s in enumerate(STEPS)]}


def choice(qid: str, title: str, options: list[tuple[str, str, str]], placeholder: str, lang: str,
           cta: str | None = None, extra: dict | None = None) -> dict:
    """Уточняющее окно: пронумерованные варианты (id, заголовок, пояснение) + свой текст + «Продолжить».
    extra — второй, короткий выбор в том же окне (стиль): {id, title, options:[{id,label,detail}], selected}."""
    out = {"type": "choice", "id": qid, "title": title,
           "options": [{"id": oid, "label": lab, "detail": det} for oid, lab, det in options],
           "custom_placeholder": placeholder, "cta": cta or tr(lang, "Продолжить", "Continue")}
    if extra:
        out["extra"] = extra
    return out


# ════════════════════════════════════════════════════════════ LLM: системные промпты и проверка
IDEAS_SYSTEM = (
    "You are a creative producer of viral short vertical videos (Reels/TikTok/Shorts). "
    "Return ONLY JSON {\"ideas\":[{\"title\":str,\"detail\":str}]} with exactly 3 ideas in {lang}. "
    "title: 4-9 words; detail: one sentence with the hook in the first 2 seconds. "
    "If the user gave a theme, all 3 ideas develop that theme in different directions. Nothing unsafe, no real people.")

CHAR_SYSTEM = (
    "You design a consistent character for a short AI video. Return ONLY JSON {\"characters\":[{"
    "\"name\":str,\"role\":str,\"age\":str,\"look\":str,\"hair\":str,\"body\":str,\"outfit\":str,\"details\":str,"
    "\"manner\":str,\"sheet_prompt\":str}]} with 1 or 2 characters. All fields except sheet_prompt in {lang}, short "
    "(one line each). sheet_prompt in English, 60-120 words: a character turnaround reference sheet — front, 3/4, side "
    "and back full-body views plus 3 facial expression close-ups, identical face, hair and outfit in every view, "
    "on a seamless light grey studio background (#E6E6E8), even soft light, no text, no logos. "
    "If a reference photo is the character, describe it as 'the person from the reference photo' and keep the "
    "likeness. If a change request is given, apply it and keep everything else. Nothing unsafe, no real celebrities.")

SCRIPT_SYSTEM = (
    "You write the overall script of a viral vertical video of {sec} seconds. Return ONLY JSON {\"title\":str,"
    "\"logline\":str,\"hook\":str,\"beats\":[str],\"ending\":str,\"mood\":str} in {lang}. hook = what happens in the "
    "first 2 seconds to stop the scroll; beats = 2-4 short steps of development; ending = payoff or call to action; "
    "mood = music and sound feel. Use the given characters and style. If a change request is given, apply it.")

BOARD_SYSTEM = (
    "You split a short vertical video script into {n} shots for an AI video model. Return ONLY JSON {\"frames\":["
    "{\"role\":str,\"seconds\":number,\"shot\":str,\"action\":str,\"camera\":str,\"prompt\":str}]}. role: hook / "
    "development / climax / ending (in {lang}); seconds: duration, all shots together = {sec}; shot: framing in {lang}; "
    "action: one sentence in {lang}; camera: ONE id from: {ids}; prompt: English, 20-45 words, self-contained, "
    "names the character by appearance (not by name), action, setting, framing, light. Keep characters and style "
    "consistent. If a change request is given, apply it.")

FRAME_SYSTEM = (
    "Rewrite ONE shot of a short vertical video. Return ONLY JSON {\"shot\":str,\"action\":str,\"camera\":str,"
    "\"prompt\":str}. shot and action in {lang}; camera: ONE id from: {ids}; prompt: English, 20-45 words. Apply the "
    "user's change, keep the character, style and story.")


def _txt(v: Any, n: int = 300) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def v_ideas(d: Any) -> dict:
    items = [{"title": _txt(x.get("title"), 90), "detail": _txt(x.get("detail"), 240)}
             for x in (d.get("ideas") if isinstance(d, dict) else None) or [] if isinstance(x, dict)]
    items = [x for x in items if x["title"]]
    if len(items) < 2:
        raise ValueError("ideas")
    return {"ideas": items[:3]}


CHAR_FIELDS = ("name", "role", "age", "look", "hair", "body", "outfit", "details", "manner")


def v_chars(d: Any) -> dict:
    out = []
    for c in (d.get("characters") if isinstance(d, dict) else None) or []:
        if not isinstance(c, dict):
            continue
        card = {k: _txt(c.get(k), 160) for k in CHAR_FIELDS}
        card["sheet_prompt"] = _txt(c.get("sheet_prompt"), 1200)
        if card["name"] and card["look"] and len(card["sheet_prompt"]) > 40:
            out.append(card)
    if not out:
        raise ValueError("characters")
    return {"characters": out[:2]}


def v_script(d: Any) -> dict:
    if not isinstance(d, dict):
        raise ValueError("script")
    s = {k: _txt(d.get(k), 300) for k in ("title", "logline", "hook", "ending", "mood")}
    s["beats"] = [_txt(b, 240) for b in (d.get("beats") or []) if _txt(b)][:4]
    if not s["hook"] or not s["beats"]:
        raise ValueError("script")
    return s


def _cam_id(v: Any) -> str:
    v = str(v or "").strip()
    return v if CAM.get(v) else ""


def v_frames(d: Any) -> dict:
    out = []
    for f in (d.get("frames") if isinstance(d, dict) else None) or []:
        if not isinstance(f, dict) or len(_txt(f.get("prompt"))) < 15:
            continue
        try:
            sec = max(1.0, min(6.0, float(f.get("seconds") or 2)))
        except (TypeError, ValueError):
            sec = 2.0
        out.append({"role": _txt(f.get("role"), 40), "seconds": round(sec, 1), "shot": _txt(f.get("shot"), 60),
                    "action": _txt(f.get("action"), 240), "camera": _cam_id(f.get("camera")),
                    "prompt": _txt(f.get("prompt"), 600)})
    if len(out) < 2:
        raise ValueError("frames")
    return {"frames": out[:MAX_FRAMES]}


def v_frame(d: Any) -> dict:
    if not isinstance(d, dict) or len(_txt(d.get("prompt"))) < 15:
        raise ValueError("frame")
    return {"shot": _txt(d.get("shot"), 60), "action": _txt(d.get("action"), 240), "camera": _cam_id(d.get("camera")),
            "prompt": _txt(d.get("prompt"), 600)}


def _fmt(system: str, lang: str, **kw: Any) -> str:
    out = system.replace("{lang}", "English" if L(lang) == "en" else "Russian")
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _context(st: dict) -> str:
    parts = [f"Idea: {st.get('idea') or '-'}", f"Style: {STYLE_EN.get(st.get('style') or '', st.get('style') or '-')}"]
    for c in st.get("characters") or []:
        parts.append("Character: " + "; ".join(f"{k}: {c.get(k)}" for k in CHAR_FIELDS if c.get(k)))
    sc = st.get("script")
    if sc:
        parts.append(f"Script: hook: {sc['hook']}; beats: {' | '.join(sc['beats'])}; ending: {sc['ending']}; "
                     f"mood: {sc['mood']}")
    refs = [r for r in st.get("refs") or [] if r.get("role") in ("character", "style")]
    if refs:
        parts.append("Reference photos: " + ", ".join(f"{r['name']} = {r['role']}" for r in refs))
    return "\n".join(parts)[:3000]


# ════════════════════════════════════════════════════════════ шаблоны без LLM
def fallback_ideas(theme: str, lang: str) -> list[dict]:
    th = theme.strip().rstrip(".")
    if L(lang) == "en":
        base = th or "an everyday moment"
        return [{"title": f"Plot twist: {base}", "detail": "Starts like an ordinary scene, the twist lands at second 2."},
                {"title": f"POV: {base}", "detail": "First-person view, the viewer is inside the story from frame one."},
                {"title": f"Before / after: {base}", "detail": "A sharp contrast cut in the first seconds, then the payoff."}]
    base = th or "обычный момент из жизни"
    return [{"title": f"Неожиданный поворот: {base}", "detail": "Начинается как обычная сцена, поворот — на 2-й секунде."},
            {"title": f"POV: {base}", "detail": "Вид от первого лица — зритель внутри истории с первого кадра."},
            {"title": f"До и после: {base}", "detail": "Резкий контраст в первые секунды, потом развязка."}]


def fallback_character(st: dict, lang: str, change: str = "") -> list[dict]:
    has_ref = any(r.get("role") == "character" for r in st.get("refs") or [])
    ru = L(lang) == "ru"
    look = (tr(lang, "как на фото-референсе", "as in the reference photo") if has_ref else
            tr(lang, "открытое лицо, выразительные глаза, лёгкая улыбка", "open face, expressive eyes, light smile"))
    card = {"name": "Мила" if ru else "Mila", "role": tr(lang, "главная героиня", "main character"),
            "age": "25", "look": look, "hair": tr(lang, "каштановые, до плеч", "chestnut, shoulder length"),
            "body": tr(lang, "стройная, средний рост", "slim, average height"),
            "outfit": tr(lang, "белая футболка оверсайз, джинсы, белые кеды", "oversized white tee, jeans, white sneakers"),
            "details": tr(lang, "тонкая цепочка на шее", "thin necklace"),
            "manner": tr(lang, "живая мимика, говорит прямо в камеру", "lively expressions, talks to camera")}
    if change:
        card["details"] = (card["details"] + "; " + change.strip())[:160]
    subject = ("the person from the reference photo, identical face and likeness" if has_ref else
               "a 25-year-old woman with an open face, expressive eyes and chestnut shoulder-length hair")
    card["sheet_prompt"] = (f"Character turnaround reference sheet of {subject}, wearing an oversized white tee, jeans and "
                            "white sneakers, thin necklace. Front, three-quarter, side and back full-body views plus "
                            "three facial expression close-ups (neutral, laughing, surprised), identical face, hair and "
                            f"outfit in every view, {SHEET_BG}, even soft light, clean layout, no text, no logos."
                            + (f" Change: {change.strip()}." if change and L(lang) == "en" else ""))
    return [card]


def fallback_script(st: dict, lang: str, sec: int) -> dict:
    who = (st.get("characters") or [{}])[0].get("name") or tr(lang, "герой", "the hero")
    idea = st.get("idea") or tr(lang, "история", "the story")
    return {"title": idea[:80], "logline": tr(lang, f"{who}: {idea}", f"{who}: {idea}"),
            "hook": tr(lang, f"{who} смотрит прямо в камеру — и происходит неожиданное", f"{who} looks straight into the camera — and something unexpected happens"),
            "beats": [tr(lang, "Показываем ситуацию и ставку", "Set up the situation and the stakes"),
                      tr(lang, "Нарастание: всё идёт не по плану", "Build-up: things go off plan"),
                      tr(lang, "Кульминация — самый яркий момент", "Climax — the brightest moment")],
            "ending": tr(lang, "Развязка и короткий призыв: «повтори»", "Payoff and a short call to action: “try it”"),
            "mood": tr(lang, "ритмичная музыка, звуки сцены", "rhythmic music, scene sounds")}


def fallback_frames(st: dict, lang: str, sec: int) -> list[dict]:
    sc = st.get("script") or fallback_script(st, lang, sec)
    c = (st.get("characters") or [{}])[0]
    who_en = "the same character" if not c else "the character (same face, hair and outfit as the reference sheet)"
    style = STYLE_EN.get(st.get("style") or "", "cinematic look")
    beats = [("hook", sc["hook"], "close-up", "fast-zoom-in" if CAM.get("fast-zoom-in") else ""),
             *[("dev", b, "medium shot", "tracking" if CAM.get("tracking") else "") for b in sc["beats"][:2]],
             ("end", sc["ending"], "wide shot", "dolly-out" if CAM.get("dolly-out") else "")]
    n = len(beats)
    per = round(sec / n, 1)
    names = {"hook": tr(lang, "хук", "hook"), "dev": tr(lang, "развитие", "development"), "end": tr(lang, "финал", "ending")}
    shots = {"close-up": tr(lang, "крупный план", "close-up"), "medium shot": tr(lang, "средний план", "medium shot"),
             "wide shot": tr(lang, "общий план", "wide shot")}
    out = []
    for role, action, shot, cam in beats:
        out.append({"role": names[role], "seconds": per, "shot": shots[shot], "action": action, "camera": cam,
                    "prompt": f"{shot.capitalize()} of {who_en}: {action}. {style}, vertical 9:16."})
    return out


# ════════════════════════════════════════════════════════════ ответы по шагам
def _chips_nav(step: str, lang: str, next_label: str | None = None) -> list[dict]:
    out = []
    if next_label:
        out.append(chip(next_label, "reel_next", primary=True))
    if step in PREV:
        out.append(chip(tr(lang, "← Назад", "← Back"), "reel_back"))
    out.append(chip(tr(lang, "Выйти из режима", "Leave Reels"), "reel_exit"))
    return out


def show_idea(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    st["step"] = "idea"
    ses["await"] = "reel"
    ideas = st.get("ideas") or []
    if not ideas:
        data = a._llm_json(_fmt(IDEAS_SYSTEM, lang), f"Theme: {st.get('idea') or '-'}", v_ideas, ses, 450,
                           timeout_scale=1.5, task="reel_ideas")
        ideas = (data or {}).get("ideas") or fallback_ideas(st.get("idea") or "", lang)
        st["ideas"] = ideas
    opts = [(f"i{i}", x["title"], x["detail"]) for i, x in enumerate(ideas)]
    style = {"id": "style", "title": tr(lang, "Стиль", "Style"), "selected": st.get("style") or "cinema",
             "options": [{"id": sid, "label": lab, "detail": det} for sid, lab, det in STYLES[L(lang)]]}
    blocks = [stepper("idea", lang),
              choice("idea", tr(lang, "Идея ролика", "Video idea"), opts,
                     tr(lang, "Опишите свою идею ролика", "Describe your own video idea"), lang, extra=style)]
    lines = [head or tr(lang, "Рилс — вирусный ролик по шагам: персонаж → сценарий → раскадровка → промпт. "
                              "С чего начнём? Выберите идею и стиль.",
                        "Reels — a viral video step by step: character → script → storyboard → prompt. "
                        "Pick an idea and a style.")]
    return response(lines, [chip(tr(lang, "Выйти из режима", "Leave Reels"), "reel_exit")], blocks, lang,
                    intent="reel_idea")


def check_refs(files: list[dict], lang: str) -> tuple[list[dict], list[str]]:
    """Проверка референсов перед персонажем: только картинки, не больше 3, остальное — честно сказать."""
    imgs = [f for f in files if f.get("kind") == "image"]
    other = [f for f in files if f.get("kind") != "image"]
    notes = []
    if other:
        notes.append(tr(lang, "Для персонажа нужны фото — " + ", ".join(f"«{f['name']}»" for f in other) +
                        " не подойдёт.", "Character references must be photos — " +
                        ", ".join(f"“{f['name']}”" for f in other) + " won't be used."))
    if len(imgs) > 3:
        notes.append(tr(lang, f"Фото {len(imgs)} — возьму первые 3: модели держат не больше трёх референсов.",
                        f"{len(imgs)} photos — I'll use the first 3: models keep at most three references."))
    return [{"name": f["name"], "kind": "image", "role": ""} for f in imgs[:3]], notes


def show_refs(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    st["step"] = "refs"
    ses["await"] = "reel"
    refs, notes = check_refs(ses.get("files") or [], lang)
    known = {r["name"]: r.get("role") for r in st.get("refs") or []}
    for r in refs:
        r["role"] = known.get(r["name"], "")
    st["refs"] = refs
    if refs:
        names = ", ".join(f"«{r['name']}»" for r in refs)
        opts = [("character", tr(lang, "Это мой персонаж", "This is my character"),
                 tr(lang, "Сохраним лицо и внешность во всех кадрах", "Keep the face and look in every shot")),
                ("style", tr(lang, "Только стиль и настроение", "Style and mood only"),
                 tr(lang, "Персонажа придумаем, с фото возьмём свет и палитру", "We'll invent the character, take light and palette from the photo")),
                ("skip", tr(lang, "Не использовать", "Don't use"), tr(lang, "Персонаж с нуля", "Character from scratch"))]
        title = tr(lang, f"Референсы: {names}", f"References: {names}")
        lines = [head or tr(lang, "Перед персонажем проверю референсы.", "Let me check the references first.")] + notes
    else:
        opts = [("invent", tr(lang, "Придумать персонажа", "Invent a character"),
                 tr(lang, "Соберу карточку по идее и стилю", "I'll build a card from the idea and style")),
                ("upload", tr(lang, "Загружу своё фото", "I'll upload my photo"),
                 tr(lang, "Нажмите скрепку — герой будет с вашим лицом", "Use the paperclip — the hero gets your face")),
                ("none", tr(lang, "Без персонажа", "No character"),
                 tr(lang, "Предметы, природа, продукт", "Objects, nature, a product"))]
        title = tr(lang, "Кто в кадре?", "Who is on screen?")
        lines = [head or tr(lang, "Референсов нет — как поступим с героем?", "No references — what about the hero?")] + notes
    blocks = [stepper("refs", lang), choice("refs", title, opts,
                                            tr(lang, "Опишите героя своими словами", "Describe the hero in your words"), lang)]
    return response(lines, _chips_nav("refs", lang), blocks, lang, intent="reel_refs")


def make_character(a: Any, ses: dict, lang: str, change: str = "", describe: str = "") -> bool:
    """→ degraded? Карточка в st['characters']."""
    st = state(ses)
    user = _context(st)
    if describe:
        user += f"\nUser's description of the hero: {describe}"
    if change:
        prev = "; ".join(f"{k}: {v}" for c in st.get("characters") or [] for k, v in c.items())
        user += f"\nCurrent card: {prev}\nChange request: {change}"
    data = a._llm_json(_fmt(CHAR_SYSTEM, lang), user, v_chars, ses, 900, timeout_scale=2, task="reel_character")
    if data:
        st["characters"] = data["characters"]
        return False
    st["characters"] = fallback_character(st, lang, change or describe)
    return True


def sheet_model(a: Any) -> Any:
    for mid in SHEET_MODELS:
        c = a.d.cards.get(mid)
        if c and a._healthy(mid):
            return c
    return None


def show_character(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None, degraded: bool = False) -> dict:
    st = state(ses)
    st["step"] = "character"
    ses["await"] = "reel"
    chars = st.get("characters") or []
    labels = {"name": tr(lang, "Имя", "Name"), "role": tr(lang, "Роль", "Role"), "age": tr(lang, "Возраст", "Age"),
              "look": tr(lang, "Внешность", "Look"), "hair": tr(lang, "Волосы", "Hair"),
              "body": tr(lang, "Телосложение", "Build"), "outfit": tr(lang, "Одежда", "Outfit"),
              "details": tr(lang, "Детали", "Details"), "manner": tr(lang, "Манера", "Manner")}
    has_ref = [r["name"] for r in st.get("refs") or [] if r.get("role") == "character"]
    blocks = [stepper("character", lang),
              {"type": "reel_character", "labels": labels, "fields": list(CHAR_FIELDS),
               "sheet_label": tr(lang, "Промпт листа персонажа", "Character sheet prompt"),
               "refs": has_ref, "characters": chars}]
    if chars:
        blocks.append(choice("fix_character", tr(lang, "Что поправить в персонаже?", "What should we change?"),
                             [("ok", tr(lang, "Всё отлично — к сценарию", "Looks great — to the script"),
                               tr(lang, "Персонаж зафиксирован для всех кадров", "Locked for every shot")),
                              ("look", tr(lang, "Внешность", "Look"), tr(lang, "Лицо, возраст, типаж", "Face, age, type")),
                              ("outfit", tr(lang, "Одежда и детали", "Outfit and details"),
                               tr(lang, "Цвета, аксессуары, стиль", "Colours, accessories, style"))],
                             tr(lang, "Напишите, что изменить", "Write what to change"), lang))
    lines = [head or tr(lang, "Карточка персонажа готова. Поправьте поля прямо в карточке или выберите ниже.",
                        "The character card is ready. Edit the fields right in the card or pick below.")]
    if degraded:
        lines.append(tr(lang, "Нейросеть-помощник сейчас недоступна — собрала карточку по шаблону.",
                        "The writing AI is unavailable — the card is built from a template."))
    chips = []
    sm = sheet_model(a)
    if chars and sm:
        chips.append(chip(tr(lang, "🖼 Сгенерировать лист персонажа", "🖼 Generate character sheet"), "reel_sheet"))
    chips += _chips_nav("character", lang, tr(lang, "Дальше: сценарий →", "Next: script →") if chars else None)
    return response(lines, chips, blocks, lang, intent="reel_character")


def make_script(a: Any, ses: dict, lang: str, change: str = "") -> bool:
    st = state(ses)
    sec = int(st.get("seconds") or 10)
    user = _context(st) + (f"\nChange request: {change}" if change else "")
    data = a._llm_json(_fmt(SCRIPT_SYSTEM, lang, sec=sec), user, v_script, ses, 700, timeout_scale=2,
                       task="reel_script")
    st["script"] = data or fallback_script(st, lang, sec)
    st["frames"] = []
    return data is None


def show_script(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None, degraded: bool = False) -> dict:
    st = state(ses)
    st["step"] = "script"
    ses["await"] = "reel"
    sc = st.get("script") or {}
    blocks = [stepper("script", lang),
              {"type": "reel_script", "labels": {"logline": tr(lang, "О чём", "Logline"), "hook": tr(lang, "Хук · первые 2 с", "Hook · first 2 s"),
                                                 "beats": tr(lang, "Развитие", "Development"), "ending": tr(lang, "Финал", "Ending"),
                                                 "mood": tr(lang, "Музыка и звук", "Music and sound")},
               "seconds": int(st.get("seconds") or 10), **sc},
              choice("fix_script", tr(lang, "Сценарий подходит?", "Is the script right?"),
                     [("ok", tr(lang, "Да — к раскадровке", "Yes — to the storyboard"),
                       tr(lang, "Разложу на кадры с движением камеры", "I'll split it into shots with camera moves")),
                      ("hook", tr(lang, "Сильнее хук", "Stronger hook"), tr(lang, "Первые 2 секунды цепляют сильнее", "A punchier first 2 seconds")),
                      ("funny", tr(lang, "Смешнее", "Funnier"), tr(lang, "Больше юмора и неожиданности", "More humour and surprise"))],
                     tr(lang, "Напишите, что изменить в сценарии", "Write what to change"), lang)]
    lines = [head or tr(lang, "Общий сценарий. Текст можно поправить прямо в карточке.",
                        "The overall script. You can edit the text right in the card.")]
    if degraded:
        lines.append(tr(lang, "Собрала по шаблону — поправьте под себя.", "Built from a template — adjust it."))
    return response(lines, _chips_nav("script", lang, tr(lang, "Дальше: раскадровка →", "Next: storyboard →")),
                    blocks, lang, intent="reel_script")


def make_frames(a: Any, ses: dict, lang: str, change: str = "") -> bool:
    st = state(ses)
    sec = int(st.get("seconds") or 10)
    n = 4 if sec <= 10 else 5
    user = _context(st) + (f"\nChange request: {change}" if change else "")
    ids = ", ".join(m["id"] for m in CAM.MOVES)
    data = a._llm_json(_fmt(BOARD_SYSTEM, lang, n=n, sec=sec, ids=ids), user, v_frames, ses, 1400,
                       timeout_scale=2.5, task="reel_storyboard")
    st["frames"] = (data or {}).get("frames") or fallback_frames(st, lang, sec)
    st["final"] = ""
    return data is None


def camera_options(lang: str) -> list[dict]:
    names = {gid: (en if L(lang) == "en" else ru) for gid, ru, en in CAM.GROUP_ORDER}
    return [{"id": m["id"], "title": CAM.title(m, lang), "group": names.get(m.get("group") or "", m.get("group") or ""),
             "preview": f"/assets/camera/{m['file']}"} for m in CAM.MOVES]


def show_storyboard(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None, degraded: bool = False) -> dict:
    st = state(ses)
    st["step"] = "storyboard"
    ses["await"] = "reel"
    t0 = 0.0
    frames = []
    for i, f in enumerate(st.get("frames") or [], 1):
        m = CAM.get(f.get("camera"))
        frames.append({**f, "n": i, "start": round(t0, 1), "end": round(t0 + float(f.get("seconds") or 2), 1),
                       "camera_title": CAM.title(m, lang) if m else tr(lang, "без движения", "no move")})
        t0 += float(f.get("seconds") or 2)
    blocks = [stepper("storyboard", lang),
              {"type": "reel_storyboard", "frames": frames, "cameras": camera_options(lang),
               "labels": {"camera": tr(lang, "Камера", "Camera"), "none": tr(lang, "Без движения", "No move"),
                          "prompt": tr(lang, "Промпт кадра", "Shot prompt"),
                          "redo": tr(lang, "Переписать кадр", "Rewrite shot"),
                          "redo_ph": tr(lang, "Что изменить в кадре?", "What to change in this shot?")}}]
    lines = [head or tr(lang, f"Раскадровка: {len(frames)} кадра на {round(t0)} с. Любой кадр можно поправить: текст, "
                              "движение камеры или «Переписать кадр».",
                        f"Storyboard: {len(frames)} shots, {round(t0)} s. Edit any shot: text, camera move, or “Rewrite shot”.")]
    if degraded:
        lines.append(tr(lang, "Кадры собраны по шаблону — поправьте под себя.", "Shots are built from a template — adjust them."))
    chips = [chip(tr(lang, "Дальше: общий промпт →", "Next: final prompt →"), "reel_next", primary=True),
             chip(tr(lang, "Пересобрать раскадровку", "Rebuild storyboard"), "reel_rebuild"),
             chip(tr(lang, "← Назад", "← Back"), "reel_back"), chip(tr(lang, "Выйти из режима", "Leave Reels"), "reel_exit")]
    return response(lines, chips, blocks, lang, intent="reel_storyboard")


def _short_cam(mid: str) -> str:
    m = CAM.get(mid)
    if not m:
        return ""
    return m["prompt"].split(". Movement:")[0].strip().rstrip(".")


def compose_final(st: dict, seconds: int) -> str:
    """Общий промпт для видеомодели: формат, персонажи, стиль, кадры с таймкодами и камерой, звук."""
    frames = st.get("frames") or []
    style = STYLE_EN.get(st.get("style") or "", st.get("style") or "cinematic look")
    parts = [f"Vertical 9:16 short-form video, {seconds} seconds, {len(frames)} shots in one continuous sequence, "
             f"{style}."]
    has_ref = any(r.get("role") == "character" for r in st.get("refs") or [])
    for c in st.get("characters") or []:
        desc = ", ".join(x for x in (c.get("age"), c.get("look"), c.get("hair"), c.get("body"), c.get("outfit"),
                                     c.get("details")) if x)
        lead = "the person from the reference image" if has_ref else "the main character"
        parts.append(f"Character ({lead}): {desc}. Keep the same face, hair and outfit in every shot.")
    t0 = 0.0
    total = sum(float(f.get("seconds") or 2) for f in frames) or 1.0
    k = seconds / total
    for i, f in enumerate(frames, 1):
        dur = float(f.get("seconds") or 2) * k
        cam = _short_cam(f.get("camera") or "")
        parts.append(f"Shot {i} ({round(t0, 1):g}-{round(t0 + dur, 1):g}s): {f.get('prompt')}" + (f" Camera: {cam}." if cam else ""))
        t0 += dur
    sc = st.get("script") or {}
    if sc.get("mood"):
        parts.append(f"Sound: {sc['mood']}.")
    parts.append("No on-screen text, no watermarks.")
    return "\n".join(parts)


def final_models(a: Any, lang: str) -> list[Any]:
    out = []
    for mid in FINAL_MODELS:
        c = a.d.cards.get(mid)
        if c and c.kind == "video" and not c.needs_image and a._healthy(mid):
            out.append(c)
    return out[:4]


def _fit_params(card: Any, seconds: int) -> tuple[dict, int]:
    raw = {"aspect_ratio": "9:16", "duration": seconds}
    params, _adj = P.fit(raw, card)
    params = P.with_defaults(card, params)
    return params, P.seconds(card, params) or seconds


def show_final(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    st["step"] = "final"
    ses["await"] = "reel"
    models = final_models(a, lang)
    if not models:
        return response([tr(lang, "Видеомодели сейчас недоступны — попробуйте позже.", "Video models are unavailable right now.")],
                        _chips_nav("final", lang), [stepper("final", lang)], lang, intent="reel_final")
    card = next((c for c in models if c.id == st.get("model")), models[0])
    st["model"] = card.id
    want = int(round(sum(float(f.get("seconds") or 2) for f in st.get("frames") or []))) or 10
    params, sec = _fit_params(card, want)
    if not st.get("final"):
        st["final"] = compose_final(st, sec)
    files = [f for f in ses.get("files") or [] if f.get("kind") == "image"
             and any(r["name"] == f["name"] and r.get("role") in ("character", "style") for r in st.get("refs") or [])]
    fplan = F.plan(card, files, lang, a.d.inputs_fn)
    price = short_price(a._price(card.id)) or ""
    opts = [{"id": c.id, "title": c.title, "price": short_price(a._price(c.id)) or "", "selected": c.id == card.id}
            for c in models]
    blocks = [stepper("final", lang),
              {"type": "reel_final", "prompt": st["final"], "model_id": card.id, "models": opts,
               "seconds": sec, "aspect": params.get("aspect_ratio") or "9:16",
               "files": F.summary_labels(fplan, lang),
               "labels": {"prompt": tr(lang, "Общий промпт", "Final prompt"), "model": tr(lang, "Модель", "Model"),
                          "files": tr(lang, "Референсы", "References"),
                          "hint": tr(lang, "можно поправить прямо здесь", "you can edit it right here")}}]
    lines = [head or tr(lang, f"Общий промпт собран: {len(st.get('frames') or [])} кадра, {sec} с, вертикально.",
                        f"Final prompt is ready: {len(st.get('frames') or [])} shots, {sec} s, vertical.")]
    if want > sec:
        lines.append(tr(lang, f"Модель снимает до {sec} с за раз — кадры сжаты по времени.",
                        f"The model makes up to {sec} s per run — shots are time-compressed."))
    gate, gate_lines, gchips = a._gate(card, params, ctx, lang)
    lines += gate_lines
    gen = [c for c in gchips if c["action"] in ("generate", "login", "open_topup", "resume")]
    chips = gen + [chip(tr(lang, "← К раскадровке", "← To storyboard"), "reel_back"),
                   chip(tr(lang, "Выйти из режима", "Leave Reels"), "reel_exit")]
    return response(lines, chips, blocks, lang, intent="reel_final", generate_model=card.id,
                    generate_prompt=st["final"], generate_params=params, ready=gate in (None, "ok", "free"),
                    generate_files=[{"kind": it["kind"], "name": it["name"]} for it in fplan if it["used"]],
                    models=[{"id": card.id, "title": card.title, "price": price}])


def show(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    step = state(ses)["step"]
    return {"idea": show_idea, "refs": show_refs, "character": show_character, "script": show_script,
            "storyboard": show_storyboard, "final": show_final}[step](a, ses, ctx, lang, head)


# ════════════════════════════════════════════════════════════ действия
def start(a: Any, ses: dict, ctx: dict, lang: str, theme: str = "") -> dict:
    ses["assist_mode"] = "reel"
    ses["reel"] = None
    st = state(ses)
    st["idea"] = (theme or ses.get("idea") or "").strip()[:400]
    st["seconds"] = 10
    return show_idea(a, ses, ctx, lang)


def _to_character(a: Any, ses: dict, ctx: dict, lang: str, describe: str = "") -> dict:
    st = state(ses)
    if st.get("no_character"):
        st["characters"] = []
        deg = make_script(a, ses, lang)
        return show_script(a, ses, ctx, lang, degraded=deg)
    deg = make_character(a, ses, lang, describe=describe)
    return show_character(a, ses, ctx, lang, degraded=deg)


def answer(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    """Ответ из уточняющего окна: {q, option?, text?} (option — id варианта, text — свой текст)."""
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    q, opt, text = str(v.get("q") or ""), str(v.get("option") or ""), _txt(v.get("text"), 600)
    if q == "idea":
        ideas = st.get("ideas") or []
        pick = next((x for i, x in enumerate(ideas) if f"i{i}" == opt), None)
        if text:
            st["idea"] = text
        elif pick:
            st["idea"] = f"{pick['title']}. {pick['detail']}"
        if v.get("style") or v.get("style_text"):
            st["style"] = str(v.get("style_text") or v.get("style"))[:200]
        if not st.get("style"):
            st["style"] = "cinema"
        if not st["idea"]:
            return show_idea(a, ses, ctx, lang, tr(lang, "Выберите идею или напишите свою.", "Pick an idea or write your own."))
        return show_refs(a, ses, ctx, lang)
    if q == "style":
        st["style"] = (text or opt or "cinema")[:200]
        return show_idea(a, ses, ctx, lang, tr(lang, "Стиль запомнила. Теперь идея.", "Style saved. Now the idea."))
    if q == "refs":
        st["no_character"] = opt == "none"
        if opt == "upload":
            r = show_refs(a, ses, ctx, lang)
            r["chips"] = [chip(tr(lang, "📎 Прикрепить фото", "📎 Attach photo"), "attach", primary=True)] + r["chips"]
            r["text"] = r["reply"] = tr(lang, "Прикрепите фото героя скрепкой — я проверю его и продолжим.",
                                         "Attach the hero's photo with the paperclip — I'll check it and we'll go on.")
            return r
        for r in st.get("refs") or []:      # своими словами при фото — по умолчанию это и есть герой
            r["role"] = opt if opt in ("character", "style") else ("character" if not opt else "")
        return _to_character(a, ses, ctx, lang, describe=text)
    if q == "fix_character":
        if opt == "ok" and not text:
            return next_step(a, ses, ctx, lang)
        change = text or {"look": tr(lang, "другая внешность и типаж", "a different look and type"),
                          "outfit": tr(lang, "другая одежда и детали", "a different outfit and details")}.get(opt, "")
        deg = make_character(a, ses, lang, change=change)
        return show_character(a, ses, ctx, lang, tr(lang, "Поправила персонажа.", "Character updated."), deg)
    if q == "fix_script":
        if opt == "ok" and not text:
            return next_step(a, ses, ctx, lang)
        change = text or {"hook": "make the hook in the first 2 seconds much stronger and more surprising",
                          "funny": "make it funnier, add an unexpected comic twist"}.get(opt, "")
        deg = make_script(a, ses, lang, change=change)
        return show_script(a, ses, ctx, lang, tr(lang, "Переписала сценарий.", "Script rewritten."), deg)
    return show(a, ses, ctx, lang)


def next_step(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    st = state(ses)
    step = st["step"]
    if step in ("idea", "refs"):
        if step == "idea":
            return show_refs(a, ses, ctx, lang)
        return _to_character(a, ses, ctx, lang)
    if step == "character":
        if not st.get("script"):
            deg = make_script(a, ses, lang)
            return show_script(a, ses, ctx, lang, degraded=deg)
        return show_script(a, ses, ctx, lang)
    if step == "script":
        if not st.get("frames"):
            deg = make_frames(a, ses, lang)
            return show_storyboard(a, ses, ctx, lang, degraded=deg)
        return show_storyboard(a, ses, ctx, lang)
    if step == "storyboard":
        return show_final(a, ses, ctx, lang)
    return show_final(a, ses, ctx, lang)


def back(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    st = state(ses)
    prev = PREV.get(st["step"])
    if not prev:
        return show(a, ses, ctx, lang)
    if prev == "character" and st.get("no_character"):
        prev = "refs"
    st["step"] = prev
    return show(a, ses, ctx, lang, tr(lang, "Вернулись на шаг назад.", "Back one step."))


def edit(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    """Правка руками в карточке: {path: 'characters.0.look' | 'script.hook' | 'script.beats.1' |
    'frames.2.prompt' | 'frames.2.camera' | 'frames.2.seconds' | 'final', value}. Ответ перерисовывает шаг на месте."""
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    path = str(v.get("path") or "").split(".")
    val = v.get("value")
    ok = False
    try:
        if path[0] == "characters" and path[2] in CHAR_FIELDS + ("sheet_prompt",):
            st["characters"][int(path[1])][path[2]] = _txt(val, 1200 if path[2] == "sheet_prompt" else 160)
            ok = True
        elif path[0] == "script" and st.get("script"):
            if path[1] == "beats":
                st["script"]["beats"][int(path[2])] = _txt(val, 240)
            elif path[1] in ("title", "logline", "hook", "ending", "mood"):
                st["script"][path[1]] = _txt(val, 300)
            ok = True
        elif path[0] == "frames":
            f = st["frames"][int(path[1])]
            if path[2] == "camera":
                f["camera"] = _cam_id(val)
            elif path[2] == "seconds":
                f["seconds"] = max(1.0, min(6.0, float(val)))
            elif path[2] in ("prompt", "action", "shot"):
                f[path[2]] = _txt(val, 600)
            st["final"] = ""
            ok = True
        elif path[0] == "final":
            st["final"] = str(val or "")[:4000]
            ok = True
        elif path[0] == "model":
            st["model"] = str(val or "")
            st["final"] = ""
            ok = True
    except (IndexError, KeyError, TypeError, ValueError):
        ok = False
    out = show(a, ses, ctx, lang, tr(lang, "Сохранила правку.", "Saved.") if ok else None)
    out["intent"] = "reel_edit"
    return out


def redo_frame(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    try:
        i = int(v.get("n")) - 1
        frame = st["frames"][i]
    except (TypeError, ValueError, IndexError, KeyError):
        return show_storyboard(a, ses, ctx, lang)
    change = _txt(v.get("text"), 400) or "make this shot more dynamic and visually striking"
    ids = ", ".join(m["id"] for m in CAM.MOVES)
    user = _context(st) + f"\nShot {i + 1}: {frame}\nChange request: {change}"
    data = a._llm_json(_fmt(FRAME_SYSTEM, lang, ids=ids), user, v_frame, ses, 500, timeout_scale=1.5,
                       task="reel_frame")
    if data:
        frame.update({k: v2 for k, v2 in data.items() if v2 or k == "camera"})
        head = tr(lang, f"Переписала кадр {i + 1}.", f"Shot {i + 1} rewritten.")
    else:
        frame["prompt"] = (frame["prompt"].rstrip(". ") + f". {change}")[:600]
        frame["action"] = (frame.get("action") or "") + (f" ({change})" if v.get("text") else "")
        head = tr(lang, f"Добавила правку в кадр {i + 1}.", f"Change added to shot {i + 1}.")
    st["final"] = ""
    out = show_storyboard(a, ses, ctx, lang, head)
    out["intent"] = "reel_frame"
    return out


def sheet(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    """Лист персонажа на светло-сером фоне: готовый запуск картинки (кнопка «Сгенерировать» — как обычно)."""
    st = state(ses)
    card = sheet_model(a)
    chars = st.get("characters") or []
    if not card or not chars:
        return show_character(a, ses, ctx, lang)
    prompt = chars[0].get("sheet_prompt") or ""
    if "grey" not in prompt.lower() and "gray" not in prompt.lower():
        prompt = prompt.rstrip(". ") + f", {SHEET_BG}."
    params = P.with_defaults(card, P.fit({"aspect_ratio": "16:9"}, card)[0])
    refs = [f for f in ses.get("files") or [] if f.get("kind") == "image"
            and any(r["name"] == f["name"] and r.get("role") == "character" for r in st.get("refs") or [])]
    fplan = F.plan(card, refs, lang, a.d.inputs_fn)
    gate, gate_lines, gchips = a._gate(card, params, ctx, lang)
    gen = [c for c in gchips if c["action"] in ("generate", "login", "open_topup", "resume")]
    out = show_character(a, ses, ctx, lang, tr(lang, f"Лист персонажа сделает {card.title}: все ракурсы и эмоции на "
                                                     "светло-сером фоне.", f"{card.title} will make the character sheet: "
                                                     "all angles and expressions on a light grey background."))
    for c in gen:
        if c["action"] == "generate":
            c["label"] = tr(lang, "🖼 Сгенерировать лист", "🖼 Generate sheet")
    out["chips"] = (gen + [c for c in out["chips"] if c["action"] != "reel_sheet"])[:6]
    out["text"] = out["reply"] = out["text"] + "\n" + "\n".join(gate_lines)
    out.update(intent="reel_sheet", generate_model=card.id, generate_prompt=prompt, generate_params=params,
               ready=gate in (None, "ok", "free"),
               generate_files=[{"kind": it["kind"], "name": it["name"]} for it in fplan if it["used"]])
    return out


def message(a: Any, ses: dict, ctx: dict, lang: str, msg: str) -> dict:
    """Свободный текст в режиме «Рилс» — ответ на текущее окно или правка текущего шага."""
    st = state(ses)
    step = st["step"]
    if step == "idea":
        return answer(a, ses, ctx, lang, {"q": "idea", "text": msg})
    if step == "refs":
        return answer(a, ses, ctx, lang, {"q": "refs", "option": "", "text": msg})
    if step == "character":
        return answer(a, ses, ctx, lang, {"q": "fix_character", "text": msg})
    if step == "script":
        return answer(a, ses, ctx, lang, {"q": "fix_script", "text": msg})
    if step == "storyboard":
        m = re.match(r"\s*(?:кадр|shot)\s*(\d)\s*[:\-—,]?\s*(.+)", msg, re.I)
        if m:
            return redo_frame(a, ses, ctx, lang, {"n": int(m.group(1)), "text": m.group(2)})
        deg = make_frames(a, ses, lang, change=msg)
        return show_storyboard(a, ses, ctx, lang, tr(lang, "Пересобрала раскадровку с правкой.",
                                                     "Storyboard rebuilt with your change."), deg)
    st["final"] = (st.get("final") or compose_final(st, 10)).rstrip() + "\n" + _txt(msg, 400)
    return show_final(a, ses, ctx, lang, tr(lang, "Добавила в промпт.", "Added to the prompt."))


def exit_mode(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    ses["assist_mode"] = None
    ses["await"] = "type"
    return a._offer_types([tr(lang, "Вышли из режима «Рилс». Черновик сохранён — вернуться можно кнопкой «🔥 Рилс».",
                              "Left Reels. The draft is kept — come back with “🔥 Reels”.")], ctx, ses, lang, "reel_exit")


REEL_RX = re.compile(r"\b(рилс\w*|reels?|вирусн\w* (ролик|видео)|виральн\w*|вирал\w*|viral (video|reel))\b", re.I)
