"""Ядро ассистента: маршрут → обработчик → ответ. Без Flask, без сети (сеть только внутри LLMChain).

Сценарий (brief=on, по умолчанию):
  «Промпт»: тип генерации → модель → уточнения (clarify модели) → варианты → polish → запуск.
  Видео сразу: модель → идея как промпт → параметры → запуск (без «улучшить промпт?»).
  Картинка: сначала промпт (уточнения → варианты), потом один раз модели.
  Музыка и остальные: модель → «нужен промпт?» → да: clarify → варианты → polish;
                                            нет: идея как промпт → параметры → запуск.
Без брифа (brief=off): идея → модели → промпт под выбранную модель.

Контракт ответа: см. render.py (text, blocks, chips, reply) + поля:
    intent, lang, models, generate_model, generate_prompt, generate_params, ready, llm{...}, degraded
Ассистент НИКОГДА не запускает генерацию: кнопка generate обрабатывается фронтом → POST /api/generate.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import brief as BR
from . import dialog as DG
from . import dialog_flow as DFLOW
from . import camera as CAM
from . import errors as err_mod
from . import files as F
from . import model_lock as ML
from . import modes as MD
from . import params as P
from . import pipeline as PL
from . import storyboard as SB
from . import tree as TR
from . import understand as UN
from .cards import Card, load_cards
from .lang import detect_lang
from .llm import LLMChain, LLMUnavailable
from .prompts import SYSTEM, build_user, fallback_prompt, validate_output
from .recommend import PIN_FIRST, Pick, cheapest, price_value, recommend
from .render import chip, estimate, model_item, per_second, response, short_price, std_chip
from .router import MINORS_SEXUAL, NSFW, OFF_TOPIC, VIOLENCE, Intent, detect_kind, detect_needs, lev, route, squeeze, topic_of
from .session import MAX_SESSION_ID, MemoryStore, load
from .texts import EXAMPLES, REFINE_SUGGEST, b, t
from .ui_help import ui_help

log = logging.getLogger("assistant")

KINDS = ("video", "image", "edit", "music", "sfx", "text")
# текстовые модели на шаге «улучшить промпт» после выбора варианта
POLISH_MODELS = ("claude-sonnet-5", "gpt-5-4", "claude-4-5-haiku")
# С фото первым идёт Opus: Sonnet картинку не принимает.
POLISH_WITH_PHOTO = ("claude-opus-4-7", "gpt-5-4", "claude-sonnet-5", "claude-4-5-haiku")
SEES_IMAGE = {"claude-opus-4-7", "gpt-5-4", "gpt-5-6-sol", "gemini-3-1-pro"}
_PICK_WORDS = re.compile(r"^\s*(выбрать|выбираю|беру|возьму|давай|хочу|модель|choose|pick|use|take)\s+", re.I)


@dataclass
class AssistantDeps:
    cards: dict[str, Card]
    neighbors: dict[str, list[str]] = field(default_factory=dict)
    price_fn: Callable[[str], "str | None"] = lambda _mid: None
    health_fn: Callable[[str], bool] | None = None
    llm: LLMChain | None = None
    store: Any = field(default_factory=MemoryStore)
    vitrina_url: str = "/vitrina.html"
    token_budget: int = 6000
    max_llm_calls: int = 15
    on_event: Callable[[dict], None] | None = None
    # цена запуска в копейках (как посчитает биллинг); None → из price_fn: «4,3 ₽/сек» × секунды
    cost_fn: Callable[[str, dict], "int | None"] | None = None
    llm_diag: Any = None          # цепочка LLM даже без ключей — для /status
    account_check: bool = False   # True, если адаптер передаёт ctx["_account"]
    brief: bool = True            # уточнять детали и давать 3 варианта промпта перед параметрами
    # какие файлы модель принимает: id → ["text", "image", "audio"] (из INTEGRATED_MODELS); None — по режимам карточки
    inputs_fn: Callable[[str], list] | None = None
    # модель открыта в студии? id → True/False (server._is_studio_visible). None — все модели с карточками
    catalog_fn: Callable[[str], bool] | None = None
    # слой 2 понимания (understand.py): непонятную правилам фразу разбирает нейросеть. В проде включён (ASSIST_UNDERSTAND_LLM)
    understand_llm: bool = False
    # дерево подсказок (tree.HintTree): истории → шаги → реакции → подсказки. None — помощник работает без дерева
    tree: Any = None
    # запись событий дерева для админки (нехарактерные действия, новые пути); сервер пишет в БД
    tree_log: Callable[[dict], None] | None = None
    # диалог v2: идея → путь → совет модели → карточка. В тестах ядра выключен, в проде включён.
    dialog_v2: bool = False
    # запасной id той же модели: (id, провайдер запуска, было ли фото) → id другой площадки
    alt_fn: Callable[[str, str, bool], "str | None"] | None = None


_POLISH_WRAP = re.compile(
    r"(?:Доработай этот промпт для генерации:[\s\S]*?Верни только улучшенный промпт\.?\s*"
    r"|Разверни этот промпт для генерации[\s\S]*?Верни только улучшенный промпт\.?\s*"
    r"|Polish this generation prompt:[\s\S]*?Return only the improved prompt\.?\s*"
    r"|Expand this generation prompt[\s\S]*?Return only the improved prompt\.?\s*)+",
    re.I,
)


def unwrap_polish(text: str) -> str:
    """Убрать служебную просьбу «доработай промпт», если она уже влипла в сам текст."""
    cur = (text or "").strip()
    for _ in range(6):
        nxt = _POLISH_WRAP.sub("", cur).strip()
        if nxt == cur:
            break
        cur = nxt
    return cur


def _clean_polish_copies(ses: dict) -> None:
    for key in ("prompt", "prompt_base", "idea", "polish_draft"):
        raw = ses.get(key) or ""
        clean = unwrap_polish(raw)
        if clean and clean != raw:
            ses[key] = clean
    flow = ses.get("flow")
    if isinstance(flow, dict):
        for key in ("idea", "idea_user"):
            raw = flow.get(key) or ""
            clean = unwrap_polish(raw)
            if clean and clean != raw:
                flow[key] = clean


def _look_buttons(lang: str) -> list[dict]:
    """Пока Claude собирает промпт: быстрый вариант через помощника или дальше с текущим текстом."""
    return [
        chip("Quick prompt" if lang == "en" else "Быстрый промпт", "look_skip"),
        chip("Keep my prompt" if lang == "en" else "Оставить свой промпт", "look_next"),
    ]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:]", " ", squeeze(s or ""))).strip()


class Assistant:
    def __init__(self, deps: AssistantDeps):
        self.d = deps
        self.titles = {c.id: c.title for c in deps.cards.values()}
        self._tls = threading.local()

    @property
    def _llm_info(self) -> dict[str, Any]:
        return self._tls.llm_info

    @_llm_info.setter
    def _llm_info(self, v: dict[str, Any]) -> None:
        self._tls.llm_info = v

    @classmethod
    def with_default_cards(cls, **kw: Any) -> "Assistant":
        cards, neighbors = load_cards()
        return cls(AssistantDeps(cards=cards, neighbors=neighbors, **kw))

    # ================================================================ entry
    def handle(self, message: str = "", context: dict | None = None, session_id: str = "",
               action: dict | None = None) -> dict[str, Any]:
        t0 = time.monotonic()
        ctx = dict(context or {})
        sid = (session_id or "")[:MAX_SESSION_ID]
        ses = load(self.d.store, sid)
        uid = ctx.get("_uid")
        if uid and ses.get("owner") and ses["owner"] != uid:   # тот же браузер, другой аккаунт — начинаем заново
            ses = load(self.d.store, "")
        if uid:
            ses["owner"] = uid                                   # анонимный разговор «переезжает» в аккаунт после входа
        # Скрепка: какие файлы прикреплены сейчас (имена — чтобы называть их в ответах)
        files = F.clean_attachments(ctx.get("attachments"), keep_id=True)
        ctx["attachments"] = files
        if any(f["kind"] == "image" for f in files):
            ctx["has_image"] = True
        ctx["_files_changed"] = bool(files) and files != (ses.get("files") or [])
        ctx["_tree_sid"] = sid
        if files != (ses.get("files") or []):
            ses["files_told"] = False                            # набор файлов поменялся — скажем о нём снова
        if files:
            ses["files"] = files
            DG.ingest_uploads(ses, files)
        else:
            sticky = DG.files_from_uploads(ses)
            if sticky:
                ses["files"] = sticky
                if any(f.get("kind") == "image" for f in sticky):
                    ctx["has_image"] = True
            else:
                ses["files"] = []
        if ctx.get("_files_changed"):
            ses["files_ok"] = False
        msg = (message or "").strip()[:2000]
        lang = self._lang(msg, ses, ctx)
        ses["lang"] = lang
        ses["turns"] = int(ses.get("turns") or 0) + 1
        self._llm_info = {"used": False, "provider": None, "tokens": 0, "latency_ms": 0}
        try:
            if action and isinstance(action, dict) and action.get("type"):
                if action.get("type") != "send":
                    ses["junk_count"] = 0
                if action["type"] in ML.ACTIONS:          # «Спросить DeepSeek» / «Подобрать модель для: …»
                    out = ML.action(self, action["type"], action.get("value"), ctx, ses, lang)
                elif action["type"] == "tree_hint":          # подсказка дерева: реакция + текст подсказки в ядро
                    out = TR.hint_action(self, action.get("value"), ctx, ses, lang)
                elif action["type"] == "tree_event":       # лайк / скачал / ошибка… под результатом
                    out = TR.event_action(self, action.get("value"), ctx, ses, lang)
                else:
                    draft = action.get("prompt")
                    if isinstance(draft, str) and draft.strip() and not BR.is_look_instruction(draft):
                        text = draft.strip()[:8000]
                        if action["type"] == "use_variant":
                            ses["_prompt_edit"] = text
                        else:
                            ses["prompt"] = ses["prompt_base"] = text
                            flow = ses.get("flow")
                            if isinstance(flow, dict):
                                flow["idea"] = text
                                ses["idea"] = text
                    out = self._action(str(action["type"]), action.get("value"), ctx, ses, lang)
            else:
                out = ML.before_message(self, msg, ctx, ses, lang) if msg else None
                if out is None:
                    out = self._message(msg, ctx, ses, lang)
        except Exception:
            log.exception("assistant handler failed")
            out = response([_generic_error(lang)], [std_chip("retry", "retry", lang)], intent="internal_error")
        try:                                # дерево подсказок: следующий шаг истории с учётом реакции и контекста
            out = TR.on_turn(self, out, msg, action, ctx, ses, lang)
        except Exception:
            log.exception("assistant tree failed")
        out = MD.decorate(out, ses, lang)   # режим «Рилс» / «Сериал» идёт — под любым ответом «↩ вернуться к шагу»
        note = ses.pop("focus_note", None) if isinstance(ses, dict) else None
        if note and not out.get("silent"):
            out["text"] = note + "\n" + (out.get("text") or "")
            out["reply"] = out["text"]
        if ses.pop("_just_parked", None) and out.get("intent") not in ("look_photo", "look_photo_wait"):
            back = DG.return_chip(ses, lang)
            if back and not any(c.get("action") == "resume_task" for c in out.get("chips") or []):
                out["chips"] = list(out.get("chips") or []) + [back]
        out = self._fill_empty(out, ses, lang, action)
        if msg:
            DG.remember(ses, "user", msg)
        if not out.get("silent"):
            DG.remember(ses, "bot", out.get("text") or "")
        if not out.get("silent"):
            ses["last_chips"] = [{k: c.get(k) for k in ("label", "action", "value")} for c in out.get("chips", [])]
        pst = ses.get("pipe") if isinstance(ses.get("pipe"), dict) else {}
        out["pipe_expect"] = pst.get("expect") if pst.get("on") else None   # приложение пришлёт pipe_result после генерации
        if sid:
            self.d.store.set(sid, ses)
        out.setdefault("intent", "unknown")
        out.setdefault("models", [])
        out.setdefault("ready", False)
        out.setdefault("degraded", False)
        out["lang"] = lang
        out["llm"] = self._llm_info
        if self.d.dialog_v2:
            out["dialog"] = DFLOW.meta(ses)
            if DFLOW.active(ses) and out.get("intent") in ("price", "compare", "question", "capabilities", "error_help"):
                back = DFLOW.back_chip(ses)
                if back and not any(c.get("action") == "flow_show" for c in out.get("chips") or []):
                    out["chips"] = list(out.get("chips") or []) + [back]
        if self.d.on_event:
            try:
                self.d.on_event({"intent": out["intent"], "lang": lang, "llm_used": self._llm_info["used"],
                                 "provider": self._llm_info["provider"], "tokens": self._llm_info["tokens"],
                                 "degraded": out["degraded"], "ms": int((time.monotonic() - t0) * 1000)})
            except Exception:
                log.exception("assistant on_event failed")
        return out

    def _fill_empty(self, out: dict, ses: dict, lang: str, action: dict | None) -> dict:
        """Пустой пузырь не отдаём: ни без текста, ни без кнопок."""
        if out.get("silent"):
            return out
        if (out.get("text") or "").strip() or out.get("blocks") or out.get("chips"):
            return out
        log.warning("assistant empty reply intent=%s action=%s", out.get("intent"),
                    (action or {}).get("type") if isinstance(action, dict) else "")
        if self.d.tree_log:
            try:
                self.d.tree_log({"kind": "empty", "intent": out.get("intent"),
                                 "action": (action or {}).get("type") if isinstance(action, dict) else "",
                                 "label": str((action or {}).get("value") if isinstance(action, dict) else "")[:80]})
            except Exception:
                log.exception("assistant empty log failed")
        back = DFLOW.back_chip(ses) if isinstance(ses.get("flow"), dict) else None
        out["text"] = out["reply"] = "Не поняла, что сделать. Опишите задачу словами."
        if back and not any(c.get("action") == "flow_show" for c in out.get("chips") or []):
            out["chips"] = list(out.get("chips") or []) + [back]
        return out

    def _lang(self, msg: str, ses: dict, ctx: dict) -> str:
        # Язык интерфейса (ctx.lang) всегда главный: RU UI → ответы по-русски, EN UI → по-английски.
        ui = str(ctx.get("lang") or "").lower()[:2]
        if ui in ("ru", "en"):
            return ui
        fallback = ses.get("lang") if ses.get("lang") in ("ru", "en") else "ru"
        if not msg:
            return fallback
        rest = msg
        for title in self.titles.values():  # «. GPT Image 2» — это не английский, это название модели
            rest = re.sub(re.escape(title), " ", rest, flags=re.I)
        if len(re.findall(r"[a-zа-яё]", rest, re.I)) < 4:
            return fallback
        return detect_lang(rest, default=fallback)

    def _message(self, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        if not (msg and BR.is_junk(msg)):
            ses["junk_count"] = 0
        # 1) текст совпал с кнопкой прошлого ответа или с названием модели → это клик
        act = self._text_as_action(msg, ses)
        if act:
            return self._action(act[0], act[1], ctx, ses, lang)
        if msg and DG.mcp_about(msg) and not ctx.get("_tree_hint"):
            hit = DG.mcp_turn(self, msg, ctx, ses, lang)
            if hit is not None:
                return hit
        if msg:
            how, found = DG.refer(msg, ses)
            if how == "many":
                return DG.ask_which(found, lang)
            if how == "dead":
                return DG.ask_attach(lang, dead=True)
            if how == "none":
                return DG.ask_attach(lang)
            if how == "one":
                ses["focus"] = [found[0].get("id")]
                ses["files_ok"] = True
                ses["focus_note"] = DG.take_line(found[0], lang)
        # 1') понимание фразы (understand.py): «включи клода», вопрос-совет, «тёмная тема», режимы; шаг режима ждёт текст
        from .switch import kind_only as _kind_only
        switching_kind = bool(msg and _kind_only(msg))
        if msg and self.d.dialog_v2 and DFLOW.active(ses) and not DG.mcp_about(msg) and ses.get("await") not in ("polish", "chat") and (ses.get("kind") != "text" or switching_kind):
            it_flow = route(msg, ctx, ses, self.titles)
            if it_flow.name not in ("crisis", "safety", "safety_person", "injection", "price", "error_help", "ui_help", "generate_now"):
                got_flow = DFLOW.on_message(self, msg, ctx, ses, lang)
                if got_flow is not None:
                    return got_flow
        if msg:
            got = self._understand(msg, ctx, ses, lang)
            if got is not None:
                return got
        # Режим «Рилс» отключён: если остался старый черновик в сессии — сбрасываем и идём обычным путём.
        if ses.get("assist_mode") == "reel" or isinstance(ses.get("reel"), dict):
            ses["assist_mode"] = None
            ses["reel"] = None
            if ses.get("await") == "reel":
                ses["await"] = "type"
        # 1а-0) флоу помощника ждёт ответ этапа (идея промпта, диалог, описание героя, текст озвучки)
        if msg and PL.waiting(ses) and not self._is_guest(ctx):
            it_pl = route(msg, ctx, ses, self.titles)
            if it_pl.name in ("crisis", "safety", "safety_person", "injection"):
                return getattr(self, "_i_" + it_pl.name)(it_pl, msg, ctx, ses, lang)
            if BR.is_junk(msg) and ses["pipe"].get("await") != "dialog":
                n = ses["junk_count"] = int(ses.get("junk_count") or 0) + 1
                return PL.reask(self, ses, ctx, lang, _junk_line(n, lang))
            return PL.message(self, ses, ctx, lang, msg)
        # 1а) режим «Раскадровка»: свободный текст — сценарий, идея или правка кадров (кроме опасного / кризиса)
        sb_on = SB.active(ses)
        if msg and (sb_on or SB.SB_RX.search(msg)) and not self._is_guest(ctx):
            it_sb = route(msg, ctx, ses, self.titles)
            if it_sb.name in ("crisis", "safety", "safety_person", "injection"):
                return getattr(self, "_i_" + it_sb.name)(it_sb, msg, ctx, ses, lang)
            if sb_on:
                return PL.decorate(SB.message(self, ses, ctx, lang, msg), ses, lang)
            return PL.decorate(SB.start(self, ses, ctx, lang, text=msg), ses, lang)
        switched = self._maybe_switch_message(msg, ctx, ses, lang)
        if switched is not None:
            return switched
        # 1б) мусор вроде «ооло» никуда не пишем — переспрашиваем по месту
        if msg and not re.fullmatch(r"\s*\d{1,2}\s*[.)]?\s*", msg) and BR.is_junk(msg):
            n = ses["junk_count"] = int(ses.get("junk_count") or 0) + 1
            aw = ses.get("await")
            card = self._current_card(ses, ctx) if ses.get("picked") else None
            guide = self._brief_card(ses)
            if aw in ("params", "refine") and card:
                return self._refine(card, msg, ctx, ses, lang)
            if aw in ("brief", "variants") and guide:   # LLM не зовём: показываем то же место, коротко
                if aw == "brief":
                    out = self._brief(guide, ses, ctx, lang)
                else:
                    out = self._show_variants(guide, ses, lang, [t("variants_head", lang)], False)
                note = _junk_line(n, lang)
                out["text"] = note + "\n" + out["text"]
                out["reply"] = note + "\n" + out["reply"]
                return out
            if ses.get("assist_mode") == "prompt" and ses.get("kind"):
                return self._ask_prompt_idea(ses, lang, junk=True)
            if ses.get("kind"):
                return self._ask_subject(ses["kind"], ses, ctx, lang, junk=True)
            ses["await"] = None
            out = DG.unclear(self, msg, lang, "junk")
            note = _junk_line(n, lang)
            out["text"] = note + "\n" + out["text"]
            out["reply"] = out["text"]
            return out
        # 1в) ждём суть идеи («о чём видео?») — любой осмысленный текст становится идеей
        if ses.get("await") == "idea" and ses.get("kind") and BR.has_subject(msg):
            it0 = route(msg, ctx, ses, self.titles)
            if it0.name in ("ask_type", "off_topic", "generate_task", "smalltalk") and (it0.kind in (None, ses["kind"])):
                ses.update(idea=msg, topic=topic_of(msg), needs=detect_needs(msg) or ses.get("needs") or [],
                           brief=None, brief_done=False, prompt="", junk_count=0)
                if ses.get("assist_mode") == "prompt":
                    # ветка «Промпт»: идея → сразу варианты промпта, без доп. вопросов и без нейросети
                    return self._prompt_from_idea(ctx, ses, lang)
                if ses.get("kind") == "image" and self.d.brief:
                    return self._enter_brief(ctx, ses, lang)
                if self.d.dialog_v2 and (ses.get("kind") or "") != "text":
                    opened = DFLOW.start(self, msg, it0, ctx, ses, lang)
                    if opened is not None:
                        return opened
                if ses.get("picked") and ses["picked"] in self.d.cards:
                    return self._pick(ses["picked"], ctx, ses, lang)
                # модель ещё не выбрана — сначала нейросеть, потом вопросы / промпт
                ses["assist_mode"] = ses.get("assist_mode") or "direct"
                return self._show_models(
                    self._recommend(ses["kind"], ses.get("needs") or [], bool(ctx.get("has_image"))),
                    ses, lang, "generate_task",
                    head=t("pick_model_for_kind", lang, kind=err_mod.KIND_WORD.get(lang, err_mod.KIND_WORD["ru"]).get(ses["kind"], ses["kind"])))
        # 1г) бриф / варианты: свободный текст — это деталь или правка, а не новая задача
        if ses.get("await") in ("brief", "variants") and self._brief_card(ses):
            it0 = route(msg, ctx, ses, self.titles)
            card = self._brief_card(ses)
            new_task = it0.name == "generate_task" and (it0.kind not in (None, card.kind) or len(msg.split()) > 8)
            if not new_task and it0.name not in ("crisis", "safety", "safety_person", "injection", "ui_help", "error_help"):
                br = ses.get("brief") or {"q": [], "a": {}, "extra": [], "summary": ""}
                fitted, _adj = P.fit(P.extract(msg), card)
                if not fitted or len(msg.split()) > 3:
                    br.setdefault("extra", []).append(msg.strip()[:200])
                ses["brief"] = br
                if fitted:
                    ses["params"] = P.with_defaults(card, {**P.validate(card, ses.get("params")), **fitted})
                    if len(msg.split()) <= 3 and ses.get("variants"):   # «вертикально» — варианты те же, LLM не зовём
                        lbl = ", ".join(P.label(k, v, lang) for k, v in fitted.items())
                        return self._show_variants(card, ses, lang, [t("settings_saved", lang, label=lbl)], False)
                # этап 1 (открытые вопросы) → после ответа показать кнопки слотов
                if ses.get("await") == "brief" and br.get("phase") == "open" and self._profile_brief(br):
                    # идея ещё не была (сразу «улучшить» после выбора модели) — первый ответ и есть идея
                    if not (ses.get("idea") or "").strip() and msg.strip():
                        ses["idea"] = msg.strip()[:500]
                        ses["topic"] = topic_of(msg) or ses.get("topic") or ""
                        ses["needs"] = detect_needs(msg) or ses.get("needs") or []
                    return self._brief_after_open(card, ses, ctx, lang)
                return self._variants(card, ses, ctx, lang, change=msg if ses.get("await") == "variants" else "")
        # 2) ждём «есть промпт?» — да/нет своими словами
        if ses.get("await") == "has_prompt" and msg:
            low = squeeze(msg).lower()
            if low in ("да", "yes", "улучшить", "есть", "помоги", "промпт"):
                return self._action("has_prompt", "yes", ctx, ses, lang)
            if low in ("нет", "no", "модели", "сразу", "без промпта"):
                return self._action("has_prompt", "no", ctx, ses, lang)
        # 2а) развёрнутый промпт: добавить что-то? да → ждём текст; нет → настройки; любой текст = дополнение
        if ses.get("await") == "add_prompt" and msg:
            low = squeeze(msg).lower()
            card = self.d.cards.get(ses.get("picked") or "") or self._current_card(ses, ctx)
            if low in ("нет", "no", "настройк", "запуск", "генерир", "сразу"):
                return self._action("add_prompt", "no", ctx, ses, lang)
            if low in ("да", "yes", "добавить", "дополнить", "хочу"):
                return self._action("add_prompt", "yes", ctx, ses, lang)
            if card and len(msg.strip()) >= 2:
                return self._action("add_prompt", {"text": msg.strip()}, ctx, ses, lang)
        # 2б) ждём ответ «какой тип» / тип для промпта — коротко и с опечатками
        if ses.get("await") in ("type", "gen_type") and len(msg.split()) <= 3:
            k = detect_kind(msg, bool(ctx.get("has_image"))) or _kind_by_number(msg, ses.get("await") == "gen_type")
            # «оживи картинку» после «Новый чат» — это задача, не старый выбор типа с сеткой моделей
            if k and k in KINDS and k != "text" and self.d.dialog_v2:
                it_short = route(msg, ctx, ses, self.titles)
                if not it_short.kind:
                    it_short.kind = k
                opened = DFLOW.start(self, msg, it_short, ctx, ses, lang)
                if opened is not None:
                    return opened
            if k == "prompt" and ses.get("await") == "gen_type":
                k = None
            if k:
                return self._action("choose_type", k, ctx, ses, lang)
            it = route(msg, ctx, ses, self.titles)
            if it.name in ("ask_type", "off_topic"):
                if ses.get("await") == "gen_type":
                    return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                    lang=lang, intent="ask_type")
                ses["await"] = "type"
                return self._offer_types([_junk_line(1, lang)], ctx, ses, lang, "ask_type")
        # 2в) длинный готовый промпт на шаге выбора типа — сразу выводим тип из текста
        if ses.get("await") in ("type", "gen_type") and len(msg.split()) > 3 and BR.has_subject(msg):
            k = detect_kind(msg, bool(ctx.get("has_image")))
            if k and k != "prompt":
                ses.update(idea=msg, topic=topic_of(msg), needs=detect_needs(msg) or ses.get("needs") or [])
                return self._action("choose_type", k, ctx, ses, lang)
            ses.update(idea=msg, topic=topic_of(msg), needs=detect_needs(msg) or ses.get("needs") or [])
            if ses.get("await") == "gen_type":
                return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                lang=lang, intent="ask_type")
            return self._ask_type(ses, ctx, lang)
        intent = route(msg, ctx, ses, self.titles)
        # уже выбран тип (видео/картинка…), а в тексте типа нет — это идея/промпт, не сбрасываем тип
        if (intent.name == "ask_type" and ses.get("kind") in KINDS and ses["kind"] != "text"
                and len(msg.split()) >= 6 and BR.has_subject(msg)):
            ses.update(idea=msg, topic=topic_of(msg) or ses.get("topic") or "",
                       needs=detect_needs(msg) or ses.get("needs") or [])
            if self.d.dialog_v2 and (ses.get("kind") or "") != "text":
                opened = DFLOW.start(self, msg, intent, ctx, ses, lang)
                if opened is not None:
                    return opened
            if ses.get("picked") and ses["picked"] in self.d.cards:
                return self._pick(ses["picked"], ctx, ses, lang)
            if ses.get("kind") == "image" and self.d.brief:
                return self._enter_brief(ctx, ses, lang)
            ses["assist_mode"] = ses.get("assist_mode") or "direct"
            return self._offer_models_for_kind(ctx, ses, lang, "generate_task",
                                              mode=ses.get("assist_mode") or "direct")
        # тип в тексте не совпал с уже выбранным — новая задача (не правка промпта)
        if (intent.name == "generate_task" and intent.kind and ses.get("kind") in KINDS
                and intent.kind != ses["kind"] and len(msg.split()) >= 6):
            return self._i_generate_task(intent, msg, ctx, ses, lang)
        # 3) модель уже выбрана: «вертикально», «10 секунд», «в 4к» — меняем параметры без LLM;
        #    любой другой короткий текст без новой задачи — правка промпта
        card = self._current_card(ses, ctx) if ses.get("picked") else None
        if card and ses.get("await") in ("params", "refine") and intent.name in ("generate_task", "ask_type", "prompt_improve", "off_topic"):
            new_task = intent.name == "generate_task" and (intent.kind != card.kind or len(msg.split()) > 5)
            if not new_task:
                fitted, adj = P.fit(P.extract(msg), card)
                if fitted and len(msg.split()) <= 5:
                    ses["params"] = P.with_defaults(card, {**P.validate(card, ses.get("params")), **fitted})
                    lbl = ", ".join(P.label(k, v, lang) for k, v in fitted.items())
                    return self._setup_reply(card, ses, ctx, lang, "param", t("settings_saved", lang, label=lbl), adj=adj)
                if ses.get("prompt") and intent.name != "generate_task":
                    return self._refine(card, msg, ctx, ses, lang)
        out = getattr(self, "_i_" + intent.name)(intent, msg, ctx, ses, lang)
        # «хочу рилс про кофе» — обычный путь (одно видео) + предложение пройти рилс по шагам
        if intent.name == "generate_task" and UN.REELS_WORD.search(msg) and not MD.state(ses) and not self._is_guest(ctx):
            out["chips"] = list(out.get("chips") or []) + [chip(t("mode_reels_offer", lang), "mode_start", {"id": "reels", "text": msg})]
        return out

    # ================================================================ понимание фразы
    def _understand(self, msg: str, ctx: dict, ses: dict, lang: str) -> dict | None:
        """None — фраза для обычного маршрута (router + флоу). Иначе — готовый ответ."""
        if ctx.get("_tree_hint"):           # текст подсказки дерева — деталь задачи, а не команда интерфейса
            return None
        it0 = route(msg, ctx, ses, self.titles)
        if it0.name == "ui_help" and not self._is_guest(ctx):
            u0 = UN.fast(msg, self.d.cards)
            if u0 and u0["intent"] == "ui_do":   # «открой витрину» — не объяснять, а открыть
                return self._ui_do(u0, ctx, ses, lang)
        # Длинная фраза со словом «как» или «история» — не справка по кнопкам, её читает модель.
        long_help = it0.name == "ui_help" and len(msg.split()) >= 6
        if (it0.name in UN.PROTECTED or (it0.name == "off_topic" and OFF_TOPIC.search(msg))) and not long_help:
            return None                     # безопасность, ошибки, короткие справки и явное «не по теме» — как раньше
        md = MD.active(ses)
        text_step = bool(md and MD.wants_text(ses) and not PL.waiting(ses) and not SB.active(ses))
        u = UN.fast(msg, self.d.cards)
        if u and u["intent"] == "question" and text_step and not (UN.QUESTION_START.search(msg) or UN.HOWTO.search(msg)):
            u = None                        # «Как бариста варит кофе?» на шаге «Идея» — это идея, не вопрос
        if u is None and text_step:
            return MD.on_text(self, ses, ctx, lang, msg)
        # Свежий запрос разбирает языковая модель и сама запускает процесс.
        # Слова из router — только если модели нет или она не ответила.
        # Уже выбранная модель, шаг диалога и кнопки сюда не попадают.
        from .model_lock import lock_of
        fresh = ses.get("await") in (None, "type", "gen_type") and not lock_of(self, ctx, ses)
        if (u is None and self.d.understand_llm and fresh and len(msg.split()) >= 2
                and (it0.name in ("ask_type", "off_topic", "generate_task") or long_help)
                and not PL.waiting(ses) and not SB.active(ses)):
            u = UN.ask_llm(self, msg, ses, ctx)
        if u is None:
            return None
        return self._understood(u, msg, ctx, ses, lang)

    def _understood(self, u: dict, msg: str, ctx: dict, ses: dict, lang: str) -> dict | None:
        intent = u["intent"]
        if intent == "switch_model":
            mid = u.get("model") or ""
            card = self.d.cards.get(mid)
            if not card or (self.d.catalog_fn and not self.d.catalog_fn(mid)):
                return None
            if self._is_guest(ctx):
                return self._ask_login(ses, lang, "switch_model")
            if card.kind != "text":
                return self._pick(mid, ctx, ses, lang, "switch_model")
            out = self._text_chat_ready(card, ses, lang, "switch_model")
            head = t("switched_model", lang, title=card.title)     # цена за ответ видна у кнопки модели
            alt = [m for m in UN.FAMILY_MODELS.get(u.get("family") or "", ()) if m != mid and m in self.d.cards]
            if alt:
                head += "\n" + t("switched_alt", lang, title=self.d.cards[alt[-1]].title)
                out["chips"] = [chip(self.d.cards[alt[-1]].title, "pick_model", alt[-1])] + list(out.get("chips") or [])
            out["text"] = out["reply"] = head
            return out
        if intent == "ui_do":
            return self._ui_do(u, ctx, ses, lang)
        if intent == "start_mode":
            if self._is_guest(ctx):
                return self._ask_login(ses, lang, "mode_start")
            m = MD.state(ses)
            if m and m["id"] == u.get("mode"):
                return MD.show(self, ses, ctx, lang, t("mode_already", lang))
            if m:                               # идёт другой режим — не бросаем его молча
                new = MD.MODES[u.get("mode") or "reels"]["title"][1 if lang.startswith("en") else 0]
                old = MD.MODES[m["id"]]["title"][1 if lang.startswith("en") else 0]
                return response([t("mode_switch_ask", lang, new=new, old=old)],
                                [chip(t("mode_switch_yes", lang, new=new), "mode_start", {"id": u.get("mode") or "reels", "text": msg}, primary=True),
                                 MD.resume_chip(ses, lang)], [], lang, intent="mode_switch_ask")
            return MD.start(self, ses, ctx, lang, u.get("mode") or "reels", text=msg)
        if intent == "question":
            return self._answer(msg, ctx, ses, lang)
        if intent == "generate" and u.get("kind") in ("text", "video", "image", "music", "voice"):
            ses.pop("flow", None)
            it = Intent("generate_task", kind=u["kind"], needs=detect_needs(msg), topic=topic_of(msg))
            return self._i_generate_task(it, msg, ctx, ses, lang)
        return None

    def _ui_do(self, u: dict, ctx: dict, ses: dict, lang: str) -> dict:
        ui, val = u.get("ui"), u.get("value")
        if ui == "theme":
            names = {"white": t("theme_white", lang), "black": t("theme_black", lang), "light": t("theme_light", lang),
                     "violet": t("theme_violet", lang)}
            others = [chip(names[k], "set_theme", k) for k in ("white", "black", "violet", "light") if k != val]
            return response([t("theme_done", lang, name=names.get(val, val))], others[:3], [], lang, intent="ui_do",
                            ui_do={"action": "set_theme", "value": val})
        if ui == "panel":
            key = {"models": "panel_models", "mcp": "panel_mcp", "vit": "panel_vit"}.get(val, "panel_models")
            return response([t(key, lang)], [], [], lang, intent="ui_do", ui_do={"action": "open_panel", "value": val})
        return response([t("new_chat_done", lang)], [], [], lang, intent="ui_do", ui_do={"action": "new_chat", "value": None})

    def _answer(self, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        """Вопрос-совет: «какая лучше для видео» — подборка из каталога; остальное — ответ по фактам студии."""
        has_image = bool(ctx.get("has_image"))
        kind = detect_kind(msg, has_image)
        if kind in KINDS and re.search(r"лучш|посовет|выбра|подойд|подход|какую|какая|какой|какие|что взять|топ|"
                                       r"стоит|цен[аыу]|стоимост|дешев|дорог|better|best|recommend|which|price|cost", msg, re.I):
            kind = "music" if kind == "sfx" else kind
            needs = detect_needs(msg)
            if kind == "text":
                pick = self._recommend("text", needs, has_image)
            else:
                pick = self._recommend(kind, needs, has_image)
            word = err_mod.KIND_WORD.get(lang, err_mod.KIND_WORD["ru"]).get(kind, kind)
            saved = {k: ses.get(k) for k in ("await", "kind", "shown", "assist_mode")}
            out = self._show_models(pick, ses, lang, "question_models", head=t("answer_models", lang, kind=word))
            if MD.active(ses):                     # в режиме подборка — справка, шаг не сбиваем
                ses.update(saved)
            return out
        got = UN.answer_llm(self, msg, ses, lang)
        if got:
            chips = [chip(self.d.cards[m].title, "pick_model", m) for m in got["models"]]
            return response([got["answer"]], chips, [], lang, intent="question")
        low = msg.lower()
        if re.search(r"тем[аеуы]\b|фон|оформлен|theme", low):
            return response([t("answer_theme", lang)], [chip(t("theme_black", lang), "set_theme", "black"),
                                                        chip(t("theme_white", lang), "set_theme", "white"),
                                                        chip(t("theme_violet", lang), "set_theme", "violet")], [], lang,
                            intent="question", degraded=True)
        return response([t("answer_unknown", lang)], [std_chip("open_models", "open_models", lang)] + self._type_chips(ctx, lang)[:3],
                        [], lang, intent="question", degraded=True)

    def _text_as_action(self, msg: str, ses: dict) -> tuple[str, Any] | None:
        if not msg or len(msg.split()) > 6:
            return None
        n = _norm(msg)
        for c in ses.get("last_chips") or []:
            if c.get("label") and _norm(c["label"]) == n and c.get("action") not in {"generate", "send"}:
                return c["action"], c.get("value")
        bare = _norm(_PICK_WORDS.sub("", msg))
        for mid, title in self.titles.items():
            tn = _norm(title)
            if bare == tn or (len(tn) >= 6 and lev(bare, tn, 2) <= 1):
                return "pick_model", mid
        return None

    # ============================================================== helpers
    def _price(self, mid: str) -> str | None:
        try:
            return self.d.price_fn(mid)
        except Exception:
            return None

    def _healthy(self, mid: str) -> bool:
        if not self.d.health_fn:
            return True
        try:
            return bool(self.d.health_fn(mid))
        except Exception:
            return True

    def _recommend(self, kind: str, needs: list[str], has_image: bool, exclude: list[str] | tuple = (),
                   with_cheap: bool = True, n: int | None = None) -> Pick:
        # Видео: сначала 6, по «Ещё» — все оставшиеся (n=None при exclude).
        if n is None and kind == "video" and not exclude:
            n = 6
        return recommend(self.d.cards, kind, needs, has_image, self.d.health_fn, self._price, self.d.neighbors,
                         exclude=exclude, n=n, with_cheap=with_cheap)

    def _sec_hint(self, ses: dict, card: Card) -> int | None:
        """Длительность для оценки цены на карточке. Без явной длительности в идее — 5 с (как в прайсе)."""
        if card.kind != "video":
            return None
        raw = P.extract(ses.get("idea") or "")
        if "duration" in raw:
            params, _ = P.fit(raw, card)
            return P.seconds(card, P.with_defaults(card, params))
        return 5

    def _show_models(self, pick: Pick, ses: dict, lang: str, intent: str, head: str | None = None,
                     extra_top: list[str] | None = None) -> dict[str, Any]:
        if ses.get("files") and not ses.get("files_told"):     # «Вижу фото «cat.png» — показываю модели…»
            extra_top = F.seen_lines(ses["files"], list(pick.cards), lang, self.d.inputs_fn) + list(extra_top or [])
            ses["files_told"] = True
        if not pick.cards:
            return response((extra_top or []) + [t("none_available", lang)],
                            [std_chip("open_models", "open_models", lang)], intent=intent)
        topic = ses.get("topic") or ""
        cards = list(pick.cards)
        prices = {c.id: price_value(short_price(self._price(c.id))) for c in cards}
        known = [p for p in prices.values() if p is not None]
        cheapest_id = min((c.id for c in cards if prices[c.id] is not None), key=lambda i: prices[i], default=None)
        best_id = max(cards, key=lambda c: c.rank).id
        items = []
        # Seedance (pin) первым; остальные — от дешёвых к дорогим
        pinned = set(PIN_FIRST.values())
        def _order(c: Card) -> tuple:
            pin = 0 if c.id in pinned else 1
            price = prices[c.id] if prices[c.id] is not None else 1e9
            return (pin, price, -c.rank)

        for c in sorted(cards, key=_order):
            badge = None
            if prices[c.id] == 0:
                badge = "бесплатно" if lang == "ru" else "free"
            elif c.id == cheapest_id and len(set(known)) > 1:
                badge = "выгоднее" if lang == "ru" else "best price"
            elif c.id == best_id:
                badge = "лучшее качество" if lang == "ru" else "best quality"
            items.append(model_item(c, self._price(c.id), lang, self.d.vitrina_url, topic, badge, self._sec_hint(ses, c)))
        if head is None:
            n = len(items)
            if not pick.exact:
                head = t("closest", lang)
            else:
                head = t("models_head", lang, n=n, topic=topic) if topic else t("models_head_plain", lang, n=n)
        ses["shown"] = list(dict.fromkeys((ses.get("shown") or []) + [c.id for c in cards]))
        ses["await"] = "model"
        # карточки моделей сами кликабельны — отдельные кнопки «Выбрать X» не дублируем
        chips = self._with_back([std_chip("more", "more", lang)], lang)
        blocks: list[dict] = []
        if ses.get("prompt"):
            blocks.append({"type": "prompt", "model_id": "", "title": t("your_prompt", lang),
                           "text": ses["prompt"], "note": ""})
        blocks.append({"type": "models", "items": items})
        return response((extra_top or []) + [head], chips, blocks, lang,
                        intent=intent, models=[{"id": i["id"], "title": i["title"], "price": i["price"]} for i in items])

    def _offer_polish(self, ses: dict, ctx: dict, lang: str, intent: str, head: str | None = None) -> dict:
        """После выбора варианта: доработать промпт Claude/GPT или сразу к запуску / моделям."""
        _clean_polish_copies(ses)
        seen: list[Card] = []
        order = POLISH_WITH_PHOTO if ctx.get("has_image") else POLISH_MODELS
        for i in order:
            c = self.d.cards.get(i)
            if c and self._healthy(i):
                seen.append(c)
        have = {c.id for c in seen}
        rest = [c for c in self.d.cards.values()
                if c.kind == "text" and c.id not in have and self._healthy(c.id)
                and (ctx.get("has_image") or c.id != "claude-opus-4-7")]
        rest.sort(key=lambda c: c.rank)
        cards = (seen + rest)[:6]
        if not cards:
            k = ses.get("kind") or ses.get("gen_kind") or "image"
            mid = ses.get("gen_model") or ses.get("brief_for_model")
            prior = self.d.cards.get(mid or "")
            if prior and prior.kind == k and self._healthy(prior.id):
                return self._pick(prior.id, ctx, ses, lang, intent)
            return self._show_models(self._recommend(k, ses.get("needs") or [], bool(ctx.get("has_image"))),
                                     ses, lang, intent, head=head or t("polish_skip", lang))
        ses["await"] = "polish"
        ses["picked"] = None
        topic = ses.get("topic") or ""
        cta = b("polish_cta", lang)
        items = []
        for c in cards:
            it = model_item(c, self._price(c.id), lang, self.d.vitrina_url, topic)
            it["vitrina_url"] = ""          # у текстовых нет примеров на витрине
            it["cta"] = cta                # явная кнопка «Доработать»
            it["price"] = it["speed"] = it["estimate"] = ""  # на шаге polish не нужны
            it["badge"] = None
            if ctx.get("has_image"):
                if c.id == "claude-opus-4-7":
                    it["badge"] = "Советую" if lang != "en" else "Suggested"
                    it["note"] = "Видит загруженное фото." if lang != "en" else "Sees the uploaded photo."
                elif c.id not in SEES_IMAGE:
                    it["note"] = ("Фото в эту модель не уйдёт." if lang != "en"
                                  else "The photo will not be sent to this model.")
            items.append(it)
        blocks: list[dict] = []
        if ses.get("prompt"):
            blocks.append({"type": "prompt", "model_id": "", "title": t("your_prompt", lang),
                           "text": ses["prompt"], "note": ""})
        blocks.append({"type": "models", "items": items})
        chips = self._with_back([std_chip("skip_polish", "skip_polish", lang, primary=True)], lang)
        return response([head or t("polish_ask", lang, title="")], chips, blocks, lang, intent=intent,
                        models=[{"id": i["id"], "title": i["title"], "price": i["price"]} for i in items])

    def _run_polish(self, text_card: Card, ctx: dict, ses: dict, lang: str) -> dict:
        """Подключить выбранную текстовую модель — дальше прямой чат с ней (не модели генерации)."""
        _clean_polish_copies(ses)
        draft = ses.get("prompt") or ses.get("prompt_base") or ses.get("idea") or ""
        # запомним тип генерации и промпт — «Использовать этот промпт» / выбор Seedance не должны их терять
        if ses.get("kind") and ses["kind"] != "text":
            ses["gen_kind"] = ses["kind"]
        ses["polish_model"] = text_card.id
        ses["polish_draft"] = draft
        self._text_chat_ready(text_card, ses, lang, "polish_chat")  # ses: kind=text, await=chat
        blocks: list[dict] = []
        if draft:
            blocks.append({"type": "prompt", "model_id": text_card.id, "title": t("your_prompt", lang),
                           "text": draft, "note": ""})
        chips = [std_chip("open_models", "open_models", lang), std_chip("ask_type_again_btn", "restart", lang)]
        return response([t("polish_chat_ready", lang, title=text_card.title)], chips, blocks, lang,
                        intent="polish_chat", generate_model=text_card.id, generate_prompt=draft)

    def _budget_ok(self, ses: dict) -> bool:
        return int(ses.get("tokens") or 0) < self.d.token_budget and int(ses.get("llm_calls") or 0) < self.d.max_llm_calls

    def _adapt(self, card: Card, idea: str, params: dict, ses: dict, lang: str, change: str = "",
               prev: str = "") -> tuple[str | None, str, bool]:
        """→ (prompt | None если небезопасно, note, degraded)."""
        llm = self.d.llm
        if llm is not None and llm.available and self._budget_ok(ses):
            ses["llm_calls"] = int(ses.get("llm_calls") or 0) + 1
            try:
                res = llm.complete_json(SYSTEM, build_user(card, idea, params, lang, change, prev), validate_output)
            except LLMUnavailable as exc:
                ses["tokens"] = int(ses.get("tokens") or 0) + exc.tokens
                self._llm_info.update(tokens=self._llm_info["tokens"] + exc.tokens, error=exc.reason, attempts=exc.attempts[-4:])
            else:
                ses["tokens"] = int(ses.get("tokens") or 0) + res.tokens
                self._llm_info.update(used=True, provider=res.provider, tokens=self._llm_info["tokens"] + res.tokens,
                                      latency_ms=res.latency_ms)
                prompt = res.data["prompt"]
                if res.data.get("note") == "unsafe" or not prompt or _unsafe(prompt):
                    return None, "", False
                return prompt, res.data.get("note", ""), False
        elif llm is not None and llm.available:
            self._llm_info["error"] = "budget"
        return fallback_prompt(card, idea, change, prev, lang), "", True

    def _llm_json(self, system: str, user: str, validate: Callable, ses: dict, max_tokens: int,
                  timeout_scale: float = 1.0, task: str = "") -> dict | None:
        """Один JSON-вызов LLM с учётом бюджета сессии. None — LLM нет / не ответила / бюджет кончился."""
        llm = self.d.llm
        if llm is None or not llm.available:
            return None
        if not self._budget_ok(ses):
            self._llm_info["error"] = "budget"
            return None
        ses["llm_calls"] = int(ses.get("llm_calls") or 0) + 1
        system = system + "\n\n" + DG.llm_preface(ses)
        try:
            res = llm.complete_json(system, user, validate, max_tokens=max_tokens, timeout_scale=timeout_scale, task=task)
        except LLMUnavailable as exc:
            ses["tokens"] = int(ses.get("tokens") or 0) + exc.tokens
            self._llm_info.update(tokens=self._llm_info["tokens"] + exc.tokens, error=exc.reason, attempts=exc.attempts[-4:])
            return None
        ses["tokens"] = int(ses.get("tokens") or 0) + res.tokens
        self._llm_info.update(used=True, provider=res.provider, tokens=self._llm_info["tokens"] + res.tokens,
                              latency_ms=res.latency_ms)
        return res.data

    def _current_card(self, ses: dict, ctx: dict) -> Card | None:
        mid = ses.get("picked") or ctx.get("selected_model_id")
        return self.d.cards.get(mid) if mid else None

    def _examples(self, lang: str) -> list[dict]:
        out = []
        for k in ("ex_video", "ex_image", "ex_music"):
            c = chip(b(k, lang), "send", EXAMPLES[k][lang])
            c["example"] = True
            out.append(c)
        return out

    def _back_chip(self, lang: str) -> dict:
        return std_chip("back", "back", lang)

    def _with_back(self, chips: list[dict], lang: str) -> list[dict]:
        if any(c.get("action") == "back" for c in chips):
            return chips
        return list(chips) + [self._back_chip(lang)]

    def _offer_types(self, lines: list[str], ctx: dict, ses: dict, lang: str, intent: str) -> dict:
        """Непонятная фраза — вопрос без меню. Кнопки типа только если тип так и не ясен."""
        if self._is_guest(ctx):
            return self._ask_login(ses, lang, intent)
        # выход из раскадровки по-прежнему предлагает этапы проекта — это не стартовое меню
        if intent == "sb_exit":
            return response(list(lines), self._type_chips(ctx, lang), lang=lang, intent=intent)
        if ses.get("topic") or BR.has_subject(ses.get("idea") or ""):
            if not DG.is_vague(ses.get("idea") or ""):
                out = DG.type_question(ses, lang)
            else:
                out = DG.unclear(self, ses.get("idea") or "", lang, intent)
        else:
            out = DG.unclear(self, ses.get("idea") or "", lang, intent)
        if lines:
            out["text"] = "\n".join(x for x in lines if x) + "\n" + out["text"]
            out["reply"] = out["text"]
            out["intent"] = intent
        return out

    def _type_chips(self, ctx: dict, lang: str) -> list[dict]:
        """Верхний ряд: Промпт → видео / картинка / музыка / звук (или правка фото)."""
        if ctx.get("has_image"):
            kinds = ["prompt", "video", "edit", "image", "music"]
        else:
            kinds = ["prompt", "video", "image", "music"]
        return PL.stage_chips(lang, bool(ctx.get("has_image")))

    def _gen_type_chips(self, ctx: dict, lang: str) -> list[dict]:
        """Типы генерации после выбора «Промпт» (без пункта Промпт). Видео раньше картинки — готовые кинопромпты чаще."""
        if ctx.get("has_image"):
            kinds = ["video", "edit", "image", "music"]
        else:
            kinds = ["video", "image", "music"]
        return self._with_back([chip(b("type_" + k, lang), "choose_type", k) for k in kinds], lang)

    @staticmethod
    def _is_guest(ctx: dict) -> bool:
        acct = ctx.get("_account")
        return isinstance(acct, dict) and not acct.get("authed")

    def _ask_login(self, ses: dict, lang: str, intent: str = "login") -> dict:
        """Гость: просьба войти до выбора типа / идеи / моделей."""
        ses["await"] = "login"
        return response([t("gate_login_early", lang)],
                        [std_chip("login_run", "login", lang, primary=True)],
                        lang=lang, intent=intent, gate="login", ready=False)

    def _ask_type(self, ses: dict, ctx: dict, lang: str) -> dict:
        if self._is_guest(ctx):
            return self._ask_login(ses, lang, "ask_type")
        ses["await"] = "type"
        ses["assist_mode"] = None
        ses["prompt_gate"] = False
        idea = ses.get("idea") or ""
        if not idea and not ses.get("topic"):
            return DG.greet(lang, "ask_type")
        if DG.is_vague(idea):
            return DG.vague_question(lang)
        return DG.type_question(ses, lang)

    def _ask_has_prompt(self, ses: dict, lang: str, intent: str = "has_prompt") -> dict:
        """Спросить, нужен ли промпт. Модель уже может быть в ses['picked'] — не сбрасываем."""
        ses["await"] = "has_prompt"
        ses["prompt_gate"] = True
        card = self.d.cards.get(ses.get("picked") or "")
        if card:
            chips = self._with_back([
                chip(b("has_prompt_yes", lang), "has_prompt", "yes", primary=True),
                chip(b("has_prompt_no_run", lang), "has_prompt", "no"),
            ], lang)
            return response([t("ask_has_prompt_model", lang, title=card.title)], chips,
                            lang=lang, intent=intent, generate_model=card.id)
        chips = self._with_back([
            chip(b("has_prompt_yes", lang), "has_prompt", "yes", primary=True),
            chip(b("has_prompt_no", lang), "has_prompt", "no"),
        ], lang)
        return response([t("ask_has_prompt", lang)], chips, lang=lang, intent=intent)

    def _ask_add_to_prompt(self, card: Card, ses: dict, lang: str, intent: str = "add_prompt") -> dict:
        """Развёрнутый промпт уже есть — уточнить, добавить ли что-то, прежде чем к настройкам."""
        ses["await"] = "add_prompt"
        ses["add_prompt_asked"] = True
        ses["picked"] = card.id
        ses["kind"] = card.kind
        chips = self._with_back([
            chip(b("add_prompt_yes", lang), "add_prompt", "yes", primary=True),
            chip(b("add_prompt_no", lang), "add_prompt", "no"),
        ], lang)
        return response([t("ask_add_to_prompt", lang)], chips, lang=lang, intent=intent, generate_model=card.id)

    def _maybe_ask_add_then_setup(self, card: Card, ctx: dict, ses: dict, lang: str, intent: str) -> dict:
        """Видео — сразу настройки, как у обычного ролика. У длинного промпта другого типа сначала «добавить что-то?»."""
        if card.kind == "video":
            return self._setup_from_idea(card, ctx, ses, lang, intent)
        idea = (ses.get("idea") or ses.get("prompt") or ctx.get("draft") or "").strip()
        if idea and BR.is_rich_prompt(idea) and not ses.get("add_prompt_asked"):
            return self._ask_add_to_prompt(card, ses, lang, "add_prompt")
        return self._setup_from_idea(card, ctx, ses, lang, intent)

    def _go_back(self, ctx: dict, ses: dict, lang: str) -> dict:
        """Шаг назад по меню: тип ← модели ← «нужен промпт?» ← бриф ← варианты ← polish."""
        aw = ses.get("await")
        if aw == "gen_type":
            ses.update(assist_mode=None, kind=None)
            return self._ask_type(ses, ctx, lang)
        if aw == "model":
            if ses.get("kind") == "image" and ses.get("variants") and not ses.get("gen_model"):
                card = self._brief_card(ses)
                if card:
                    return self._show_variants(card, ses, lang, [t("variants_head", lang)], False)
            if ses.get("from_polish"):
                ses["from_polish"] = False
                return self._offer_polish(ses, ctx, lang, "back",
                                          head=t("polish_ask", lang, title=""))
            ses.update(picked=None, brief=None, brief_done=False, brief_for_model=None, shown=[],
                       from_polish=False)
            if ses.get("assist_mode") == "prompt":
                # были в ветке «Промпт» → вернуть выбор типа генерации
                ses["kind"] = None
                ses["await"] = "gen_type"
                return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                lang=lang, intent="back")
            ses.update(kind=None, assist_mode=None, prompt_gate=False)
            return self._ask_type(ses, ctx, lang)
        if aw == "has_prompt":
            ses["picked"] = None
            mode = "prompt" if ses.get("assist_mode") == "prompt" else "direct"
            return self._offer_models_for_kind(ctx, ses, lang, "back", mode=mode)
        if aw == "add_prompt":
            ses["add_prompt_asked"] = False
            mid = ses.get("picked")
            ses["picked"] = None
            mode = "prompt" if ses.get("assist_mode") == "prompt" else "direct"
            if mid and ses.get("kind"):
                return self._offer_models_for_kind(ctx, ses, lang, "back", mode=mode)
            return self._ask_type(ses, ctx, lang)
        if aw == "brief":
            mid = ses.get("brief_for_model") or ses.get("brief_guide")
            ses.update(brief=None, brief_done=False, brief_for_model=None, brief_guide=None)
            if ses.get("prompt_gate") and mid:
                ses["picked"] = mid
                return self._ask_has_prompt(ses, lang, "back")
            ses["picked"] = None
            if ses.get("assist_mode") == "prompt":
                # ветка «Промпт»: назад к выбору типа, без шага нейросети
                ses["kind"] = None
                ses["await"] = "gen_type"
                return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                lang=lang, intent="back")
            if not ses.get("kind") and mid and mid in self.d.cards:
                ses["kind"] = self.d.cards[mid].kind
            if ses.get("kind") == "image" and not ses.get("gen_model"):
                ses["kind"] = None
                return self._ask_type(ses, ctx, lang)
            return self._offer_models_for_kind(ctx, ses, lang, "back", mode="direct")
        if aw == "variants":
            # ветка «Промпт» без опросника — назад к «опишите идею»
            br = ses.get("brief") or {}
            if ses.get("assist_mode") == "prompt" and (br.get("src") == "prompt-direct" or not br.get("q")):
                ses.update(brief=None, brief_done=False, brief_guide=None, brief_for_model=None,
                           variants=[], var_round=0, idea="")
                return self._ask_prompt_idea(ses, lang, intent="back")
            card = self._brief_card(ses)
            if card:
                ses["brief_done"] = False
                return self._brief(card, ses, ctx, lang)
            return self._ask_type(ses, ctx, lang)
        if aw == "polish":
            card = self._brief_card(ses) or self._brief_guide(ses, ctx)
            if card and ses.get("variants"):
                return self._show_variants(card, ses, lang, [t("variants_head", lang)], False)
            if card:
                return self._variants(card, ses, ctx, lang)
            return self._ask_type(ses, ctx, lang)
        if aw in ("params", "refine", "idea"):
            if aw == "idea" and ses.get("assist_mode") == "prompt":
                # ветка «Промпт»: с «опишите идею» назад к выбору типа
                ses["kind"] = None
                ses["await"] = "gen_type"
                return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                lang=lang, intent="back")
            k = ses.get("kind") or ses.get("gen_kind")
            if k and k != "text":
                ses["kind"] = k
                ses["picked"] = None
                ses["prompt_gate"] = False
                mode = ses.get("assist_mode") or "direct"
                return self._offer_models_for_kind(ctx, ses, lang, "back", mode=mode)
            return self._ask_type(ses, ctx, lang)
        # корень / неизвестно
        return self._ask_type(ses, ctx, lang)

    def _start_prompt_assist(self, ctx: dict, ses: dict, lang: str, intent: str) -> dict:
        """Сборка промпта: после «да, улучшить» → clarify модели (идею добираем там), не отдельным «опишите идею»."""
        ses["assist_mode"] = "prompt"
        card = self.d.cards.get(ses.get("picked") or "")
        idea = ses.get("idea") or ""
        if self.d.brief and card:
            # есть модель — сразу вопросы под неё (даже без идеи: clarify соберёт суть)
            if idea and (ses.get("brief_done") or BR.detail_level(idea) >= 12):
                return self._variants(card, ses, ctx, lang)
            return self._brief(card, ses, ctx, lang)
        if not BR.has_subject(idea):
            ses["idea"] = ""
            return self._ask_prompt_idea(ses, lang, intent=intent,
                                         generate_model=card.id if card else None)
        if self.d.brief:
            # модели ещё нет — бриф по типу (нейросеть выберем позже, после промпта)
            return self._enter_brief(ctx, ses, lang)
        if card:
            return self._setup_from_idea(card, ctx, ses, lang, intent)
        return self._enter_brief(ctx, ses, lang)

    def _offer_models_for_kind(self, ctx: dict, ses: dict, lang: str, intent: str,
                               mode: str = "direct") -> dict:
        """Показать модели выбранного типа. mode=prompt|direct — что делать после pick."""
        if self._is_guest(ctx):
            return self._ask_login(ses, lang, intent)
        k = ses.get("kind")
        if k not in KINDS or k == "text":
            return self._ask_type(ses, ctx, lang)
        ses["assist_mode"] = mode
        ses["from_polish"] = False
        has_image = bool(ctx.get("has_image"))
        kind_word = err_mod.KIND_WORD.get(lang, err_mod.KIND_WORD["ru"]).get(k, k)
        head = t("pick_model_for_prompt", lang) if mode == "prompt" else t("pick_model_for_kind", lang, kind=kind_word)
        return self._show_models(self._recommend(k, ses.get("needs") or [], has_image),
                                 ses, lang, intent, head=head)

    def _start_direct_models(self, ctx: dict, ses: dict, lang: str, intent: str) -> dict:
        """Модели для типа (путь без кнопки «Промпт»)."""
        return self._offer_models_for_kind(ctx, ses, lang, intent, mode="direct")

    def _setup_from_idea(self, card: Card, ctx: dict, ses: dict, lang: str, intent: str) -> dict:
        """Без сборки промпта: идея → параметры и запуск под уже выбранную модель."""
        idea = ses.get("idea") or ctx.get("draft") or ""
        if not idea:
            ses["await"] = "idea"
            ses["picked"] = card.id
            return response([t("describe_idea", lang)], [], intent=intent, generate_model=card.id)
        raw_params, adj = P.fit(P.extract(idea), card)
        params = P.with_defaults(card, {**P.validate(card, ses.get("params")), **raw_params})
        ses["prompt_base"] = idea
        ses["prompt"] = CAM.compose(idea, ses.get("camera")) if card.kind == "video" else idea
        ses["params"] = params
        ses["picked"] = card.id
        ses["kind"] = card.kind
        head = t("video_settings" if card.kind == "video" else "model_for_prompt", lang, title=card.title)
        return self._setup_reply(card, ses, ctx, lang, intent, head, "", False, adj)

    # ----------------------------------------------- prompt + params + summary
    def _setup_reply(self, card: Card, ses: dict, ctx: dict, lang: str, intent: str, head: str,
                     note: str = "", degraded: bool = False, adj: list[dict] | None = None) -> dict:
        if card.kind == "video":
            CAM.ensure_default(ses)
            prompt = CAM.apply(ses)  # движение камеры дописывается к базовому промпту
        else:
            prompt = ses.get("prompt") or ""
        params = P.validate(card, ses.get("params"))
        lines = [head]
        for a in adj or []:
            if a["param"] in P.DURATION_NAMES:
                lines.append(t("params_adjusted", lang, asked=a["asked"], got=a["got"]))
        if degraded and not ses.get("degraded_told"):  # один раз за разговор, без технических слов
            lines.append(t("degraded", lang))
            ses["degraded_told"] = True
        bill_id = str(ses.get("route_model") or "") or card.id
        price = short_price(self._price(bill_id)) or t("price_unknown", lang)
        est = estimate(price, P.seconds(card, params), lang)
        has_image = bool(ctx.get("has_image"))
        # Скрепка: какой файл чем станет — по имени («Фото «cat.png» — первый кадр видео»)
        fplan = F.plan(card, ses.get("files") or [], lang, self.d.inputs_fn)
        lines += F.lines(card, fplan, lang)
        blocks: list[dict] = []
        # видео: только настройки + камера (промпт уходит в generate_prompt, без редактора на экране)
        if card.kind != "video":
            blocks.append({"type": "prompt", "model_id": card.id, "title": card.title, "text": prompt, "note": note})
        if card.kind == "video":
            blocks.append(CAM.block(ses.get("camera"), lang))
        groups = P.groups(card, params, lang, has_image)
        if groups:
            blocks.append({"type": "params", "model_id": card.id, "groups": groups})
        cam = CAM.get(ses.get("camera")) if card.kind == "video" else None
        param_lines = [g["label"] + ": " + next((o["label"] for o in g["options"] if o["selected"]), "—")
                       for g in groups]
        if cam:
            param_lines = [t("camera_summary", lang, title=CAM.title(cam, lang))] + param_lines
        blocks.append({"type": "summary", "model_id": card.id, "title": card.title, "price": price, "estimate": est,
                       "prompt": prompt, "params": param_lines, "editable": True,
                       "allow_file": F.accepts(card, "image", self.d.inputs_fn),
                       "files": F.summary_labels(fplan, lang), "files_title": F.summary_title(lang)})
        fb = DG.files_block(card, ses, lang)
        if fb:
            blocks.append(fb)
        sending = bool(ses.get("media")) and (ses.get("files_ok") or len(DG.alive_media(ses)) <= 1)
        if sending:
            bad = DG.incompatible(self, card, ses, ctx, lang)
            if bad:
                return bad
        gate = None
        if card.needs_image and not has_image:
            lines.append(t("needs_image", lang))
            chips = [std_chip("attach", "attach", lang, primary=True), std_chip("no_photo_model", "no_photo_model", lang)]
            ready = False
        else:
            gate, gate_lines, chips = self._gate(card, params, ctx, lang, bill_id)
            lines += gate_lines
            ready = gate in (None, "ok", "free")
        if fb and fb.get("need_confirm"):
            ready = False
            chips = [c for c in chips if c.get("action") != "generate"]
            lines.append("Отметьте, что отправить." if lang != "en" else "Tick what to send.")
        ses["await"] = "params"
        media_files = DG.generate_files(ses) if ses.get("media") else []
        gen_files = media_files or [{"kind": it["kind"], "name": it["name"], **({"id": it["id"]} if it.get("id") else {})}
                                    for it in fplan if it["used"]]
        out = response(lines, chips, blocks, lang, intent=intent, generate_model=bill_id, generate_prompt=prompt,
                       generate_params=params, ready=ready, degraded=degraded, gate=gate,
                       generate_files=gen_files,
                       models=[{"id": bill_id, "title": card.title, "price": price}])
        src = (ses.get("switch_from") or "").strip()
        if src:
            out["switch_line"] = f"{src} → {card.title}"
            ses["switch_from"] = ""
        return out

    # ------------------------------------------- перед запуском: вход → баланс
    def _cost_kop(self, card: Card, params: dict, mid: str | None = None) -> int | None:
        use = mid or card.id
        if self.d.cost_fn:
            try:
                v = self.d.cost_fn(use, params)
                return None if v is None else int(v)
            except Exception:
                log.exception("assistant cost_fn failed")
        price = short_price(self._price(use))
        if not price:
            return None
        ps = per_second(price)
        if ps is not None:
            sec = P.seconds(card, params) or 5
            return int(math.ceil(ps * sec * 100))
        v = price_value(price)
        return None if v is None else int(math.ceil(v * 100))

    def _gate(self, card: Card, params: dict, ctx: dict, lang: str, bill_id: str | None = None) -> tuple[str | None, list[str], list[dict]]:
        """Порядок обязателен: 1) вход, 2) баланс, 3) «Сгенерировать». Сервер /api/generate проверяет то же самое."""
        # видео: только запуск (+ назад); картинка/музыка — ещё улучшить / другая модель
        video = card.kind == "video"
        tail = ([self._back_chip(lang)] if video
                else [std_chip("improve", "improve", lang), std_chip("other_model", "more", lang), self._back_chip(lang)])
        acct = ctx.get("_account")
        use = bill_id or card.id
        cost = self._cost_kop(card, params, use)
        gen_primary = [std_chip("generate", "generate", lang, use, primary=True)]
        if acct is None:  # адаптер не передал аккаунт — проверку делает только сервер генерации
            extras = [] if video else [std_chip("improve", "improve", lang), std_chip("mine", "use_mine", lang),
                                       std_chip("other_model", "more", lang)]
            return None, [t("gate_ready", lang)], self._with_back(gen_primary + extras, lang)
        if not acct.get("authed"):
            return "login", [t("gate_login", lang)], [std_chip("login_run", "login", lang, primary=True)] + tail
        if cost == 0:
            return "free", [t("gate_free", lang)], self._with_back(gen_primary + ([] if video else tail[:-1]), lang)
        have = int(acct.get("available_kop") or 0)
        if cost is not None and have < cost:
            return "topup", [t("gate_topup", lang, have=_rub(have), need=_rub(cost))], self._with_back([
                std_chip("topup", "open_topup", lang, primary=True), std_chip("resume_topup", "resume", lang),
                std_chip("cheaper", "cheaper", lang)], lang)
        head = t("gate_ready_cost", lang, cost=_rub(cost)) if cost else t("gate_ready", lang)
        extras = [] if video else [std_chip("improve", "improve", lang), std_chip("mine", "use_mine", lang),
                                   std_chip("other_model", "more", lang)]
        return "ok", [head], self._with_back(gen_primary + extras, lang)

    def _pick(self, mid: str, ctx: dict, ses: dict, lang: str, intent: str = "pick_model") -> dict:
        alt_of = ses.get("alt_of") if isinstance(ses.get("alt_of"), dict) else {}
        if mid and mid in alt_of:
            ses["route_model"] = mid
            mid = str(alt_of[mid] or "")
        else:
            ses["route_model"] = ""
        card = self.d.cards.get(mid or "")
        if not card:
            if ses.get("kind"):
                pick = self._recommend(ses["kind"], ses.get("needs") or [], bool(ctx.get("has_image")))
                return self._show_models(pick, ses, lang, intent, head=t("unknown_model", lang))
            return self._ask_type(ses, ctx, lang)
        if not self._healthy(card.id):
            pick = self._recommend(card.kind, ses.get("needs") or [], bool(ctx.get("has_image")), exclude=[card.id])
            return self._show_models(pick, ses, lang, "model_down", head=t("alternatives", lang),
                                     extra_top=[t("model_down", lang, title=card.title)])
        # шаг улучшения: Claude/GPT — прямой чат; видео/картинка на этом шаге = взять промпт и к запуску
        if ses.get("await") == "polish":
            if card.kind == "text":
                return self._run_polish(card, ctx, ses, lang)
        ses["picked"] = card.id
        # тип всегда от выбранной карточки (иначе после Claude kind=text «залипает» на Seedance)
        ses["kind"] = card.kind
        if card.kind != "text":
            ses["gen_kind"] = card.kind
            ses["gen_model"] = card.id  # запомнить: после polish не спрашивать модель снова
        # текст — сразу чат с моделью, без брифа / вариантов промпта
        if card.kind == "text":
            out = self._text_chat_ready(card, ses, lang, intent)
            ask = (ses.get("text_ask") or "").strip()
            if ask:
                out["text_ask"] = ask
                ses["text_ask"] = ""
            return out
        # промпт мог остаться только в polish_draft после чата с Claude/GPT
        if not ses.get("prompt") and ses.get("polish_draft"):
            base = ses["polish_draft"]
            ses["prompt_base"] = CAM.strip(base) if card.kind == "video" else base
            ses["prompt"] = CAM.compose(ses["prompt_base"], ses.get("camera")) if card.kind == "video" else base
        idea = ses.get("idea") or ctx.get("draft") or ""
        # без брифа идея нужна сразу; с брифом — сначала «улучшить промпт?», идея/уточнения потом
        if not idea and not ses.get("prompt") and not self.d.brief:
            ses["await"] = "idea"
            return response([t("describe_idea", lang)], [], intent=intent,
                            generate_model=str(ses.get("route_model") or "") or card.id)
        # промпт уже собран: видео — сразу те же настройки, что у обычного ролика; иначе «добавить?» у длинного текста
        if self.d.brief and ses.get("prompt"):
            if card.kind == "video":
                raw_params, adj = P.fit(P.extract(ses.get("idea") or ses["prompt"]), card)
                params = P.with_defaults(card, {**P.validate(card, ses.get("params")), **raw_params})
                ses["params"] = params
                head = t("video_settings", lang, title=card.title)
                return self._setup_reply(card, ses, ctx, lang, intent, head, "", False, adj)
            if BR.is_rich_prompt(ses["prompt"]) and not ses.get("add_prompt_asked") and not ses.get("brief_done"):
                if not ses.get("idea"):
                    ses["idea"] = ses["prompt"]
                return self._ask_add_to_prompt(card, ses, lang, intent)
            raw_params, adj = P.fit(P.extract(idea or ses["prompt"]), card)
            params = P.with_defaults(card, {**P.validate(card, ses.get("params")), **raw_params})
            ses["params"] = params
            head = t("video_settings" if card.kind == "video" else "model_for_prompt", lang, title=card.title)
            return self._setup_reply(card, ses, ctx, lang, intent, head, "", False, adj)
        if self.d.brief:
            mode = ses.get("assist_mode")
            # видео: без «улучшить промпт?»; если промпт уже развёрнутый — спросить, добавить ли что-то
            if card.kind == "video" and mode != "prompt":
                return self._maybe_ask_add_then_setup(card, ctx, ses, lang, intent)
            # картинка/музыка/… → сначала «нужен промпт?», потом clarify под модель
            # (не спрашиваем «опишите идею» до этого — иначе двойной опрос)
            if mode != "prompt" and ses.get("await") != "has_prompt":
                return self._ask_has_prompt(ses, lang, "has_prompt")
            # путь «Промпт» или «да, улучшить» — вопросы профиля модели (и идея, если её ещё нет)
            ses["brief_guide"] = card.id
            if idea and (ses.get("brief_done") or BR.detail_level(idea) >= 12):
                return self._variants(card, ses, ctx, lang)
            return self._brief(card, ses, ctx, lang)
        raw_params, adj = P.fit(P.extract(idea), card)
        kept = P.validate(card, ses.get("params"))
        params = P.with_defaults(card, {**kept, **raw_params})
        prompt, note, degraded = self._adapt(card, idea, params, ses, lang)
        if prompt is None:
            return self._i_safety(Intent("safety"), "", ctx, ses, lang)
        ses["prompt_base"] = prompt
        ses["prompt"] = CAM.compose(prompt, ses.get("camera")) if card.kind == "video" else prompt
        ses["params"] = params
        if card.kind == "video":
            head = t("video_settings", lang, title=card.title)
        else:
            head = t("prompt_ready_simple" if degraded else "prompt_ready", lang, title=card.title)
        return self._setup_reply(card, ses, ctx, lang, intent, head, note, degraded, adj)

    # ============================================================== intents
    def _edit_prompt(self, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        text = value.get("text") if isinstance(value, dict) else value
        text = str(text or "").strip()[:4000]
        card = self._current_card(ses, ctx)
        if not card or not text:
            return response([t("describe_idea", lang)], [], intent="edit_prompt")
        if card.kind == "video":
            prompt = CAM.apply(ses, text)
        else:
            ses["prompt_base"] = text
            ses["prompt"] = text
            prompt = text
        flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
        if flow is not None:
            flow["idea"] = text
            flow["stage"] = "card"
        if isinstance(value, dict) and value.get("quiet"):
            return {"text": "", "reply": "", "blocks": [], "chips": [], "silent": True,
                    "intent": "edit_prompt", "lang": lang, "generate_model": card.id, "generate_prompt": prompt}
        return self._setup_reply(card, ses, ctx, lang, "edit_prompt", t("prompt_changed", lang))

    def _files_confirm(self, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        card = self._current_card(ses, ctx)
        if not card:
            return self._ask_type(ses, ctx, lang)
        problem = DG.confirm(ses, value, card.kind)
        if problem == "limit-video":
            return DG.limit_question(ses, lang, "video")
        return self._setup_reply(card, ses, ctx, lang, "files_confirm", t("summary_head", lang))

    def _media_pick(self, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        mid = str(value or "")
        item = next((m for m in DG.alive_media(ses) if m.get("id") == mid), None)
        if not item:
            return DG.ask_attach(lang, dead=True)
        ses["focus"] = [mid]
        ses["files_ok"] = True
        ses["focus_note"] = DG.take_line(item, lang)
        card = self._current_card(ses, ctx)
        if card:
            return self._setup_reply(card, ses, ctx, lang, "media_pick", DG.take_line(item, lang))
        if item.get("kind") == "video":
            ses["kind"] = ses.get("kind") or "video"
        elif item.get("kind") == "image" and not ses.get("kind"):
            ses["kind"] = "image"
        return self._offer_models_for_kind(ctx, ses, lang, "media_pick", mode="direct")

    def _resume_task(self, ctx: dict, ses: dict, lang: str) -> dict:
        parked = ses.get("parked") if isinstance(ses.get("parked"), dict) else None
        if not parked:
            return DG.greet(lang, "resume")
        ses.update(idea=parked.get("idea") or "", kind=parked.get("kind"), picked=parked.get("picked"),
                   prompt=parked.get("prompt") or "", prompt_base=parked.get("prompt_base") or "",
                   params=parked.get("params") or {}, camera=parked.get("camera"),
                   topic=parked.get("topic") or "", needs=parked.get("needs") or [])
        ses["parked"] = None
        card = self.d.cards.get(ses.get("picked") or "")
        if card and ses.get("prompt"):
            return self._setup_reply(card, ses, ctx, lang, "resume_task", t("summary_head", lang))
        if ses.get("kind"):
            return self._offer_models_for_kind(ctx, ses, lang, "resume_task", mode="direct")
        return DG.greet(lang, "resume")

    def _new_task(self, kind: str | None, msg: str, needs: list[str], topic: str, ses: dict) -> None:
        if DG.maybe_park(ses, msg):
            ses["_just_parked"] = True
        ses.update(kind=kind, assist_mode=None, topic=topic, needs=needs, idea=msg, picked=None, prompt="", prompt_base="",
                   camera=None, camera_cleared=False, params={}, shown=[], gen_model=None, gen_kind=None,
                   brief=None, brief_done=False, brief_guide=None, brief_for_model=None, variants=[], var_round=0)

    def _ask_prompt_idea(self, ses: dict, lang: str, junk: bool = False,
                         intent: str = "need_subject", generate_model: str | None = None) -> dict:
        """Ветка «Промпт»: только просьба описать идею, без опросника «кто в кадре?»."""
        ses["await"] = "idea"
        ses["assist_mode"] = "prompt"
        head = t("describe_idea", lang)
        if junk:
            head = _junk_line(int(ses.get("junk_count") or 1), lang) + "\n" + head
        return response([head], [self._back_chip(lang)], intent=intent, generate_model=generate_model)

    def _ask_subject(self, kind: str, ses: dict, ctx: dict, lang: str, junk: bool = False) -> dict:
        """Пустая или непонятная идея → уточняющие вопросы. Без примеров сюжетов.
        Если человек раз за разом пишет непонятное — не повторяем одно и то же: на 2-й раз коротко,
        с 3-го — кнопки категорий (жанр / тема), чтобы можно было двигаться дальше без текста.
        В ветке «Промпт» — только короткая просьба описать идею."""
        if ses.get("assist_mode") == "prompt":
            return self._ask_prompt_idea(ses, lang, junk=junk)
        ses["await"] = "idea"
        k = kind if kind in KINDS else "image"
        n = int(ses.get("junk_count") or 0) if junk else 0
        if n <= 1:
            head = t("need_subject_" + k, lang)
            if junk:
                head = _junk_line(1, lang) + "\n" + head
            return response([head], [], intent="need_subject")
        L = "en" if lang == "en" else "ru"
        picks = QUICK_PICKS.get(k, QUICK_PICKS["image"])[L]
        chips = [chip(label, "send", value) for label, value in picks]
        chips.append(self._back_chip(lang))
        chips.append(std_chip("ask_type_again_btn", "restart", lang))
        head = _junk_line(n, lang) + "\n" + t("quick_pick_" + ("short" if n == 2 else "buttons"), lang)
        return response([head], chips, intent="need_subject")

    def _text_chat_models(self, ses: dict, ctx: dict, lang: str, intent: str) -> dict:
        """Текст: без брифа — сразу выбрать LLM и перейти в обычный чат."""
        pick = self._recommend("text", ses.get("needs") or [], bool(ctx.get("has_image")))
        if not pick.cards:
            return response([t("none_available", lang)],
                            [std_chip("open_models", "open_models", lang)], intent=intent)
        locked = str(ctx.get("selected_model_id") or "")
        chosen = self.d.cards.get(locked)
        card = chosen if chosen and chosen.kind == "text" else pick.cards[0]
        ses["picked"] = card.id
        ses["kind"] = "text"
        out = self._text_chat_ready(card, ses, lang, intent)
        ask = (ses.get("idea") or "").strip()
        if ask:
            out["text_ask"] = ask
        return out

    def _text_chat_ready(self, card: Card, ses: dict, lang: str, intent: str) -> dict:
        ses["picked"] = card.id
        ses["kind"] = "text"
        ses["await"] = "chat"
        ses.update(brief=None, brief_done=False, brief_guide=None, brief_for_model=None, variants=[], var_round=0,
                   prompt="", prompt_base="", params={})
        # смена модели — отдельной кнопкой; дальше сообщения идут как обычный чат
        chips = [std_chip("open_models", "open_models", lang), std_chip("ask_type_again_btn", "restart", lang)]
        return response([t("text_chat_ready", lang, title=card.title)], chips, intent=intent, generate_model=card.id)

    def _i_generate_task(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        if (it.kind or "") == "text":
            self._new_task("text", msg, it.needs, it.topic, ses)
            if self._is_guest(ctx):
                return self._ask_login(ses, lang, "generate_task")
            return self._text_chat_models(ses, ctx, lang, "generate_task")
        if self._is_guest(ctx):
            # гость: сначала вход, идею/тип сохраняем и продолжим после resume
            idea = msg if BR.has_subject(msg) else ""
            self._new_task(it.kind, idea, it.needs, it.topic if idea else "", ses)
            return self._ask_login(ses, lang, "generate_task")
        if self.d.dialog_v2 and (it.kind or "") != "text":
            opened = DFLOW.start(self, msg, it, ctx, ses, lang)
            if opened is not None:
                return opened
        if self.d.brief and not BR.has_subject(msg):   # «нужно сделать видео» — о чём? сначала суть
            self._new_task(it.kind, "", it.needs, "", ses)
            ses["assist_mode"] = "direct"
            return self._ask_subject(it.kind or "image", ses, ctx, lang)
        self._new_task(it.kind, msg, it.needs, it.topic, ses)
        # картинка: сначала промпт, модели — один раз после варианта
        if (it.kind or "") == "image" and self.d.brief:
            return self._enter_brief(ctx, ses, lang)
        # видео и остальное: сначала модель, потом «нужен промпт?» / clarify
        return self._offer_models_for_kind(ctx, ses, lang, "generate_task", mode="direct")

    def _i_ask_type(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        if self.d.dialog_v2 and not self._is_guest(ctx):
            story = DFLOW.guess_story(msg, self.d.tree)
            if story:
                return DFLOW.start(self, msg, DFLOW._Kind(story), ctx, ses, lang)
            return DFLOW.ask_type(self, msg, ctx, ses, lang)
        self._new_task(None, msg, it.needs, it.topic, ses)
        return self._ask_type(ses, ctx, lang)

    # ------------------------------------------------ бриф и варианты промпта (до выбора модели)
    def _brief_card(self, ses: dict) -> Card | None:
        mid = ses.get("brief_guide") or ses.get("picked")
        return self.d.cards.get(mid) if mid else None

    def _brief_guide(self, ses: dict, ctx: dict) -> Card | None:
        """Модель-ориентир для вопросов/вариантов промпта — ещё не выбор пользователя."""
        card = self._brief_card(ses)
        if card:
            return card
        kind = ses.get("kind") or "image"
        pick = self._recommend(kind, ses.get("needs") or [], bool(ctx.get("has_image")), with_cheap=False)
        if not pick.cards:
            return None
        ses["brief_guide"] = pick.cards[0].id
        return pick.cards[0]

    def _enter_brief(self, ctx: dict, ses: dict, lang: str) -> dict:
        if ses.get("kind") == "text":
            return self._text_chat_models(ses, ctx, lang, "generate_task")
        card = self._brief_guide(ses, ctx)
        if not card:
            pick = self._recommend(ses.get("kind") or "image", ses.get("needs") or [], bool(ctx.get("has_image")))
            return self._show_models(pick, ses, lang, "generate_task")
        if card.kind == "text":
            return self._text_chat_models(ses, ctx, lang, "generate_task")
        idea = ses.get("idea") or ""
        if ses.get("brief_done") or BR.detail_level(idea) >= 12:
            return self._variants(card, ses, ctx, lang)
        return self._brief(card, ses, ctx, lang)

    def _prompt_from_idea(self, ctx: dict, ses: dict, lang: str) -> dict:
        """Ветка «Промпт»: идея уже есть → сразу варианты промпта, без опросника и без выбора модели."""
        ses["assist_mode"] = "prompt"
        if ses.get("kind") == "text":
            return self._text_chat_models(ses, ctx, lang, "generate_task")
        card = self._brief_guide(ses, ctx)
        if not card:
            return response([t("describe_idea", lang)], [self._back_chip(lang)], intent="need_subject")
        ses["brief"] = {"q": [], "a": {}, "extra": [], "summary": "", "src": "prompt-direct", "phase": "done"}
        return self._variants(card, ses, ctx, lang)

    @staticmethod
    def _profile_brief(br: dict) -> bool:
        src = br.get("src") or ""
        return src.startswith("rules-profile") or src.startswith("llm-profile")

    def _brief_after_open(self, card: Card, ses: dict, ctx: dict, lang: str) -> dict:
        """После этапа 1 (ответ или «Продолжить») — кнопки по незакрытым параметрам."""
        br = ses.get("brief") or {}
        blob = " ".join([ses.get("idea") or ""] + list(br.get("extra") or []))
        found = BR.detect_slot_answers(card.kind, blob)
        a = {**(br.get("a") or {}), **found}
        q, _ = BR.rule_questions(card.kind, blob, lang, card=card, use_profile=True, phase="slots")
        if not q:
            return self._variants(card, ses, ctx, lang)
        br.update(q=q, a=a, phase="slots", src=br.get("src") or "rules-profile")
        ses["brief"] = br
        note = t("brief_head_slots" if br.get("extra") else "brief_head_slots_skip", lang)
        return self._brief(card, ses, ctx, lang, note=note)

    def _brief(self, card: Card, ses: dict, ctx: dict, lang: str, note: str = "") -> dict:
        idea = ses.get("idea") or ""
        br = ses.get("brief") or {}
        # модель: этап 1 — clarify (открытые); этап 2 — кнопки слотов; structure/example — при сборке
        ses["brief_guide"] = card.id
        picking = bool(ses.get("picked") == card.id and card.clarify_list(lang))
        use_profile = picking or (ses.get("brief_for_model") == card.id and bool(card.clarify_list(lang)))
        if picking and ses.get("brief_for_model") != card.id:
            br = {}  # только при первом входе под выбранную модель — вопросы из clarify
            ses["brief_for_model"] = card.id
        if not br.get("q") and br.get("phase") != "slots":
            if use_profile:
                # без LLM на этом шаге — иначе UI «думает» 5–15 с; темы из clarify,
                # уже закрытые идеей, отфильтровываем в rule_questions
                q, a = BR.rule_questions(card.kind, idea, lang, card=card, use_profile=True, phase="open")
                br = {"q": q, "a": a, "extra": [], "summary": "", "src": "rules-profile", "phase": "open"}
                if not br.get("q"):
                    # идея уже закрыла clarify → сразу кнопки стиля/атмосферы/кадра
                    ses["brief"] = {**br, "phase": "open"}
                    return self._brief_after_open(card, ses, ctx, lang)
            else:
                data = self._llm_json(BR.BRIEF_SYSTEM, BR.brief_user(card, idea, lang),
                                      BR.validate_brief, ses, 450, timeout_scale=1.5, task="brief")
                if data is not None and not data["clear"]:
                    ses["idea"] = ""
                    return self._ask_subject(card.kind, ses, ctx, lang, junk=True)
                if data and data["questions"]:
                    br = {"q": data["questions"], "a": {}, "extra": [], "summary": data.get("summary") or "",
                          "src": "llm", "phase": "all"}
                else:
                    q, a = BR.rule_questions(card.kind, idea, lang, phase="all")
                    br = {"q": q, "a": a, "extra": [], "summary": "", "src": "rules", "phase": "all"}
        ses["brief"] = br
        ses["await"] = "brief"
        for_model = ses.get("brief_for_model") == card.id
        ses["picked"] = None
        phase = br.get("phase") or "all"
        if note and phase == "slots":
            head = note
            note = ""
        elif for_model:
            head = (t("brief_head_model_summary", lang, summary=br["summary"], title=card.title)
                    if br.get("summary") else t("brief_head_model", lang, title=card.title))
        else:
            head = t("brief_head_summary", lang, summary=br["summary"]) if br.get("summary") else t("brief_head", lang)
        lines = ([note] if note else []) + [head]
        if br.get("extra") and phase != "slots":
            lines.append(t("brief_saved", lang, detail="; ".join(br["extra"])))
        blocks = [{"type": "brief", "model_id": card.id, "title": "",
                   "questions": BR.render_questions(br["q"], br["a"], lang)}]
        # камера и кнопки слотов — только на этапе 2 (или в классическом брифе)
        if card.kind == "video" and phase != "open":
            CAM.ensure_default(ses)
            blocks.append(CAM.block(ses.get("camera"), lang))
        # этап 1: «Продолжить» → кнопки; этап 2: «Сделать промпт» → варианты
        cta = "continue_brief" if phase == "open" else "continue_prompt"
        chips = [
            std_chip(cta, "variants", lang, "skip", primary=True),
            self._back_chip(lang),
        ]
        return response(lines, chips, blocks, lang, intent="brief")

    def _answers_text(self, br: dict) -> dict[str, str]:
        out = {}
        for q in br.get("q") or []:
            v = (br.get("a") or {}).get(q["id"])
            if v and v != BR.ANY:
                out[q["label"]] = next((o["label"] for o in q["options"] if o["value"] == v), v)
        return out

    def _photo_upload(self, ses: dict) -> dict | None:
        for f in ses.get("files") or []:
            if not isinstance(f, dict) or f.get("kind") != "image":
                continue
            fid = str(f.get("id") or "")
            if fid.startswith("upl_"):
                return f
        return None

    def _maybe_look(self, card: Card, ses: dict, ctx: dict, lang: str) -> dict | None:
        """Фото есть, а сетка его не видит. Просим Opus посмотреть кадр и назвать действия."""
        if not self.d.dialog_v2 or card.kind not in ("video", "image"):
            return None
        if self._is_guest(ctx) or not ctx.get("has_image"):
            return None
        photo = self._photo_upload(ses)
        if not photo:
            return None
        key = f"{photo['id']}:{int(ses.get('var_round') or 0)}"
        state = str(ses.get("photo_look") or "")
        if state == key:
            return None
        head = ("Forming the prompt with Claude, about 20 seconds — the AI is polishing the details."
                if lang == "en" else
                "Формирую промпт через Claude, около 20 секунд — нейросеть дорабатывает детали.")
        buttons = _look_buttons(lang)
        if state == "pending:" + key:
            return response([head], buttons, lang=lang, intent="look_photo_wait")
        ses["photo_look"] = "pending:" + key
        ask = BR.look_ask(lang, ses.get("idea") or "", card.kind)
        return response([head], buttons, lang=lang, intent="look_photo",
                        generate_model=BR.LOOK_MODEL, text_ask=ask)

    def _variants(self, card: Card, ses: dict, ctx: dict, lang: str, change: str = "") -> dict:
        looked = self._maybe_look(card, ses, ctx, lang)
        if looked is not None:
            return looked
        idea = ses.get("idea") or ""
        br = ses.get("brief") or {"q": [], "a": {}, "extra": []}
        ses["brief_guide"] = card.id
        raw_params, adj = P.fit(P.extract(idea + " " + " ".join(br.get("extra") or [])), card)
        params = P.with_defaults(card, {**P.validate(card, ses.get("params")), **raw_params})
        # Готовый длинный текст (например после Claude) не переписываем коротким шаблоном.
        if BR.detail_level(idea) >= 40 and card.kind in ("image", "edit", "video", "music", "voice"):
            title = "As described" if lang == "en" else "Как вы описали"
            ses.update(variants=[{"id": "v1", "title": title, "text": idea.strip()}],
                       brief_done=True, params=params, picked=None)
            lines = ["Using this text as the prompt. You can edit it in the card." if lang == "en" else
                     "Беру этот текст как промпт. Его можно поправить прямо в карточке."]
            return self._show_variants(card, ses, lang, lines, True)
        answers_text = self._answers_text(br)
        extra = list(br.get("extra") or [])
        if ctx.get("has_image") and not BR.scene_words(idea):
            idea = BR.photo_frame(lang)
        elif ctx.get("has_image"):
            lock = ("Кадр — загруженное фото: человека, одежду, место и свет не меняй."
                    if lang != "en" else
                    "The frame is the uploaded photo: do not change the person, clothes, place or light.")
            if lock not in extra:
                extra.append(lock)
        data = self._llm_json(BR.VARIANTS_SYSTEM, BR.variants_user(card, idea, answers_text, extra,
                                                                  params, lang, change, bool(ctx.get("has_image"))),
                              BR.validate_variants, ses, 1400, timeout_scale=2.5, task="variants")
        if data is None and self.d.llm is not None and self._llm_info.get("error") != "budget":
            # на 3 варианта модели не хватило (время/формат) — просим ОДИН промпт
            full = "; ".join([idea] + [f"{k}: {v}" for k, v in answers_text.items()] + extra)
            if change:
                full += "; " + change
            one = self._llm_json(SYSTEM, build_user(card, full, params, lang), validate_output, ses, 450,
                                 timeout_scale=1.5, task="variants_one")
            if one and one.get("prompt") and one.get("note") != "unsafe" and not _unsafe(one["prompt"]) and BR.in_lang(one["prompt"], lang):
                data = {"variants": BR.variants_from_one(card, one["prompt"], lang)}
        if data and not all(BR.in_lang(v.get("text") or "", lang) for v in data.get("variants") or []):
            data = None
        if data and ctx.get("has_image") and not all(
                BR.keeps_photo(v.get("text") or "", lang, idea) for v in data.get("variants") or []):
            data = None
        degraded = data is None
        if degraded:
            answers = {k: v for k, v in (br.get("a") or {}).items()}
            if change and change not in extra:
                extra.append(change)
            items = BR.rule_variants(card, idea, answers, extra, lang, int(ses.get("var_round") or 0),
                                     questions=br.get("q"))
        else:
            items = [v for v in data["variants"] if not _unsafe(v["text"])]
            if not items:
                own = ses.get("idea") or idea
                if _unsafe(own):
                    return self._i_safety(Intent("safety"), "", ctx, ses, lang)
                items = BR.quick_generation_variants(
                    card, own, lang, bool(ctx.get("has_image")), int(ses.get("var_round") or 0))
        ses.update(variants=items, brief_done=True, params=params, picked=None)
        quick = bool(ses.pop("_quick_prompt", None))
        if quick:
            lines = ["A quick prompt." if lang == "en" else "Быстрый промпт."]
        else:
            lines = [t("variants_simple" if degraded else "variants_head", lang)]
            if degraded and not ses.get("degraded_told"):
                lines.append(t("degraded", lang))
                ses["degraded_told"] = True
        return self._show_variants(card, ses, lang, lines, degraded)

    def _show_variants(self, card: Card, ses: dict, lang: str, lines: list[str], degraded: bool) -> dict:
        ses["await"] = "variants"
        items, params = ses.get("variants") or [], P.validate(card, ses.get("params"))
        # в карточках вариантов сразу видно дописанное движение камеры (база в ses["variants"] без него)
        shown = items
        if card.kind == "video" and ses.get("camera"):
            shown = [{"id": i["id"], "title": i["title"], "text": CAM.compose(i["text"], ses.get("camera"))}
                     for i in items]
        # камера только на брифе — на вариантах промпта пикер не показываем
        blocks = [{"type": "variants", "model_id": card.id, "title": "", "items": shown}]
        chips = [
            std_chip("more_variants", "more_variants", lang),
            std_chip("back", "back", lang),  # тот же «Назад», что и на других шагах
        ]
        return response(lines, chips, blocks, lang, intent="variants", degraded=degraded, generate_params=params)

    def _look_done(self, value: dict, ctx: dict, ses: dict, lang: str) -> dict:
        """Ответ Opus по фото → сетка действий. Пустой или кривой ответ — прежние общие варианты."""
        photo = self._photo_upload(ses)
        if photo:
            ses["photo_look"] = f"{photo['id']}:{int(ses.get('var_round') or 0)}"
        card = self._brief_guide(ses, ctx)
        items = [v for v in (BR.parse_look(str(value.get("text") or "")) or []) if not _unsafe(v.get("text") or "")]
        if card and len(items) >= 2:
            ses.update(variants=items, brief_done=True, picked=None)
            flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
            if flow is not None:
                flow["stage"] = "variants"
                flow["next"] = "variants"
            head = ("Three actions from this photo. Edit the text, then pick one."
                    if lang == "en" else
                    "Три действия по этому фото. Текст можно поправить, потом выберите одно.")
            out = self._show_variants(card, ses, lang, [head], False)
            if card.kind == "video":
                label = "Refine in Claude or GPT" if lang == "en" else "Доработать в Claude или GPT"
                out["chips"] = [chip(label, "flow_polish")] + list(out.get("chips") or [])
            return out
        if card:
            return self._look_skip(ctx, ses, lang)
        return response(["Не разобрала ответ." if lang != "en" else "Could not read the reply."],
                        [], lang=lang, intent="look_done")

    def _look_skip(self, ctx: dict, ses: dict, lang: str) -> dict:
        """Не ждать Claude: быстрый промпт собирает помощник."""
        photo = self._photo_upload(ses)
        if photo:
            ses["photo_look"] = f"{photo['id']}:{int(ses.get('var_round') or 0)}"
        card = self._brief_guide(ses, ctx)
        if not card:
            return response(["Не вижу задачу." if lang != "en" else "I don't see a task."],
                            [], lang=lang, intent="look_skip")
        idea = (ses.get("idea") or "").strip()
        flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
        if BR.is_look_instruction(idea):
            idea = ((flow or {}).get("idea_user") or "").strip()
            if BR.is_look_instruction(idea):
                idea = ""
            ses["idea"] = idea
            if flow is not None:
                flow["idea"] = idea
        items = BR.quick_generation_variants(card, idea, lang, bool(ctx.get("has_image")), int(ses.get("var_round") or 0))
        ses.update(variants=items, brief_done=True, picked=None)
        head = "A quick prompt." if lang == "en" else "Быстрый промпт."
        out = self._show_variants(card, ses, lang, [head], True)
        if card.kind == "video" and not any(c.get("action") == "flow_polish" for c in out.get("chips") or []):
            label = "Refine in Claude or GPT" if lang == "en" else "Доработать в Claude или GPT"
            out["chips"] = [chip(label, "flow_polish")] + list(out.get("chips") or [])
        return out

    def _look_next(self, ctx: dict, ses: dict, lang: str) -> dict:
        """Не собирать новый промпт: текущий текст идёт на следующий шаг."""
        photo = self._photo_upload(ses)
        if photo:
            ses["photo_look"] = f"{photo['id']}:{int(ses.get('var_round') or 0)}"
        flow = ses.get("flow") if isinstance(ses.get("flow"), dict) else None
        text = (ses.get("prompt_base") or ses.get("prompt") or (flow or {}).get("idea") or ses.get("idea") or "").strip()
        if not text:
            return response(["Нет текущего промпта." if lang != "en" else "There is no prompt yet."],
                            _look_buttons(lang), lang=lang, intent="look_next")
        card = self._brief_guide(ses, ctx)
        ses["prompt_base"] = text
        if card and card.kind == "video":
            CAM.ensure_default(ses)
            ses["prompt"] = CAM.compose(text, ses.get("camera"))
        else:
            ses["prompt"] = text
        ses["brief_done"] = True
        ses["polish_draft"] = ses["prompt"]
        if flow is not None:
            flow["idea"] = ses["prompt"]
            ses["idea"] = ses["prompt"]
            which = flow.get("prompt_for") or "idea"
            kind = flow.get("kind") or (card.kind if card else "") or ses.get("kind")
            if which == "photos":
                flow["path"] = "photos"
                flow["next"] = "cast_images"
                return DFLOW._advise(self, ctx, ses, lang)
            if which == "board":
                return DFLOW._board(self, ctx, ses, lang)
            if kind == "video":
                if flow.get("polished"):
                    return DFLOW._go_direct(self, ctx, ses, lang)
                return DFLOW._paths(self, ses, lang)
            return DFLOW._advise(self, ctx, ses, lang)
        return response([ses["prompt"]], [], lang=lang, intent="look_next")

    def _i_prompt_improve(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        card = self._current_card(ses, ctx)
        if not card:
            if ses.get("kind"):
                return self._show_models(self._recommend(ses["kind"], ses.get("needs") or [], bool(ctx.get("has_image"))),
                                         ses, lang, "prompt_improve")
            return self._ask_type(ses, ctx, lang)
        if ses.get("prompt"):
            return self._refine(card, it.data.get("change") or msg, ctx, ses, lang)
        idea = re.sub(r"^\W*(улучши|перепиши|доработай|improve|rewrite)\w*\s*(промпт|текст|prompt|the prompt|my prompt)?\s*[:\-—]?\s*",
                      "", msg, flags=re.I).strip() or (ctx.get("draft") or "")
        ses.update(idea=idea, kind=card.kind, picked=card.id, topic=topic_of(idea))
        return self._pick(card.id, ctx, ses, lang, intent="prompt_improve")

    def _refine(self, card: Card, change: str, ctx: dict, ses: dict, lang: str) -> dict:
        if BR.is_junk(change):  # «ооло» не дописываем в промпт — переспрашиваем
            sugg = REFINE_SUGGEST.get(card.kind, REFINE_SUGGEST["image"])["en" if lang == "en" else "ru"]
            ses["await"] = "refine"
            return response([t("refine_unclear", lang)], [chip(x, "refine", x) for x in sugg], intent="refine_unclear")
        params = P.validate(card, ses.get("params"))
        prompt, note, degraded = self._adapt(card, ses.get("idea") or "", params, ses, lang,
                                             change=change, prev=ses.get("prompt") or "")
        if prompt is None:
            return self._i_safety(Intent("safety"), "", ctx, ses, lang)
        ses["prompt_base"] = prompt
        ses["prompt"] = CAM.compose(prompt, ses.get("camera")) if card.kind == "video" else prompt
        return self._setup_reply(card, ses, ctx, lang, "prompt_improve", t("prompt_changed", lang), note, degraded)

    def _i_generate_now(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        card = self._current_card(ses, ctx)
        # «сгенерируй картинку девушки…» — идея. Голое «запускай» — команда запуска.
        rest = re.sub(
            r"^(сгенерируй|генерируй|запусти|запускай|давай\s+генерир\w*|поехали|го|generate|run\s+it|go\s+ahead|start)\b",
            "", msg or "", count=1, flags=re.I).strip(" \t:.-—")
        if BR.has_subject(rest):
            kind = detect_kind(msg, bool(ctx.get("has_image")))
            if not kind and card:
                kind = "image" if card.kind == "edit" else card.kind
            task = Intent("generate_task", kind=kind or "image", needs=detect_needs(msg), topic=topic_of(msg))
            return self._i_generate_task(task, msg, ctx, ses, lang)
        if not card:
            return self._ask_type(ses, ctx, lang)
        if not ses.get("prompt"):
            ses["prompt"] = ses.get("idea") or ctx.get("draft") or ""
        if not ses["prompt"]:
            ses["await"] = "idea"
            ses["kind"] = "image" if card.kind == "edit" else card.kind
            ses["picked"] = card.id
            return response([t("describe_idea", lang)], [], intent="generate_now", generate_model=card.id)
        ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
        return self._setup_reply(card, ses, ctx, lang, "generate_now", t("summary_head", lang))

    def _i_compare(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ids = [m for m in it.data.get("models", []) if m in self.d.cards]
        cards = [self.d.cards[m] for m in ids]
        if self.d.dialog_v2:
            return DFLOW.compare_cards(self, cards, lang)
        if cards and not ses.get("kind"):
            ses["kind"] = cards[0].kind
        return self._show_models(Pick(cards, True), ses, lang, "compare", head=t("compare_head", lang))

    def _i_price(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        kind = ses.get("kind")
        rows = cheapest(self.d.cards, kind, self._price, self.d.health_fn, limit=4 if kind else 3)
        return self._show_models(Pick([c for c, _ in rows], True), ses, lang, "price", head=t("cheapest_head", lang))

    def _alt_kind(self, card, ctx: dict, ses: dict) -> str | None:
        """Тип для подбора замены: панель UI (картинка/видео) важнее kind карточки (edit у Nano Banana)."""
        ui = str(ctx.get("selected_model_kind") or "").strip().lower()
        if ui in KINDS:
            return ui
        if card and card.kind in KINDS:
            # правки фото на панели = картинки → при отказе предлагаем image-модели
            return "image" if card.kind == "edit" else card.kind
        k = ses.get("kind")
        return k if k in KINDS else None

    def _i_error_help(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        mid = str(ctx.get("selected_model_id") or ses.get("picked") or "")
        card = self.d.cards.get(mid) if mid else None
        kind = self._alt_kind(card, ctx, ses)
        code, lines, chip_keys = err_mod.explain(ctx, lang, kind)
        chips = [std_chip(key, action, lang) for key, action in chip_keys]
        # канал недоступен или фильтр контента — сразу другие нейросети того же типа
        # (Seedance → Kling, Seedream/Nano Banana → другие картинки)
        if code == "timeout" and kind:
            return self._timeout_models(mid, card, kind, ctx, ses, lang, lines)
        if code in {"channel_unavailable", "moderation"} and kind:
            title = (card.title if card else None) or str(ctx.get("selected_model_title") or mid or "").strip() or kind
            if code == "moderation":
                lines = [t("moderation_try_other", lang, title=title)]
            exclude = [mid] if mid else []
            if card and card.id not in exclude:
                exclude.append(card.id)
            # Nano Banana = edit в карточках, но на UI картинка — не предлагать «себя» из edit
            if kind == "image":
                for bid in ("nano-banana-2", "nano-banana-pro"):
                    if bid not in exclude and (mid.startswith("nano-banana") or (card and card.id.startswith("nano-banana"))):
                        exclude.append(bid)
            pick = self._recommend(kind, ses.get("needs") or [], bool(ctx.get("has_image")), exclude=exclude,
                                   with_cheap=False)
            head = t("alternatives", lang) if code == "channel_unavailable" else t("moderation_models", lang)
            out = self._show_models(pick, ses, lang, "error_help", head=head, extra_top=lines)
            out["error_code"] = code
            if code == "moderation":
                out_chips = list(out.get("chips") or [])
                out_chips.append(std_chip("rephrase", "rephrase", lang))
                out["chips"] = out_chips
            return out
        return response(lines, chips, intent="error_help", error_code=code)

    def _timeout_models(self, mid: str, card: Card | None, kind: str, ctx: dict, ses: dict, lang: str,
                        lines: list[str]) -> dict:
        """Таймаут: та же модель по цене другой площадки, затем остальные нейросети."""
        title = (card.title if card else None) or str(ctx.get("selected_model_title") or mid or "").strip() or kind
        alt_id = ""
        if self.d.alt_fn and mid:
            try:
                alt_id = str(self.d.alt_fn(mid, str(ctx.get("job_provider") or ""), bool(ctx.get("has_image"))) or "")
            except Exception:
                log.exception("assistant alt_fn failed")
                alt_id = ""
        if alt_id and card:
            lines = [t("timeout_try_other", lang, title=title)]
        else:
            lines = [t("timeout_other_only", lang, title=title)]
        exclude = [mid] if mid else []
        if card and card.id not in exclude:
            exclude.append(card.id)
        pick = self._recommend(kind, ses.get("needs") or [], bool(ctx.get("has_image")), exclude=exclude, with_cheap=False)
        out = self._show_models(pick, ses, lang, "error_help", head=t("alternatives", lang), extra_top=lines)
        if alt_id and card:
            price = short_price(self._price(alt_id)) or t("price_unknown", lang)
            item = model_item(card, price, lang, self.d.vitrina_url, ses.get("topic") or "", t("other_route", lang), None)
            item["id"] = alt_id
            item["why"] = t("same_model_other_route", lang)
            item["estimate"] = None
            for bl in out.get("blocks") or []:
                if bl.get("type") == "models":
                    bl["items"] = [item] + list(bl.get("items") or [])
                    break
            else:
                out["blocks"] = list(out.get("blocks") or []) + [{"type": "models", "items": [item]}]
            ses.setdefault("alt_of", {})[alt_id] = card.id
            out["models"] = [{"id": alt_id, "title": card.title, "price": price}] + list(out.get("models") or [])
        out["error_code"] = "timeout"
        return out

    def _i_ui_help(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        lines, chip_keys = ui_help(it.data.get("topic", "models"), lang)
        chips = [std_chip(k, a, lang, self.d.vitrina_url if a == "open_vitrina" else None) for k, a in chip_keys]
        return response(lines, chips, intent="ui_help", topic=it.data.get("topic"))

    def _i_smalltalk(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses["await"] = "idea"
        kind = it.data.get("kind", "hello")
        if kind == "hello" and not self._is_guest(ctx):
            return DG.greet(lang, "smalltalk")
        if kind == "who" and not self._is_guest(ctx):
            return DG.capabilities(lang)
        return self._offer_types([t(kind, lang)], ctx, ses, lang, "smalltalk")

    def _i_off_topic(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        # формат → содержание → модель; примеры сюжетов не подсовываем
        ses.update({"await": None, "assist_mode": None, "idea": "", "topic": "", "kind": None,
                    "picked": None, "prompt": "", "params": {}, "junk_count": 0})
        return DG.unclear(self, msg, lang, "off_topic")

    def _i_injection(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses.update({"await": "type", "assist_mode": None, "idea": "", "topic": "", "kind": None,
                    "picked": None, "prompt": "", "params": {}, "junk_count": 0})
        return response([t("injection", lang)], [], intent="injection")

    def _i_safety(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses.update(prompt="")
        return response([t("safety", lang)], [std_chip("rephrase", "rephrase", lang)], intent="safety")

    def _i_safety_person(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        return response([t("safety_person", lang)], [], intent="safety_person")

    def _i_crisis(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        return response([t("crisis", lang)], [], intent="crisis")

    # ============================================================== actions
    def _maybe_switch_message(self, msg: str, ctx: dict, ses: dict, lang: str) -> dict | None:
        """Из чата генерации — в текст, или «по этому» после ответа текстовой модели."""
        if not msg or SB.active(ses) or PL.waiting(ses) or ses.get("assist_mode") in {"sb", "reel"}:
            return None
        from assistant.switch import generation_kind, refers_to_previous

        if ses.get("kind") in {"video", "image", "music", "edit"} and generation_kind(msg, False) is None:
            if re.search(r"объясни|перевед|придумай\s+текст|напиши\s+(сценарий|подпись|текст|пост)|подпись\s+для", msg, re.I):
                return self._offer_text_for_write(msg, ses, ctx, lang)
        kind = generation_kind(msg, bool(ctx.get("has_image")))
        texts = [row.get("text") for row in (ses.get("texts") or []) if isinstance(row, dict) and row.get("text")]
        if kind and refers_to_previous(msg) and texts:
            last = (ses.get("texts") or [])[-1]
            return self._model_switch({
                "text": msg, "kind": kind, "replies": texts,
                "from_name": last.get("name") or "", "from_id": last.get("model") or "",
            }, ctx, ses, lang)
        return None

    def _remember_texts(self, ses: dict, value: dict) -> None:
        if not isinstance(value, dict):
            return
        name = str(value.get("from_name") or value.get("name") or "")[:80]
        mid = str(value.get("from_id") or value.get("model") or "")[:80]
        items: list[str] = []
        replies = value.get("replies")
        if isinstance(replies, list):
            items = [str(x).strip()[:4000] for x in replies if str(x).strip()]
        elif str(value.get("text") or "").strip():
            items = [str(value.get("text")).strip()[:4000]]
        bag = [row for row in (ses.get("texts") or []) if isinstance(row, dict)]
        for text in items:
            bag.append({"model": mid, "name": name, "text": text})
        ses["texts"] = bag[-8:]

    def _offer_text_for_write(self, msg: str, ses: dict, ctx: dict, lang: str) -> dict:
        ses["text_ask"] = msg[:2000]
        pick = self._recommend("text", [], False, n=3)
        head = "Для такого текста лучше языковая модель." if lang != "en" else "A text model is a better fit for this."
        return self._show_models(pick, ses, lang, "switch_text", head=head)

    def _model_switch(self, value: dict, ctx: dict, ses: dict, lang: str) -> dict:
        from assistant.switch import generation_kind, prompt_candidates, refers_to_previous

        text = str(value.get("text") or "")[:2000]
        replies = [str(x).strip()[:4000] for x in (value.get("replies") or []) if str(x).strip()]
        if not replies:
            replies = [str(row.get("text")).strip()[:4000] for row in (ses.get("texts") or [])
                       if isinstance(row, dict) and str(row.get("text") or "").strip()]
        self._remember_texts(ses, value if replies and value.get("replies") else {"text": ""})
        from assistant.switch import kind_only
        only = kind_only(text)
        kind = only or str(value.get("kind") or "") or generation_kind(text, bool(ctx.get("has_image"))) or "video"
        if kind == "storyboard":
            cands = prompt_candidates(replies)
            script = cands[0] if cands else text
            return SB.start(self, ses, ctx, lang, text=script)
        if kind not in {"video", "image", "music", "voice"}:
            kind = "video"
        from_name = str(value.get("from_name") or ("Claude" if lang != "en" else "the text model"))
        stay = chip(
            (f"Остаться в {from_name}" if lang != "en" else f"Stay in {from_name}"),
            "stay_text",
            {"text": text, "model": str(value.get("from_id") or "")},
        )
        cands = prompt_candidates(replies) if refers_to_previous(text) else []
        if only and replies:
            cands = [max(replies, key=len)]
        if refers_to_previous(text) and len(cands) >= 2:
            ses["switch_cands"] = cands[:4]
            ses["switch_kind"] = kind
            ses["switch_text"] = text
            ses["switch_from"] = from_name
            ses["switch_from_id"] = str(value.get("from_id") or "")
            labels = []
            for i, cand in enumerate(cands[:4]):
                head = cand.replace("\n", " ")[:42]
                labels.append(chip(f"{i + 1}) «{head}»", "switch_pick", i))
            ask = "По какому тексту делаем?" if lang != "en" else "Which text should we use?"
            return response([ask], labels + [stay], intent="switch_which", lang=lang)
        prompt = cands[0] if cands else text
        return self._open_switch(prompt, kind, text, from_name, bool(cands), ctx, ses, lang, stay)

    def _switch_pick(self, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        cands = list(ses.get("switch_cands") or [])
        try:
            idx = int(value)
        except (TypeError, ValueError):
            idx = 0
        prompt = cands[idx] if 0 <= idx < len(cands) else (cands[0] if cands else str(ses.get("switch_text") or ""))
        kind = str(ses.get("switch_kind") or "video")
        from_name = str(ses.get("switch_from") or "")
        text = str(ses.get("switch_text") or "")
        stay = chip(
            (f"Остаться в {from_name}" if from_name else ("Остаться в чате" if lang != "en" else "Stay in chat")),
            "stay_text",
            {"text": text, "model": str(ses.get("switch_from_id") or "")},
        )
        return self._open_switch(prompt, kind, text, from_name, True, ctx, ses, lang, stay)

    def _open_switch(self, prompt: str, kind: str, text: str, from_name: str, took_reply: bool,
                     ctx: dict, ses: dict, lang: str, stay: dict) -> dict:
        from assistant.router import detect_needs, topic_of

        ses["switch_from"] = from_name
        ses["kind"] = kind
        ses["idea"] = (prompt or text)[:2000]
        ses["topic"] = topic_of(prompt or text)
        ses["prompt_base"] = (prompt or text)[:4000]
        ses["prompt"] = ses["prompt_base"]
        ses["assist_mode"] = "direct"
        ses["await"] = "model"
        has_image = bool(ctx.get("has_image")) or any(
            isinstance(row, dict) and row.get("kind") == "image" for row in (ses.get("media") or [])
        )
        pick = self._recommend(kind, detect_needs(prompt or text), has_image, n=3)
        word = {"video": "видео", "image": "картинку", "music": "музыку"}.get(kind, "это")
        if lang == "en":
            word = {"video": "a video", "image": "an image", "music": "music"}.get(kind, "this")
            head = f"Let's make {word}."
            if took_reply:
                head = f"Let's make {word}. I'll use the prompt from {from_name} above."
        else:
            head = f"Сделаем {word}."
            if took_reply:
                head = f"Сделаем {word}. Беру промпт из ответа {from_name} выше."
        if self.d.dialog_v2:
            return DFLOW.from_handoff(self, prompt or text, kind, from_name, took_reply, ctx, ses, lang, stay)
        out = self._show_models(pick, ses, lang, "model_switch", head=head)
        out["chips"] = list(out.get("chips") or []) + [stay]
        ids = [m.get("id") for m in out.get("models") or []]
        out["models"] = [m for m in (out.get("models") or []) if m.get("id") in ids][:3]
        return out

    def _action(self, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        has_image = bool(ctx.get("has_image"))
        if kind == "pipe_result":
            pst = ses.get("pipe") if isinstance(ses.get("pipe"), dict) else {}
            kind_in = ""
            if isinstance(value, dict):
                kind_in = str(value.get("kind") or "")
            # текст кадров — в раскадровку; картинка листа при expect=board остаётся артефактом флоу
            if pst.get("expect") == "sb_frames" or (pst.get("expect") == "board" and kind_in in ("", "text")):
                return SB.apply_writer_reply(self, ses, ctx, lang, value)
            return MD.after_result(self, ses, ctx, lang, value, PL.result(self, ses, ctx, lang, value))
        if kind.startswith("mode_"):            # режимы «Рилс» / «Сериал» (modes.py)
            if self._is_guest(ctx):
                return self._ask_login(ses, lang, kind)
            return MD.action(self, kind, value, ctx, ses, lang)
        if kind == "restart":
            ses["mode"] = None
        if kind.startswith("sb_"):
            return PL.decorate(self._sb_action(kind, value, ctx, ses, lang), ses, lang)
        if self.d.dialog_v2:
            hit = DFLOW.on_action(self, kind, value, ctx, ses, lang)
            if hit is not None:
                return hit
        if kind.startswith("pipe_"):
            return self._pipe_action(kind, value, ctx, ses, lang)
        if kind in ("choose_type", "restart"):   # обычный выбор типа — вне флоу: результат генерации не ждём
            PL.state(ses).update(expect=None, stage=None, sub=None)
            ses["pipe"]["await"] = None
        if ses.get("assist_mode") == "sb" and kind not in ("send", "resume"):
            ses["assist_mode"] = None          # любая обычная кнопка — выход из раскадровки (кадры сохраняются)
        if kind == "edit_prompt":
            return self._edit_prompt(value, ctx, ses, lang)
        if kind == "media_add":
            if isinstance(value, dict) and (value.get("url") or value.get("work_id")):
                DG.add_result(ses, value)
            return {"text": "", "reply": "", "blocks": [], "chips": [], "silent": True, "intent": "media_add", "lang": lang}
        if kind == "files_confirm":
            return self._files_confirm(value, ctx, ses, lang)
        if kind == "files_drop":
            DG.drop(ses, (value or {}).get("id") if isinstance(value, dict) else value)
            card = self._current_card(ses, ctx)
            if card:
                return self._setup_reply(card, ses, ctx, lang, "files_drop", "Файл убран." if lang != "en" else "File removed.")
            return response(["Файл убран." if lang != "en" else "File removed."], [], lang=lang, intent="files_drop")
        if kind == "files_sync":
            card = self._current_card(ses, ctx)
            if card:
                return self._setup_reply(card, ses, ctx, lang, "files_sync", "Файлы обновлены." if lang != "en" else "Files updated.")
            return response(["Прикрепите файл и выберите модель." if lang != "en" else "Attach a file and pick a model."],
                            [], lang=lang, intent="files_sync")
        if kind == "media_pick":
            return self._media_pick(value, ctx, ses, lang)
        if kind == "resume_task":
            return self._resume_task(ctx, ses, lang)
        if kind == "make":
            return DFLOW.from_prompt(self, value, ctx, ses, lang)
        if kind == "model_switch":
            return self._model_switch(value if isinstance(value, dict) else {}, ctx, ses, lang)
        if kind == "switch_pick":
            return self._switch_pick(value, ctx, ses, lang)
        if kind == "text_note":
            self._remember_texts(ses, value if isinstance(value, dict) else {})
            return {"text": "", "reply": "", "blocks": [], "chips": [], "silent": True, "intent": "text_note", "lang": lang}
        if kind == "look_done":
            return self._look_done(value if isinstance(value, dict) else {}, ctx, ses, lang)
        if kind == "look_skip":
            return self._look_skip(ctx, ses, lang)
        if kind == "look_next":
            return self._look_next(ctx, ses, lang)
        if kind == "pick_model":
            return self._pick(str(value or ""), ctx, ses, lang)
        if kind == "choose_type":
            if self._is_guest(ctx):
                # тип запомним после входа; сейчас — только просьба войти
                if value == "prompt":
                    ses.update(assist_mode="prompt", kind=None, idea="", topic="", needs=[])
                elif value == "sfx" or value in KINDS:
                    ses["kind"] = "music" if value == "sfx" else value
                return self._ask_login(ses, lang, "choose_type")
            # «Промпт» — отдельный помощник: дальше выбираем тип генерации и собираем текст
            if value == "prompt":
                ses.update(assist_mode="prompt", kind=None, idea="", topic="", picked=None, prompt="", prompt_base="",
                           camera=None, camera_cleared=False, params={}, shown=[], junk_count=0,
                           gen_model=None, gen_kind=None, needs=[],
                           brief=None, brief_done=False, brief_guide=None, brief_for_model=None,
                           variants=[], var_round=0, prompt_gate=False, from_polish=False)
                ses["await"] = "gen_type"
                return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                lang=lang, intent="choose_type")
            if value == "sfx":
                value = "music"  # «звук» = музыка, отдельной кнопки нет
            if value not in KINDS:
                return self._ask_type(ses, ctx, lang)
            from_prompt = ses.get("assist_mode") == "prompt" or ses.get("await") == "gen_type"
            ses.update(kind=value, picked=None, prompt="", prompt_base="", camera=None, camera_cleared=False,
                       params={}, shown=[], junk_count=0, gen_model=None, gen_kind=None,
                       brief=None, brief_done=False, brief_guide=None, brief_for_model=None,
                       variants=[], var_round=0)
            if not ses.get("needs"):
                ses["needs"] = detect_needs(ses.get("idea") or "")
            if value == "text":
                ses["assist_mode"] = None
                if not (ses.get("idea") or "").strip() and ses.get("topic"):
                    ses["idea"] = ses.get("topic")
                return self._text_chat_models(ses, ctx, lang, "choose_type")
            # «Промпт» → тип → просто «опишите идею», без брифа и без выбора нейросети
            if from_prompt:
                ses["assist_mode"] = "prompt"
                idea = (ses.get("idea") or "").strip()
                if BR.has_subject(idea):
                    return self._prompt_from_idea(ctx, ses, lang)
                ses["junk_count"] = 0
                return self._ask_prompt_idea(ses, lang)
            # картинка без нового диалога: старый бриф. В диалоге v2 промпт как у видео.
            if value == "image" and self.d.brief and not self.d.dialog_v2:
                if BR.has_subject(ses.get("idea") or ""):
                    return self._enter_brief(ctx, ses, lang)
                return self._ask_subject("image", ses, ctx, lang)
            # новый диалог не начинает с сетки моделей: сначала идея и промпт
            if self.d.dialog_v2:
                idea = (ses.get("idea") or "").strip()
                opened = DFLOW.start(self, idea, Intent("generate_task", kind=value), ctx, ses, lang)
                if opened is not None:
                    return opened
            return self._offer_models_for_kind(ctx, ses, lang, "choose_type", mode="direct")
        if kind == "has_prompt":
            if not ses.get("kind") or ses["kind"] not in KINDS or ses["kind"] == "text":
                return self._ask_type(ses, ctx, lang)
            ans = str(value or "").lower().strip()
            card = self.d.cards.get(ses.get("picked") or "")
            if ans in ("yes", "y", "да", "1"):
                ses["assist_mode"] = "prompt"
                return self._start_prompt_assist(ctx, ses, lang, "has_prompt")
            if ans in ("no", "n", "нет", "0"):
                if card:
                    return self._maybe_ask_add_then_setup(card, ctx, ses, lang, "has_prompt")
                return self._start_direct_models(ctx, ses, lang, "has_prompt")
            return self._ask_has_prompt(ses, lang, "has_prompt")
        if kind == "add_prompt":
            card = self.d.cards.get(ses.get("picked") or "") or self._current_card(ses, ctx)
            if not card:
                return self._ask_type(ses, ctx, lang)
            ans = value
            if isinstance(ans, dict):
                add = str(ans.get("text") or "").strip()
                if add:
                    base = (ses.get("idea") or ses.get("prompt") or "").strip()
                    merged = (base.rstrip(". ") + ". " + add).strip() if base else add
                    ses["idea"] = merged[:4000]
                    if ses.get("prompt"):
                        ses["prompt_base"] = merged[:4000]
                        ses["prompt"] = ""
                ses["add_prompt_asked"] = True
                return self._setup_from_idea(card, ctx, ses, lang, "add_prompt")
            low = str(ans or "").lower().strip()
            if low in ("no", "n", "нет", "0"):
                ses["add_prompt_asked"] = True
                return self._setup_from_idea(card, ctx, ses, lang, "add_prompt")
            if low in ("yes", "y", "да", "1"):
                ses["await"] = "add_prompt"
                return response([t("ask_add_to_prompt_write", lang)], [self._back_chip(lang)],
                                lang=lang, intent="add_prompt", generate_model=card.id)
            return self._ask_add_to_prompt(card, ses, lang, "add_prompt")
        if kind in {"more", "similar", "cheaper", "faster", "no_photo_model"}:
            cur = self._current_card(ses, ctx)
            k = ses.get("kind") or (cur.kind if cur else None)
            if not k:
                return self._ask_type(ses, ctx, lang)
            needs = list(ses.get("needs") or [])
            if kind == "cheaper":
                needs = ["дешево"] + needs
            if kind == "faster":
                needs = ["быстро", "черновик"] + needs
            exclude = list(ses.get("shown") or []) if kind == "more" else ([cur.id] if cur else [])
            pick = self._recommend(k, needs, False if kind == "no_photo_model" else has_image, exclude=exclude,
                                   with_cheap=False)
            if not pick.cards:
                return response([t("no_more", lang)], [std_chip("open_models", "open_models", lang)], intent=kind)
            head = t("more", lang) if kind == "more" else t("alternatives", lang)
            return self._show_models(Pick(pick.cards, True), ses, lang, kind, head=head)
        if kind == "use_mine":
            card = self._current_card(ses, ctx)
            idea = ses.get("idea") or ""
            if not card or not idea:
                return response([t("describe_idea", lang)], [], intent="use_mine")
            ses["prompt_base"] = idea
            ses["prompt"] = CAM.compose(idea, ses.get("camera")) if card.kind == "video" else idea
            ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
            return self._setup_reply(card, ses, ctx, lang, "use_mine", t("kept_text", lang))
        if kind == "pick_camera":
            card = self._current_card(ses, ctx) or self._brief_guide(ses, ctx)
            if not card or card.kind != "video":
                if ses.get("kind") == "video":
                    card = self._brief_guide(ses, ctx)
                if not card or card.kind != "video":
                    return self._ask_type(ses, ctx, lang)
            mid = str(value or "")
            if mid in {"", "none", "skip"}:
                ses["camera"] = None
                ses["camera_cleared"] = True
                head = t("camera_cleared", lang)
            elif CAM.get(mid):
                ses["camera"] = mid
                ses["camera_cleared"] = False
                head = t("camera_picked", lang, title=CAM.title(CAM.get(mid), lang))
            else:
                head = t("camera_unknown", lang)
            if not ses.get("prompt_base") and not ses.get("prompt"):
                ses["prompt_base"] = ses.get("idea") or ""
            # На брифе / вариантах остаёмся на том же шаге — не прыгаем к запуску
            if ses.get("await") == "brief":
                r = self._brief(card, ses, ctx, lang, note=head)
                r["intent"] = "pick_camera"
                return r
            if ses.get("await") == "variants":
                lines = [head, t("variants_head", lang)]
                r = self._show_variants(card, ses, lang, lines, False)
                r["intent"] = "pick_camera"
                return r
            return self._setup_reply(card, ses, ctx, lang, "pick_camera", head)
        if kind == "param" and isinstance(value, dict):
            card = self._current_card(ses, ctx)
            if not card:
                return self._ask_type(ses, ctx, lang)
            clean = P.validate(card, {value.get("name"): value.get("value")})
            ses["params"] = P.with_defaults(card, {**P.validate(card, ses.get("params")), **clean})
            if not ses.get("prompt"):
                ses["prompt"] = ses.get("idea") or ""
            lbl = ", ".join(P.label(k, v, lang) for k, v in clean.items()) or "—"
            return self._setup_reply(card, ses, ctx, lang, "param", t("settings_saved", lang, label=lbl))
        if kind == "improve":
            card = self._current_card(ses, ctx)
            k = card.kind if card else (ses.get("kind") or "image")
            sugg = REFINE_SUGGEST.get(k, REFINE_SUGGEST["image"])[lang if lang == "en" else "ru"]
            ses["await"] = "refine"
            return response([t("what_improve", lang)], [chip(s, "refine", s) for s in sugg], intent="improve")
        if kind == "refine" and isinstance(value, str):
            card = self._current_card(ses, ctx)
            if not card or not ses.get("prompt"):
                return self._message(value, ctx, ses, lang)
            return self._refine(card, value, ctx, ses, lang)
        if kind in ("brief", "variants", "more_variants", "back_brief", "use_variant"):
            card = self._brief_guide(ses, ctx)
            if not card:
                return self._ask_type(ses, ctx, lang)
            if kind == "brief" and isinstance(value, dict):
                br = ses.get("brief") or {}
                if br.get("q"):
                    qid, val = str(value.get("id") or ""), value.get("value")
                    valid = {o["value"] for q in br["q"] if q["id"] == qid for o in q["options"]}
                    if val == BR.ANY:
                        br.get("a", {}).pop(qid, None)
                    elif val in valid:
                        br.setdefault("a", {})[qid] = val
                    ses["brief"] = br
                return self._brief(card, ses, ctx, lang)
            if kind == "back_brief":
                return self._go_back(ctx, ses, lang)
            if kind == "more_variants":
                ses["var_round"] = int(ses.get("var_round") or 0) + 1
                return self._variants(card, ses, ctx, lang, change="other creative directions, different from before")
            if kind == "use_variant":
                v = next((x for x in ses.get("variants") or [] if x.get("id") == value), None)
                if not v:
                    return self._variants(card, ses, ctx, lang)
                live = ses.pop("_prompt_edit", None)
                text = v["text"]
                if isinstance(live, str) and live.strip():
                    text = live.strip()[:8000]
                    v["text"] = text
                ses["prompt_base"] = text
                if card.kind == "video":
                    CAM.ensure_default(ses)
                    ses["prompt"] = CAM.compose(text, ses.get("camera"))
                else:
                    ses["prompt"] = text
                ses["brief_done"] = True
                # модель генерации уже выбрана до брифа — не теряем; picked очищаем под Claude/GPT
                if not ses.get("gen_model"):
                    prior = ses.get("brief_for_model") or ses.get("picked")
                    if prior and prior in self.d.cards and self.d.cards[prior].kind != "text":
                        ses["gen_model"] = prior
                ses["picked"] = None
                ses["gen_kind"] = ses.get("kind") or card.kind
                ses["polish_draft"] = ses["prompt"]
                ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
                flow = ses.get("flow") if self.d.dialog_v2 and isinstance(ses.get("flow"), dict) else None
                if flow and flow.get("stage") == "variants":
                    flow["idea"] = ses["prompt"]
                    ses["idea"] = ses["prompt"]
                    which = flow.get("prompt_for") or "idea"
                    if which == "idea" and (flow.get("kind") or "") == "video":
                        from . import model_lock as ML
                        lock = ML.lock_of(self, ctx, ses)
                        if lock and lock["kind"] in ("image", "edit"):
                            flow["kind"] = "image"
                            ses["kind"] = "image"
                            return DFLOW._advise(self, ctx, ses, lang)
                        if flow.get("polished"):
                            return DFLOW._go_direct(self, ctx, ses, lang)
                        return DFLOW._paths(self, ses, lang)
                    if which == "idea" and (flow.get("kind") or "") in ("image", "voice", "music"):
                        return DFLOW._advise(self, ctx, ses, lang)
                    flow["stage"] = "polish"
                    flow["next"] = "polish"
                    return self._offer_polish(ses, ctx, lang, "use_variant",
                                              head=t("polish_ask", lang, title=v["title"]))
                # картинку ещё не выбирали: один список моделей вместе с готовым промптом
                if (ses.get("kind") or card.kind) == "image" and not ses.get("gen_model") and not ses.get("brief_for_model"):
                    ses["kind"] = "image"
                    ses["picked"] = None
                    word = err_mod.KIND_WORD.get(lang, err_mod.KIND_WORD["ru"]).get("image", "картинки")
                    return self._show_models(
                        self._recommend("image", ses.get("needs") or [], bool(ctx.get("has_image"))),
                        ses, lang, "use_variant", head=t("polish_skip", lang, kind=word))
                return self._offer_polish(ses, ctx, lang, "use_variant",
                                          head=t("polish_ask", lang, title=v["title"]))
            # «Продолжить» / «Сделать промпт» на этапе открытых вопросов → сначала кнопки
            br = ses.get("brief") or {}
            if br.get("phase") == "open" and self._profile_brief(br) and kind == "variants":
                return self._brief_after_open(card, ses, ctx, lang)
            return self._variants(card, ses, ctx, lang)
        if kind == "skip_polish":
            flow = ses.get("flow") if self.d.dialog_v2 and isinstance(ses.get("flow"), dict) else None
            if flow and flow.get("stage") in ("polish", "variants"):
                prompt = ses.get("prompt") or ses.get("prompt_base") or ses.get("polish_draft") or flow.get("idea") or ""
                flow["idea"] = prompt
                ses["idea"] = prompt
                ses["prompt"] = prompt
                ses["prompt_base"] = prompt
                ses["kind"] = flow.get("kind") or ses.get("kind")
                which = flow.get("prompt_for") or "idea"
                if which == "photos":
                    flow["path"] = "photos"
                    flow["next"] = "cast_images"
                    return DFLOW._advise(self, ctx, ses, lang)
                if which == "board":
                    return DFLOW._board(self, ctx, ses, lang)
                if (flow.get("kind") or "") == "video":
                    return DFLOW._paths(self, ses, lang)
                return DFLOW._advise(self, ctx, ses, lang)
            k = ses.get("kind") if ses.get("kind") != "text" else None
            k = k or ses.get("gen_kind")
            if not k or k == "text":
                return self._ask_type(ses, ctx, lang)
            ses["kind"] = k
            if not ses.get("prompt"):
                draft = ses.get("prompt_base") or ses.get("polish_draft") or ses.get("idea") or ""
                ses["prompt_base"] = CAM.strip(draft) if k == "video" else draft
                ses["prompt"] = CAM.compose(ses["prompt_base"], ses.get("camera")) if k == "video" else draft
            # модель уже выбрали на первом шаге — сразу настройки/запуск, без второго выбора
            mid = ses.get("gen_model") or ses.get("brief_for_model")
            prior = self.d.cards.get(mid or "")
            if prior and prior.kind == k and self._healthy(prior.id):
                ses["from_polish"] = False
                ses["assist_mode"] = ses.get("assist_mode") or "prompt"
                return self._pick(prior.id, ctx, ses, lang, "skip_polish")
            pick = self._recommend(k, ses.get("needs") or [], has_image)
            kind_word = err_mod.KIND_WORD.get(lang, err_mod.KIND_WORD["ru"]).get(k, k)
            ses["from_polish"] = True
            return self._show_models(pick, ses, lang, "skip_polish",
                                     head=t("polish_skip", lang, kind=kind_word))
        if kind == "back":
            return self._go_back(ctx, ses, lang)
        if kind == "restart":
            self._new_task(None, "", [], "", ses)
            ses["junk_count"] = 0
            ses["prompt_gate"] = False
            ses["from_polish"] = False
            return self._ask_type(ses, ctx, lang)
        if kind.startswith("reel_"):
            # Режим «Рилс» снят с продукта — любые старые кнопки ведут в обычный выбор формата.
            ses["assist_mode"] = None
            ses["reel"] = None
            return self._ask_type(ses, ctx, lang)
        if kind == "resume":  # вернулись после входа / пополнения — показать то же место с новой проверкой
            if self._is_guest(ctx):
                return self._ask_login(ses, lang, "resume")
            if isinstance(ses.get("mcp"), dict) and ses["mcp"].get("stage"):
                return DG.mcp_show(self, ctx, ses, lang)
            if self.d.dialog_v2 and isinstance(ses.get("flow"), dict) and ses["flow"].get("stage") not in (None, "", "card"):
                return DFLOW.show(self, ctx, ses, lang)
            if self.d.dialog_v2 and not isinstance(ses.get("flow"), dict) and ses.get("kind") not in (None, "text") and (ses.get("idea") or ""):
                opened = DFLOW.start_saved(self, ctx, ses, lang)
                if opened is not None:
                    return opened
            if SB.active(ses):
                return SB.show(self, ses, ctx, lang, t("resumed", lang))
            card = self._current_card(ses, ctx) if ses.get("picked") else None
            if card and (ses.get("prompt") or ses.get("idea")):
                if not ses.get("prompt"):
                    ses["prompt"] = ses.get("idea")
                ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
                return self._setup_reply(card, ses, ctx, lang, "resume", t("resumed", lang))
            # ранний вход (ещё до типа/моделей) — продолжаем сборку с сохранённого места
            if ses.get("assist_mode") == "prompt":
                if not ses.get("kind"):
                    ses["await"] = "gen_type"
                    return response([t("ask_gen_type", lang)], self._gen_type_chips(ctx, lang),
                                    lang=lang, intent="resume")
                if BR.has_subject(ses.get("idea") or ""):
                    return self._prompt_from_idea(ctx, ses, lang)
                return self._ask_prompt_idea(ses, lang, intent="resume")
            if ses.get("kind") and ses["kind"] != "text":
                if self.d.dialog_v2:
                    opened = DFLOW.start(self, ses.get("idea") or "", Intent("generate_task", kind=ses["kind"]), ctx, ses, lang)
                    if opened is not None:
                        return opened
                if BR.has_subject(ses.get("idea") or ""):
                    return self._offer_models_for_kind(ctx, ses, lang, "resume",
                                                      mode=ses.get("assist_mode") or "direct")
                return self._ask_subject(ses["kind"], ses, ctx, lang)
            if ses.get("kind") == "text":
                return self._text_chat_models(ses, ctx, lang, "resume")
            ses["await"] = "type"
            return self._offer_types([t("nothing_to_resume", lang)], ctx, ses, lang, "resume")
        if kind == "edit_prompt":
            return response([t("what_change", lang)], [], intent="edit_prompt")
        if kind == "rephrase":
            return response([t("rephrase_ask", lang)], [], intent="rephrase")
        if kind == "send" and isinstance(value, str):
            return self._message(value, ctx, ses, lang)
        if kind == "mcp_goal":
            return DG.mcp_goal(self, value, ctx, ses, lang)
        if kind == "open_mcp":
            return DG.mcp_open(self, value, ctx, ses, lang)
        if kind == "mcp_compare":
            return DG.mcp_compare(ses, lang)
        if kind == "mcp_try" or kind == "mcp_connected":
            return DG.mcp_connected(self, value, ctx, ses, lang) if kind == "mcp_connected" else DG.mcp_try(self, ctx, ses, lang)
        if kind == "mcp_failed":
            return DG.mcp_failed(ses, lang)
        if kind == "mcp_support":
            return DG.mcp_support(lang)
        if kind == "mcp_topic":
            return response(["О какой теме найти тренды?"], [], intent="mcp")
        if kind == "ui_more":
            return DG.ui_more(lang)
        if kind == "retry":
            return response(["Не вышло с прошлого раза. Опишите задачу ещё раз — начну заново."], [], intent="retry")
        return response(["Не поняла, что сделать. Опишите задачу словами."], [], intent="noop")

    def _pipe_action(self, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        """Флоу помощника (pipeline.py): этапы, артефакты сессии, результат генерации."""
        if kind == "pipe_result":           # служебное: приложение сообщает о готовой генерации
            return PL.result(self, ses, ctx, lang, value)
        if self._is_guest(ctx):
            return self._ask_login(ses, lang, kind)
        if ses.get("assist_mode") == "sb":
            ses["assist_mode"] = None
        if kind == "pipe_menu":
            return PL.menu(self, ses, ctx, lang)
        if kind == "pipe_stage":
            if value == "video" and not PL.arts(ses):
                # артефактов ещё нет — обычный путь «Видео» (идея из чата сохраняется), результат запишем в артефакты
                out = self._action("choose_type", "video", ctx, ses, lang)
                PL.state(ses).update(on=True, stage="video", expect="video")
                return out
            return PL.stage(self, ses, ctx, lang, value)
        if kind == "pipe_sub":
            return PL.sub(self, ses, ctx, lang, value)
        if kind == "pipe_dialog_save":
            return PL.dialog_save(self, ses, ctx, lang)
        if kind == "pipe_video_plain":
            return PL.video(self, ses, ctx, lang, plain=True)
        if kind == "pipe_voice_model":
            return PL.voice(self, ses, ctx, lang, text=PL.state(ses).get("voice_text") or "", model=str(value or ""))
        if kind == "pipe_summary":
            return PL.summary(self, ses, ctx, lang)
        if kind == "pipe_arts":
            return PL.menu(self, ses, ctx, lang)
        return PL.menu(self, ses, ctx, lang)

    def _sb_action(self, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        """Режим «Раскадровка» (storyboard.py): кнопки и правки на месте."""
        if self._is_guest(ctx):
            return self._ask_login(ses, lang, kind)
        if kind == "sb_start":
            if isinstance(value, str) and value not in ("", "new") and len(value.split()) >= 3:
                return SB.start(self, ses, ctx, lang, text=value)
            return SB.start(self, ses, ctx, lang, value)
        if not isinstance(ses.get("sb"), dict):
            return SB.start(self, ses, ctx, lang)
        ses["assist_mode"] = "sb"
        if kind == "sb_noscript":
            return SB.show_idea(self, ses, ctx, lang)
        if kind == "sb_answer":
            return SB.answer(self, ses, ctx, lang, value)
        if kind == "sb_edit":
            return SB.edit(self, ses, ctx, lang, value)
        if kind == "sb_frame":
            return SB.redo_frame(self, ses, ctx, lang, value)
        if kind == "sb_rebuild":
            return SB.rebuild(self, ses, ctx, lang)
        if kind == "sb_setup":            # шаг 2: оформление и запуск
            return SB.show_setup(self, ses, ctx, lang)
        if kind == "sb_frames_view":      # назад к тексту кадров
            return SB.show_frames(self, ses, ctx, lang)
        if kind == "sb_back":
            return SB.back(self, ses, ctx, lang)
        if kind == "sb_exit":
            return SB.exit_mode(self, ses, ctx, lang)
        return SB.show(self, ses, ctx, lang)

def _kind_by_number(msg: str, gen_types_only: bool = False) -> str | None:
    """Номер кнопки: верхний ряд 1=Промпт…; после «Промпт» — 1=картинка…"""
    m = re.fullmatch(r"\s*([1-5])\s*[.)]?\s*", msg or "")
    if not m:
        return None
    idx = int(m.group(1)) - 1
    order = ["image", "video", "music"] if gen_types_only else ["prompt", "image", "video", "music"]
    return order[idx] if 0 <= idx < len(order) else None


def _unsafe(text: str) -> bool:
    return bool(MINORS_SEXUAL.search(text) or VIOLENCE.search(text) or NSFW.search(text))


def _generic_error(lang: str) -> str:
    return "Что-то пошло не так. Попробуйте ещё раз." if lang != "en" else "Something went wrong. Please try again."


def _rub(kop: int | None) -> str:
    if kop is None:
        return "—"
    s = str(kop // 100) if kop % 100 == 0 else f"{kop / 100:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " ₽"


# Категории вместо примеров сюжетов: человек выбирает направление, детали спросим дальше
QUICK_PICKS = {
    "video": {"ru": [("Природа", "видео про природу"), ("Город", "видео про город"), ("Животные", "видео с животными"),
                     ("Люди", "видео с людьми"), ("Абстракция", "абстрактное видео")],
              "en": [("Nature", "a video about nature"), ("City", "a city video"), ("Animals", "a video with animals"),
                     ("People", "a video with people"), ("Abstract", "an abstract video")]},
    "image": {"ru": [("Портрет", "портрет"), ("Пейзаж", "пейзаж"), ("Логотип", "логотип"), ("Постер", "постер"),
                     ("Иллюстрация", "иллюстрация")],
              "en": [("Portrait", "a portrait"), ("Landscape", "a landscape"), ("Logo", "a logo"), ("Poster", "a poster"),
                     ("Illustration", "an illustration")]},
    "edit": {"ru": [("Заменить фон", "заменить фон на фото"), ("Улучшить свет", "улучшить свет на фото"),
                    ("Убрать лишнее", "убрать лишние объекты с фото")],
             "en": [("Replace background", "replace the photo background"), ("Fix lighting", "improve the photo lighting"),
                    ("Remove objects", "remove unwanted objects from the photo")]},
    "music": {"ru": [("Поп", "поп-трек"), ("Электроника", "электронный трек"), ("Лоу-фай", "лоу-фай трек"),
                     ("Рок", "рок-трек"), ("Оркестр", "оркестровая музыка")],
              "en": [("Pop", "a pop track"), ("Electronic", "an electronic track"), ("Lo-fi", "a lo-fi track"),
                     ("Rock", "a rock track"), ("Orchestral", "orchestral music")]},
    "sfx": {"ru": [("Природа", "звуки природы"), ("Город", "звуки города"), ("Интерфейс", "звук интерфейса, клик"),
                   ("Удар", "звук удара")],
            "en": [("Nature", "nature sounds"), ("City", "city sounds"), ("UI", "a UI click sound"), ("Impact", "an impact sound")]},
    "text": {"ru": [("Пост", "пост для соцсети"), ("Письмо", "деловое письмо"), ("Статья", "короткая статья"),
                    ("Сценарий", "сценарий ролика"), ("Стих", "стихотворение")],
             "en": [("Post", "a social media post"), ("Letter", "a business letter"), ("Article", "a short article"),
                    ("Script", "a short video script"), ("Poem", "a poem")]},
}

_JUNK_LINES = {
    "ru": ["Не совсем поняла 🙂", "Похоже, сообщение не получилось 🙂", "Всё ещё не разобрала текст 🙂"],
    "en": ["Sorry, I didn't get that 🙂", "Looks like the message didn't come through 🙂", "Still can't make it out 🙂"],
}


def _junk_line(n: int, lang: str) -> str:
    lines = _JUNK_LINES["en" if lang == "en" else "ru"]
    return lines[min(max(n, 1), len(lines)) - 1]
