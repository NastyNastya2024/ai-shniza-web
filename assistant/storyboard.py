"""Режим «Раскадровка»: серия картинок по сценарию.

Первое сообщение объясняет, что делает режим, и просит сценарий.
  • Есть сценарий — человек вставляет текст, помощник разбивает его на кадры.
  • Сценария нет — идея одной фразой (или пример из окна), помощник сам расписывает кадры.
Дальше — карточка со списком кадров: номер, время, подпись, описание, план, движение камеры.
Любой кадр правится на месте, убирается или добавляется; «Переписать кадр» — своими словами.
Запуск:
  • «Одним листом» — одна картинка-сетка: номера, таймкоды, подписи (как раскадровки-листы на 20 кадров);
  • «Каждый кадр отдельно» — серия картинок, по одной на кадр (фронтенд запускает их подряд).

Состояние — ses["sb"]. LLM пишет кадры; без неё — шаблоны (режим работает и без ключей).
Модуль без Flask: всё внешнее — через объект помощника `a` (Assistant).
"""
from __future__ import annotations

import math
import re
from typing import Any

from . import camera as CAM
from . import files as F
from . import params as P
from .render import chip, response, short_price
from .texts import b

MIN_FRAMES, MAX_FRAMES = 3, 20
MAX_SERIES = 12                       # серия отдельных картинок — не больше 12 запусков за раз
COUNTS = (6, 9, 12, 16, 20)
DURATIONS = (10, 15, 30, 60)
SHEET_MODELS = ("nano-banana-pro", "gpt-image-2", "nano-banana-2", "seedream-5-pro")
SERIES_MODELS = ("nano-banana-2", "nano-banana-pro", "seedream-5-pro", "gpt-image-2", "soul-cinema")
ASPECTS = ("16:9", "9:16", "1:1", "4:3")
STYLES = {
    "cinema": ("Кино", "Cinematic", "photorealistic cinematic film still, dramatic natural light, shallow depth of field"),
    "ad": ("Реклама", "Commercial", "high-end commercial product photography, crisp light, vivid colors, dynamic angles"),
    "sketch": ("Карандашный скетч", "Pencil sketch", "classic storyboard pencil sketch, grey marker shading, loose confident lines"),
    "cartoon": ("Мультик 3D", "3D cartoon", "stylized 3D animated film look, soft global illumination, vivid palette"),
    "anime": ("Аниме", "Anime", "anime key frame, clean cel shading, expressive lighting"),
}
LABELS = {"title": ("Номер, время, название", "Number, time, title"),
          "full": ("+ описание кадра", "+ shot description"),
          "none": ("Без подписей", "No captions")}

SB_RX = re.compile(r"(^\s*(раскадровк\w*|сториборд\w*|storyboard\w*)\b)|"
                   r"\b(сдела\w*|созда\w*|нарису\w*|нужн\w*|хочу|сгенерир\w*|собер\w*|make|create|draw|generate|need)\s+"
                   r"(мне\s+|me\s+|a\s+)?(\w+\s+)?(раскадровк\w*|сториборд\w*|storyboards?)\b", re.I)
_FRAME_RX = re.compile(r"^\s*(?:кадр|frame|shot)\s*№?\s*(\d{1,2})\s*[:.,—-]\s*(.+)$", re.I | re.S)
_COUNT_RX = re.compile(r"\b(\d{1,2})\s*(кадр\w*|frames?|shots?|панел\w*|panels?)\b", re.I)
_SEC_RX = re.compile(r"\b(\d{1,3})\s*(секунд\w*|сек\b|с\b|s\b|sec\w*)", re.I)


def L(lang: str) -> str:
    return "en" if lang == "en" else "ru"


def tr(lang: str, ru: str, en: str) -> str:
    return en if L(lang) == "en" else ru


def state(ses: dict) -> dict:
    st = ses.get("sb")
    if not isinstance(st, dict):
        st = {}
    for k, v in (("step", "ask"), ("source", ""), ("script", ""), ("idea", ""), ("title", ""), ("bible", ""),
                 ("frames", []), ("count", 9), ("seconds", 10), ("style", "cinema"), ("aspect", "16:9"),
                 ("format", "sheet"), ("labels", "title"), ("model", "")):
        st.setdefault(k, v)
    ses["sb"] = st
    return st


def active(ses: dict) -> bool:
    return ses.get("assist_mode") == "sb" and isinstance(ses.get("sb"), dict)


