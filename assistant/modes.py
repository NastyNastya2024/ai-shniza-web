"""Режимы помощника — сценарии по шагам с выходами: «Рилс» и «Сериал».

Режим — это рельсы, но не клетка:
  * на каждом шаге видно «Рилс · шаг 3 из 8 — Раскадровка», кнопки «Дальше», «Назад», «Выйти»;
  * свободный текст на текстовом шаге (идея, правка сценария) — ответ на шаг;
  * вопрос («а чем kling лучше seedance?») или действие («сделай тёмную тему») — ответ, затем «↩ Вернуться к шагу»;
  * другая задача («нарисуй логотип») — делается обычным путём, под ответом остаётся «↩ Рилс · шаг N»;
  * шаги с генерацией передают работу существующим флоу (раскадровка storyboard.py, видео и озвучка pipeline.py),
    а результат генерации (pipe_result) сам переводит режим на следующий шаг.

Состояние: ses["mode"] = {id, step, data, paused}. Живёт столько же, сколько сессия помощника (24 ч).
"""
from __future__ import annotations

import re
from typing import Any

from . import brief as BR
from . import pipeline as PL
from . import storyboard as SB
from .render import chip, response


def tr(lang: str, ru: str, en: str) -> str:
    return en if (lang or "ru").startswith("en") else ru


# шаг: id, заголовок ru/en, ввод: text — ждём текст; act — кнопки; result — какой результат генерации закрывает шаг
MODES: dict[str, dict] = {
    "reels": {
        "icon": "🎬", "title": ("Рилс", "Reels"),
        "steps": [
            {"id": "idea", "t": ("Идея", "Idea"), "input": "text"},
            {"id": "script", "t": ("Сценарий и хук", "Script and hook"), "input": "text"},
            {"id": "board", "t": ("Раскадровка", "Storyboard"), "input": "act", "result": "board"},
            {"id": "video", "t": ("Видео", "Video"), "input": "act", "result": "video"},
            {"id": "sound", "t": ("Озвучка и музыка", "Voice and music"), "input": "act", "result": "audio"},
            {"id": "edit", "t": ("Монтаж 9:16", "Edit 9:16"), "input": "act"},
            {"id": "viral", "t": ("Прогноз виральности", "Virality forecast"), "input": "act"},
            {"id": "publish", "t": ("Публикация", "Publishing"), "input": "act"},
        ],
    },
    "series": {
        "icon": "📺", "title": ("Сериал", "Series"),
        "steps": [
            {"id": "world", "t": ("Мир и герои", "World and heroes"), "input": "text"},
            {"id": "heroes", "t": ("Портреты героев", "Hero portraits"), "input": "act", "result": "hero"},
            {"id": "episode", "t": ("Сценарий серии", "Episode script"), "input": "text"},
            {"id": "board", "t": ("Раскадровка", "Storyboard"), "input": "act", "result": "board"},
            {"id": "video", "t": ("Видео серии", "Episode video"), "input": "act", "result": "video"},
            {"id": "next", "t": ("Следующая серия", "Next episode"), "input": "act"},
        ],
    },
}
MODE_WORDS = re.compile(r"\b(сделай|создай|сними|хочу|запусти|давай|режим\w*|по\s+шагам|под\s+ключ|полн\w+\s+цикл\w*|целиком|"
                        r"сериал\w*|серии|мини-?сериал|рилс\w*|reels?|шортс\w*|shorts)\b", re.I)


# ─────────────────────────────────────────── состояние
def state(ses: dict) -> dict | None:
    m = ses.get("mode")
    return m if isinstance(m, dict) and m.get("id") in MODES else None


def active(ses: dict) -> dict | None:
    m = state(ses)
    return m if m and not m.get("paused") else None


def _steps(m: dict) -> list[dict]:
    return MODES[m["id"]]["steps"]


def cur(m: dict) -> dict:
    st = _steps(m)
    return st[max(0, min(len(st) - 1, int(m.get("step") or 0)))]


def wants_text(ses: dict) -> bool:
    m = active(ses)
    return bool(m and cur(m)["input"] == "text")


def title(m: dict, lang: str) -> str:
    spec = MODES[m["id"]]
    name = spec["title"][1 if lang.startswith("en") else 0]
    s = cur(m)
    n, total = int(m.get("step") or 0) + 1, len(_steps(m))
    ep = (tr(lang, f" · серия {m['data'].get('ep', 1)}", f" · episode {m['data'].get('ep', 1)}")
          if m["id"] == "series" and int(m.get("step") or 0) >= 2 else "")
    return f"{spec['icon']} {name}{ep} · " + tr(lang, f"шаг {n} из {total} — ", f"step {n} of {total} — ") + s["t"][1 if lang.startswith("en") else 0]


