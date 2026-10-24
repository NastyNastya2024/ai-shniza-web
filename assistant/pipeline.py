"""Флоу помощника: Промпт → Картинка → Раскадровка → Видео → Озвучка.

Главное меню — пять этапов (+ Музыка). В любой этап можно войти сразу. После каждого этапа помощник предлагает
следующий шаг и «← Главное меню».

Артефакты (ses["arts"]) — всё, что получилось на этапах: промпт видео, промпт речи, JSON оформления, итог диалога,
картинки, раскадровка, ролик, озвучка. Хранятся ТОЛЬКО в сессии помощника (Redis, ASSIST_SESSION_TTL_SEC, по умолчанию
24 ч): «Новый чат» сбрасывает сессию — и артефакты. Файлы картинок, видео и озвучки при этом остаются в «Моих работах».
Следующие этапы сами берут нужные артефакты (промпт, герой как первый кадр, раскадровка, стиль).

Генерация запускается обычной кнопкой «Сгенерировать» в приложении. Когда результат готов, приложение сообщает
о нём действием pipe_result — артефакт сохраняется, помощник предлагает следующий шаг.

Состояние: ses["pipe"] = {on, stage, sub, await, expect, chat}. Модуль без Flask: всё внешнее — через помощника `a`.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import storyboard as SB
from .render import chip, response, short_price
from .texts import b

MAX_ARTS = 40
STAGES = ("prompt", "image", "board", "video", "voice")
STAGE_TITLE = {"ru": {"prompt": "Промпт", "image": "Картинка", "board": "Раскадровка", "video": "Видео", "voice": "Озвучка"},
               "en": {"prompt": "Prompt", "image": "Image", "board": "Storyboard", "video": "Video", "voice": "Voiceover"}}
STAGE_ICON = {"prompt": "✍️", "image": "🖼", "board": "🎞", "video": "🎬", "voice": "🎙"}
STYLE_MODELS = ("gpt-5-4", "gpt-5-6-sol")          # видят картинку: разбор стиля в JSON
VOICE_MODELS = (("elevenlabs-v3", "ElevenLabs v3"), ("gemini-3-1-flash-tts", "Gemini 3.1 Flash TTS"))
IMAGE_SUBS = ("hero", "scene", "bg", "other")
SUB_TITLE = {"ru": {"video": "Промпт видео", "speech": "Промпт для речи", "style": "JSON оформления", "dialog": "Диалог",
                    "hero": "Портрет героя", "scene": "Сцена кадра", "bg": "Задний план / окружение", "other": "Другое"},
             "en": {"video": "Video prompt", "speech": "Speech prompt", "style": "Style JSON", "dialog": "Dialogue",
                    "hero": "Hero portrait", "scene": "Scene shot", "bg": "Background / setting", "other": "Other"}}
IMAGE_PREFIX = {"hero": "Character portrait, head and shoulders, neutral background, the same face must be reusable in later shots",
                "scene": "Key scene still, cinematic composition, the hero in action",
                "bg": "Environment plate without people, wide establishing view",
                "other": "Single image"}
STYLE_INSTR = (
    "Analyze ONLY the visual style of the attached image — not its subject or story. Return strictly one JSON object, "
    "no prose, with keys: style_name (string), palette (array of 5 hex colors), light {type, direction, contrast, "
    "color_temperature}, camera {lens, aperture, angle, depth_of_field}, composition (string), texture (string), "
    "mood (string), avoid (array of strings). Write all string values in Russian except hex codes and lens values."
)


def L(lang: str) -> str:
    return "en" if lang == "en" else "ru"


def tr(lang: str, ru: str, en: str) -> str:
    return en if L(lang) == "en" else ru


def state(ses: dict) -> dict:
    st = ses.get("pipe")
    if not isinstance(st, dict):
        st = {}
    for k, v in (("on", False), ("stage", None), ("sub", None), ("await", None), ("expect", None), ("chat", [])):
        st.setdefault(k, v)
    ses["pipe"] = st
    if not isinstance(ses.get("arts"), list):
        ses["arts"] = []
    return st


def arts(ses: dict) -> list[dict]:
    if not isinstance(ses.get("arts"), list):
        ses["arts"] = []
    return ses["arts"]


def last(ses: dict, *types: str) -> dict | None:
    for a in reversed(arts(ses)):
        if a.get("type") in types:
            return a
    return None


def _txt(v: Any, n: int = 4000) -> str:
    return re.sub(r"[ \t]+", " ", str(v or "")).strip()[:n]


def save(ses: dict, stage: str, typ: str, title: str, **data: Any) -> dict:
    lst = arts(ses)
    a = {"id": (lst[-1]["id"] + 1) if lst else 1, "stage": stage, "type": typ, "title": title, "ts": int(time.time())}
    for k, v in data.items():
        if v not in (None, "", [], {}):
            a[k] = v
    lst.append(a)
    del lst[:-MAX_ARTS]
    return a


# ════════════════════════════════════════════════════════════ тексты и кнопки
def session_note(lang: str) -> str:
    return tr(lang, "Всё, что получится, я сохраню артефактами — но только в этом чате и на время сессии (до 24 часов). "
                    "«Новый чат» начнётся с чистого листа; картинки, видео и озвучка останутся в «Моих работах».",
              "I’ll keep everything you make as artifacts — only in this chat and for this session (up to 24 hours). "
              "A new chat starts from scratch; images, videos and voiceovers stay in “My works”.")


def first_note(ses: dict, lang: str) -> list[str]:
    """Пометка «артефакты — только в этом чате» под первым меню сессии (один раз; в «Главном меню» — всегда)."""
    st = state(ses)
    st["on"] = True
    if st.get("told") or arts(ses):
        return []
    st["told"] = True
    return [session_note(lang)]


def menu_chip(lang: str) -> dict:
    return chip(tr(lang, "← Главное меню", "← Main menu"), "pipe_menu")


def stage_chips(lang: str, has_image: bool = False) -> list[dict]:
    """Первый ряд помощника: этапы флоу + Музыка (+ Правка фото, если прикреплено фото)."""
    names = STAGE_TITLE[L(lang)]
    out = [chip(STAGE_ICON[s] + " " + names[s], "pipe_stage", s) for s in STAGES]
    if has_image:
        out.append(chip(b("type_edit", lang), "choose_type", "edit"))
    out.append(chip(b("type_music", lang), "choose_type", "music"))
    return out


def arts_block(ses: dict, lang: str, title: str | None = None) -> dict:
    names = STAGE_TITLE[L(lang)]
    groups = []
    for s in STAGES:
        items = [{k: a.get(k) for k in ("id", "type", "title", "sub", "url", "kind") if a.get(k)}
                 for a in arts(ses) if a.get("stage") == s]
        groups.append({"stage": s, "title": names[s], "items": items})
    return {"type": "pipe_arts", "title": title or tr(lang, "Артефакты этой сессии", "Artifacts of this session"),
            "groups": groups, "note": tr(lang, "Только в этом чате, до 24 часов. «Новый чат» очищает список.",
                                         "This chat only, up to 24 hours. A new chat clears the list.")}


def saved_line(a: dict, lang: str) -> str:
    return tr(lang, f"✓ Сохранила в артефакты сессии: {a['title']}.", f"✓ Saved to this session’s artifacts: {a['title']}.")


def offers(stage: str, lang: str) -> list[dict]:
    """Кнопки «дальше» после этапа — как на схеме флоу."""
    if stage == "prompt":
        out = [chip(tr(lang, "🖼 Сгенерировать изображения героев", "🖼 Generate hero images"), "pipe_sub", "hero", primary=True),
               chip(tr(lang, "🎬 Перейти сразу в видео", "🎬 Go straight to video"), "pipe_stage", "video")]
    elif stage == "image":
        out = [chip(tr(lang, "🎞 Сгенерировать раскадровку", "🎞 Generate a storyboard"), "pipe_stage", "board", primary=True),
               chip(tr(lang, "🖼 Ещё картинку", "🖼 Another image"), "pipe_stage", "image"),
               chip(tr(lang, "🎬 Перейти сразу в видео", "🎬 Go straight to video"), "pipe_stage", "video")]
    elif stage == "board":
        out = [chip(tr(lang, "🎬 Сгенерировать видео по раскадровке", "🎬 Generate video from the storyboard"), "pipe_stage", "video", primary=True),
               chip(tr(lang, "🎬 Перейти сразу в видео", "🎬 Go straight to video"), "pipe_video_plain")]
    elif stage == "video":
        out = [chip(tr(lang, "🎙 Добавить озвучку", "🎙 Add a voiceover"), "pipe_stage", "voice", primary=True),
               chip(tr(lang, "🎬 Ещё вариант видео", "🎬 Another video"), "pipe_stage", "video")]
    elif stage == "voice":
        out = [chip(tr(lang, "📋 Итог проекта", "📋 Project summary"), "pipe_summary", primary=True)]
    else:
        out = []
    return out + [menu_chip(lang)]


# ════════════════════════════════════════════════════════════ главное меню и этапы
def menu(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    st.update(on=True, stage=None, sub=None, expect=None)
    st["await"] = None
    ses["await"] = "type"
    lines = [head] if head else []
    lines.append(tr(lang, "Что делаем? Можно идти по шагам — от промпта до озвучки — или начать с любого этапа.",
                    "What are we making? Go step by step — from prompt to voiceover — or start at any stage."))
    blocks = []
    if arts(ses):
        n = len(arts(ses))
        word = "артефакт" if n % 10 == 1 and n % 100 != 11 else ("артефакта" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "артефактов")
        lines.append(tr(lang, f"В этой сессии уже {n} {word} — следующие этапы возьмут их сами.",
                        f"This session already has {n} artifact{'s' if n != 1 else ''} — the next stages will use them."))
        blocks.append(arts_block(ses, lang))
    else:
        lines.append(session_note(lang))
    return response(lines, stage_chips(lang, bool(ctx.get("has_image"))), blocks, lang, intent="pipe_menu")


def stage(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    st = state(ses)
    s = str(value or "")
    if s not in STAGES:
        return menu(a, ses, ctx, lang)
    st.update(on=True, stage=s, sub=None, expect=None)
    st["await"] = None
    names = SUB_TITLE[L(lang)]
    if s == "prompt":
        return response([tr(lang, "Какой промпт нужен?", "What kind of prompt?")],
                        [chip("🎬 " + names["video"], "pipe_sub", "video", primary=True), chip("🎙 " + names["speech"], "pipe_sub", "speech"),
                         chip("{ } " + names["style"], "pipe_sub", "style"), chip("💬 " + names["dialog"], "pipe_sub", "dialog"),
                         menu_chip(lang)], [], lang, intent="pipe_prompt")
    if s == "image":
        return response([tr(lang, "Что рисуем? Портрет героя лучше сделать первым — по нему нейросети держат лицо и образ во всех кадрах.",
                            "What are we drawing? Do the hero portrait first — models keep the face and look from it in every shot.")],
                        [chip(names["hero"], "pipe_sub", "hero", primary=True), chip(names["scene"], "pipe_sub", "scene"),
                         chip(names["bg"], "pipe_sub", "bg"), chip(names["other"], "pipe_sub", "other"), menu_chip(lang)],
                        [], lang, intent="pipe_image")
    if s == "board":
        return board(a, ses, ctx, lang)
    if s == "video":
        return video(a, ses, ctx, lang)
    return voice(a, ses, ctx, lang)


def sub(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    st = state(ses)
    v = str(value or "")
    names = SUB_TITLE[L(lang)]
    if v in IMAGE_SUBS:
        st.update(on=True, stage="image", sub=v)
        return image(a, ses, ctx, lang, v)
    st.update(on=True, stage="prompt", sub=v)
    if v == "video":
        st["await"] = "video_idea"
        return response([tr(lang, "Опишите идею своими словами — одной-двумя фразами. Я допишу свет, камеру, движение и длительность.",
                            "Describe the idea in a sentence or two. I’ll add light, camera, motion and duration.")],
                        [menu_chip(lang)], [], lang, intent="pipe_video_prompt")
    if v == "speech":
        st["await"] = "speech_idea"
        return response([tr(lang, "Кто говорит и что? Можно просто идею — я напишу текст, подберу голос и расставлю паузы и интонацию.",
                            "Who speaks and what? An idea is enough — I’ll write the text, pick a voice and mark pauses and tone.")],
                        [menu_chip(lang)], [], lang, intent="pipe_speech_prompt")
    if v == "style":
        return style(a, ses, ctx, lang)
    if v == "dialog":
        st["await"] = "dialog"
        st["chat"] = []
        return response([tr(lang, "Давайте просто обсудим идею. Пишите как удобно — я задам вопросы и предложу варианты. "
                                  "Когда договоримся, сохраню итог промптом.",
                            "Let’s just talk the idea through. Write freely — I’ll ask questions and suggest options. "
                            "When we agree, I’ll save the result as a prompt.")],
                        [menu_chip(lang)], [], lang, intent="pipe_dialog")
    return stage(a, ses, ctx, lang, "prompt")


# ════════════════════════════════════════════════════════════ 1. Промпт
VIDEO_SYSTEM = (
    "You are a film director writing prompts for AI video models. From the user's idea write ONE English video prompt: "
    "subject and action, setting, light, camera move and lens, mood, duration, aspect ratio. 40-90 words. "
    "Return JSON only: {\"prompt\": English prompt, \"summary\": one line in {lang} listing light · camera · duration · aspect}."
)
SPEECH_SYSTEM = (
    "You write voiceover scripts for TTS (ElevenLabs v3, Gemini TTS). From the user's request return JSON only: "
    "{\"voice\": short voice description in {lang} (gender, age, timbre, tempo), \"text\": the spoken text in the user's "
    "language, 2-5 sentences, with inline tags in square brackets for tone and pauses like [тихо] [пауза 0.5 с] "
    "[улыбка в голосе] (in {lang}), \"seconds\": estimated duration}."
)
DIALOG_SYSTEM = (
    "You are a friendly creative director helping a person shape a short video idea. Reply in {lang}, 1-3 short "
    "sentences: react, ask ONE clarifying question or suggest one concrete option. Also keep a running English video "
    "prompt that sums up what you have agreed so far. Return JSON only: {\"reply\": text, \"prompt\": English prompt}."
)


def _fmt(system: str, lang: str) -> str:
    return system.replace("{lang}", "English" if L(lang) == "en" else "Russian")


def v_video(d: Any) -> dict:
    p = _txt(d.get("prompt") if isinstance(d, dict) else "", 1500)
    if len(p) < 30:
        raise ValueError("prompt")
    return {"prompt": p, "summary": _txt(d.get("summary"), 200)}


def v_speech(d: Any) -> dict:
    t = _txt(d.get("text") if isinstance(d, dict) else "", 3000)
    if len(t) < 10:
        raise ValueError("text")
    try:
        sec = max(2, min(120, int(float(d.get("seconds") or 0)))) or None
    except (TypeError, ValueError):
        sec = None
    return {"text": t, "voice": _txt(d.get("voice"), 160), "seconds": sec}


def v_dialog(d: Any) -> dict:
    r = _txt(d.get("reply") if isinstance(d, dict) else "", 800)
    if len(r) < 3:
        raise ValueError("reply")
    return {"reply": r, "prompt": _txt(d.get("prompt"), 1500)}


def style_line(ses: dict) -> str:
    """Короткая строка стиля из JSON оформления — добавляется к промптам следующих этапов."""
    a = last(ses, "style")
    if not a or not isinstance(a.get("json"), dict):
        return ""
    j = a["json"]
    light, cam = j.get("light") or {}, j.get("camera") or {}
    bits = [j.get("style_name"), "palette " + " ".join(j.get("palette") or []) if j.get("palette") else "",
            light.get("type") if isinstance(light, dict) else "", cam.get("lens") if isinstance(cam, dict) else "",
            j.get("texture"), j.get("mood")]
    s = ", ".join(str(x) for x in bits if x)
    avoid = ", ".join(str(x) for x in (j.get("avoid") or [])[:4])
    return f"Visual style: {s}." + (f" Avoid: {avoid}." if avoid else "")


def make_video_prompt(a: Any, ses: dict, lang: str, idea: str) -> tuple[str, str, bool]:
    data = a._llm_json(_fmt(VIDEO_SYSTEM, lang), f"Idea: {idea}\n{style_line(ses)}", v_video, ses, 600, task="pipe_video")
    if data:
        return data["prompt"], data["summary"], False
    p = (f"Cinematic shot: {idea}. Natural motivated light, smooth slow camera move, 35mm lens, shallow depth of field, "
         f"calm atmosphere. 10 s, 16:9.")
    sl = style_line(ses)
    return (p + (" " + sl if sl else "")), tr(lang, "свет мягкий · камера плавная · 10 с · 16:9", "soft light · smooth camera · 10 s · 16:9"), True


def video_prompt(a: Any, ses: dict, ctx: dict, lang: str, idea: str) -> dict:
    st = state(ses)
    st["await"] = None
    p, summary, deg = make_video_prompt(a, ses, lang, idea)
    art = save(ses, "prompt", "videoPrompt", SUB_TITLE[L(lang)]["video"], text=p, sub=_txt(idea, 60), idea=_txt(idea, 500))
    ses["idea"] = idea
    lines = [tr(lang, "Готово. Промпт на английском — так нейросети понимают его точнее.",
                "Done. The prompt is in English — models follow it more precisely.")]
    if deg:
        lines.append(tr(lang, "Помощник-сценарист сейчас недоступен — собрала промпт по шаблону, поправьте его под себя.",
                        "The writing model is unavailable — I used a template, adjust it as you like."))
    lines.append(saved_line(art, lang))
    blocks = [{"type": "prompt", "label": True, "title": SUB_TITLE[L(lang)]["video"], "text": p, "note": summary}]
    return response(lines, offers("prompt", lang), blocks, lang, intent="pipe_video_prompt_done", degraded=deg)


def speech_prompt(a: Any, ses: dict, ctx: dict, lang: str, idea: str) -> dict:
    st = state(ses)
    st["await"] = None
    data = a._llm_json(_fmt(SPEECH_SYSTEM, lang), f"Request: {idea}", v_speech, ses, 700, task="pipe_speech")
    deg = not data
    if not data:
        data = {"text": idea, "voice": tr(lang, "нейтральный, спокойный темп", "neutral, calm pace"), "seconds": None}
    art = save(ses, "prompt", "speechPrompt", SUB_TITLE[L(lang)]["speech"], text=data["text"], voice=data["voice"],
               sub=(data["voice"] or "")[:60])
    lines = [tr(lang, "Текст для озвучки готов. Теги в скобках — интонация и паузы, их понимают ElevenLabs v3 и Gemini TTS.",
                "The voiceover text is ready. Bracket tags set tone and pauses — ElevenLabs v3 and Gemini TTS read them.")]
    if deg:
        lines.append(tr(lang, "Сценарист сейчас недоступен — оставила ваш текст как есть.", "The writing model is unavailable — kept your text as is."))
    lines.append(saved_line(art, lang))
    note = tr(lang, "Голос: ", "Voice: ") + (data["voice"] or "—") + (f" · ≈ {data['seconds']} с" if data.get("seconds") else "")
    blocks = [{"type": "prompt", "label": True, "title": SUB_TITLE[L(lang)]["speech"], "text": data["text"], "note": note}]
    return response(lines, offers("prompt", lang), blocks, lang, intent="pipe_speech_prompt_done", degraded=deg)


def _style_model(a: Any) -> Any:
    for mid in STYLE_MODELS:
        c = a.d.cards.get(mid)
        if c and a._healthy(mid):
            return c
    return None


def style(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    """JSON оформления: объясняем метод, просим картинку, разбор — моделью, которая видит изображения (GPT-5.4)."""
    st = state(ses)
    st.update(stage="prompt", sub="style")
    st["await"] = "style_image"
    imgs = [f["name"] for f in ses.get("files") or [] if f.get("kind") == "image"]
    method = {"type": "pipe_method", "steps": [
        {"t": tr(lang, "Ваша картинка", "Your image"), "s": tr(lang, "любой сюжет", "any subject")},
        {"t": tr(lang, "JSON стиля", "Style JSON"), "s": tr(lang, "палитра, свет, оптика, композиция, фактура", "palette, light, lens, composition, texture")},
        {"t": tr(lang, "Новый сюжет", "New subject"), "s": tr(lang, "в том же стиле", "in the same style")}]}
    lines = [tr(lang, "JSON оформления — это стиль картинки, записанный параметрами. Сюжет я не копирую: только то, как картинка "
                      "сделана — палитру, свет, оптику, композицию, фактуру и настроение. Потом этот JSON можно приложить к "
                      "любому другому сюжету — и новая картинка или видео получатся в том же стиле.",
                "Style JSON is the look of an image written as parameters. I don’t copy the subject — only how the image is made: "
                "palette, light, lens, composition, texture and mood. Then you can apply this JSON to any other subject.")]
    card = _style_model(a)
    if not imgs:
        lines.append(tr(lang, "Прикрепите картинку-образец скрепкой и напишите «готово» — разберу стиль.",
                        "Attach a reference image with the paperclip and type “done” — I’ll extract the style."))
        return response(lines, [chip(tr(lang, "📎 Прикрепить картинку", "📎 Attach an image"), "attach"), menu_chip(lang)],
                        [method], lang, intent="pipe_style")
    if not card:
        lines.append(tr(lang, "Сейчас нет доступной модели, которая видит картинки. Попробуйте через пару минут.",
                        "No image-reading model is available right now. Try again in a couple of minutes."))
        return response(lines, [menu_chip(lang)], [method], lang, intent="pipe_style")
    st["expect"] = "style"
    st["await"] = None
    lines.append(tr(lang, f"Разберу стиль «{imgs[0]}» — жмите «Разобрать стиль». Это запрос к {card.title}.",
                    f"I’ll extract the style of “{imgs[0]}” — tap “Extract style”. It runs on {card.title}."))
    gen = chip(tr(lang, "{ } Разобрать стиль", "{ } Extract style"), "generate", card.id, primary=True)
    return response(lines, [gen, menu_chip(lang)], [method], lang, intent="pipe_style_ready", generate_model=card.id,
                    generate_prompt=STYLE_INSTR, generate_params={}, ready=True,
                    generate_files=[{"kind": "image", "name": imgs[0]}], keep_assistant=True)


def parse_style(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(d, dict) or not (d.get("palette") or d.get("light") or d.get("style_name")):
        return None
    keep = ("style_name", "palette", "light", "camera", "composition", "texture", "mood", "avoid")
    out = {k: d[k] for k in keep if k in d}
    if isinstance(out.get("palette"), list):
        out["palette"] = [str(x)[:9] for x in out["palette"] if re.fullmatch(r"#?[0-9a-fA-F]{3,8}", str(x).strip())][:8]
    return out


def dialog(a: Any, ses: dict, ctx: dict, lang: str, msg: str) -> dict:
    st = state(ses)
    chat = st.setdefault("chat", [])
    chat.append({"r": "user", "t": _txt(msg, 600)})
    hist = "\n".join(("User: " if c["r"] == "user" else "You: ") + c["t"] for c in chat[-8:])
    data = a._llm_json(_fmt(DIALOG_SYSTEM, lang), hist, v_dialog, ses, 500, task="pipe_dialog")
    deg = not data
    if not data:
        data = {"reply": tr(lang, "Интересно! Что важнее в ролике — настроение, герой или место? От этого зависят свет и камера.",
                            "Nice! What matters most — mood, hero or place? That decides the light and the camera."),
                "prompt": " ".join(c["t"] for c in chat if c["r"] == "user")[-600:]}
    chat.append({"r": "me", "t": data["reply"]})
    st["draft"] = data["prompt"]
    del chat[:-16]
    st["await"] = "dialog"
    return response([data["reply"]], [chip(tr(lang, "💾 Сохранить итог как промпт", "💾 Save the result as a prompt"), "pipe_dialog_save", primary=True),
                                      menu_chip(lang)], [], lang, intent="pipe_dialog", degraded=deg)


def dialog_save(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    st = state(ses)
    p = _txt(st.get("draft") or " ".join(c["t"] for c in st.get("chat") or [] if c["r"] == "user"), 1500)
    if not p:
        return sub(a, ses, ctx, lang, "dialog")
    st["await"] = None
    art = save(ses, "prompt", "videoPrompt", tr(lang, "Итог диалога", "Dialogue result"), text=p, sub=tr(lang, "промпт по обсуждению", "prompt from the chat"))
    return response([tr(lang, "Записала итог разговора промптом.", "Saved the result of our chat as a prompt."), saved_line(art, lang)],
                    offers("prompt", lang), [{"type": "prompt", "label": True, "title": art["title"], "text": p, "note": ""}], lang,
                    intent="pipe_dialog_saved")


# ════════════════════════════════════════════════════════════ 2. Картинка / 4. Видео — передаём в подбор моделей
def _subject(ses: dict) -> str:
    a = last(ses, "videoPrompt")
    return (a or {}).get("text") or ""


def _handoff(a: Any, ses: dict, ctx: dict, lang: str, kind: str, prompt: str, expect: str, head: str,
             has_image: bool = False, attach: list[dict] | None = None) -> dict:
    """Промпт собран из артефактов → обычный подбор модели помощника → «Сгенерировать». Результат вернётся pipe_result."""
    st = state(ses)
    st["expect"] = expect
    st["await"] = None
    a._new_task(kind, prompt[:4000], [], re.sub(r"[^\w\s-]", "", prompt)[:40], ses)
    # промпт уже собран — после выбора модели сразу настройки, без опросника и вариантов
    ses.update(assist_mode="direct", prompt=prompt[:4000], prompt_base=prompt[:4000], brief_done=True)
    pick = a._recommend(kind, [], has_image)
    out = a._show_models(pick, ses, lang, "pipe_" + expect, head=head)
    out["chips"] = [c for c in out.get("chips") or [] if c.get("action") != "back"] + [menu_chip(lang)]
    if attach:
        out["attach_urls"] = attach
    art_block = {"type": "prompt", "label": True, "title": tr(lang, "Промпт из артефактов", "Prompt from artifacts"), "text": prompt,
                 "note": tr(lang, "Подставится в выбранную нейросеть — его можно поправить на следующем шаге.",
                            "It goes into the model you pick — you can still edit it on the next step.")}
    # «Промпт под Ваш промпт» из подбора моделей дублирует этот блок — в чате оставляем один
    out["blocks"] = [art_block] + [b for b in (out.get("blocks") or []) if b.get("type") != "prompt"]
    return out


def image(a: Any, ses: dict, ctx: dict, lang: str, kind_sub: str, desc: str = "") -> dict:
    st = state(ses)
    subj = desc or _subject(ses)
    if not subj:
        st["await"] = "image_desc"
        st["sub"] = kind_sub
        ask = {"hero": tr(lang, "Опишите героя: кто это, внешность, одежда, характер.", "Describe the hero: who, looks, outfit, character."),
               "scene": tr(lang, "Опишите сцену: кто, где и что происходит.", "Describe the scene: who, where, what happens."),
               "bg": tr(lang, "Опишите место: где это и какое время суток.", "Describe the place and time of day."),
               "other": tr(lang, "Что нарисовать?", "What should I draw?")}[kind_sub]
        return response([ask], [menu_chip(lang)], [], lang, intent="pipe_image_ask")
    used = []
    if not desc and last(ses, "videoPrompt"):
        used.append(tr(lang, "промпт", "prompt"))
    sl = style_line(ses)
    if sl:
        used.append(tr(lang, "стиль", "style"))
    hero = last(ses, "hero") if kind_sub == "scene" else None
    prompt = f"{IMAGE_PREFIX[kind_sub]}. {subj}" + (f" {sl}" if sl else "")
    head = (tr(lang, f"{SUB_TITLE['ru'][kind_sub]}: собрала промпт", f"{SUB_TITLE['en'][kind_sub]}: prompt is ready")
            + (tr(lang, " из артефактов (" + ", ".join(used) + ")", " from artifacts (" + ", ".join(used) + ")") if used else "")
            + tr(lang, ". Выберите нейросеть:", ". Pick a model:"))
    attach = [{"src": hero["url"], "name": "hero.png"}] if hero and hero.get("url") else None
    return _handoff(a, ses, ctx, lang, "image", prompt, "hero" if kind_sub == "hero" else "image:" + kind_sub, head,
                    has_image=bool(attach), attach=attach)


def video(a: Any, ses: dict, ctx: dict, lang: str, plain: bool = False) -> dict:
    st = state(ses)
    st.update(on=True, stage="video")
    sb = ses.get("sb") if isinstance(ses.get("sb"), dict) else None
    used, base = [], ""
    if not plain and last(ses, "board") and sb and sb.get("frames"):
        tl = SB.timeline(sb["frames"])
        shots = " ".join(f"Shot {i + 1} ({tl[i][0]:g}-{tl[i][1]:g}s): {SB.frame_visual(f).rstrip('. ')}." for i, f in enumerate(sb["frames"]))
        base = f"{int(round(tl[-1][1]))}-second video in {len(sb['frames'])} shots. {shots}"
        used.append(tr(lang, "раскадровка", "storyboard"))
    elif _subject(ses):
        base = _subject(ses)
        used.append(tr(lang, "промпт", "prompt"))
    hero = last(ses, "hero", "image")
    attach = None
    if hero and hero.get("url"):
        attach = [{"src": hero["url"], "name": "first-frame.png"}]
        used.append(tr(lang, "герой — первый кадр", "hero as the first frame"))
    if not base and not attach:
        st["await"] = "video_idea_direct"
        return response([tr(lang, "Артефактов для видео пока нет — опишите ролик, и я соберу промпт сама.",
                             "No artifacts for the video yet — describe it and I’ll build the prompt.")], [menu_chip(lang)], [],
                        lang, intent="pipe_video_ask")
    sl = style_line(ses)
    if sl:
        used.append(tr(lang, "стиль", "style"))
    prompt = (base or tr(lang, "Animate the attached first frame with a slow cinematic camera move.", "Animate the attached first frame with a slow cinematic camera move.")) + (f" {sl}" if sl else "")
    head = tr(lang, "Соберу ролик из артефактов: " + ", ".join(used) + ". Выберите нейросеть:",
              "Building the video from artifacts: " + ", ".join(used) + ". Pick a model:")
    return _handoff(a, ses, ctx, lang, "video", prompt, "video", head, has_image=bool(attach), attach=attach)


# ════════════════════════════════════════════════════════════ 3. Раскадровка
def board(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    st = state(ses)
    st.update(on=True, stage="board", expect="board")
    st["await"] = None
    sb = ses.get("sb") if isinstance(ses.get("sb"), dict) else None
    subj = _subject(ses)
    hero = last(ses, "hero")
    fresh = [x for x in arts(ses) if x.get("type") in ("videoPrompt", "hero")]
    if sb and sb.get("frames") and not (fresh and fresh[-1].get("ts", 0) > int(sb.get("pipe_ts") or 0)):
        out = SB.start(a, ses, ctx, lang)          # кадры уже есть — продолжаем с них
    elif subj or hero:
        text = (subj or "") + (" " + tr(lang, "Главный герой — как на портрете из артефактов.", "The main hero looks like the portrait in the artifacts.") if hero else "")
        out = SB.start(a, ses, ctx, lang, "new", text=tr(lang, "Сделай раскадровку: ", "Make a storyboard: ") + text.strip())
        out["text"] = tr(lang, "Раскадровка из артефактов сессии. ", "Storyboard from this session’s artifacts. ") + out["text"]
        out["reply"] = tr(lang, "Раскадровка из артефактов сессии. ", "Storyboard from this session’s artifacts. ") + out["reply"]
        if isinstance(ses.get("sb"), dict):
            ses["sb"]["pipe_ts"] = int(time.time())
    else:
        out = SB.start(a, ses, ctx, lang, "new")
    return decorate(out, ses, lang)


def decorate(out: dict, ses: dict, lang: str) -> dict:
    """Кнопки флоу под ответами режима «Раскадровка»: сразу в видео и главное меню."""
    if not state(ses)["on"] or not isinstance(out, dict):
        return out
    chips = [c for c in out.get("chips") or [] if c.get("action") not in ("pipe_menu", "pipe_video_plain")]
    if out.get("intent") in ("sb_frames", "sb_edit", "sb_frame"):
        chips.append(chip(tr(lang, "🎬 Перейти сразу в видео", "🎬 Go straight to video"), "pipe_video_plain"))
    chips.append(menu_chip(lang))
    out["chips"] = chips
    return out


# ════════════════════════════════════════════════════════════ 5. Озвучка
def _voice_card(a: Any, mid: str) -> bool:
    try:
        return bool(a._healthy(mid))
    except Exception:
        return True


def voice(a: Any, ses: dict, ctx: dict, lang: str, text: str = "", model: str = "") -> dict:
    st = state(ses)
    st.update(on=True, stage="voice")
    sp = last(ses, "speechPrompt")
    body = text or (sp or {}).get("text") or ""
    if not body:
        st["await"] = "voice_text"
        return response([tr(lang, "Какой текст озвучить? Можно вставить готовый — или сначала сделать «Промпт → Промпт для речи».",
                            "What text should I voice? Paste it — or make “Prompt → Speech prompt” first.")],
                        [chip(tr(lang, "🎙 Сделать промпт речи", "🎙 Make a speech prompt"), "pipe_sub", "speech"), menu_chip(lang)],
                        [], lang, intent="pipe_voice_ask")
    st["await"] = None
    st["voice_text"] = body
    models = [(m, t) for m, t in VOICE_MODELS if _voice_card(a, m)] or list(VOICE_MODELS)
    mid = model if any(m == model for m, _ in models) else models[0][0]
    title = dict(VOICE_MODELS)[mid]
    st["expect"] = "voice"
    acct = ctx.get("_account")
    lines = [tr(lang, f"Озвучу {'текст из промпта речи' if sp and not text else 'ваш текст'} голосом {title}.",
                f"I’ll voice {'the speech prompt' if sp and not text else 'your text'} with {title}.")]
    if sp and sp.get("voice") and not text:
        lines.append(tr(lang, "Голос по промпту: ", "Voice per prompt: ") + sp["voice"])
    price = short_price(a._price(mid))
    if price and L(lang) == "ru":
        price = re.sub(r"\s*per thousand (input )?characters", " за 1000 символов", price, flags=re.I)
    if price:
        lines.append(tr(lang, f"Цена: {price}.", f"Price: {price}."))
    if isinstance(acct, dict) and not acct.get("authed"):
        return response(lines + [b("gate_login", lang)], [chip(b("login_run", lang), "login", primary=True), menu_chip(lang)],
                        [], lang, intent="pipe_voice", gate="login")
    alt = [chip(tr(lang, "Голос: ", "Voice: ") + t, "pipe_voice_model", m) for m, t in models if m != mid]
    blocks = [{"type": "prompt", "label": True, "title": tr(lang, "Текст озвучки", "Voiceover text"), "text": body, "note": title}]
    return response(lines, [chip(tr(lang, "🎙 Озвучить", "🎙 Generate voice"), "generate", mid, primary=True)] + alt + [menu_chip(lang)],
                    blocks, lang, intent="pipe_voice", generate_model=mid, generate_prompt=body, generate_params={}, ready=True,
                    generate_kind="audio")


# ════════════════════════════════════════════════════════════ результат генерации → артефакт
def result(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    kind = str(v.get("kind") or "")
    url = _txt(v.get("url"), 1000)
    url = url if re.match(r"^(https?://|/)", url) else ""
    exp = st.get("expect")
    model = _txt(v.get("model"), 60)
    if not exp:
        # генерация вне флоу — артефакт тихо, без сообщения
        if url and kind in ("image", "video", "audio"):
            save(ses, {"image": "image", "video": "video", "audio": "voice"}[kind], kind, _txt(v.get("title"), 60) or kind,
                 url=url, kind=kind, model=model, work_id=_txt(v.get("work_id"), 40))
        return {"silent": True, "text": "", "reply": "", "chips": [], "blocks": [], "intent": "pipe_result_silent"}
    if exp == "style":
        st["expect"] = None
        js = parse_style(_txt(v.get("reply"), 8000))
        if not js:
            return response([tr(lang, "Не получилось разобрать стиль: модель ответила не в формате JSON. Попробуйте ещё раз или другую картинку.",
                                "Couldn’t read the style: the model didn’t answer in JSON. Try again or use another image.")],
                            [chip(tr(lang, "{ } Ещё раз", "{ } Try again"), "pipe_sub", "style"), menu_chip(lang)], [], lang, intent="pipe_style_fail")
        art = save(ses, "prompt", "style", SUB_TITLE[L(lang)]["style"], json=js, sub=_txt(js.get("style_name"), 60), model=model)
        return response([tr(lang, "Разобрала стиль. Сюжета в JSON нет — только оформление. Он сам добавится к картинкам, "
                                  "раскадровке и видео в этой сессии.",
                            "Style extracted. The JSON has no subject — only the look. It will be added to images, the "
                            "storyboard and video in this session."), saved_line(art, lang)],
                        [chip(tr(lang, "✍️ Применить к другому сюжету", "✍️ Apply to another subject"), "pipe_sub", "video", primary=True)]
                        + [dict(c, primary=False) for c in offers("prompt", lang)], [{"type": "pipe_json", "title": art["title"], "json": json.dumps(js, ensure_ascii=False, indent=2)}],
                        lang, intent="pipe_style_done")
    if kind not in ("image", "video", "audio") or not url:
        return {"silent": True, "text": "", "reply": "", "chips": [], "blocks": [], "intent": "pipe_result_silent"}
    names = SUB_TITLE[L(lang)]
    if exp == "board" and kind == "image":
        urls = [u for u in (_txt(x, 1000) for x in (v.get("urls") or [])[:30]) if re.match(r"^(https?://|/)", u)]
        series = bool(v.get("series")) and len(urls) > 1
        art = save(ses, "board", "board", STAGE_TITLE[L(lang)]["board"], url=url, kind=kind, model=model,
                   sub=tr(lang, f"серия из {len(urls)} кадров", f"series of {len(urls)} frames") if series
                   else tr(lang, "лист раскадровки", "storyboard sheet"), frames=urls if series else None)
        stage_id = "board"
    elif exp == "video" and kind == "video":
        art = save(ses, "video", "video", tr(lang, "Ролик", "Video"), url=url, kind=kind, model=model, sub=model)
        stage_id = "video"
    elif exp == "voice" and kind == "audio":
        art = save(ses, "voice", "voiceTrack", STAGE_TITLE[L(lang)]["voice"], url=url, kind=kind, model=model, sub=model)
        stage_id = "voice"
    elif (exp == "hero" or str(exp).startswith("image:")) and kind == "image":
        sub_id = "hero" if exp == "hero" else str(exp).split(":", 1)[1]
        art = save(ses, "image", "hero" if sub_id == "hero" else "image", names.get(sub_id, names["other"]), url=url, kind=kind,
                   model=model, sub=model)
        stage_id = "image"
    else:   # результат не того типа, что ждали (например, человек сам запустил другую модель) — сохраняем по типу
        st_map = {"image": "image", "video": "video", "audio": "voice"}
        art = save(ses, st_map[kind], kind, kind, url=url, kind=kind, model=model, sub=model)
        stage_id = st_map[kind]
    st["expect"] = None
    head = {"image": tr(lang, "Картинка готова.", "The image is ready."), "board": tr(lang, "Раскадровка готова.", "The storyboard is ready."),
            "video": tr(lang, "Ролик готов.", "The video is ready."), "voice": tr(lang, "Озвучка готова.", "The voiceover is ready.")}[stage_id]
    extra = {"image": tr(lang, " Портрет героя станет первым кадром видео и ориентиром для раскадровки.",
                         " The hero portrait becomes the first video frame and the storyboard reference.") if art["type"] == "hero" else ""}.get(stage_id, "")
    return response([head + extra, saved_line(art, lang)], offers(stage_id, lang), [], lang, intent="pipe_saved_" + stage_id)


def summary(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    state(ses)["await"] = None
    return response([tr(lang, "Всё, что получилось в этой сессии. Список живёт только в этом чате — файлы картинок, видео и озвучки "
                              "лежат в «Моих работах».",
                        "Everything made in this session. The list lives only in this chat — image, video and voice files are in "
                        "“My works”.")],
                    [chip(tr(lang, "🆕 Новый чат", "🆕 New chat"), "new_chat"), menu_chip(lang)],
                    [arts_block(ses, lang, tr(lang, "Итог проекта", "Project summary"))], lang, intent="pipe_summary")


# ════════════════════════════════════════════════════════════ свободный текст
def waiting(ses: dict) -> bool:
    st = ses.get("pipe")
    return isinstance(st, dict) and bool(st.get("on")) and bool(st.get("await"))


def reask(a: Any, ses: dict, ctx: dict, lang: str, note: str) -> dict:
    """Непонятный ответ («ооло») — тот же вопрос этапа ещё раз, с пометкой."""
    st = state(ses)
    w = st.get("await")
    if w in ("video_idea", "speech_idea"):
        out = sub(a, ses, ctx, lang, "video" if w == "video_idea" else "speech")
    elif w == "image_desc":
        out = image(a, ses, ctx, lang, st.get("sub") or "other")
    elif w == "style_image":
        out = style(a, ses, ctx, lang)
    elif w == "voice_text":
        out = voice(a, ses, ctx, lang)
    elif w == "video_idea_direct":
        out = video(a, ses, ctx, lang)
    else:
        out = menu(a, ses, ctx, lang)
    out["text"] = note + "\n" + out["text"]
    out["reply"] = note + "\n" + out["reply"]
    out["intent"] = "pipe_junk"
    return out


def message(a: Any, ses: dict, ctx: dict, lang: str, msg: str) -> dict:
    st = state(ses)
    w = st.get("await")
    if w == "video_idea":
        return video_prompt(a, ses, ctx, lang, msg)
    if w == "video_idea_direct":
        video_prompt(a, ses, ctx, lang, msg)
        return video(a, ses, ctx, lang)
    if w == "speech_idea":
        return speech_prompt(a, ses, ctx, lang, msg)
    if w == "dialog":
        return dialog(a, ses, ctx, lang, msg)
    if w == "style_image":
        return style(a, ses, ctx, lang)
    if w == "image_desc":
        return image(a, ses, ctx, lang, st.get("sub") or "other", desc=msg)
    if w == "voice_text":
        return voice(a, ses, ctx, lang, text=msg)
    st["await"] = None
    return menu(a, ses, ctx, lang)