def _txt(v: Any, n: int = 300) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _rub(kop: int | None) -> str:
    if kop is None:
        return "—"
    s = str(kop // 100) if kop % 100 == 0 else f"{kop / 100:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " ₽"


def is_script(text: str) -> bool:
    """Сценарий или идея? Сценарий — длинный текст, несколько строк/сцен или нумерованные пункты."""
    t = (text or "").strip()
    if len(t.split()) >= 30:
        return True
    if len([x for x in t.splitlines() if x.strip()]) >= 3:
        return True
    if re.search(r"(сцен\w*|кадр|scene|shot|int\.|ext\.)\s*\d", t, re.I):
        return True
    return len(re.findall(r"(?:^|\s)\d{1,2}[.)]\s", t)) >= 2


def parse_settings(text: str) -> dict:
    out: dict[str, Any] = {}
    m = _COUNT_RX.search(text or "")
    if m:
        out["count"] = max(MIN_FRAMES, min(MAX_FRAMES, int(m.group(1))))
    m = _SEC_RX.search(text or "")
    if m and 3 <= int(m.group(1)) <= 300:
        out["seconds"] = int(m.group(1))
    low = (text or "").lower()
    if re.search(r"вертикал|9:16|vertical|рилс|reels|сторис|shorts|tiktok|тикток", low):
        out["aspect"] = "9:16"
    elif re.search(r"горизонт|16:9|horizontal|widescreen|youtube", low):
        out["aspect"] = "16:9"
    elif re.search(r"квадрат|1:1|square", low):
        out["aspect"] = "1:1"
    if re.search(r"отдельн|по кадр|кажд\w* кадр|серией|separate|one by one|each frame", low):
        out["format"] = "series"
    elif re.search(r"лист|сетк|одной картинк|grid|sheet|one image", low):
        out["format"] = "sheet"
    if re.search(r"скетч|карандаш|набросок|sketch|pencil", low):
        out["style"] = "sketch"
    elif re.search(r"аниме|anime", low):
        out["style"] = "anime"
    elif re.search(r"мульт|3d|cartoon|pixar", low):
        out["style"] = "cartoon"
    elif re.search(r"реклам|продукт|commercial|product", low):
        out["style"] = "ad"
    return out


# ════════════════════════════════════════════════════════════ LLM
BOARD_SYSTEM = (
    "You are a film storyboard artist. {task}\n"
    "Return JSON only: {\"title\": short title of the piece in {lang}, "
    "\"bible\": one English paragraph (max 60 words) describing recurring characters, products, places and palette, "
    "so every frame looks like the same film, "
    "\"frames\": [{\"title\": punchy 2-5 word shot title in {lang}, \"title_en\": the same title in English UPPERCASE, "
    "\"text\": 1-2 sentences in {lang}: what we see and what happens, "
    "\"shot\": shot size and angle in {lang} (e.g. close-up, low angle, macro), "
    "\"camera\": one camera move id from the list or \"\", \"seconds\": duration of the shot, "
    "\"prompt\": English image prompt for this single frame, 25-60 words, concrete and visual, repeat the key look of "
    "recurring characters/products, no text or captions in the image}]}.\n"
    "Rules: keep the order of the story; one frame = one clear moment; vary shot sizes and angles; {count_rule} "
    "Total duration about {seconds} seconds. Camera move ids: {ids}."
)
FRAME_SYSTEM = (
    "You are a film storyboard artist. Rewrite ONE storyboard frame according to the change request, keep the rest of "
    "the story and the recurring look. Return JSON only: {\"title\": 2-5 words in {lang}, \"title_en\": English UPPERCASE, "
    "\"text\": 1-2 sentences in {lang}, \"shot\": in {lang}, \"camera\": id from the list or \"\", "
    "\"prompt\": English image prompt, 25-60 words, no text in the image}. Camera move ids: {ids}."
)


def _fmt(system: str, lang: str, **kw: Any) -> str:
    out = system.replace("{lang}", "English" if L(lang) == "en" else "Russian")
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _cam_id(v: Any) -> str:
    v = str(v or "").strip()
    return v if CAM.get(v) else ""


def _frame(x: dict) -> dict:
    try:
        sec = max(0.2, min(20.0, float(x.get("seconds") or 1)))
    except (TypeError, ValueError):
        sec = 1.0
    title = _txt(x.get("title"), 60)
    return {"title": title, "title_en": _txt(x.get("title_en"), 60).upper() or title.upper(),
            "text": _txt(x.get("text"), 320), "shot": _txt(x.get("shot"), 60), "camera": _cam_id(x.get("camera")),
            "seconds": round(sec, 2), "prompt": _txt(x.get("prompt"), 600)}


def v_board(d: Any) -> dict:
    frames = []
    for x in (d.get("frames") if isinstance(d, dict) else None) or []:
        if isinstance(x, dict) and len(_txt(x.get("prompt"))) >= 15 and _txt(x.get("title")):
            frames.append(_frame(x))
    if len(frames) < MIN_FRAMES:
        raise ValueError("frames")
    return {"title": _txt(d.get("title"), 80), "bible": _txt(d.get("bible"), 500), "frames": frames[:MAX_FRAMES]}


def v_one(d: Any) -> dict:
    if not isinstance(d, dict) or len(_txt(d.get("prompt"))) < 15 or not _txt(d.get("title")):
        raise ValueError("frame")
    return _frame({**d, "seconds": 1})


# ════════════════════════════════════════════════════════════ без LLM: шаблоны
_BEATS = {
    "ru": [("Хук", "Яркое открытие: {i}"), ("Знакомство", "Общий план: где мы и кто в кадре — {i}"),
           ("Деталь", "Макро: фактура и детали — {i}"), ("Движение", "Динамика: герой начинает действие — {i}"),
           ("Ракурс снизу", "Низкий ракурс, герой крупно — {i}"), ("Поворот", "Неожиданный поворот истории — {i}"),
           ("Крупно", "Крупный план эмоции или продукта — {i}"), ("Пролёт", "Камера пролетает через сцену — {i}"),
           ("Нарастание", "Темп растёт, всё ближе к кульминации — {i}"), ("Кульминация", "Главный момент — {i}"),
           ("Реакция", "Реакция героя или окружения — {i}"), ("Финал", "Финальный геройский кадр — {i}")],
    "en": [("Hook", "Bold opening: {i}"), ("Setup", "Wide shot: where we are and who is here — {i}"),
           ("Detail", "Macro: textures and details — {i}"), ("Motion", "Action begins — {i}"),
           ("Low angle", "Low angle, hero up close — {i}"), ("Twist", "An unexpected twist — {i}"),
           ("Close-up", "Close-up of emotion or product — {i}"), ("Fly-through", "Camera flies through the scene — {i}"),
           ("Build-up", "Pace rises toward the climax — {i}"), ("Climax", "The key moment — {i}"),
           ("Reaction", "Reaction of the hero or the crowd — {i}"), ("Final", "Final hero shot — {i}")],
}
_BEAT_EN = ["bold opening shot", "wide establishing shot", "macro detail shot", "dynamic action shot",
            "low-angle hero shot", "unexpected twist moment", "expressive close-up", "camera fly-through",
            "build-up shot", "climax moment", "reaction shot", "final hero shot"]


def _spread(total: float, n: int) -> list[float]:
    return [round(total / n, 2)] * n


def fallback_frames(st: dict, lang: str) -> list[dict]:
    if st.get("source") == "script" and st.get("script"):
        lines = [x for x in st["script"].splitlines() if x.strip()]
        raw = lines if len(lines) >= MIN_FRAMES else re.split(r"(?<=[.!?…])\s+(?!\d)", st["script"])
        label = re.compile(r"^\s*(?:(?:сцена|кадр|scene|shot|frame)\s*№?\s*\d{1,2}|\d{1,2})\s*[.):—-]\s*", re.I)
        parts = [label.sub("", p).strip(" -–—•\t") for p in raw]
        parts = [p for p in parts if len(p) > 3][:MAX_FRAMES]
        while len(parts) < MIN_FRAMES and parts:
            parts.append(parts[-1])
        secs = _spread(st["seconds"], len(parts))
        return [{"title": " ".join(p.split()[:4]).rstrip(".,:;"),
                 "title_en": "", "text": _txt(p, 320), "shot": "", "camera": "", "seconds": secs[i], "prompt": ""}
                for i, p in enumerate(parts)]
    idea = st.get("idea") or tr(lang, "ваша история", "your story")
    n = max(MIN_FRAMES, min(MAX_FRAMES, int(st.get("count") or 9)))
    beats = _BEATS[L(lang)]
    last = len(beats) - 1
    # первый — хук, последний — финал, между ними — равномерно по списку сюжетных ходов
    idx = [round(k * last / (n - 1)) for k in range(n)]
    secs = _spread(st["seconds"], n)
    return [{"title": beats[j][0], "title_en": "", "text": beats[j][1].format(i=idea), "shot": "", "camera": "",
             "seconds": secs[k], "prompt": f"{_BEAT_EN[j]} of {idea}"} for k, j in enumerate(idx)]


def make_frames(a: Any, ses: dict, lang: str, change: str = "") -> bool:
    """Кадры в st['frames']; True — без LLM (шаблон)."""
    st = state(ses)
    ids = ", ".join(m["id"] for m in CAM.MOVES)
    if st["source"] == "script":
        task = "Split the user's script into storyboard frames."
        count_rule = ("Make as many frames as the script needs, from 4 to 20." if not st.get("count_fixed")
                      else f"Make exactly {st['count']} frames.")
        user = f"Script:\n{st['script'][:6000]}"
    else:
        task = "There is no script: invent a short visual story from the idea and split it into storyboard frames."
        count_rule = f"Make exactly {st['count']} frames: a strong hook first, a final hero shot last."
        user = f"Idea: {st['idea']}"
    user += f"\nVisual style: {STYLES[st['style']][2]}\nFrame aspect ratio: {st['aspect']}"
    if change:
        cur = "\n".join(f"{i + 1}. {f['title']}: {f['text']}" for i, f in enumerate(st.get("frames") or []))
        user += f"\nCurrent frames:\n{cur}\nChange request: {change}"
    data = a._llm_json(_fmt(BOARD_SYSTEM, lang, task=task, count_rule=count_rule, seconds=st["seconds"], ids=ids),
                       user, v_board, ses, 3500, timeout_scale=3, task="storyboard")
    if data:
        st["frames"] = data["frames"]
        st["title"] = data["title"] or st.get("title") or ""
        st["bible"] = data["bible"]
        _fit_seconds(st)
        return False
    st["frames"] = fallback_frames(st, lang)
    if change:
        st["frames"] = [{**f, "text": f["text"] + ". " + change} for f in st["frames"]]
    st["title"] = st.get("title") or _txt(st.get("idea") or st.get("script"), 40)
    return True


def _fit_seconds(st: dict) -> None:
    """Длительности кадров → в сумме длительность ролика."""
    fr = st.get("frames") or []
    if not fr:
        return
    tot = sum(float(f.get("seconds") or 1) for f in fr) or 1
    k = float(st["seconds"]) / tot
    for f in fr:
        f["seconds"] = round(float(f.get("seconds") or 1) * k, 2)


def timeline(frames: list[dict]) -> list[tuple[float, float]]:
    out, t0 = [], 0.0
    for f in frames:
        t1 = t0 + float(f.get("seconds") or 1)
        out.append((round(t0, 2), round(t1, 2)))
        t0 = t1
    return out


def _tc(v: float) -> str:
    return f"{v:.2f}"


# ════════════════════════════════════════════════════════════ промпты для картинок
def frame_visual(f: dict) -> str:
    return f.get("prompt") or f.get("text") or f.get("title") or ""


def _cam_short(mid: str) -> str:
    m = CAM.get(mid)
    return m["prompt"].split(". Movement:")[0].strip().rstrip(".") if m else ""


def _ratio(ar: str) -> float:
    w, h = (ar.split(":") + ["1"])[:2]
    try:
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 1.0


def grid(n: int, frame_ar: str, sheet_options: list[str], labels: str) -> tuple[int, int, str]:
    """Колонки, ряды и формат листа: сетка, у которой лист ближе всего к доступному формату модели."""
    fa = _ratio(frame_ar)
    cap = {"none": 1.0, "title": 1.12, "full": 1.4}.get(labels, 1.12)
    best = None
    for c in range(1, min(n, 6) + 1):
        r = math.ceil(n / c)
        sr = c * fa / (r * cap)
        for opt in sheet_options or ["1:1"]:
            score = abs(math.log(sr / _ratio(opt))) + 0.3 * (r * c - n) / n
            if best is None or score < best[0]:
                best = (score, c, r, opt)
    return best[1], best[2], best[3]


def sheet_prompt(st: dict, cols: int, rows: int) -> str:
    fr = st["frames"]
    tl = timeline(fr)
    n = len(fr)
    lab = st.get("labels") or "title"
    lines = [f"Professional film storyboard sheet: {n} panels in a clean grid of {cols} columns and {rows} rows, "
             f"thin white gutters, every panel in {st['aspect']} framing, read left to right, top to bottom.",
             f"One consistent look across all panels: {STYLES[st['style']][2]}."]
    if st.get("bible"):
        lines.append(f"Same characters, products and places in every panel: {st['bible']}")
    if lab == "none":
        lines.append("No text, numbers or captions anywhere on the sheet.")
    else:
        cap = ("a black caption bar with the shot title in bold white uppercase sans-serif"
               + (" and one short line of description under it" if lab == "full" else ""))
        lines.append("Labels: in the top-left corner of each panel a small black tab with the white bold frame number "
                     f"(01, 02…) and its timecode; along the bottom of each panel {cap}. "
                     "Text must be crisp, legible and spelled exactly as given. No other text, no watermarks.")
    lines.append("Panels:")
    for i, f in enumerate(fr):
        title = f.get("title_en") or (f.get("title") or "").upper()
        cam = _cam_short(f.get("camera") or "")
        row = f"{i + 1:02d} ({_tc(tl[i][0])}–{_tc(tl[i][1])})"
        if lab != "none":
            row += f" «{title}»"
        row += f" — {frame_visual(f)}"
        if f.get("shot"):
            row += f" Shot: {f['shot']}."
        if lab == "full" and f.get("text"):
            row += f" Caption line: «{_txt(f['text'], 120)}»."
        if cam:
            row += f" Camera: {cam}."
        lines.append(row)
    return "\n".join(lines)


def series_prompts(st: dict) -> list[dict]:
    fr = st["frames"]
    tl = timeline(fr)
    out = []
    for i, f in enumerate(fr):
        p = [f"Storyboard frame {i + 1} of {len(fr)}, {st['aspect']} framing. {STYLES[st['style']][2]}."]
        if st.get("bible"):
            p.append(f"Same characters, products and places as in every other frame: {st['bible']}")
        p.append(frame_visual(f).rstrip(". ") + ".")
        if f.get("shot"):
            p.append(f"Shot: {f['shot']}.")
        cam = _cam_short(f.get("camera") or "")
        if cam:
            p.append(f"Camera: {cam}.")
        p.append("No text, no captions, no watermark.")
        out.append({"n": i + 1, "title": f.get("title") or "", "time": f"{_tc(tl[i][0])}–{_tc(tl[i][1])}",
                    "prompt": " ".join(p)})
    return out


# ════════════════════════════════════════════════════════════ модели, цена, запуск
def models(a: Any, fmt: str) -> list[Any]:
    out = []
    for mid in SHEET_MODELS if fmt == "sheet" else SERIES_MODELS:
        c = a.d.cards.get(mid)
        if c and a._healthy(mid):
            out.append(c)
    return out


def current_model(a: Any, st: dict) -> Any:
    ms = models(a, st["format"])
    for c in ms:
        if c.id == st.get("model"):
            return c
    return ms[0] if ms else None


def gen_params(card: Any, st: dict) -> tuple[dict, int, int]:
    """Параметры запуска + (колонки, ряды) листа."""
    opts = list((card.params or {}).get("aspect_ratio") or [])
    cols = rows = 0
    if st["format"] == "sheet":
        cols, rows, sheet_ar = grid(len(st["frames"]), st["aspect"], opts, st["labels"])
        want: dict[str, Any] = {"aspect_ratio": sheet_ar}
        big = len(st["frames"]) > 9
        for k, hi, lo in (("resolution", "4K", "2K"), ("size", "4K", "2K"), ("quality", "high", "high")):
            vals = (card.params or {}).get(k) or []
            if vals:
                want[k] = hi if (big and hi in vals) else (lo if lo in vals else vals[-1])
    else:
        want = {"aspect_ratio": st["aspect"]}
    fitted = {**P.fit({"aspect_ratio": want.pop("aspect_ratio")}, card)[0], **P.validate(card, want)}
    return P.with_defaults(card, fitted), cols, rows


def _gate(a: Any, card: Any, params: dict, ctx: dict, lang: str, n: int,
          gen_chip: dict) -> tuple[str | None, list[str], list[dict], int | None]:
    """Вход → баланс (на всю серию) → запуск. Сервер генерации всё равно проверяет каждый запуск."""
    one = a._cost_kop(card, params)
    total = None if one is None else one * n
    acct = ctx.get("_account")
    if acct is None:
        return None, [], [gen_chip], total
    if not acct.get("authed"):
        return "login", [tr(
            lang, "Кадры готовы. Чтобы запустить генерацию, войдите — после входа продолжим с этого места.",
            "Frames are ready. Log in to run the generation — we’ll continue from here.")], \
            [chip(b("login_run", lang), "login", primary=True)], total
    have = int(acct.get("available_kop") or 0)
    if total and have < total:
        return "topup", [tr(lang, f"На балансе {_rub(have)}, для запуска нужно ≈ {_rub(total)}. Пополните — и сразу запустим.",
                            f"Balance is {_rub(have)}, the run needs ≈ {_rub(total)}. Top up and we’ll start right away.")], \
            [chip(b("topup", lang), "open_topup", primary=True), chip(b("resume_topup", lang), "resume")], total
    return ("free" if total == 0 else "ok"), [], [gen_chip], total


def camera_options(lang: str) -> list[dict]:
    names = {gid: (en if L(lang) == "en" else ru) for gid, ru, en in CAM.GROUP_ORDER}
    return [{"id": m["id"], "title": CAM.title(m, lang), "group": names.get(m.get("group") or "", m.get("group") or "")}
            for m in CAM.MOVES]


# ════════════════════════════════════════════════════════════ ответы
INTRO = {
    "ru": ("🎞 Раскадровка — это серия картинок по вашему сценарию: каждый кадр со своим номером, временем и подписью.\n\n"
           "Как это работает:\n"
           "1. Вы присылаете сценарий — просто вставьте текст сюда.\n"
           "2. Я разбиваю его на кадры. Вы проверяете список: любой кадр можно поправить, убрать или добавить.\n"
           "3. Я генерирую раскадровку — одним листом-сеткой или каждым кадром отдельной картинкой.\n\n"
           "Пришлите сценарий. Сценария нет — нажмите «Сценария нет» или напишите идею одной фразой: "
           "я сама распишу кадры."),
    "en": ("🎞 Storyboard is a series of images from your script: every frame gets its number, timecode and caption.\n\n"
           "How it works:\n"
           "1. You send the script — just paste the text here.\n"
           "2. I split it into frames. You check the list: edit, remove or add any frame.\n"
           "3. I generate the storyboard — as one grid sheet or as a separate image per frame.\n\n"
           "Send your script. No script? Tap “No script” or describe the idea in one line — I’ll write the frames myself."),
}


def _nav(lang: str) -> list[dict]:
    return [chip(tr(lang, "← Назад", "← Back"), "sb_back"), chip(tr(lang, "Выйти из режима", "Leave mode"), "sb_exit")]


def show_ask(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    st["step"] = "ask"
    ses["await"] = "sb"
    lines = [head] if head else []
    lines.append(INTRO[L(lang)])
    imgs = [f["name"] for f in ses.get("files") or [] if f.get("kind") == "image"]
    if imgs:
        lines.append(tr(lang, f"Фото «{'», «'.join(imgs[:3])}» возьму как референс: герой или продукт будет таким же во всех кадрах.",
                        f"I’ll use “{'”, “'.join(imgs[:3])}” as a reference so the hero or product stays the same in every frame."))
    chips = [chip(tr(lang, "Сценария нет — придумай кадры", "No script — invent the frames"), "sb_noscript", primary=True),
             chip(tr(lang, "Выйти из режима", "Leave mode"), "sb_exit")]
    return response(lines, chips, [], lang, intent="sb_intro")


IDEAS = {
    "ru": [("ad", "Реклама продукта в движении", "Например: оранжевые кроссовки на улице — макро сетки, разворот, прыжок, финальный геройский кадр."),
           ("build", "Пространство собирается само", "Например: диван падает с неба на газон, вокруг прилетают пол, стены, мебель — и получается гостиная."),
           ("story", "Короткая история с героем", "Завязка, поворот и финал: один герой, одна локация, ясная эмоция.")],
    "en": [("ad", "Product ad in motion", "E.g. orange sneakers on the street — mesh macro, a turn, a jump, a final hero shot."),
           ("build", "A space assembles itself", "E.g. a sofa falls from the sky onto a lawn, then floor, walls and furniture fly in."),
           ("story", "A short story with a hero", "Setup, twist and ending: one hero, one place, one clear emotion.")],
}


def show_idea(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    st["step"] = "idea"
    ses["await"] = "sb"
    block = {"type": "choice", "id": "sb_idea", "action": "sb_answer",
             "title": tr(lang, "О чём раскадровка?", "What is the storyboard about?"),
             "options": [{"id": i, "label": t0, "detail": d0} for i, t0, d0 in IDEAS[L(lang)]],
             "custom_placeholder": tr(lang, "Своя идея одной-двумя фразами", "Your idea in a sentence or two"),
             "cta": tr(lang, "Расписать кадры", "Write the frames"),
             "extra": {"title": tr(lang, "Сколько кадров", "How many frames"),
                       "options": [{"id": str(n), "label": str(n)} for n in COUNTS],
                       "selected": str(st.get("count") or 9)}}
    lines = [head or tr(lang, "Без сценария — тоже можно. Выберите направление или напишите свою идею: я распишу кадры, "
                              "вы проверите список, потом запустим генерацию.",
                        "No script is fine. Pick a direction or write your idea: I’ll write the frames, you check them, "
                        "then we generate.")]
    return response(lines, _nav(lang), [block], lang, intent="sb_idea")


def show_frames(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None, degraded: bool = False) -> dict:
    st = state(ses)
    st["step"] = "frames"
    ses["await"] = "sb"
    fr = st["frames"]
    if st["format"] == "series" and len(fr) > MAX_SERIES:
        st["format"] = "sheet"
        head = (head + "\n" if head else "") + tr(
            lang, f"Отдельными картинками — до {MAX_SERIES} кадров за раз, поэтому оставила формат «одним листом».",
            f"Separate images are limited to {MAX_SERIES} frames per run, so I kept the single sheet.")
    card = current_model(a, st)
    tl = timeline(fr)
    lab = L(lang)
    frames_out = [{"n": i + 1, "title": f["title"], "text": f["text"], "shot": f.get("shot") or "",
                   "camera": f.get("camera") or "", "time": f"{_tc(tl[i][0])}–{_tc(tl[i][1])}"} for i, f in enumerate(fr)]

    def pills(key: str, items: list[tuple[str, str]]) -> dict:
        return {"key": key, "options": [{"id": k, "label": v} for k, v in items], "selected": str(st[key])}

    settings = [
        dict(pills("format", [("sheet", tr(lang, "Одним листом", "One sheet")),
                              ("series", tr(lang, "Каждый кадр отдельно", "Image per frame"))]),
             label=tr(lang, "Формат", "Format")),
        dict(pills("aspect", [(x, x) for x in ASPECTS]), label=tr(lang, "Кадр", "Frame")),
        dict(pills("style", [(k, v[0] if lab == "ru" else v[1]) for k, v in STYLES.items()]), label=tr(lang, "Стиль", "Style")),
    ]
    if st["format"] == "sheet":
        settings.append(dict(pills("labels", [(k, v[0] if lab == "ru" else v[1]) for k, v in LABELS.items()]),
                             label=tr(lang, "Подписи", "Captions")))
    settings.append(dict(pills("seconds", [(str(x), f"{x} " + tr(lang, "с", "s")) for x in DURATIONS]),
                         label=tr(lang, "Длительность", "Duration")))
    block = {"type": "sb_frames", "title": st.get("title") or "", "frames": frames_out, "cameras": camera_options(lang),
             "settings": settings, "models": [], "can_add": len(fr) < MAX_FRAMES, "can_del": len(fr) > MIN_FRAMES,
             "labels": {"camera": tr(lang, "Камера", "Camera"), "none": tr(lang, "Без движения", "No movement"),
                        "shot": tr(lang, "План", "Shot"), "add": tr(lang, "+ Добавить кадр", "+ Add frame"),
                        "del": tr(lang, "Убрать кадр", "Remove frame"), "redo": tr(lang, "Переписать", "Rewrite"),
                        "redo_ph": tr(lang, "Что изменить в кадре?", "What to change in this frame?"),
                        "model": tr(lang, "Нейросеть", "Model"), "files": tr(lang, "Референсы", "References"),
                        "hint": tr(lang, "Текст кадра правится прямо здесь", "Edit frame text right here")}}
    lines = [head] if head else []
    if degraded:
        lines.append(tr(lang, "Помощник-сценарист сейчас недоступен — расписала кадры по шаблону, поправьте их под себя.",
                        "The writing model is unavailable — I used a template, adjust the frames to your story."))
    total_sec = round(tl[-1][1]) if tl else 0
    lines.append(tr(lang, f"Раскадровка{' «' + st['title'] + '»' if st.get('title') else ''}: {len(fr)} кадров, {total_sec} с. "
                          "Проверьте кадры — текст правится прямо в карточке, у каждого кадра можно поменять камеру "
                          "или переписать его своими словами.",
                    f"Storyboard{' “' + st['title'] + '”' if st.get('title') else ''}: {len(fr)} frames, {total_sec} s. "
                    "Check the frames — edit text right in the card, change the camera or rewrite any frame."))
    out_extra: dict[str, Any] = {}
    chips: list[dict] = []
    if not card:
        lines.append(tr(lang, "Сейчас нет доступной нейросети для картинок — попробуйте через пару минут.",
                        "No image model is available right now — try again in a couple of minutes."))
    else:
        params, cols, rows = gen_params(card, st)
        n = 1 if st["format"] == "sheet" else len(fr)
        refs = [f for f in ses.get("files") or [] if f.get("kind") == "image"]
        fplan = F.plan(card, refs, lang, a.d.inputs_fn)
        if st["format"] == "sheet":
            prompt = sheet_prompt(st, cols, rows)
            gen_chip = chip(tr(lang, "🖼 Сгенерировать раскадровку", "🖼 Generate storyboard"), "generate", card.id, primary=True)
            block["sheet"] = {"cols": cols, "rows": rows, "aspect": params.get("aspect_ratio") or ""}
            series = None
        else:
            series = series_prompts(st)
            prompt = series[0]["prompt"]
            gen_chip = chip(tr(lang, f"🖼 Сгенерировать {n} кадров", f"🖼 Generate {n} frames"), "generate_series",
                            card.id, primary=True)
        gate, glines, gchips, total = _gate(a, card, params, ctx, lang, n, gen_chip)
        one = a._cost_kop(card, params)
        block["models"] = [{"id": c.id, "title": c.title, "price": short_price(a._price(c.id)) or "",
                            "selected": c.id == card.id} for c in models(a, st["format"])]
        block["model"] = card.id
        if total is not None:
            block["cost"] = (tr(lang, f"≈ {_rub(total)} за лист", f"≈ {_rub(total)} for the sheet") if n == 1 else
                             f"{n} × {_rub(one)} = {_rub(total)}")
        used = [it for it in fplan if it["used"]]
        if used:
            block["files"] = [it["name"] for it in used]
        lines += glines
        if gate in (None, "ok", "free"):
            lines.append(tr(lang, f"Жмите «{gen_chip['label']}»." + (f" Спишется ≈ {_rub(total)}." if total else ""),
                            f"Tap “{gen_chip['label']}”." + (f" Cost ≈ {_rub(total)}." if total else "")))
        chips = gchips
        out_extra = {"generate_model": card.id, "generate_prompt": prompt, "generate_params": params,
                     "ready": gate in (None, "ok", "free"),
                     "generate_files": [{"kind": it["kind"], "name": it["name"]} for it in used]}
        if series is not None:
            out_extra["generate_series"] = series
    chips += [chip(tr(lang, "Пересобрать кадры", "Rebuild frames"), "sb_rebuild")] + _nav(lang)
    return response(lines, chips, [block], lang, intent="sb_frames", degraded=degraded, **out_extra)


def show(a: Any, ses: dict, ctx: dict, lang: str, head: str | None = None) -> dict:
    st = state(ses)
    if st["step"] == "frames" and st.get("frames"):
        return show_frames(a, ses, ctx, lang, head)
    if st["step"] == "idea":
        return show_idea(a, ses, ctx, lang, head)
    return show_ask(a, ses, ctx, lang, head)


# ════════════════════════════════════════════════════════════ действия
def start(a: Any, ses: dict, ctx: dict, lang: str, value: Any = None, text: str = "") -> dict:
    old = ses.get("sb") if isinstance(ses.get("sb"), dict) else None
    ses["assist_mode"] = "sb"
    if old and old.get("frames") and value != "new" and not text:
        out = show_frames(a, ses, ctx, lang, tr(lang, "Продолжаем раскадровку — кадры на месте.",
                                                 "Back to your storyboard — the frames are here."))
        out["chips"] = out["chips"][:-1] + [chip(tr(lang, "Начать новую", "Start a new one"), "sb_start", "new")] + out["chips"][-1:]
        return out
    ses["sb"] = None
    state(ses)
    if text:
        rest = SB_RX.sub(" ", text).strip(" :.,—-\n")
        if len(rest.split()) >= 3:
            return take_text(a, ses, ctx, lang, rest)
    return show_ask(a, ses, ctx, lang)


def take_text(a: Any, ses: dict, ctx: dict, lang: str, text: str) -> dict:
    """Текст на шаге «пришлите сценарий» / «идея»: сценарий → кадры по сценарию, короткий текст → идея."""
    st = state(ses)
    st.update({k: v for k, v in parse_settings(text).items() if k in ("aspect", "format", "style", "seconds")})
    s = parse_settings(text)
    if "count" in s:
        st["count"], st["count_fixed"] = s["count"], True
    if is_script(text):
        st.update(source="script", script=text.strip()[:8000], idea="")
        head = tr(lang, "Сценарий получила — разбила на кадры.", "Got the script — split it into frames.")
    else:
        st.update(source="idea", idea=text.strip()[:500], script="")
        head = (tr(lang, "Это похоже на идею, а не на сценарий, — расписала кадры сама.",
                   "That looks like an idea rather than a script — I wrote the frames myself.")
                if st["step"] == "ask" else tr(lang, "Расписала кадры по идее.", "Wrote the frames from your idea."))
    deg = make_frames(a, ses, lang)
    return show_frames(a, ses, ctx, lang, head, deg)


def answer(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    """Окно «О чём раскадровка?»: пример или своя идея + число кадров."""
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    try:
        st["count"] = max(MIN_FRAMES, min(MAX_FRAMES, int(v.get("style") or st.get("count") or 9)))
        st["count_fixed"] = True
    except (TypeError, ValueError):
        pass
    text = _txt(v.get("text"), 500)
    if not text:
        opt = {i: (t0, d0) for i, t0, d0 in IDEAS[L(lang)]}.get(str(v.get("option") or ""))
        if not opt:
            return show_idea(a, ses, ctx, lang)
        text = opt[0] + ". " + opt[1]
    st.update(source="idea", idea=text, script="")
    st["step"] = "idea"
    deg = make_frames(a, ses, lang)
    return show_frames(a, ses, ctx, lang, tr(lang, "Расписала кадры — проверьте.", "Frames are ready — check them."), deg)


def edit(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    """Правка на месте: frames.i.title|text|shot|camera, frames.add.i, frames.del.i, set.<key>, model."""
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    path = str(v.get("path") or "")
    val = v.get("value")
    fr = st["frames"]
    head = None
    m = re.fullmatch(r"frames\.(\d{1,2})\.(title|text|shot|camera)", path)
    if m and int(m.group(1)) < len(fr):
        f = fr[int(m.group(1))]
        key = m.group(2)
        if key == "camera":
            f["camera"] = _cam_id(val)
        else:
            f[key] = _txt(val, 320 if key == "text" else 60).strip("—- ") if key == "shot" else _txt(val, 320 if key == "text" else 60)
            if key == "title":
                f["title_en"] = ""             # подпись на листе = то, что написал человек
            if key == "text":
                f["prompt"] = ""               # визуальный промпт = новый текст кадра
    elif (m := re.fullmatch(r"frames\.add\.(\d{1,2})", path)) and len(fr) < MAX_FRAMES:
        i = min(int(m.group(1)), len(fr))
        sec = round(float(st["seconds"]) / (len(fr) + 1), 2)
        fr.insert(i, {"title": tr(lang, "Новый кадр", "New frame"), "title_en": "", "shot": "", "camera": "",
                      "text": tr(lang, "Опишите, что в кадре", "Describe what is in the frame"), "seconds": sec, "prompt": ""})
        _fit_seconds(st)
    elif (m := re.fullmatch(r"frames\.del\.(\d{1,2})", path)) and len(fr) > MIN_FRAMES and int(m.group(1)) < len(fr):
        fr.pop(int(m.group(1)))
        _fit_seconds(st)
    elif path == "model":
        if any(c.id == val for c in models(a, st["format"])):
            st["model"] = str(val)
    elif path.startswith("set."):
        key = path[4:]
        val = str(val or "")
        allowed = {"format": ("sheet", "series"), "aspect": ASPECTS, "style": tuple(STYLES), "labels": tuple(LABELS),
                   "seconds": tuple(str(x) for x in DURATIONS)}
        if val in allowed.get(key, ()):
            if key == "seconds":
                st["seconds"] = int(val)
                _fit_seconds(st)
            else:
                st[key] = val
            if key == "format":
                st["model"] = ""
                if val == "series" and len(fr) > MAX_SERIES:
                    head = tr(lang, f"Отдельными картинками — до {MAX_SERIES} кадров. Уберите лишние кадры или оставьте лист.",
                              f"Separate images are limited to {MAX_SERIES} frames. Remove some frames or keep the sheet.")
    out = show_frames(a, ses, ctx, lang, head)
    out["intent"] = "sb_edit"
    return out


def redo_frame(a: Any, ses: dict, ctx: dict, lang: str, value: Any) -> dict:
    st = state(ses)
    v = value if isinstance(value, dict) else {}
    try:
        i = int(v.get("n")) - 1
    except (TypeError, ValueError):
        return show_frames(a, ses, ctx, lang)
    change = _txt(v.get("text"), 300)
    fr = st["frames"]
    if not (0 <= i < len(fr)) or not change:
        return show_frames(a, ses, ctx, lang)
    f = fr[i]
    ids = ", ".join(x["id"] for x in CAM.MOVES)
    ctx_txt = "\n".join(f"{k + 1}. {x['title']}: {x['text']}" for k, x in enumerate(fr))
    data = a._llm_json(_fmt(FRAME_SYSTEM, lang, ids=ids),
                       f"Story frames:\n{ctx_txt}\nRecurring look: {st.get('bible') or '-'}\n"
                       f"Frame to rewrite: {i + 1}. {f['title']}: {f['text']}\nChange request: {change}",
                       v_one, ses, 700, timeout_scale=2, task="storyboard_frame")
    if data:
        fr[i] = {**data, "seconds": f["seconds"]}
    else:
        f["text"] = (f["text"].rstrip(". ") + ". " + change)[:320]
        f["prompt"] = ""
    out = show_frames(a, ses, ctx, lang, tr(lang, f"Переписала кадр {i + 1}.", f"Rewrote frame {i + 1}."), not data)
    out["intent"] = "sb_frame"
    return out


def rebuild(a: Any, ses: dict, ctx: dict, lang: str, change: str = "") -> dict:
    deg = make_frames(a, ses, lang, change)
    return show_frames(a, ses, ctx, lang, tr(lang, "Пересобрала кадры" + (" с правкой." if change else "."),
                                             "Rebuilt the frames" + (" with your change." if change else ".")), deg)


def back(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    st = state(ses)
    if st["step"] == "frames":
        return show_idea(a, ses, ctx, lang) if st.get("source") == "idea" else show_ask(a, ses, ctx, lang)
    if st["step"] == "idea":
        return show_ask(a, ses, ctx, lang)
    return exit_mode(a, ses, ctx, lang)


def exit_mode(a: Any, ses: dict, ctx: dict, lang: str) -> dict:
    ses["assist_mode"] = None
    ses["await"] = "type"
    keep = bool((ses.get("sb") or {}).get("frames"))
    out = a._offer_types([tr(lang, "Вышла из раскадровки." + (" Кадры сохранила — «🎞 Раскадровка» вернёт к ним." if keep else ""),
                             "Left the storyboard." + (" Frames are saved — “🎞 Storyboard” brings them back." if keep else ""))],
                         ctx, ses, lang, "sb_exit")
    return out


def message(a: Any, ses: dict, ctx: dict, lang: str, msg: str) -> dict:
    """Свободный текст в режиме: сценарий / идея / правка кадров."""
    st = state(ses)
    if st["step"] in ("ask", "idea"):
        return take_text(a, ses, ctx, lang, msg)
    m = _FRAME_RX.match(msg)
    if m:
        return redo_frame(a, ses, ctx, lang, {"n": int(m.group(1)), "text": m.group(2)})
    s = parse_settings(msg)
    if s and len(msg.split()) <= 6:
        for k in ("aspect", "format", "style", "seconds"):
            if k in s:
                st[k] = s[k]
        if "seconds" in s:
            _fit_seconds(st)
        if "count" in s and s["count"] != len(st["frames"]):
            st["count"], st["count_fixed"] = s["count"], True
            return rebuild(a, ses, ctx, lang)
        return show_frames(a, ses, ctx, lang, tr(lang, "Поменяла настройки.", "Settings updated."))
    if is_script(msg):                               # прислали новый сценарий целиком
        return take_text(a, ses, ctx, lang, msg)
    return rebuild(a, ses, ctx, lang, msg)
