"""Ядро ассистента: маршрут → обработчик → ответ. Без Flask, без сети (сеть только внутри LLMChain).

Сценарий (brief=on, по умолчанию):
  1. идея / тип                    → уточняющие вопросы и бриф
  2. ответ / «Пропустить»          → 2–3 варианта промпта; человек выбирает один
  3. выбор модели под готовый промпт → параметры + «Сгенерировать»
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
from . import camera as CAM
from . import errors as err_mod
from . import files as F
from . import params as P
from .cards import Card, load_cards
from .lang import detect_lang
from .llm import LLMChain, LLMUnavailable
from .prompts import SYSTEM, build_user, fallback_prompt, validate_output
from .recommend import PIN_FIRST, Pick, cheapest, price_value, recommend
from .render import chip, estimate, model_item, per_second, response, short_price, std_chip
from .router import MINORS_SEXUAL, NSFW, VIOLENCE, Intent, detect_kind, detect_needs, lev, route, squeeze, topic_of
from .session import MAX_SESSION_ID, MemoryStore, load
from .texts import EXAMPLES, REFINE_SUGGEST, b, t
from .ui_help import ui_help

log = logging.getLogger("assistant")

KINDS = ("video", "image", "edit", "music", "sfx", "text")
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
        files = F.clean_attachments(ctx.get("attachments"))
        ctx["attachments"] = files
        if any(f["kind"] == "image" for f in files):
            ctx["has_image"] = True
        if files != (ses.get("files") or []):
            ses["files_told"] = False                            # набор файлов поменялся — скажем о нём снова
        ses["files"] = files
        msg = (message or "").strip()[:2000]
        lang = self._lang(msg, ses, ctx)
        ses["lang"] = lang
        ses["turns"] = int(ses.get("turns") or 0) + 1
        self._llm_info = {"used": False, "provider": None, "tokens": 0, "latency_ms": 0}
        try:
            if action and isinstance(action, dict) and action.get("type"):
                if action.get("type") != "send":
                    ses["junk_count"] = 0
                out = self._action(str(action["type"]), action.get("value"), ctx, ses, lang)
            else:
                out = self._message(msg, ctx, ses, lang)
        except Exception:
            log.exception("assistant handler failed")
            out = response([_generic_error(lang)], [std_chip("retry", "retry", lang)], intent="internal_error")
        ses["last_chips"] = [{k: c.get(k) for k in ("label", "action", "value")} for c in out.get("chips", [])]
        if sid:
            self.d.store.set(sid, ses)
        out.setdefault("intent", "unknown")
        out.setdefault("models", [])
        out.setdefault("ready", False)
        out.setdefault("degraded", False)
        out["lang"] = lang
        out["llm"] = self._llm_info
        if self.d.on_event:
            try:
                self.d.on_event({"intent": out["intent"], "lang": lang, "llm_used": self._llm_info["used"],
                                 "provider": self._llm_info["provider"], "tokens": self._llm_info["tokens"],
                                 "degraded": out["degraded"], "ms": int((time.monotonic() - t0) * 1000)})
            except Exception:
                log.exception("assistant on_event failed")
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
            if ses.get("kind"):
                return self._ask_subject(ses["kind"], ses, ctx, lang, junk=True)
            ses["await"] = "type"
            return self._offer_types([_junk_line(n, lang)], ctx, ses, lang, "junk")
        # 1в) ждём суть идеи («о чём видео?») — любой осмысленный текст становится идеей
        if ses.get("await") == "idea" and ses.get("kind") and BR.has_subject(msg):
            it0 = route(msg, ctx, ses, self.titles)
            if it0.name in ("ask_type", "off_topic", "generate_task", "smalltalk") and (it0.kind in (None, ses["kind"])):
                ses.update(idea=msg, topic=topic_of(msg), needs=detect_needs(msg) or ses.get("needs") or [],
                           brief=None, brief_done=False, prompt="")
                if ses.get("picked") and ses["picked"] in self.d.cards and not self.d.brief:
                    return self._pick(ses["picked"], ctx, ses, lang)
                if self.d.brief:
                    return self._enter_brief(ctx, ses, lang)
                pick = self._recommend(ses["kind"], ses.get("needs") or [], bool(ctx.get("has_image")))
                return self._show_models(pick, ses, lang, "generate_task")
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
                return self._variants(card, ses, ctx, lang, change=msg if ses.get("await") == "variants" else "")
        # 2) ждём ответ «какой тип» — понимаем коротко и с опечатками
        if ses.get("await") == "type" and len(msg.split()) <= 3:
            k = detect_kind(msg, bool(ctx.get("has_image"))) or _kind_by_number(msg)
            if k:
                return self._action("choose_type", k, ctx, ses, lang)
            it = route(msg, ctx, ses, self.titles)
            if it.name in ("ask_type", "off_topic"):
                ses["await"] = "type"
                return self._offer_types([_junk_line(1, lang)], ctx, ses, lang, "ask_type")
        intent = route(msg, ctx, ses, self.titles)
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
        return getattr(self, "_i_" + intent.name)(intent, msg, ctx, ses, lang)

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
                   with_cheap: bool = True) -> Pick:
        return recommend(self.d.cards, kind, needs, has_image, self.d.health_fn, self._price, self.d.neighbors,
                         exclude=exclude, with_cheap=with_cheap)

    def _sec_hint(self, ses: dict, card: Card) -> int | None:
        raw = P.extract(ses.get("idea") or "")
        params, _ = P.fit(raw, card)
        return P.seconds(card, P.with_defaults(card, params))

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
        # Seedance / Omni free и т.п. — первой карточкой; остальные — по цене
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
        chips = [std_chip("more", "more", lang)]
        blocks: list[dict] = []
        if ses.get("prompt"):
            blocks.append({"type": "prompt", "model_id": "", "title": t("your_prompt", lang),
                           "text": ses["prompt"], "note": ""})
        blocks.append({"type": "models", "items": items})
        return response((extra_top or []) + [head], chips, blocks, lang,
                        intent=intent, models=[{"id": i["id"], "title": i["title"], "price": i["price"]} for i in items])

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

    def _offer_types(self, lines: list[str], ctx: dict, ses: dict, lang: str, intent: str) -> dict:
        """Вопрос «что сделать» + кнопки типов (картинка / видео / музыка / …)."""
        return response(list(lines) + [t("ask_type", lang)], self._type_chips(ctx, lang), lang=lang, intent=intent)

    def _type_chips(self, ctx: dict, lang: str) -> list[dict]:
        kinds = ["image", "video", "music", "text", "edit" if ctx.get("has_image") else "sfx"]
        if ctx.get("has_image"):
            kinds = ["video", "edit", "image", "music", "text"]
        return [chip(b("type_" + k, lang), "choose_type", k) for k in kinds]

    def _ask_type(self, ses: dict, ctx: dict, lang: str) -> dict:
        ses["await"] = "type"
        topic = ses.get("topic") or ""
        head = t("ask_type_idea", lang, topic=topic) if topic else t("ask_type_plain", lang)
        return response([head], self._type_chips(ctx, lang), lang=lang, intent="ask_type")

    # ----------------------------------------------- prompt + params + summary
    def _setup_reply(self, card: Card, ses: dict, ctx: dict, lang: str, intent: str, head: str,
                     note: str = "", degraded: bool = False, adj: list[dict] | None = None) -> dict:
        if card.kind == "video":
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
        price = short_price(self._price(card.id)) or t("price_unknown", lang)
        est = estimate(price, P.seconds(card, params), lang)
        has_image = bool(ctx.get("has_image"))
        # Скрепка: какой файл чем станет — по имени («Фото «cat.png» — первый кадр видео»)
        fplan = F.plan(card, ses.get("files") or [], lang, self.d.inputs_fn)
        lines += F.lines(card, fplan, lang)
        blocks: list[dict] = [{"type": "prompt", "model_id": card.id, "title": card.title, "text": prompt, "note": note}]
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
                       "prompt": prompt, "params": param_lines,
                       "files": F.summary_labels(fplan, lang), "files_title": F.summary_title(lang)})
        gate = None
        if card.needs_image and not has_image:
            lines.append(t("needs_image", lang))
            chips = [std_chip("attach", "attach", lang, primary=True), std_chip("no_photo_model", "no_photo_model", lang)]
            ready = False
        else:
            gate, gate_lines, chips = self._gate(card, params, ctx, lang)
            lines += gate_lines
            ready = gate in (None, "ok", "free")
        ses["await"] = "params"
        return response(lines, chips, blocks, lang, intent=intent, generate_model=card.id, generate_prompt=prompt,
                        generate_params=params, ready=ready, degraded=degraded, gate=gate,
                        generate_files=[{"kind": it["kind"], "name": it["name"]} for it in fplan if it["used"]],
                        models=[{"id": card.id, "title": card.title, "price": price}])

    # ------------------------------------------- перед запуском: вход → баланс
    def _cost_kop(self, card: Card, params: dict) -> int | None:
        if self.d.cost_fn:
            try:
                v = self.d.cost_fn(card.id, params)
                return None if v is None else int(v)
            except Exception:
                log.exception("assistant cost_fn failed")
        price = short_price(self._price(card.id))
        if not price:
            return None
        ps = per_second(price)
        if ps is not None:
            sec = P.seconds(card, params) or 5
            return int(math.ceil(ps * sec * 100))
        v = price_value(price)
        return None if v is None else int(math.ceil(v * 100))

    def _gate(self, card: Card, params: dict, ctx: dict, lang: str) -> tuple[str | None, list[str], list[dict]]:
        """Порядок обязателен: 1) вход, 2) баланс, 3) «Сгенерировать». Сервер /api/generate проверяет то же самое."""
        tail = [std_chip("improve", "improve", lang), std_chip("other_model", "more", lang)]
        acct = ctx.get("_account")
        cost = self._cost_kop(card, params)
        if acct is None:  # адаптер не передал аккаунт — проверку делает только сервер генерации
            gen = [std_chip("generate", "generate", lang, card.id, primary=True), std_chip("improve", "improve", lang),
                   std_chip("mine", "use_mine", lang), std_chip("other_model", "more", lang)]
            return None, [t("gate_ready", lang)], gen
        if not acct.get("authed"):
            return "login", [t("gate_login", lang)], [std_chip("login", "login", lang, primary=True)] + tail
        if cost == 0:
            return "free", [t("gate_free", lang)], [std_chip("generate", "generate", lang, card.id, primary=True)] + tail
        have = int(acct.get("available_kop") or 0)
        if cost is not None and have < cost:
            return "topup", [t("gate_topup", lang, have=_rub(have), need=_rub(cost))], [
                std_chip("topup", "open_topup", lang, primary=True), std_chip("resume_topup", "resume", lang),
                std_chip("cheaper", "cheaper", lang)]
        head = t("gate_ready_cost", lang, cost=_rub(cost)) if cost else t("gate_ready", lang)
        return "ok", [head], [std_chip("generate", "generate", lang, card.id, primary=True),
                              std_chip("improve", "improve", lang), std_chip("mine", "use_mine", lang),
                              std_chip("other_model", "more", lang)]

    def _pick(self, mid: str, ctx: dict, ses: dict, lang: str, intent: str = "pick_model") -> dict:
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
        ses["picked"] = card.id
        ses["kind"] = ses.get("kind") or card.kind
        # текст — сразу чат с моделью, без брифа / вариантов промпта
        if card.kind == "text":
            return self._text_chat_ready(card, ses, lang, intent)
        idea = ses.get("idea") or ctx.get("draft") or ""
        if not idea and not ses.get("prompt"):
            ses["await"] = "idea"
            return response([t("describe_idea", lang)], [], intent=intent, generate_model=card.id)
        # промпт уже собран в брифе — накладываем параметры модели и показываем запуск
        if self.d.brief and ses.get("prompt"):
            raw_params, adj = P.fit(P.extract(idea or ses["prompt"]), card)
            params = P.with_defaults(card, {**P.validate(card, ses.get("params")), **raw_params})
            ses["params"] = params
            head = t("model_for_prompt", lang, title=card.title)
            return self._setup_reply(card, ses, ctx, lang, intent, head, "", False, adj)
        if self.d.brief:
            # модель выбрали раньше промпта (старый путь / прямая ссылка) — сначала дособерём промпт
            ses["brief_guide"] = card.id
            if ses.get("brief_done") or BR.detail_level(idea) >= 12:
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
        head = t("prompt_ready_simple" if degraded else "prompt_ready", lang, title=card.title)
        return self._setup_reply(card, ses, ctx, lang, intent, head, note, degraded, adj)

    # ============================================================== intents
    def _new_task(self, kind: str | None, msg: str, needs: list[str], topic: str, ses: dict) -> None:
        ses.update(kind=kind, topic=topic, needs=needs, idea=msg, picked=None, prompt="", prompt_base="",
                   camera=None, params={}, shown=[],
                   brief=None, brief_done=False, brief_guide=None, variants=[], var_round=0)

    def _ask_subject(self, kind: str, ses: dict, ctx: dict, lang: str, junk: bool = False) -> dict:
        """Пустая или непонятная идея → уточняющие вопросы. Без примеров сюжетов.
        Если человек раз за разом пишет непонятное — не повторяем одно и то же: на 2-й раз коротко,
        с 3-го — кнопки категорий (жанр / тема), чтобы можно было двигаться дальше без текста."""
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
        chips.append(std_chip("ask_type_again_btn", "restart", lang))
        head = _junk_line(n, lang) + "\n" + t("quick_pick_" + ("short" if n == 2 else "buttons"), lang)
        return response([head], chips, intent="need_subject")

    def _text_chat_models(self, ses: dict, ctx: dict, lang: str, intent: str) -> dict:
        """Текст: без брифа — сразу выбрать LLM и перейти в обычный чат."""
        pick = self._recommend("text", ses.get("needs") or [], bool(ctx.get("has_image")))
        if not pick.cards:
            return response([t("none_available", lang)],
                            [std_chip("open_models", "open_models", lang)], intent=intent)
        card = pick.cards[0]
        ses["picked"] = card.id
        ses["kind"] = "text"
        return self._text_chat_ready(card, ses, lang, intent)

    def _text_chat_ready(self, card: Card, ses: dict, lang: str, intent: str) -> dict:
        ses["picked"] = card.id
        ses["kind"] = "text"
        ses["await"] = "chat"
        ses.update(brief=None, brief_done=False, brief_guide=None, variants=[], var_round=0,
                   prompt="", prompt_base="", params={})
        # смена модели — отдельной кнопкой; дальше сообщения идут как обычный чат
        chips = [std_chip("open_models", "open_models", lang), std_chip("ask_type_again_btn", "restart", lang)]
        return response([t("text_chat_ready", lang, title=card.title)], chips, intent=intent, generate_model=card.id)

    def _i_generate_task(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        if (it.kind or "") == "text":
            self._new_task("text", msg, it.needs, it.topic, ses)
            return self._text_chat_models(ses, ctx, lang, "generate_task")
        if self.d.brief and not BR.has_subject(msg):   # «нужно сделать видео» — о чём? сначала суть
            self._new_task(it.kind, "", it.needs, "", ses)
            return self._ask_subject(it.kind or "image", ses, ctx, lang)
        self._new_task(it.kind, msg, it.needs, it.topic, ses)
        if self.d.brief:
            return self._enter_brief(ctx, ses, lang)
        pick = self._recommend(it.kind or "image", it.needs, bool(ctx.get("has_image")))
        return self._show_models(pick, ses, lang, "generate_task")

    def _i_ask_type(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
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

    def _brief(self, card: Card, ses: dict, ctx: dict, lang: str) -> dict:
        idea = ses.get("idea") or ""
        br = ses.get("brief") or {}
        ses["brief_guide"] = card.id
        if not br.get("q"):
            data = self._llm_json(BR.BRIEF_SYSTEM, BR.brief_user(card, idea, lang), BR.validate_brief, ses, 450,
                                  timeout_scale=1.5, task="brief")
            if data is not None and not data["clear"]:
                ses["idea"] = ""
                return self._ask_subject(card.kind, ses, ctx, lang, junk=True)
            if data and data["questions"]:
                br = {"q": data["questions"], "a": {}, "extra": [], "summary": data.get("summary") or "", "src": "llm"}
            else:
                q, a = BR.rule_questions(card.kind, idea, lang)
                br = {"q": q, "a": a, "extra": [], "summary": "", "src": "rules"}
        ses["brief"] = br
        ses["await"] = "brief"
        ses["picked"] = None
        head = t("brief_head_summary", lang, summary=br["summary"]) if br.get("summary") else t("brief_head", lang)
        lines = [head] + ([t("brief_saved", lang, detail="; ".join(br["extra"]))] if br.get("extra") else [])
        blocks = [{"type": "brief", "model_id": card.id, "title": "",
                   "questions": BR.render_questions(br["q"], br["a"], lang)}]
        chips = [std_chip("skip_brief", "variants", lang, "skip")]
        return response(lines, chips, blocks, lang, intent="brief")

    def _answers_text(self, br: dict) -> dict[str, str]:
        out = {}
        for q in br.get("q") or []:
            v = (br.get("a") or {}).get(q["id"])
            if v and v != BR.ANY:
                out[q["label"]] = next((o["label"] for o in q["options"] if o["value"] == v), v)
        return out

    def _variants(self, card: Card, ses: dict, ctx: dict, lang: str, change: str = "") -> dict:
        idea = ses.get("idea") or ""
        br = ses.get("brief") or {"q": [], "a": {}, "extra": []}
        ses["brief_guide"] = card.id
        raw_params, adj = P.fit(P.extract(idea + " " + " ".join(br.get("extra") or [])), card)
        params = P.with_defaults(card, {**P.validate(card, ses.get("params")), **raw_params})
        answers_text = self._answers_text(br)
        data = self._llm_json(BR.VARIANTS_SYSTEM, BR.variants_user(card, idea, answers_text, br.get("extra") or [],
                                                                  params, lang, change), BR.validate_variants, ses, 1000,
                              timeout_scale=2.5, task="variants")
        if data is None and self.d.llm is not None and self._llm_info.get("error") != "budget":
            # на 3 варианта модели не хватило (время/формат) — просим ОДИН промпт (короче и надёжнее)
            full = "; ".join([idea] + [f"{k}: {v}" for k, v in answers_text.items()] + list(br.get("extra") or []))
            if change:
                full += "; " + change
            one = self._llm_json(SYSTEM, build_user(card, full, params, lang), validate_output, ses, 300,
                                 timeout_scale=1.5, task="variants_one")
            if one and one.get("prompt") and one.get("note") != "unsafe" and not _unsafe(one["prompt"]):
                data = {"variants": BR.variants_from_one(card, one["prompt"], lang)}
        degraded = data is None
        if degraded:
            answers = {k: v for k, v in (br.get("a") or {}).items()}
            items = BR.rule_variants(card, idea, answers, list(br.get("extra") or []), lang, int(ses.get("var_round") or 0),
                                     questions=br.get("q"))
        else:
            items = [v for v in data["variants"] if not _unsafe(v["text"])]
            if not items:
                return self._i_safety(Intent("safety"), "", ctx, ses, lang)
        ses.update(variants=items, brief_done=True, params=params, picked=None)
        lines = [t("variants_simple" if degraded else "variants_head", lang)]
        if degraded and not ses.get("degraded_told"):
            lines.append(t("degraded", lang))
            ses["degraded_told"] = True
        return self._show_variants(card, ses, lang, lines, degraded)

    def _show_variants(self, card: Card, ses: dict, lang: str, lines: list[str], degraded: bool) -> dict:
        ses["await"] = "variants"
        items, params = ses.get("variants") or [], P.validate(card, ses.get("params"))
        blocks = [{"type": "variants", "model_id": card.id, "title": "", "items": items}]
        chips = [std_chip("more_variants", "more_variants", lang), std_chip("back_brief", "back_brief", lang)]
        return response(lines, chips, blocks, lang, intent="variants", degraded=degraded, generate_params=params)

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
        if not card:
            return self._ask_type(ses, ctx, lang)
        if not ses.get("prompt"):
            ses["prompt"] = ses.get("idea") or ctx.get("draft") or ""
        if not ses["prompt"]:
            return response([t("describe_idea", lang)], [], intent="generate_now", generate_model=card.id)
        ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
        return self._setup_reply(card, ses, ctx, lang, "generate_now", t("summary_head", lang))

    def _i_compare(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ids = [m for m in it.data.get("models", []) if m in self.d.cards]
        cards = [self.d.cards[m] for m in ids]
        if cards and not ses.get("kind"):
            ses["kind"] = cards[0].kind
        return self._show_models(Pick(cards, True), ses, lang, "compare", head=t("compare_head", lang))

    def _i_price(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        kind = ses.get("kind")
        rows = cheapest(self.d.cards, kind, self._price, self.d.health_fn, limit=4 if kind else 3)
        return self._show_models(Pick([c for c, _ in rows], True), ses, lang, "price", head=t("cheapest_head", lang))

    def _i_error_help(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        card = self.d.cards.get(ctx.get("selected_model_id") or ses.get("picked") or "")
        kind = card.kind if card else ses.get("kind")
        code, lines, chip_keys = err_mod.explain(ctx, lang, kind)
        chips = [std_chip(key, action, lang) for key, action in chip_keys]
        if code == "channel_unavailable" and card:
            pick = self._recommend(card.kind, ses.get("needs") or [], bool(ctx.get("has_image")), exclude=[card.id],
                                   with_cheap=False)
            out = self._show_models(pick, ses, lang, "error_help", head=t("alternatives", lang), extra_top=lines)
            out["error_code"] = code
            return out
        return response(lines, chips, intent="error_help", error_code=code)

    def _i_ui_help(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        lines, chip_keys = ui_help(it.data.get("topic", "models"), lang)
        chips = [std_chip(k, a, lang, self.d.vitrina_url if a == "open_vitrina" else None) for k, a in chip_keys]
        return response(lines, chips, intent="ui_help", topic=it.data.get("topic"))

    def _i_smalltalk(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses["await"] = "idea"
        return self._offer_types([t(it.data.get("kind", "hello"), lang)], ctx, ses, lang, "smalltalk")

    def _i_off_topic(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        # формат → содержание → модель; примеры сюжетов не подсовываем
        ses.update({"await": "type", "idea": "", "topic": "", "kind": None, "picked": None, "prompt": "", "params": {}, "junk_count": 0})
        return self._offer_types([t("off_topic", lang)], ctx, ses, lang, "off_topic")

    def _i_injection(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses.update({"await": "type", "idea": "", "topic": "", "kind": None, "picked": None, "prompt": "", "params": {}, "junk_count": 0})
        return response([t("injection", lang)], self._type_chips(ctx, lang), intent="injection")

    def _i_safety(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses.update(prompt="")
        return response([t("safety", lang)], [std_chip("rephrase", "rephrase", lang)], intent="safety")

    def _i_safety_person(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        return response([t("safety_person", lang)], [], intent="safety_person")

    def _i_crisis(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        return response([t("crisis", lang)], [], intent="crisis")

    # ============================================================== actions
    def _action(self, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        has_image = bool(ctx.get("has_image"))
        if kind == "pick_model":
            return self._pick(str(value or ""), ctx, ses, lang)
        if kind == "choose_type":
            if value not in KINDS:
                return self._ask_type(ses, ctx, lang)
            ses.update(kind=value, picked=None, prompt="", prompt_base="", camera=None, params={}, shown=[], junk_count=0,
                       brief=None, brief_done=False, brief_guide=None, variants=[], var_round=0)
            if not ses.get("needs"):
                ses["needs"] = detect_needs(ses.get("idea") or "")
            if value == "text":
                return self._text_chat_models(ses, ctx, lang, "choose_type")
            idea = ses.get("idea") or ""
            if self.d.brief and not BR.has_subject(idea):
                ses["idea"] = ""
                return self._ask_subject(value, ses, ctx, lang)
            if not idea:
                ses["await"] = "idea"
                return response([t("describe_idea", lang)], [], intent="choose_type")
            if self.d.brief:
                return self._enter_brief(ctx, ses, lang)
            return self._show_models(self._recommend(value, ses.get("needs") or [], has_image), ses, lang, "choose_type")
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
            if not pick.cards and kind == "more":
                ses["shown"] = [cur.id] if cur else []  # всё показали — начинаем круг заново
                pick = self._recommend(k, needs, has_image, exclude=ses["shown"], with_cheap=False)
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
            card = self._current_card(ses, ctx)
            if not card or card.kind != "video":
                return self._ask_type(ses, ctx, lang)
            mid = str(value or "")
            if mid in {"", "none", "skip"}:
                ses["camera"] = None
                head = t("camera_cleared", lang)
            elif CAM.get(mid):
                ses["camera"] = mid
                head = t("camera_picked", lang, title=CAM.title(CAM.get(mid), lang))
            else:
                head = t("camera_unknown", lang)
            if not ses.get("prompt_base") and not ses.get("prompt"):
                ses["prompt_base"] = ses.get("idea") or ""
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
                return self._brief(card, ses, ctx, lang)
            if kind == "more_variants":
                ses["var_round"] = int(ses.get("var_round") or 0) + 1
                return self._variants(card, ses, ctx, lang, change="other creative directions, different from before")
            if kind == "use_variant":
                v = next((x for x in ses.get("variants") or [] if x.get("id") == value), None)
                if not v:
                    return self._variants(card, ses, ctx, lang)
                ses["prompt_base"] = v["text"]
                ses["prompt"] = v["text"]
                ses["brief_done"] = True
                ses["picked"] = None
                ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
                pick = self._recommend(ses.get("kind") or card.kind, ses.get("needs") or [], has_image)
                return self._show_models(pick, ses, lang, "use_variant",
                                         head=t("variant_chosen", lang, title=v["title"]))
            return self._variants(card, ses, ctx, lang)
        if kind == "restart":
            self._new_task(None, "", [], "", ses)
            ses["junk_count"] = 0
            return self._ask_type(ses, ctx, lang)
        if kind == "resume":  # вернулись после входа / пополнения — показать то же место с новой проверкой
            card = self._current_card(ses, ctx) if ses.get("picked") else None
            if card and (ses.get("prompt") or ses.get("idea")):
                if not ses.get("prompt"):
                    ses["prompt"] = ses.get("idea")
                ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
                return self._setup_reply(card, ses, ctx, lang, "resume", t("resumed", lang))
            ses["await"] = "type"
            return self._offer_types([t("nothing_to_resume", lang)], ctx, ses, lang, "resume")
        if kind == "edit_prompt":
            return response([t("what_change", lang)], [], intent="edit_prompt")
        if kind == "rephrase":
            return response([t("rephrase_ask", lang)], [], intent="rephrase")
        if kind == "send" and isinstance(value, str):
            return self._message(value, ctx, ses, lang)
        return response([], [], intent="noop")


def _kind_by_number(msg: str) -> str | None:
    m = re.fullmatch(r"\s*([1-4])\s*[.)]?\s*", msg or "")
    return ["image", "video", "music", "text", "sfx"][int(m.group(1)) - 1] if m else None


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