def resume_chip(ses: dict, lang: str) -> dict | None:
    m = state(ses)
    if not m:
        return None
    s = cur(m)
    name = MODES[m["id"]]["title"][1 if lang.startswith("en") else 0]
    return chip(tr(lang, f"↩ {name}: шаг {int(m.get('step') or 0) + 1} — {s['t'][0]}",
                   f"↩ {name}: step {int(m.get('step') or 0) + 1} — {s['t'][1]}"), "mode_resume")


def decorate(out: dict, ses: dict, lang: str) -> dict:
    """Под ответом вне шага режима — кнопка вернуться к шагу (режим не теряется)."""
    if not isinstance(out, dict) or out.get("silent") or str(out.get("intent") or "").startswith("mode_"):
        return out
    rc = resume_chip(ses, lang)
    if rc and not any(c.get("action") == "mode_resume" for c in out.get("chips") or []):
        out["chips"] = list(out.get("chips") or []) + [rc]
    return out


# ─────────────────────────────────────────── нейросеть: сценарий, герои, серия
REELS_SYSTEM = (
    "You are a short-form video scriptwriter (Reels / Shorts / TikTok). From the idea write a 15-30 second vertical "
    "video script in {lang}. The first 1-3 seconds must hook the viewer. 4-6 scenes. Return JSON only: "
    '{"hook": one line, "scenes": [{"sec": "0-3", "shot": what we see, short, "text": voiceover or on-screen text}], '
    '"caption": post caption with 3-5 hashtags}.'
)
HEROES_SYSTEM = (
    "From the series idea extract 2-4 main characters in {lang}. Return JSON only: "
    '{"genre": short, "world": one sentence, "heroes": [{"name": short name, "look": appearance, outfit, character — one sentence}]}.'
)
EPISODE_SYSTEM = (
    "You write episodes of a short AI-video series in {lang}. Keep the same characters and world. Episode length 30-60 s, "
    "4-7 scenes, ends with a hook for the next episode. Return JSON only: "
    '{"title": episode title, "summary": one sentence, "scenes": [{"shot": what we see, "text": line or action}]}.'
)


def _lang_name(lang: str) -> str:
    return "English" if lang.startswith("en") else "Russian"


def _v_reels(d: Any) -> dict:
    if not isinstance(d, dict) or not isinstance(d.get("scenes"), list) or len(d["scenes"]) < 2:
        raise ValueError("bad script")
    sc = [{"sec": str(x.get("sec") or "")[:12], "shot": str(x.get("shot") or "")[:240], "text": str(x.get("text") or "")[:240]}
          for x in d["scenes"][:8] if isinstance(x, dict) and (x.get("shot") or x.get("text"))]
    if len(sc) < 2:
        raise ValueError("bad scenes")
    return {"hook": str(d.get("hook") or "")[:200], "scenes": sc, "caption": str(d.get("caption") or "")[:400]}


def _v_heroes(d: Any) -> dict:
    if not isinstance(d, dict) or not isinstance(d.get("heroes"), list) or not d["heroes"]:
        raise ValueError("no heroes")
    hs = [{"name": str(h.get("name") or "")[:40], "look": str(h.get("look") or "")[:300]}
          for h in d["heroes"][:4] if isinstance(h, dict) and h.get("name")]
    if not hs:
        raise ValueError("no heroes")
    return {"genre": str(d.get("genre") or "")[:60], "world": str(d.get("world") or "")[:300], "heroes": hs}


def _v_episode(d: Any) -> dict:
    if not isinstance(d, dict) or not isinstance(d.get("scenes"), list) or len(d["scenes"]) < 2:
        raise ValueError("bad episode")
    sc = [{"shot": str(x.get("shot") or "")[:240], "text": str(x.get("text") or "")[:240]}
          for x in d["scenes"][:8] if isinstance(x, dict)]
    return {"title": str(d.get("title") or "")[:80], "summary": str(d.get("summary") or "")[:300], "scenes": sc}


