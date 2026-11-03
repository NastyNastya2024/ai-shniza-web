"""Дерево подсказок помощника: вектор → подвектор → user story → шаг → реакция → контекст → подсказки.

Как работает в ответе помощника (engine.Assistant.handle):
  1. Ядро (engine) отвечает как раньше: генерации, модели, промпты, вопросы, ошибки, безопасность.
  2. Дерево определяет, в какой истории и на каком шаге человек, какой была его реакция на прошлые подсказки,
     и добавляет к ответу кнопки следующего шага (on_turn). Если ядро не поняло фразу, а дерево узнало историю —
     кнопки дерева идут первыми и в тексте появляется строка «Похоже, задача — …».
  3. Вопрос посреди истории ядро отвечает само (правила + нейросеть), дерево добавляет «↩ вернуться к шагу».
     Так помощник пользуется деревом, но при необходимости отвечает сверх него.

Источник: assistant/data/hint_tree.json (сборка: scripts/build_hint_tree.py). Опубликованная в админке версия
подменяет файл без рестарта (HintTree.load_json / Assistant.d.tree = …). Правила листьев совпадают с генератором
эталона ai-shnitsa-hint-leaves-vX.jsonl — это проверяет tests/assistant/test_hint_tree.py.

В подсказках и ответах не называем внутреннюю архитектуру и поставщиков API — только модели каталога и MCP,
которые человек подключает сам.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Callable
from urllib.parse import quote

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "hint_tree.json")

MCP_WORDS = ['vidIQ', 'Higgsfield', 'Dropbox', 'Meshy', 'Tripo', 'Blender', 'DaVinci', 'FFmpeg', 'ElevenLabs', 'Viral',
             'MCP', 'мост', 'виральност']
DESKTOP_ONLY = ['Blender', 'DaVinci', 'FFmpeg', 'мост']
PAID_WORDS = ['Видео', 'видео', 'Оживить', 'Озвуч', 'Музык', 'Песн', 'Апскейл', 'Рендер', 'Сцена', 'Портрет', 'Генер',
              'кадр', 'Ещё', 'Перенести', 'Карусель', 'Пачк', 'Стиль']
GEN_FREE_VEC = ('INT', 'ADM', 'HLP')            # векторы без генерации: нет R08/R10/R14
CTX_VEC = {                                     # где контекст вообще имеет смысл (как в генераторе эталона)
    'C7': ('IMG', 'VID', 'STO', 'PER', 'COM', 'DSN', 'MKT', 'ART'),
    'C5': ('VID', 'STO', 'COM', 'PER'),
}
STYLE_VEC = ('IMG', 'VID', 'STO', 'PER', 'COM', 'DSN', 'MKT', 'ART')
# ядро не справилось само — кнопки дерева первыми
WEAK_INTENTS = {"unknown", "junk", "off_topic", "ask_type", "question", "smalltalk", "need_subject"}
# ответы, к которым дерево ничего не добавляет
BLOCK_INTENTS = {"crisis", "safety", "safety_person", "injection", "internal_error"}
QUESTION_INTENTS = {"question", "question_models", "ui_help", "price", "compare", "error_help"}
# кнопки ядра, которые нельзя вытеснять подсказками
FUNCTIONAL = re.compile(r"^(generate|generate_series|pick_model|param|use_variant|variants|more_variants|brief|add_prompt|"
                        r"has_prompt|use_mine|skip_polish|pick_camera|open_topup|login|sb_|pipe_(?!stage|menu)|mode_|reel_)")
MAX_TREE_CHIPS = 4
ADVANCE = ("R01", "R02", "R06", "R14", "R05")      # после этих реакций история идёт на следующий шаг
MAX_CHIPS = 8
_STOP = set("это как что для мне меня нужно надо хочу сделай сделать можно чтобы если или под над при про без все ещё уже "
            "the and for with make need want please".split())


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower())
    return {w[:5] for w in words if len(w) >= 3 and w not in _STOP}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def _sid_hash(sid: str) -> str:
    return hashlib.sha256(("tree:" + (sid or "")).encode()).hexdigest()[:16] if sid else ""


# ===================================================================== данные дерева
class HintTree:
    def __init__(self, data: dict):
        self.data = data
        self.version = str(data.get("version") or "0.0.0")
        self.reactions: dict = data.get("reactions") or {}
        self.contexts: dict = data.get("contexts") or {}
        self.finish: dict = data.get("finish") or {}
        self.what_wrong: dict = data.get("what_wrong") or {}
        self.rules: dict = data.get("rules") or {}
        self.professions = {p["id"]: p for p in data.get("professions") or []}
        self.stories: dict[str, dict] = {}
        self.vec_of: dict[str, tuple[dict, dict]] = {}
        self.vectors: dict[str, dict] = {}
        self._kw: dict[str, set[str]] = {}
        self._sig: dict[str, list[str]] = {}
        for v in data.get("vectors") or []:
            self.vectors[v["id"]] = v
            self._sig[v["id"]] = [w.lower() for w in v.get("signals") or []]
            for s in v.get("subs") or []:
                for o in s.get("stories") or []:
                    if o.get("status", "active") != "active":
                        continue
                    self.stories[o["id"]] = o
                    self.vec_of[o["id"]] = (v, s)
                    first = o["steps"][0]["step"] if o.get("steps") else ""
                    self._kw[o["id"]] = _stems(o["title"]) | (_stems(first) if first.startswith("«") else set())
        self.sub_keywords: dict[str, list[str]] = {}
        kw_path = os.path.join(os.path.dirname(__file__), "data", "dialog_keywords.json")
        try:
            with open(kw_path, encoding="utf-8") as fh:
                extra = json.load(fh)
        except Exception:
            extra = {}
        for v in data.get("vectors") or []:
            for s in v.get("subs") or []:
                sid = s.get("id") or ""
                raw = extra.get(sid) or []
                extra_words = raw.get("keywords") if isinstance(raw, dict) else raw
                if isinstance(raw, dict) and raw.get("slots") and not s.get("slots"):
                    s["slots"] = list(raw["slots"])
                words = [str(w).lower() for w in (s.get("keywords") or [])]
                words += [str(w).lower() for w in (extra_words or [])]
                if words and sid:
                    s["keywords"] = list(dict.fromkeys(words))
                    self.sub_keywords[sid] = s["keywords"]
        self.out_nodes = [o for o in data.get("out_of_platform") or [] if not str(o.get("id", "")).startswith("TYPE")]
        self._out_kw = [(o, _stems(o.get("request", ""))) for o in self.out_nodes]

    @classmethod
    def load_json(cls, path: str | None = None) -> "HintTree":
        with open(path or os.getenv("ASSIST_TREE_PATH") or DATA_PATH, encoding="utf-8") as f:
            return cls(json.load(f))

    # ------------------------------------------------------------ сводка для админки
    def summary(self) -> dict:
        vecs = []
        for v in self.data.get("vectors") or []:
            subs = [{"id": s["id"], "title": s["title"], "examples": s.get("examples") or [],
                     "stories": [{"id": o["id"], "title": o["title"], "steps": len(o.get("steps") or []),
                                  "priority": o.get("priority"), "professions": o.get("professions") or [],
                                  "status": o.get("status", "active")} for o in s.get("stories") or []]}
                    for s in v.get("subs") or []]
            vecs.append({"id": v["id"], "title": v["title"], "subs": subs})
        return {"version": self.version, "vectors": vecs, "professions": list(self.professions.values()),
                "rules": self.rules}

    # ------------------------------------------------------------ распознавание
    def vector_scores(self, msg: str) -> dict[str, float]:
        low = (msg or "").lower()
        out: dict[str, float] = {}
        for vid, words in self._sig.items():
            n = sum(1 for w in words if w and w in low)
            if n:
                out[vid] = float(n)
        return out

    def match(self, msg: str, kind: str | None = None, profession: str | None = None,
              exclude: str | None = None) -> tuple[str | None, float]:
        """Лучшая история для фразы. Профессия поднимает «свои» истории, приоритет low — опускает."""
        st = _stems(msg)
        if not st:
            return None, 0.0
        mcpish = bool(re.search(r"\bmcp\b|мсп|vidiq|подключ", msg or "", re.I))
        if (not mcpish) and re.search(r"тем[аеуы]", msg or "", re.I) and re.search(r"т[её]мн|ч[её]рн|светл", msg or "", re.I):
            for prefer in ("HLP.UI.S02", "HLP.UI.S01"):
                if prefer in self.stories:
                    return prefer, 5.0
        vs = self.vector_scores(msg)
        kind_vec = {"video": ("VID", "STO", "DSN"), "image": ("IMG", "DSN", "ART", "COM"), "edit": ("IMG", "EDT", "ART"),
                    "music": ("AUD",), "sfx": ("AUD",), "text": ("HLP", "MKT")}.get(kind or "", ())
        prof_nodes = set((self.professions.get(profession) or {}).get("primary_nodes") or [])
        best, best_s = None, 0.0
        for sid, kw in self._kw.items():
            if sid == exclude:
                continue
            hit = len(st & kw)
            if not hit:
                continue
            v, s = self.vec_of[sid]
            o = self.stories[sid]
            score = 2.0 * hit + 0.5 * vs.get(v["id"], 0.0) + (0.5 if v["id"] in kind_vec else 0.0)
            if profession and (profession in (o.get("professions") or []) or s["id"] in prof_nodes):
                score += 1.5
            if o.get("priority") == "low" and not re.search(r"интерфейс|экран|кнопк|иконк|figma|ui\b|ux\b", msg, re.I):
                score -= 2.0
            mcpish = bool(re.search(r"\bmcp\b|мсп|vidiq|подключ", msg or "", re.I))
            if mcpish and s["id"] == "INT.CONNECT":
                score += 3.5
            if mcpish and (s["id"] == "HLP.UI" or v["id"] == "HLP"):
                score -= 6.0
            if (not mcpish) and s["id"] == "HLP.UI" and re.search(r"тем[аеуы]|интерфейс|оформлен|кнопк|язык", msg or "", re.I):
                score += 2.5
            if score > best_s:
                best, best_s = sid, score
        if best_s < float(self.rules.get("story_min_score", 3.0)):
            return None, best_s
        return best, best_s

    def match_sub(self, msg: str) -> str | None:
        """Подвектор по keywords (синонимы, бренды). None — история не узнана."""
        low = (msg or "").lower()
        best, nbest = None, 0
        for sid, words in self.sub_keywords.items():
            n = sum(1 for w in words if w and w in low)
            if n > nbest:
                best, nbest = sid, n
        return best

    def match_out(self, msg: str) -> dict | None:
        st = _stems(msg)
        if len(st) < 2:
            return None
        best, best_n = None, 0
        for o, kw in self._out_kw:
            n = len(st & kw)
            if n > best_n and n >= max(2, int(len(kw) * 0.6)):
                best, best_n = o, n
        return best

    # ------------------------------------------------------------ листья (те же правила, что у эталона)
    def leaf(self, story_id: str, i: int, rid: str) -> dict | None:
        o = self.stories.get(story_id)
        if not o:
            return None
        vec = self.vec_of[story_id][0]["id"]
        steps = o.get("steps") or [{"step": "Старт", "hints": self.finish.get(vec, [])}]
        i = max(0, min(i, len(steps) - 1))
        for r, hints, log, rule in self._leaves_for_step(o["title"], vec, steps, i):
            if r == rid:
                return {"hints": hints, "log": log, "rule": rule, "id": f"{story_id}.T{i + 1}.{rid}"}
        return None

    def step_hints(self, story_id: str, i: int) -> list[str]:
        o = self.stories.get(story_id)
        if not o:
            return []
        vec = self.vec_of[story_id][0]["id"]
        steps = o.get("steps") or []
        if i >= len(steps):
            return list(self.finish.get(vec, []))
        return list(steps[i].get("hints") or self.finish.get(vec, []))

    def _leaves_for_step(self, story: str, vec: str, steps: list[dict], i: int) -> list[tuple]:
        fin = self.finish.get(vec, [])
        st = steps[i]
        cur = st.get("hints") or fin
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        nxt_h = (nxt.get("hints") or fin) if nxt else fin
        nxt_name = nxt["step"] if nxt else 'Финал истории'
        out: list[tuple] = []
        no_result = st["step"].startswith('«') or st["step"] == 'Старт'

        def L(rid: str, hints: list[str], log: str, rule: str) -> None:
            if no_result and rid in ('R06', 'R07', 'R08', 'R14'):
                return
            out.append((rid, hints[:4], log, rule))

        L('R01', nxt_h, f'story_runs: шаг {i + 2 if nxt else "конец"}', 'нажатая подсказка ведёт на следующий шаг ветки')
        alt = cur[1] if len(cur) > 1 else cur[0]
        L('R02', [f'↩ Основной путь: {nxt_name}'] + nxt_h[:2], f'story_runs: ветка «{alt}»',
          'альтернативная ветка, возврат на основной путь первой кнопкой')
        L('R03', [f'Дальше: {nxt_name}'] + [x for x in cur if x != cur[0]][:2], 'шаг тот же, правка учтена',
          'правка выполняется, затем шаг вперёд')
        L('R04', (cur[1:] + cur[:1])[:3], 'ignore: +1 к первой подсказке', 'проигнорированная уходит в конец')
        L('R05', [f'Дальше: {nxt_name}'] + nxt_h[:2], 'ветка понижена до конца истории', 'дважды проигнорировано — не показывать')
        L('R06', nxt_h[:2] + (['Сохранить стиль'] if vec in STYLE_VEC else ['На витрину']), 'like',
          'лайк: следующий шаг + закрепить удачное')
        gen = vec not in GEN_FREE_VEC
        L('R07', ['Что не так? ' + ' · '.join(self.what_wrong.get(vec, []))], 'dislike → уточнение причины',
          'сначала причина, потом смена модели')
        if gen:
            L('R08', ['Другая модель (цена)', 'Уточнить промпт вместе', f'Дальше как есть: {nxt_name}'], 'regen×2',
              'та же модель редко меняет суть')
            L('R09', ['Повторить', 'Другая модель того же типа (цена)'], 'error; деньги не списаны', 'техническая ошибка')
        else:
            L('R09', ['Повторить', 'Показать ответ целиком', 'Написать в поддержку'], 'error', 'ошибка сервиса или сервера')
        if gen:
            L('R10', ['Похожая модель дешевле (хватает)', 'Пополнить на недостающую сумму']
              + (['Бесплатно на Seedance'] if vec in ('VID', 'PER', 'STO') else []), 'need_topup', 'нехватка видна до запуска')
        L('R11', [f'↩ {story}: шаг {i + 1}'] + cur[:2], 'question; история на паузе', 'ответ, затем возврат первой кнопкой')
        L('R12', ['(выполнить задачу)', f'↩ Вернуться к «{story}»'], 'off_story +1; при 3 подряд → story_candidates',
          'вне истории — пауза, кандидат в новую историю')
        L('R13', [f'↩ Продолжить «{story}» с шага {i + 1}'] + cur[:2], 'resume', 'история живёт 24 ч, дальше — в «Моих работах»')
        if gen:
            L('R14', nxt_h[:2] + ['Ещё в этом стиле'], 'download', 'скачал — значит результат принят')
        L('R15', ['Добавить файл в текущую историю', 'Новая задача с этим файлом'] + cur[:1], 'attachment mid-story',
          'новое вложение посреди истории: спросить, к чему оно')
        return out

    @staticmethod
    def apply_ctx(hints: list[str], ctx: str, vec: str) -> tuple[list[str], str]:
        h = list(hints)
        notes: list[str] = []
        if ctx == 'C1':
            repl = []
            for x in h:
                if any(w.lower() in x.lower() for w in DESKTOP_ONLY):
                    notes.append('десктопное MCP заменено облачным')
                    repl.append('Облачная альтернатива (без компьютера)')
                else:
                    repl.append(x)
            h = list(dict.fromkeys(repl))[:3]
            notes.append('максимум 3 кнопки')
        elif ctx == 'C2':
            out, seen = [], False
            for x in h:
                n = next((w for w in MCP_WORDS if w.lower() in x.lower()), None)
                if n:
                    if not seen:
                        out.append(f'Подключить {n} (1 минута)')
                        seen = True
                    notes.append('MCP-подсказка → «Подключить»')
                else:
                    out.append(x)
            h = out
        elif ctx == 'C3':
            out = [x + ' (нужно пополнить)' if any(w in x for w in PAID_WORDS) else x for x in h]
            if vec in ('VID', 'PER', 'STO'):
                out.append('Бесплатно на Seedance')
            out.append('Пополнить')
            h = out
            notes.append('цена и нехватка видны до запуска')
        elif ctx == 'C5':
            h = ['Следующий шаг режима'] + h[:2] + ['Выйти из режима']
            notes.append('в режиме первая кнопка — шаг режима')
        elif ctx == 'C6':
            out = [x + ' (после входа)' if any(w in x for w in PAID_WORDS) else x for x in h]
            h = out[:3] + ['Войти: Google · Яндекс · VK · Telegram · телефон']
            notes.append('после входа — возврат к той же подсказке')
        elif ctx == 'C7':
            h = ['В моём сохранённом стиле'] + h[:2] + ['Мои стили…']
            notes.append('сохранённое поднимается первым')
        elif ctx == 'C4':
            h = h[:3] + ['Ещё…']
            notes.append('тип не влияет на порядок; подсказки по истории')
        return h[:4], '; '.join(dict.fromkeys(notes))

    def ctx_allowed(self, c: str, vec: str) -> bool:
        if c in CTX_VEC and vec not in CTX_VEC[c]:
            return False
        if c == 'C6' and vec in ('ADM', 'INT'):
            return False
        if c == 'C3' and vec == 'ADM':
            return False
        return True


# ===================================================================== состояние в сессии
def state(ses: dict) -> dict:
    st = ses.get("tree")
    if not isinstance(st, dict):
        st = ses["tree"] = {"story": None, "step": 0, "shown": [], "ign": {}, "off": 0, "trail": [], "ts": 0,
                            "prof": None, "pc": {}, "just": None, "ver": None}
    return st


def profession(st: dict, ctx: dict) -> str | None:
    p = str(ctx.get("profession") or "").strip().upper()
    if p:
        return p
    if st.get("prof"):
        return st["prof"]
    pc = st.get("pc") or {}
    if pc:
        top, n = max(pc.items(), key=lambda kv: kv[1])
        if n >= 2:
            return top
    return None


def pick_context(a: Any, tree: HintTree, vec: str, hints: list[str], ctx: dict, ses: dict, prof: str | None) -> str:
    """Один контекст на ответ, по важности: гость → мало денег → режим → телефон → нет MCP → свои стили → тип неясен."""
    from . import modes as MD
    acc = ctx.get("_account") if isinstance(ctx.get("_account"), dict) else None
    low_kop = int(tree.rules.get("low_balance_kop", 3000))
    cands = []
    if a._is_guest(ctx):
        cands.append("C6")
    if acc and acc.get("authed") and acc.get("available_kop") is not None and int(acc.get("available_kop") or 0) < low_kop:
        cands.append("C3")
    if MD.active(ses):
        cands.append("C5")
    if str(ctx.get("device") or "") == "mobile":
        cands.append("C1")
    if ctx.get("mcp_connected") is False and any(any(w.lower() in h.lower() for w in MCP_WORDS) for h in hints):
        cands.append("C2")
    if ctx.get("saved_styles"):
        cands.append("C7")
    if not prof:
        cands.append("C4")
    for c in cands:
        if tree.ctx_allowed(c, vec):
            return c
    return "C0"


# ===================================================================== кнопки
_CAM_ALIAS = {"orbit": "orbit-cw", "дрон": "drone-push", "облёт": "orbit-cw", "таймлапс": "time-lapse"}


def camera_move(label: str) -> dict | None:
    """«Пример: Dolly in», «Движение камеры: Crane up», «Облёт (Drone push in)» → движение из camera.MOVES."""
    from . import camera as CAM
    low = label.lower()
    best = None
    for m in CAM.MOVES:
        t = m["title_en"].lower()
        if t and t in low and (best is None or len(t) > len(best["title_en"])):
            best = m
    if best is None:
        for word, mid in _CAM_ALIAS.items():
            if re.search(r"\b" + word + r"\b", low):
                return CAM.get(mid)
    return best


def showcase_work(label: str) -> str | None:
    """«Пример: Liquid Silver Orbit» → id официальной работы витрины (aish-liquid-silver-orbit) с открытым промптом."""
    m = re.match(r"^(?:пример|example)\s*:\s*(.+)$", label.strip(), re.I)
    if not m:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", m.group(1).lower()).strip("-")
    return ("aish-" + slug) if slug and slug in AISH_WORKS else None


AISH_WORKS = {"invisible-dancer", "pressure-surgery", "liquid-silver-orbit", "apartment-speed-ramp", "lime-hypercar-build",
              "invisible-man-looks", "cherry-red-manicure", "beach-house-origami", "diamond-kiss", "canyon-sofa-select",
              "orange-skincare", "red-mannequin-transform", "mclaren-sky-launch", "ginger-icon-glasses"}


def _image_already(ses: dict | None, ctx: dict | None) -> bool:
    if (ctx or {}).get("has_image"):
        return True
    return any(isinstance(f, dict) and f.get("kind") == "image" for f in ((ses or {}).get("files") or []))


def video_context(a: Any, ses: dict | None, ctx: dict | None) -> bool:
    """Помощник уже настраивает видео — движение камеры ставим кнопкой pick_camera, а не уводим на витрину."""
    if not ses:
        return False
    card = a.d.cards.get(ses.get("picked") or "") if ses.get("picked") else None
    return (card is not None and card.kind == "video") or ses.get("kind") == "video" or ses.get("gen_kind") == "video"


def hint_chip(label: str, a: Any, st: dict, idx: int, lang: str, ses: dict | None = None,
              ctx: dict | None = None) -> dict | None:
    from . import camera as CAM
    from .render import chip
    if label.startswith("(") and label.endswith(")"):          # «(выполнить задачу)» — служебная пометка, не кнопка
        return None
    base = {"s": st.get("story"), "t": st.get("step"), "i": idx, "label": label[:80]}
    low = label.lower()
    if "пополнить" in low:
        return chip(label, "open_topup")
    if low.startswith("войти"):
        return chip("Войти", "login")
    if re.match(r"^(загрузить|прикрепить|attach|upload)\b", low):
        return chip(label, "attach")
    if low.startswith("подключить "):
        return chip(label, "open_panel", "mcp")
    if low.startswith("выйти из режима"):
        return chip(label, "mode_exit")
    if low == "повторить":
        return chip(label, "retry")
    if low.startswith("другая модель") or low.startswith("похожая модель дешевле"):
        return chip(label, "cheaper" if "дешевле" in low else "more")
    if low.startswith("уточнить промпт"):
        return chip(label, "improve")
    if "бесплатно на seedance" in low and "veo-free-seedance" in (a.d.cards or {}):
        return chip(label, "pick_model", "veo-free-seedance")
    # раскадровка — в текущий режим «Раскадровка» (storyboard.py), а не отдельным путём
    if "раскадров" in low or "storyboard" in low:
        return chip(label, "sb_start")
    # движение камеры — в текущий выбор камеры (camera.py): в настройке видео сразу ставим, иначе — пример с промптом
    work = showcase_work(label)
    if work:
        return chip(label, "open_work", work)
    mv = camera_move(label)
    if mv and (low.startswith("пример") or "камер" in low or "облёт" in low or "движен" in low or "(" in label
               or low == mv["title_en"].lower()):
        if video_context(a, ses, ctx):
            return chip(label, "pick_camera", mv["id"])
        return chip(label, "open_work", CAM.work_id(mv))
    g = re.match(r"^каталог:\s*(.+)$", label, re.I)
    if g:
        return chip(label, "open_vitrina", CAM.vitrina_href(group=g.group(1).strip()))
    if re.search(r"движени\w* камеры|ещё движение|сравнить 2 движения", low):
        return chip(label, "open_vitrina", CAM.vitrina_href())
    if low.startswith("пример с витрины") or low.startswith("пример:"):
        q = label.split(":", 1)[1].strip() if ":" in label else ""
        return chip(label, "open_vitrina", a.d.vitrina_url + ("?q=" + quote(q) if q else ""))
    if low.startswith("что не так?"):
        return None                                           # раскладывается на варианты в chips_for()
    return chip(label, "tree_hint", base)


_DROP_HINT = re.compile(r"^(попробовать|ещё вопрос|еще вопрос|вернуться к задаче|готово)$", re.I)
_FINALE = re.compile(r"финал истории", re.I)
_MAIN_PATH = re.compile(r"^↩\s*основной путь:\s*(.+)$", re.I)
_STEP_N = re.compile(r"^↩\s*(.+?):\s*шаг\s*\d+\s*$", re.I)
_CONTINUE_N = re.compile(r"^↩\s*продолжить «([^»]+)» с шага\s*\d+", re.I)
_AFTER = re.compile(r"^после «[^»]*»\.?\s*", re.I)
_FORBIDDEN = re.compile(r"основной путь|финал истории|шаг\s*\d|\(выполнить задачу\)", re.I)


def task_title(ses: dict | None, story_title: str = "") -> str:
    """Название задачи словами человека, без внутренних подписей дерева."""
    if isinstance(ses, dict):
        flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else {}
        for src in (ses.get("idea"), flow.get("source"), flow.get("idea_user")):
            s = str(src or "").strip().split("\n")[0]
            if s and not _FORBIDDEN.search(s):
                return s[:40]
    title = (story_title or "").strip()
    if title and not _FORBIDDEN.search(title):
        return title[:40]
    return "задаче"


def present_hint(label: str, task: str = "") -> str | None:
    """Подпись для человека. None — подсказку не показываем: нет действия или внутренние слова."""
    raw = (label or "").strip()
    if not raw or (raw.startswith("(") and raw.endswith(")")):
        return None
    if _DROP_HINT.match(raw) or _FINALE.search(raw):
        return None
    m = _MAIN_PATH.match(raw)
    if m:
        nxt = _AFTER.sub("", m.group(1)).strip("«» .")
        if not nxt or _FINALE.search(nxt):
            return None
        return "↩ Дальше: " + nxt
    m = _STEP_N.match(raw) or _CONTINUE_N.match(raw)
    if m:
        return f"↩ Вернуться к «{task or 'задаче'}»"
    if _FORBIDDEN.search(raw):
        return None
    return raw


def chips_for(a: Any, hints: list[str], st: dict, lang: str, ses: dict | None = None, ctx: dict | None = None) -> list[dict]:
    from .render import chip
    story = ""
    tree = getattr(getattr(a, "d", None), "tree", None)
    if tree is not None and st.get("story") in getattr(tree, "stories", {}):
        story = tree.stories[st["story"]].get("title") or ""
    task = task_title(ses, story)
    out: list[dict] = []
    for i, h in enumerate(hints):
        low = h.lower()
        if low.startswith("что не так?"):
            for opt in [x.strip() for x in h.split("?", 1)[1].split("·") if x.strip()]:
                shown = present_hint(opt, task)
                if shown:
                    out.append(chip(shown, "tree_hint", {"s": st.get("story"), "t": st.get("step"), "i": i, "label": shown, "why": 1}))
            continue
        if low in ("что ещё можно настроить", "что еще можно настроить"):
            out.append(chip("Что ещё можно настроить", "ui_more"))
            continue
        if low == "попробовать на последнем результате":
            out.append(chip("Попробовать на последнем результате", "mcp_try"))
            continue
        if low == "следующий инструмент":
            out.append(chip("Другой сервис", "open_panel", "mcp"))
            continue
        shown = present_hint(h, task)
        if not shown:
            continue
        if re.match(r"^(загрузить|прикрепить|attach|upload)\b", shown.lower()) and _image_already(ses, ctx):
            continue
        c = hint_chip(shown, a, st, i, lang, ses, ctx)
        if c:
            out.append(c)
    return out


def merge(out: dict, tree_chips: list[dict], first: bool) -> dict:
    eng = list(out.get("chips") or [])
    seen = {_norm(c.get("label", "")) for c in eng}
    functional = any(FUNCTIONAL.match(str(c.get("action") or "")) for c in eng)
    add = [c for c in tree_chips if _norm(c.get("label", "")) not in seen][:(2 if functional else MAX_TREE_CHIPS)]
    if first and not functional:
        chips = add + eng
    else:
        chips = eng + add
    out["chips"] = chips[:MAX_CHIPS]
    return out


# ===================================================================== ход диалога
def _log(a: Any, ses: dict, ctx: dict, kind: str, **kw: Any) -> None:
    fn = getattr(a.d, "tree_log", None)
    if not fn:
        return
    try:
        fn({"kind": kind, "uid": ctx.get("_uid"), "sid": ctx.get("_tree_sid") or "", "ts": int(time.time()), **kw})
    except Exception:
        pass


def _reaction_from_text(a: Any, tree: HintTree, st: dict, msg: str, out: dict, ctx: dict, ses: dict,
                        prof: str | None) -> tuple[str, str | None]:
    """Реакция на прошлые подсказки по свободному тексту. Вторым значением — новая история (для R12)."""
    n = _norm(msg)
    for i, h in enumerate(st.get("shown") or []):
        if n and (_norm(h) == n or (len(n) > 3 and _norm(h).startswith(n))):
            return ("R01" if i == 0 else "R02"), None
    if out.get("intent") in QUESTION_INTENTS:
        return "R11", None
    if ctx.get("attachments") and ctx.get("_files_changed"):
        return "R15", None
    other, score = tree.match(msg, ses.get("kind"), prof, exclude=st.get("story"))
    if other and other != st.get("story") and score >= float(tree.rules.get("story_min_score", 3.0)) + 1:
        return "R12", other
    shown = st.get("shown") or []
    if shown:
        first = shown[0]
        st["ign"][first] = int(st["ign"].get(first) or 0) + 1
        if st["ign"][first] >= 2:
            return "R05", None
        if len(msg.split()) <= 2:
            return "R04", None
    return "R03", None


def _advance(st: dict, rid: str) -> bool:
    if rid in ADVANCE:
        st["step"] = int(st.get("step") or 0) + 1
        return True
    return False


def _start(a: Any, tree: HintTree, st: dict, story_id: str, prof: str | None) -> None:
    st.update(story=story_id, step=0, shown=[], ign={}, off=0, just="START", ver=tree.version)
    for p in tree.stories[story_id].get("professions") or []:
        st["pc"][p] = int(st["pc"].get(p) or 0) + 1


def on_turn(a: Any, out: dict, msg: str, action: dict | None, ctx: dict, ses: dict, lang: str) -> dict:
    """Вызывается после ответа ядра. Добавляет подсказки дерева и out["tree"]. Ничего не ломает при сбое."""
    tree: HintTree | None = getattr(a.d, "tree", None)
    if tree is None or out.get("silent") or out.get("intent") in BLOCK_INTENTS or out.get("gate") in ("login", "topup"):
        return out
    if str(out.get("intent") or "").startswith("mcp"):
        return out
    st = state(ses)
    prof = profession(st, ctx)
    atype = str((action or {}).get("type") or "")
    flow = active_flow(ses, out)
    if flow:                                   # раскадровка / камера / этапы / режим ведут шаги сами — дерево не мешает
        return sync_flow(a, tree, st, out, flow, atype, ctx, ses, prof, msg)
    rid: str | None = None
    weak = out.get("intent") in WEAK_INTENTS or bool(out.get("degraded"))
    now = int(time.time())
    if st.get("just"):                         # реакцию уже учли (клик по подсказке / событие)
        rid = None if st["just"] == "START" else st["just"]
        st["just"] = None
    elif atype in ("restart",):
        st.update(story=None, step=0, shown=[], ign={}, off=0)
    elif atype and atype not in ("send",):
        return out                             # кнопки ядра: дерево молчит, чтобы не мешать шагам генерации
    elif not msg and ctx.get("last_error") and st.get("story"):
        rid = "R09"                            # генерация упала: ядро объясняет ошибку, дерево — «Повторить / другая модель»
    elif msg:
        if st.get("story") and st.get("ts") and now - int(st["ts"]) > float(tree.rules.get("resume_hours", 20)) * 3600:
            rid = "R13"
        elif st.get("story"):
            rid, other = _reaction_from_text(a, tree, st, msg, out, ctx, ses, prof)
            if rid == "R12":
                st["off"] = int(st.get("off") or 0) + 1
                _log(a, ses, ctx, "off_story", story=st.get("story"), step=st.get("step"), to=other, label=msg[:80],
                     streak=st["off"], profession=prof)
                if other:
                    _start(a, tree, st, other, prof)
                    st["just"] = None
                    rid = None
            else:
                st["off"] = 0
            if rid in ("R03", "R04", "R05"):
                _log(a, ses, ctx, "atypical", story=st.get("story"), step=st.get("step"), reaction=rid,
                     label=msg[:80], profession=prof)
        else:
            from . import dialog as DG
            if DG.mcp_about(msg):
                return out
            sid, score = tree.match(msg, out.get("kind") or ses.get("kind"), prof)
            min_s = float(tree.rules.get("story_min_score", 3.0))
            if sid and out.get("intent") in ("question", "ui_do", "ui_help", "question_models") and score < min_s + 1.5:
                sid = None
            if sid:
                _start(a, tree, st, sid, prof)
                st["just"] = None
                _log(a, ses, ctx, "start", story=sid, step=0, profession=prof)
            else:
                node = tree.match_out(msg) if weak else None
                if node:
                    return _out_reply(a, out, node, st, lang)
                trail = st.setdefault("trail", [])
                trail.append(msg[:60])
                del trail[:-5]
                if len(trail) >= int(tree.rules.get("new_path_streak", 3)):
                    _log(a, ses, ctx, "new_path", trail=list(trail), profession=prof)
                return out
    if not st.get("story") or st["story"] not in tree.stories:
        return out
    vec = tree.vec_of[st["story"]][0]["id"]
    i = int(st.get("step") or 0)
    if rid:
        lf = tree.leaf(st["story"], max(0, i - 1) if st.get("_advanced") else i, rid)
        if lf is None:
            rid = None
    if rid:
        hints = lf["hints"]
        leaf_id = lf["id"]
        if not st.get("_advanced"):
            _advance(st, rid)
    else:
        hints = tree.step_hints(st["story"], i)
        leaf_id = f"{st['story']}.T{i + 1}.START"
    st.pop("_advanced", None)
    c = pick_context(a, tree, vec, hints, ctx, ses, prof)
    if c != "C0" and (rid in (None, "R01", "R02", "R06", "R14")):
        h2, _note = tree.apply_ctx(hints, c, vec)
        if h2 != hints:
            hints = h2
        else:
            c = "C0"
    else:
        c = "C0"
    st["shown"] = [h for h in hints if not h.startswith("(")]
    st["ts"] = now
    tc = chips_for(a, hints, st, lang, ses, ctx)
    o = tree.stories[st["story"]]
    steps = o.get("steps") or []
    step_name = steps[min(int(st["step"]), len(steps) - 1)]["step"] if steps else ""
    if weak and not out.get("blocks") and rid in (None, "R03", "R04"):
        plain = _AFTER.sub("", step_name.strip("«» ")).strip()
        title = task_title(ses, o["title"])
        line = (f"Похоже, задача — «{title}». {plain}." if lang != "en"
                else f"Looks like: «{title}». {plain}.")
        out["text"] = (line + ("\n" + out["text"] if out.get("text") else "")).strip()
        out["reply"] = (line + ("\n" + out["reply"] if out.get("reply") else "")).strip()
    merge(out, tc, first=weak)
    out["tree"] = {"version": tree.version, "path": [vec, tree.vec_of[st["story"]][1]["id"], st["story"], int(st["step"]) + 1],
                   "story": o["title"], "step": step_name, "reaction": rid or "START", "context": c, "leaf": leaf_id + "." + c,
                   "profession": prof}
    out["hint_source"] = "tree" if weak else "assistant+tree"
    _log(a, ses, ctx, "run", story=st["story"], step=int(st["step"]), reaction=rid or "START", context=c,
         profession=prof, leaf=leaf_id)
    return out


FLOW_BLOCKS = {"camera": "camera", "params": "setup", "summary": "setup", "prompt": "setup"}


def active_flow(ses: dict, out: dict) -> str | None:
    """Идёт ли сейчас процесс со своими кнопками шагов: раскадровка, этапы проекта, режим «Рилс/Сериал»,
    настройка видео с выбором движения камеры. Тогда дерево не добавляет кнопок, только отмечает шаг истории."""
    from . import modes as MD
    from . import pipeline as PL
    from . import storyboard as SB
    if SB.active(ses) or str(out.get("intent") or "").startswith("sb_"):
        return "storyboard"
    pst = ses.get("pipe") if isinstance(ses.get("pipe"), dict) else {}
    if PL.waiting(ses) or (pst.get("on") and pst.get("stage")):
        return "pipeline"
    if MD.active(ses):
        return "mode"
    for bl in out.get("blocks") or []:
        f = FLOW_BLOCKS.get(str(bl.get("type") or ""))
        if f:
            return "camera" if any(b.get("type") == "camera" for b in out.get("blocks") or []) else f
    return None


def _step_index(o: dict, rx: str) -> int | None:
    for i, stp in enumerate(o.get("steps") or []):
        if re.search(rx, stp["step"], re.I):
            return i
    return None


def sync_flow(a: Any, tree: HintTree, st: dict, out: dict, flow: str, atype: str, ctx: dict, ses: dict,
              prof: str | None, msg: str = "") -> dict:
    """Синхронизирует шаг истории с процессом: зашли в раскадровку → шаг «Раскадровка»; выбрали движение камеры →
    шаг с камерой пройден. Кнопки процесса остаются как есть."""
    o = tree.stories.get(st.get("story") or "")
    if o is None and msg:                      # «хочу ИИ-сериал» сразу открыл режим — историю всё равно запоминаем
        sid, _ = tree.match(msg, ses.get("kind"), prof)
        if sid:
            _start(a, tree, st, sid, prof)
            st["just"] = None
            o = tree.stories[sid]
            _log(a, ses, ctx, "start", story=sid, step=0, profession=prof, flow=flow)
    if flow == "storyboard":
        if o is None:
            sid, _ = tree.match("раскадровка " + str((ses.get("sb") or {}).get("idea") or ""), "video", prof)
            if sid:
                _start(a, tree, st, sid, prof)
                st["just"] = None
                o = tree.stories[sid]
        if o is not None:
            j = _step_index(o, r"раскадров")
            if j is not None and j > int(st.get("step") or 0):
                st["step"] = j
    elif flow == "camera" and o is not None and atype == "pick_camera":
        j = _step_index(o, r"камер|движен|пример с промптом|облёт")
        if j is not None and j >= int(st.get("step") or 0):
            st["step"] = j + 1
    st["just"] = None
    st["shown"] = []
    st["ts"] = int(time.time())
    if o is not None:
        steps = o.get("steps") or []
        i = min(int(st.get("step") or 0), max(0, len(steps) - 1))
        vec, sub = tree.vec_of[o["id"]][0]["id"], tree.vec_of[o["id"]][1]["id"]
        out["tree"] = {"version": tree.version, "path": [vec, sub, o["id"], i + 1], "story": o["title"],
                       "step": steps[i]["step"] if steps else "", "reaction": "FLOW", "context": "C0", "flow": flow,
                       "profession": prof}
        _log(a, ses, ctx, "flow", story=o["id"], step=i, flow=flow, action=atype, profession=prof)
    out["hint_source"] = "assistant"
    return out


def _out_reply(a: Any, out: dict, node: dict, st: dict, lang: str) -> dict:
    """Просьба про то, чего нет на платформе: честный ответ + ближайшее, что студия умеет (раздел 28)."""
    parts = [p.strip() for p in re.split(r"\s·\s", node.get("reaction") or "") if p.strip()]
    text = ""
    if parts and parts[0].startswith("«"):
        text = parts.pop(0).strip("«»")
    elif parts and parts[0] == "[план]":
        parts.pop(0)
        text = "Этого пока нет, но в планах." if lang != "en" else "Not available yet, it is planned."
    if text:
        out["text"] = out["reply"] = text
    merge(out, chips_for(a, parts, {"story": None, "step": 0}, lang), first=True)
    out["tree"] = {"version": a.d.tree.version, "path": ["OUT"], "out": node.get("id"), "reaction": "OUT", "context": "C0"}
    out["hint_source"] = "tree"
    return out


def resume_step(a: Any, tree: HintTree, st: dict, ses: dict, lang: str) -> dict:
    """Кнопка «вернуться» показывает сам шаг: вопрос и рабочие подсказки, без пустого «продолжаем»."""
    from .render import response
    o = tree.stories.get(st.get("story") or "")
    if not o:
        return response(["Не поняла, куда вернуться. Опишите задачу словами."], [], [], lang, intent="tree_resume")
    steps = o.get("steps") or []
    i = min(int(st.get("step") or 0), max(0, len(steps) - 1)) if steps else 0
    step = steps[i]["step"] if steps else ""
    plain = _AFTER.sub("", step.strip("«» ")).strip()
    title = task_title(ses, o.get("title") or "")
    if plain and plain.lower() not in ("старт", title.lower()):
        line = f"«{title}». {plain}."
    else:
        line = f"«{title}». Выберите, что сделать дальше."
    if lang == "en":
        line = f"«{title}». {plain or 'Pick the next step.'}"
    out = response([line], [], [], lang, intent="tree_resume")
    merge(out, chips_for(a, tree.step_hints(o["id"], i), st, lang, ses), first=True)
    if not (out.get("text") or "").strip() and not out.get("chips"):
        out["text"] = out["reply"] = "Опишите задачу словами."
    return out


def hint_action(a: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """Клик по подсказке дерева: реакция R01/R02, шаг вперёд; текст подсказки разбирает ядро как обычную фразу."""
    from .render import response
    tree: HintTree | None = getattr(a.d, "tree", None)
    v = value if isinstance(value, dict) else {"label": str(value or "")}
    label = str(v.get("label") or "")[:80]
    st = state(ses)
    if tree is None or not label:
        return a._message(label, ctx, ses, lang)
    idx = int(v.get("i") or 0)
    if v.get("s") and v.get("s") in tree.stories and v.get("s") != st.get("story"):
        _start(a, tree, st, v["s"], profession(st, ctx))
        st["just"] = None
    if re.match(r"^(загрузить|прикрепить|attach|upload)\b", label.strip(), re.I):
        from .render import chip
        if _image_already(ses, ctx):
            line = ("Эта картинка уже в задаче, промпт про неё. Другую можно прикрепить скрепкой."
                    if lang != "en" else
                    "This picture is already in the task, and the prompt is about it. Attach another with the paperclip.")
        else:
            line = ("Прикрепите файл скрепкой." if lang != "en" else "Attach the file with the paperclip.")
        return response([line], [chip("Прикрепить" if lang != "en" else "Attach", "attach")],
                        lang=lang, intent="need_file", ui_do={"action": "attach"})
    if label.startswith("↩"):                  # вернуться к шагу — показать сам шаг, а не пустое «продолжаем»
        st["just"] = "START"
        return resume_step(a, tree, st, ses, lang)
    if label in ("Ещё…", "More…"):
        st["just"] = None
        o = tree.stories.get(st.get("story") or "")
        out = response(["Ещё варианты для этого шага:" if lang != "en" else "More options for this step:"], [], [], lang,
                       intent="tree_more")
        if o:
            merge(out, chips_for(a, tree.step_hints(o["id"], int(st.get("step") or 0)), st, lang, ses, ctx), first=True)
        return out
    rid = "R07" if v.get("why") else ("R01" if idx == 0 else "R02")
    _log(a, ses, ctx, "click", story=st.get("story"), step=st.get("step"), reaction=rid, label=label,
         profession=profession(st, ctx))
    if rid == "R07":
        st["just"] = "R03"                     # «что не так → движение» — правка в рамках шага
    else:
        lf = tree.leaf(st["story"], int(st.get("step") or 0), rid) if st.get("story") else None
        st["just"] = rid if lf else "START"
        if lf and _advance(st, rid):
            st["_advanced"] = True
    ctx = dict(ctx)
    ctx["_tree_hint"] = True                   # «Тёмная тема» в истории про интерфейс — это деталь задачи, не смена темы
    out = a._message(label, ctx, ses, lang)
    if out.get("intent") in WEAK_INTENTS | {"noop"} and st.get("story"):
        o = tree.stories[st["story"]]
        steps = o.get("steps") or []
        nxt = steps[min(int(st.get("step") or 0), len(steps) - 1)]["step"] if steps else ""
        nxt = _AFTER.sub("", nxt.strip("«» ")).strip()
        if not nxt or _FINALE.search(nxt):
            line = (f"Принято: «{label}». Опишите детали или выберите вариант ниже."
                    if lang != "en" else f"Got it: «{label}». Add details or pick an option below.")
        else:
            line = (f"Принято: «{label}». Дальше — {nxt}. Опишите детали или выберите вариант ниже."
                    if lang != "en" else f"Got it: «{label}». Next — {nxt}. Add details or pick an option below.")
        out["text"] = out["reply"] = line
        out["intent"] = "tree_step"
        out["degraded"] = False
    return out


EVENTS = {"like": "R06", "dislike": "R07", "regen": "R08", "error": "R09", "topup_needed": "R10", "download": "R14"}


def event_action(a: Any, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
    """События студии под результатом: лайк, дизлайк, перегенерация, ошибка, нехватка денег, скачивание."""
    from .render import response
    tree: HintTree | None = getattr(a.d, "tree", None)
    name = str((value or {}).get("name") if isinstance(value, dict) else value or "")
    rid = EVENTS.get(name)
    st = state(ses)
    if tree is None or not rid or not st.get("story") or st["story"] not in tree.stories:
        return response([], [], [], lang, intent="tree_event", silent=True)
    lf = tree.leaf(st["story"], int(st.get("step") or 0), rid)
    if not lf:
        return response([], [], [], lang, intent="tree_event", silent=True)
    st["just"] = rid
    if _advance(st, rid):
        st["_advanced"] = True
    text = {"R06": "Отлично! Что дальше?", "R07": "Что не так?", "R08": "Не получается с этой моделью?",
            "R09": "Генерация не прошла, деньги не списаны.", "R10": "Не хватает на эту модель.",
            "R14": "Сохранили. Продолжим?"}.get(rid, "") if lang != "en" else \
        {"R06": "Great! What next?", "R07": "What is wrong?", "R08": "Not working with this model?",
         "R09": "Generation failed, no charge.", "R10": "Not enough balance for this model.",
         "R14": "Saved. Continue?"}.get(rid, "")
    return response([text], [], [], lang, intent="tree_event")


def context_text(ses: dict, tree: HintTree | None) -> str:
    """Строка для нейросети помощника: где человек в дереве (чтобы ответ сверх дерева не уводил в сторону)."""
    st = ses.get("tree") if isinstance(ses.get("tree"), dict) else None
    if not tree or not st or not st.get("story") or st["story"] not in tree.stories:
        return ""
    o = tree.stories[st["story"]]
    steps = o.get("steps") or []
    i = min(int(st.get("step") or 0), max(0, len(steps) - 1))
    nxt = ", ".join(tree.step_hints(o["id"], i)[:3])
    return f"CONTEXT: user story «{o['title']}», step «{steps[i]['step'] if steps else ''}»; next options: {nxt}."


def make_logger(write: Callable[[dict], None], sid_salt: str = "") -> Callable[[dict], None]:
    """Обёртка для сервера: хэширует sid, режет длины. write — запись в БД (hint_tree_routes)."""
    def log(ev: dict) -> None:
        ev = dict(ev)
        ev["sid"] = _sid_hash(sid_salt + str(ev.get("sid") or ""))
        if isinstance(ev.get("label"), str):
            ev["label"] = ev["label"][:80]
        write(ev)
    return log