def _fallback_reels(idea: str, lang: str) -> dict:
    i = idea.strip().rstrip(".")
    return {"hook": tr(lang, f"Стоп-кадр: самое неожиданное в «{i}»", f"Freeze frame: the most surprising part of “{i}”"),
            "scenes": [
                {"sec": "0-3", "shot": tr(lang, f"Крупно и резко: {i}", f"Close and sharp: {i}"),
                 "text": tr(lang, "Вы точно такого не видели", "You haven’t seen this")},
                {"sec": "3-10", "shot": tr(lang, "Контекст: где и с кем это происходит", "Context: where and who"),
                 "text": tr(lang, "Коротко — в чём дело", "In short — what it’s about")},
                {"sec": "10-20", "shot": tr(lang, "Главное действие, смена ракурса", "Main action, angle change"),
                 "text": tr(lang, "Самый сильный момент", "The strongest moment")},
                {"sec": "20-25", "shot": tr(lang, "Финал: результат и эмоция", "Ending: result and emotion"),
                 "text": tr(lang, "Подпишитесь — дальше ещё интереснее", "Follow — it gets better")}],
            "caption": i, "template": True}


def _script_text(sc: dict, lang: str) -> str:
    lines = []
    if sc.get("hook"):
        lines.append(tr(lang, "Хук: ", "Hook: ") + sc["hook"])
    for n, s in enumerate(sc.get("scenes") or [], 1):
        sec = f" ({s['sec']} с)" if s.get("sec") else ""
        lines.append(f"{n}{sec}. {s.get('shot', '')}" + (f" — «{s['text']}»" if s.get("text") else ""))
    if sc.get("caption"):
        lines.append(tr(lang, "Подпись: ", "Caption: ") + sc["caption"])
    return "\n".join(lines)


def _scenes_plain(sc: dict) -> str:
    """Сценарий для раскадровки и видео: сцены через точку, без служебных пометок."""
    return " ".join(f"{s.get('shot', '').rstrip('.')}. {s.get('text', '')}".strip() for s in sc.get("scenes") or [])


def _write_reels(a: Any, ses: dict, lang: str, idea: str, change: str = "") -> dict:
    user = f"IDEA: {idea[:800]}" + (f"\nCHANGE REQUEST: {change[:400]}\nPREVIOUS: {_script_text(ses['mode']['data'].get('script') or {}, lang)[:1500]}" if change else "")
    got = a._llm_json(REELS_SYSTEM.replace("{lang}", _lang_name(lang)), user, _v_reels, ses, max_tokens=700, task="mode_reels")
    return got or _fallback_reels(idea + (f". {change}" if change else ""), lang)


def _write_heroes(a: Any, ses: dict, lang: str, world: str) -> dict:
    got = a._llm_json(HEROES_SYSTEM.replace("{lang}", _lang_name(lang)), "SERIES IDEA: " + world[:800], _v_heroes, ses,
                      max_tokens=500, task="mode_heroes")
    if got:
        return got
    return {"genre": "", "world": world, "template": True,
            "heroes": [{"name": tr(lang, "Главный герой", "Main hero"), "look": tr(lang, f"по описанию: «{world[:280]}»", f"as described: “{world[:280]}”")}]}


def _write_episode(a: Any, ses: dict, lang: str, d: dict, change: str = "") -> dict:
    heroes = "; ".join(f"{h['name']}: {h['look']}" for h in d.get("heroes") or [])
    prev = " | ".join(d.get("episodes") or [])[-1200:]
    user = (f"WORLD: {d.get('world', '')[:600]}\nHEROES: {heroes[:900]}\nEPISODE NUMBER: {d.get('ep', 1)}\n"
            f"PREVIOUS EPISODES: {prev or 'none'}" + (f"\nCHANGE REQUEST: {change[:400]}" if change else ""))
    got = a._llm_json(EPISODE_SYSTEM.replace("{lang}", _lang_name(lang)), user, _v_episode, ses, max_tokens=800, task="mode_episode")
    if got:
        return got
    names = ", ".join(h["name"] for h in d.get("heroes") or []) or tr(lang, "герои", "heroes")
    w = d.get("world") or ""
    return {"title": tr(lang, f"Серия {d.get('ep', 1)}", f"Episode {d.get('ep', 1)}"), "summary": w[:200], "template": True,
            "scenes": [{"shot": tr(lang, f"Общий план: {w[:120]}", f"Wide shot: {w[:120]}"), "text": ""},
                       {"shot": tr(lang, f"{names} — знакомство в кадре", f"{names} — intro shot"), "text": ""},
                       {"shot": tr(lang, "Завязка: что-то идёт не так", "Inciting incident: something goes wrong"), "text": ""},
                       {"shot": tr(lang, "Кульминация серии", "Episode climax"), "text": ""},
                       {"shot": tr(lang, "Крючок на следующую серию", "Hook for the next episode"), "text": ""}]}


# ─────────────────────────────────────────── показ шага
def _nav(m: dict, lang: str, next_label: str | None = None, primary_next: bool = False) -> list[dict]:
    out = []
    if next_label is not False:
        out.append(chip(next_label or tr(lang, "Дальше →", "Next →"), "mode_next", primary=primary_next))
    if int(m.get("step") or 0) > 0:
        out.append(chip(tr(lang, "← Назад", "← Back"), "mode_back"))
    out.append(chip(tr(lang, "Выйти из режима", "Leave the mode"), "mode_exit"))
    return out


def show(a: Any, ses: dict, ctx: dict, lang: str, head: str = "") -> dict:
    m = state(ses)
    if not m:
        return a._offer_types([tr(lang, "Режим закрыт.", "The mode is closed.")], ctx, ses, lang, "mode_none")
    m["paused"] = False
    s, d = cur(m), m["data"]
    lines = [title(m, lang)] + ([head] if head else [])
    blocks: list[dict] = []
    chips: list[dict] = []
    sid = s["id"]
    if m["id"] == "reels":
        if sid == "idea":
            lines.append(tr(lang, "О чём рилс? Одной-двумя фразами: что показываем, для кого и какая эмоция.",
                            "What’s the reel about? One or two sentences: what we show, for whom, what feeling."))
            chips = [chip(tr(lang, "☕ Утро бариста в кофейне", "☕ A barista’s morning"), "mode_input", tr(lang, "Утро бариста в маленькой кофейне: первый кофе дня", "A barista’s morning in a small café: the first coffee of the day")),
                     chip(tr(lang, "👟 Новые кроссовки", "👟 New sneakers"), "mode_input", tr(lang, "Реклама новых кроссовок: прыжок через лужу в замедленной съёмке", "Sneaker ad: a slow-motion jump over a puddle")),
                     chip(tr(lang, "💡 Лайфхак за 15 секунд", "💡 15-second life hack"), "mode_input", tr(lang, "Лайфхак: как за 15 секунд почистить авокадо", "Life hack: peel an avocado in 15 seconds"))]
            chips += _nav(m, lang, next_label=False)
        elif sid == "script":
            sc = d.get("script") or {}
            blocks.append({"type": "mode_text", "title": tr(lang, "Сценарий рилса", "Reel script"), "text": _script_text(sc, lang),
                           "note": tr(lang, "Чтобы поправить — напишите, что изменить: «хук смешнее», «короче», «добавь кота».",
                                      "To change it, just write what to change: “funnier hook”, “shorter”, “add a cat”.")})
            if sc.get("template"):
                lines.append(tr(lang, "Нейросеть-сценарист сейчас недоступна — собрала каркас по вашей идее, его легко поправить.",
                                "The script writer is unavailable — I built a skeleton from your idea; edit it freely."))
            chips = [chip(tr(lang, "↻ Переписать", "↻ Rewrite"), "mode_redo")] + _nav(m, lang, tr(lang, "Дальше: раскадровка →", "Next: storyboard →"), True)
        elif sid == "board":
            lines.append(tr(lang, "Разложу сценарий на кадры: текст кадров можно поправить, потом — картинки кадров одной нейросетью.",
                            "I’ll split the script into frames: edit the frame text, then render the frames with one model."))
            chips = [chip(tr(lang, "🎞 Собрать раскадровку", "🎞 Build the storyboard"), "mode_go", "board", primary=True)] + _nav(m, lang, tr(lang, "Пропустить →", "Skip →"))
        elif sid == "video":
            lines.append(tr(lang, "Оживлю кадры в видео 9:16. Возьму раскадровку и героя, если они есть.",
                            "I’ll animate the frames into a 9:16 video, using the storyboard and hero if present."))
            chips = [chip(tr(lang, "🎬 Сделать видео", "🎬 Make the video"), "mode_go", "video", primary=True)] + _nav(m, lang, tr(lang, "Пропустить →", "Skip →"))
        elif sid == "sound":
            lines.append(tr(lang, "Голос за кадром по тексту сценария и/или фоновая музыка.", "Voiceover from the script and/or background music."))
            chips = [chip(tr(lang, "🎙 Озвучка", "🎙 Voiceover"), "mode_go", "voice", primary=True),
                     chip(tr(lang, "🎵 Музыка", "🎵 Music"), "mode_go", "music")] + _nav(m, lang, tr(lang, "Пропустить →", "Skip →"))
        elif sid == "edit":
            lines.append(tr(lang, "Монтаж 9:16: склейка видео, озвучки и музыки, субтитры. Подключите видеоредактор во вкладке «MCP» "
                                  "(FFmpeg, DaVinci) — кнопки монтажа появятся под роликом. Или скачайте файлы из «Моих работ» в свой редактор.",
                            "9:16 edit: video, voice and music, subtitles. Connect an editor in the “MCP” tab (FFmpeg, DaVinci) — "
                            "edit buttons appear under the video. Or download files from “My works”."))
            chips = [chip(tr(lang, "✂️ Подключения: монтаж", "✂️ Connections: editing"), "open_mcp", "edit")] + _nav(m, lang)
        elif sid == "viral":
            lines.append(tr(lang, "Higgsfield Virality Predictor оценит ролик до 15 с: балл 0–100, силу хука и удержание. "
                                  "Подключите Higgsfield во вкладке «MCP» — кнопка прогноза появится под роликом.",
                            "Higgsfield Virality Predictor scores clips up to 15 s: 0–100, hook strength and hold rate. "
                            "Connect Higgsfield in the “MCP” tab — the forecast button appears under the video."))
            chips = [chip(tr(lang, "📈 Подключения: виральность", "📈 Connections: virality"), "open_mcp", "viral")] + _nav(m, lang)
        elif sid == "publish":
            sc = d.get("script") or {}
            if sc.get("caption"):
                blocks.append({"type": "mode_text", "title": tr(lang, "Подпись к посту", "Post caption"), "text": sc["caption"]})
            lines.append(tr(lang, "Опубликовать: на витрине {AI}-шницы — кнопкой под роликом; в Reels и YouTube — через vidIQ во вкладке «MCP».",
                            "Publish: to the {AI}-shnitsa showcase — button under the video; to Reels and YouTube — via vidIQ in the “MCP” tab."))
            chips = [chip(tr(lang, "🚀 Подключения: публикация", "🚀 Connections: publishing"), "open_mcp", "reels"),
                     chip(tr(lang, "✅ Готово", "✅ Done"), "mode_exit", "done", primary=True)] + _nav(m, lang, next_label=False)[:-1]
    else:   # series
        if sid == "world":
            lines.append(tr(lang, "О чём сериал? Жанр, мир и главный герой. Например: «детектив: кот-сыщик в дождливом Париже».",
                            "What’s the series about? Genre, world, main hero. E.g. “detective: a cat sleuth in rainy Paris”."))
            chips = [chip(tr(lang, "🕵️ Кот-детектив в Париже", "🕵️ Cat detective in Paris"), "mode_input", tr(lang, "Детектив: кот-сыщик и его напарница-ворона расследуют дела в дождливом Париже", "Detective: a cat sleuth and his crow partner solve cases in rainy Paris")),
                     chip(tr(lang, "🚀 Космическая станция", "🚀 Space station"), "mode_input", tr(lang, "Комедия на космической станции: робот-повар и капитан-неудачник", "Comedy on a space station: a robot cook and a clumsy captain")),
                     chip(tr(lang, "🏰 Сказка про дракона", "🏰 Dragon tale"), "mode_input", tr(lang, "Сказка: маленький дракон боится огня и учится летать с девочкой-рыцарем", "Fairy tale: a little dragon afraid of fire learns to fly with a girl knight"))]
            chips += _nav(m, lang, next_label=False)
        elif sid == "heroes":
            hs = d.get("heroes") or []
            blocks.append({"type": "mode_text", "title": tr(lang, "Герои сериала", "Series heroes"),
                           "text": "\n".join(f"{h['name']} — {h['look']}" for h in hs),
                           "note": tr(lang, "Портрет каждого героя станет референсом: в раскадровке и видео лица будут одинаковыми из серии в серию.",
                                      "Each portrait becomes a reference so faces stay the same across episodes.")})
            done = set(d.get("portraits") or [])
            chips = [chip(("✓ " if i in done else "🖼 ") + tr(lang, f"Портрет: {h['name']}", f"Portrait: {h['name']}"), "mode_go", f"hero:{i}",
                          primary=(i not in done and not any(j not in done for j in range(i))))
                     for i, h in enumerate(hs[:4])]
            chips += _nav(m, lang, tr(lang, "Дальше: сценарий серии →", "Next: episode script →"), bool(done))
        elif sid == "episode":
            ep = d.get("episode") or {}
            blocks.append({"type": "mode_text", "title": tr(lang, f"Серия {d.get('ep', 1)}: ", f"Episode {d.get('ep', 1)}: ") + (ep.get("title") or ""),
                           "text": "\n".join(f"{n}. {s.get('shot', '')}" + (f" — {s['text']}" if s.get("text") else "") for n, s in enumerate(ep.get("scenes") or [], 1)),
                           "note": tr(lang, "Поправить — напишите, что изменить.", "To change it, write what to change.")})
            if ep.get("template"):
                lines.append(tr(lang, "Нейросеть-сценарист сейчас недоступна — собрала каркас серии, его легко поправить.",
                                "The script writer is unavailable — here is an episode skeleton to edit."))
            chips = [chip(tr(lang, "↻ Переписать", "↻ Rewrite"), "mode_redo")] + _nav(m, lang, tr(lang, "Дальше: раскадровка →", "Next: storyboard →"), True)
        elif sid == "board":
            lines.append(tr(lang, "Разложу серию на кадры. Портреты героев из этого чата отмечу референсами.",
                            "I’ll split the episode into frames and mark hero portraits from this chat as references."))
            chips = [chip(tr(lang, "🎞 Собрать раскадровку", "🎞 Build the storyboard"), "mode_go", "board", primary=True)] + _nav(m, lang, tr(lang, "Пропустить →", "Skip →"))
        elif sid == "video":
            lines.append(tr(lang, "Соберу видео серии по раскадровке, первый кадр — портрет героя.", "I’ll make the episode video from the storyboard, hero as the first frame."))
            chips = [chip(tr(lang, "🎬 Сделать видео", "🎬 Make the video"), "mode_go", "video", primary=True)] + _nav(m, lang, tr(lang, "Пропустить →", "Skip →"))
        elif sid == "next":
            ep = d.get("episode") or {}
            lines.append(tr(lang, f"Серия {d.get('ep', 1)} готова" + (f": «{ep.get('title')}»" if ep.get("title") else "") + ". Герои и мир сохранены — следующая серия продолжит историю.",
                            f"Episode {d.get('ep', 1)} is done. Heroes and world are kept — the next episode continues the story."))
            chips = [chip(tr(lang, f"▶ Серия {int(d.get('ep', 1)) + 1}", f"▶ Episode {int(d.get('ep', 1)) + 1}"), "mode_episode", primary=True),
                     chip(tr(lang, "✅ Завершить сериал", "✅ Finish the series"), "mode_exit", "done")] + _nav(m, lang, next_label=False)[:-1]
    return response(lines, chips, blocks, lang, intent=f"mode_{m['id']}_{sid}")


# ─────────────────────────────────────────── вход, текст, переходы
def start(a: Any, ses: dict, ctx: dict, lang: str, mode_id: str, text: str = "") -> dict:
    if mode_id not in MODES:
        mode_id = "reels"
    ses["mode"] = {"id": mode_id, "step": 0, "data": {"ep": 1} if mode_id == "series" else {}, "paused": False}
    for k in ("assist_mode",):
        if ses.get(k) == "sb":
            ses[k] = None
    PL.state(ses)["on"] = True
    rest = MODE_WORDS.sub(" ", text or "").strip(" :.,—-\n")
    rest = re.sub(r"^(про|о|об|about)\s+", "", rest, flags=re.I).strip()
    if rest and len(rest.split()) >= 2 and BR.has_subject(rest):
        return on_text(a, ses, ctx, lang, rest)
    name = MODES[mode_id]["title"][1 if lang.startswith("en") else 0]
    steps = " → ".join(s["t"][1 if lang.startswith("en") else 0] for s in MODES[mode_id]["steps"])
    return show(a, ses, ctx, lang, tr(lang, f"Режим «{name}» по шагам: {steps}. На любом шаге можно задать вопрос или выйти.",
                                     f"“{name}” step by step: {steps}. Ask anything or leave at any step."))


def on_text(a: Any, ses: dict, ctx: dict, lang: str, msg: str) -> dict:
    m = active(ses)
    if not m:
        return show(a, ses, ctx, lang)
    s, d = cur(m), m["data"]
    text = msg.strip()[:1500]
    if m["id"] == "reels":
        if s["id"] == "idea":
            d["idea"] = text
            d["script"] = _write_reels(a, ses, lang, text)
            m["step"] = 1
            return show(a, ses, ctx, lang, tr(lang, "Написала сценарий с хуком на первые секунды:", "Here’s a script with a hook in the first seconds:"))
        if s["id"] == "script":
            d["script"] = _write_reels(a, ses, lang, d.get("idea") or text, change=text)
            return show(a, ses, ctx, lang, tr(lang, "Переписала с учётом правки:", "Rewritten with your change:"))
    else:
        if s["id"] == "world":
            d["world"] = text
            got = _write_heroes(a, ses, lang, text)
            d.update(heroes=got["heroes"], genre=got.get("genre", ""), portraits=[])
            if got.get("world"):
                d["world"] = got["world"] if len(got["world"]) > len(text) else text
            m["step"] = 1
            return show(a, ses, ctx, lang, tr(lang, "Вот герои. Сделаем портреты — по ним лица будут одинаковыми во всех сериях:",
                                              "Here are the heroes. Let’s make portraits so faces stay consistent:"))
        if s["id"] == "episode":
            d["episode"] = _write_episode(a, ses, lang, d, change=text)
            return show(a, ses, ctx, lang, tr(lang, "Переписала серию:", "Episode rewritten:"))
    return show(a, ses, ctx, lang)


def _enter_step(a: Any, ses: dict, ctx: dict, lang: str, head: str = "") -> dict:
    m = state(ses)
    if m["id"] == "series" and cur(m)["id"] == "episode" and not m["data"].get("episode"):
        m["data"]["episode"] = _write_episode(a, ses, lang, m["data"])
        head = head or tr(lang, "Написала сценарий серии:", "Here’s the episode script:")
    return show(a, ses, ctx, lang, head)


def action(a: Any, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Кнопки режима: mode_start | mode_input | mode_next | mode_back | mode_redo | mode_go | mode_episode |
    mode_exit | mode_pause | mode_resume."""
    if kind == "mode_start":
        return start(a, ses, ctx, lang, str(value or "reels") if not isinstance(value, dict) else str(value.get("id") or "reels"),
                     text=(value or {}).get("text", "") if isinstance(value, dict) else "")
    m = state(ses)
    if not m:
        return a._offer_types([tr(lang, "Режим уже закрыт — выберите, что делаем.", "The mode is closed — pick what to do.")], ctx, ses, lang, "mode_none")
    m["paused"] = False
    if kind == "mode_input":
        return on_text(a, ses, ctx, lang, str(value or ""))
    if kind == "mode_resume":
        return show(a, ses, ctx, lang, tr(lang, "Возвращаемся.", "Back to it."))
    if kind == "mode_pause":
        m["paused"] = True
        return response([tr(lang, "Поставила режим на паузу. Вернуться — кнопкой ниже.", "The mode is paused. Return with the button below.")],
                        [resume_chip(ses, lang)], [], lang, intent="mode_pause")
    if kind == "mode_next":
        if m["step"] < len(_steps(m)) - 1:
            m["step"] += 1
        return _enter_step(a, ses, ctx, lang)
    if kind == "mode_back":
        m["step"] = max(0, m["step"] - 1)
        return show(a, ses, ctx, lang)
    if kind == "mode_redo":
        d = m["data"]
        if m["id"] == "reels" and d.get("idea"):
            d["script"] = _write_reels(a, ses, lang, d["idea"], change=tr(lang, "другой вариант, другой хук", "another take, another hook"))
        elif m["id"] == "series" and cur(m)["id"] == "episode":
            d["episode"] = _write_episode(a, ses, lang, d, change=tr(lang, "другой вариант серии", "another take"))
        return show(a, ses, ctx, lang, tr(lang, "Другой вариант:", "Another take:"))
    if kind == "mode_episode":
        d = m["data"]
        ep = d.get("episode") or {}
        d.setdefault("episodes", []).append((ep.get("title") or "") + ": " + (ep.get("summary") or ""))
        d["ep"] = int(d.get("ep") or 1) + 1
        d["episode"] = None
        m["step"] = next(i for i, s in enumerate(_steps(m)) if s["id"] == "episode")
        return _enter_step(a, ses, ctx, lang)
    if kind == "mode_exit":
        name = MODES[m["id"]]["title"][1 if lang.startswith("en") else 0]
        done = value == "done"
        ses["mode"] = None
        return a._offer_types([tr(lang, f"«{name}» — готово! Всё, что сделали, — в артефактах этого чата и в «Моих работах»." if done
                                  else f"Вышла из режима «{name}». Артефакты остались в этом чате.",
                                  f"“{name}” — done! Everything is in this chat’s artifacts and “My works”." if done
                                  else f"Left “{name}”. Artifacts stay in this chat.")], ctx, ses, lang, "mode_exit")
    if kind == "mode_go":
        return go(a, ses, ctx, lang, str(value or ""))
    return show(a, ses, ctx, lang)


def _scenario(m: dict) -> str:
    d = m["data"]
    if m["id"] == "reels":
        sc = d.get("script") or {}
        return (_scenes_plain(sc) or d.get("idea") or "").strip()
    ep = d.get("episode") or {}
    return (" ".join(f"{s.get('shot', '').rstrip('.')}. {s.get('text', '')}".strip() for s in ep.get("scenes") or [])
            or d.get("world") or "").strip()


def go(a: Any, ses: dict, ctx: dict, lang: str, what: str) -> dict:
    """Шаг с генерацией — передаём работу существующим флоу; результат вернёт pipe_result → after_result."""
    m = state(ses)
    d = m["data"]
    scen = _scenario(m)
    if what == "board":
        out = SB.start(a, ses, ctx, lang, "new", text=scen or (d.get("idea") or d.get("world") or ""))
        return PL.decorate(out, ses, lang)
    if what == "video":
        if not PL.last(ses, "board") and not PL.last(ses, "videoPrompt") and scen:
            PL.save(ses, "prompt", "videoPrompt", tr(lang, "Промпт видео", "Video prompt"),
                    text=("Vertical 9:16 video. " if m["id"] == "reels" else "") + scen[:3000])
        return PL.video(a, ses, ctx, lang)
    if what == "voice":
        sc = d.get("script") or {}
        said = " ".join(s.get("text", "") for s in sc.get("scenes") or [] if s.get("text"))
        return PL.voice(a, ses, ctx, lang, text=said or scen[:800])
    if what == "music":
        idea = tr(lang, "Фоновая музыка для рилса, 30 секунд: ", "Background music for a reel, 30 seconds: ") + (d.get("idea") or scen)[:300]
        a._new_task("music", idea, [], "music", ses)
        PL.state(ses).update(on=True, stage="voice", expect="voice")
        return a._offer_models_for_kind(ctx, ses, lang, "mode_music", mode="direct")
    if what.startswith("hero:"):
        try:
            i = int(what.split(":", 1)[1])
            h = d.get("heroes")[i]
        except (ValueError, IndexError, TypeError):
            return show(a, ses, ctx, lang)
        d["hero_pending"] = i
        style = f" {d['genre']} series." if d.get("genre") else ""
        return PL.image(a, ses, ctx, lang, "hero", desc=f"{h['name']}: {h['look']}.{style}")
    return show(a, ses, ctx, lang)


def after_result(a: Any, ses: dict, ctx: dict, lang: str, value: Any, out: dict) -> dict:
    """Готова генерация: если она закрывает текущий шаг режима — переходим к следующему и показываем его."""
    m = active(ses)
    if not m or not isinstance(value, dict):
        return out
    kind = str(value.get("kind") or "")
    s = cur(m)
    need = s.get("result")
    if not need:
        return out
    hit = ((need == "board" and kind == "image" and (value.get("series") or PL.last(ses, "board")))
           or (need == "video" and kind == "video") or (need == "audio" and kind == "audio")
           or (need == "hero" and kind == "image"))
    if not hit:
        return out
    if need == "hero":
        i = m["data"].pop("hero_pending", None)
        if i is not None:
            m["data"].setdefault("portraits", [])
            if i not in m["data"]["portraits"]:
                m["data"]["portraits"].append(i)
        if len(m["data"]["portraits"]) < len(m["data"].get("heroes") or []):
            nxt = show(a, ses, ctx, lang, tr(lang, "Портрет готов и сохранён референсом. Следующий герой:",
                                             "Portrait saved as a reference. Next hero:"))
            return _merge(out, nxt)
    if m["step"] < len(_steps(m)) - 1:
        m["step"] += 1
    nxt = _enter_step(a, ses, ctx, lang, tr(lang, "Шаг готов — идём дальше.", "Step done — moving on."))
    return _merge(out, nxt)


def _merge(out: dict, nxt: dict) -> dict:
    if not out or out.get("silent"):
        return nxt
    for k in ("text", "reply"):
        nxt[k] = (out.get(k) or "") + ("\n\n" if out.get(k) else "") + (nxt.get(k) or "")
    nxt["blocks"] = list(out.get("blocks") or []) + list(nxt.get("blocks") or [])
    return nxt
