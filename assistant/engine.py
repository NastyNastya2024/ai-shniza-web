"""Ядро ассистента: маршрут → обработчик → ответ. Без Flask, без сети (сеть только внутри LLMChain).

Сценарий (как на эталонном экране):
  1. «кот жарит яичницу»          → «Что сделать — картинку, видео или музыку?» + кнопки типов
     (ответ текстом с опечаткой «карттинку» тоже понимается)
  2. тип известен                  → карточки 2–3 моделей: цена, оценка за N с, бейдж, «примеры на витрине»
  3. клик по карточке (или имя модели текстом) → промпт под модель + параметры кнопками (выбраны значения
     по умолчанию / из текста) + итог с ценой + «Сгенерировать»
  4. клик по параметру → итог пересчитан, без LLM;  «Улучшить промпт» → подсказки-кнопки или свой текст

Контракт ответа: см. render.py (text, blocks, chips, reply) + поля:
    intent, lang, models, generate_model, generate_prompt, generate_params, ready, llm{...}, degraded
Ассистент НИКОГДА не запускает генерацию: кнопка generate обрабатывается фронтом → POST /api/generate.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import errors as err_mod
from . import params as P
from .cards import Card, load_cards
from .lang import detect_lang
from .llm import LLMChain, LLMUnavailable
from .prompts import SYSTEM, build_user, fallback_prompt, validate_output
from .recommend import Pick, cheapest, price_value, recommend
from .render import chip, estimate, model_item, response, short_price, std_chip
from .router import MINORS_SEXUAL, NSFW, VIOLENCE, Intent, detect_kind, detect_needs, lev, route, squeeze, topic_of
from .session import MAX_SESSION_ID, MemoryStore, load
from .texts import EXAMPLES, REFINE_SUGGEST, b, t
from .ui_help import ui_help

log = logging.getLogger("assistant")

KINDS = ("video", "image", "edit", "music", "sfx")
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
        msg = (message or "").strip()[:2000]
        lang = self._lang(msg, ses, ctx)
        ses["lang"] = lang
        ses["turns"] = int(ses.get("turns") or 0) + 1
        self._llm_info = {"used": False, "provider": None, "tokens": 0, "latency_ms": 0}
        try:
            if action and isinstance(action, dict) and action.get("type"):
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
        fallback = ses.get("lang") or (ctx.get("lang") if ctx.get("lang") in ("ru", "en") else None) or "ru"
        if not msg:
            return fallback
        rest = msg
        for title in self.titles.values():  # «. GPT Image 2» — это не английский, это название модели
            rest = re.sub(re.escape(title), " ", rest, flags=re.I)
        if len(re.findall(r"[a-zа-яё]", rest, re.I)) < 4:
            return fallback
        return detect_lang(rest, default=fallback)

    def _message(self, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        # 1) текст совпал с кнопкой прошлого ответа или с названием модели → это клик
        act = self._text_as_action(msg, ses)
        if act:
            return self._action(act[0], act[1], ctx, ses, lang)
        # 2) ждём ответ «какой тип» — понимаем коротко и с опечатками
        if ses.get("await") == "type" and len(msg.split()) <= 3:
            k = detect_kind(msg, bool(ctx.get("has_image"))) or _kind_by_number(msg)
            if k:
                return self._action("choose_type", k, ctx, ses, lang)
            it = route(msg, ctx, ses, self.titles)
            if it.name in ("ask_type", "off_topic"):
                return response([t("ask_type_again", lang)], self._type_chips(ctx, lang), intent="ask_type")
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
            if c.get("label") and _norm(c["label"]) == n and c.get("action") not in {"generate"}:
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
        for c in sorted(cards, key=lambda c: (prices[c.id] if prices[c.id] is not None else 1e9, -c.rank)):
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
        return response((extra_top or []) + [head], chips, [{"type": "models", "items": items}], lang,
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
                self._llm_info.update(tokens=exc.tokens, error=exc.reason, attempts=exc.attempts[-4:])
            else:
                ses["tokens"] = int(ses.get("tokens") or 0) + res.tokens
                self._llm_info.update(used=True, provider=res.provider, tokens=res.tokens, latency_ms=res.latency_ms)
                prompt = res.data["prompt"]
                if res.data.get("note") == "unsafe" or not prompt or _unsafe(prompt):
                    return None, "", False
                return prompt, res.data.get("note", ""), False
        elif llm is not None and llm.available:
            self._llm_info["error"] = "budget"
        return fallback_prompt(card, idea, change, prev, lang), "", True

    def _current_card(self, ses: dict, ctx: dict) -> Card | None:
        mid = ses.get("picked") or ctx.get("selected_model_id")
        return self.d.cards.get(mid) if mid else None

    def _examples(self, lang: str) -> list[dict]:
        return [chip(b(k, lang), "send", EXAMPLES[k][lang]) for k in ("ex_video", "ex_image", "ex_music")]

    def _type_chips(self, ctx: dict, lang: str) -> list[dict]:
        kinds = ["image", "video", "music", "edit" if ctx.get("has_image") else "sfx"]
        if ctx.get("has_image"):
            kinds = ["video", "edit", "image", "music"]
        return [chip(b("type_" + k, lang), "choose_type", k) for k in kinds]

    def _ask_type(self, ses: dict, ctx: dict, lang: str) -> dict:
        ses["await"] = "type"
        topic = ses.get("topic") or ""
        head = t("ask_type_idea", lang, topic=topic) if topic else t("ask_type_plain", lang)
        return response([head], self._type_chips(ctx, lang), intent="ask_type")

    # ----------------------------------------------- prompt + params + summary
    def _setup_reply(self, card: Card, ses: dict, ctx: dict, lang: str, intent: str, head: str,
                     note: str = "", degraded: bool = False, adj: list[dict] | None = None) -> dict:
        prompt = ses.get("prompt") or ""
        params = P.validate(card, ses.get("params"))
        lines = [head]
        for a in adj or []:
            if a["param"] in P.DURATION_NAMES:
                lines.append(t("params_adjusted", lang, asked=a["asked"], got=a["got"]))
        if degraded and self._llm_info.get("error"):  # LLM настроена, но не ответила — честно скажем
            lines.append(t("degraded", lang))
        price = short_price(self._price(card.id)) or t("price_unknown", lang)
        est = estimate(price, P.seconds(card, params), lang)
        has_image = bool(ctx.get("has_image"))
        blocks: list[dict] = [{"type": "prompt", "model_id": card.id, "title": card.title, "text": prompt, "note": note}]
        groups = P.groups(card, params, lang, has_image)
        if groups:
            blocks.append({"type": "params", "model_id": card.id, "groups": groups})
        blocks.append({"type": "summary", "model_id": card.id, "title": card.title, "price": price, "estimate": est,
                       "prompt": prompt, "params": [g["label"] + ": " + next((o["label"] for o in g["options"] if o["selected"]), "—")
                                                     for g in groups]})
        if card.needs_image and not has_image:
            lines.append(t("needs_image", lang))
            chips = [std_chip("attach", "attach", lang, primary=True), std_chip("no_photo_model", "no_photo_model", lang)]
            ready = False
        else:
            chips = [std_chip("generate", "generate", lang, card.id, primary=True), std_chip("improve", "improve", lang),
                     std_chip("mine", "use_mine", lang), std_chip("other_model", "more", lang)]
            ready = True
        ses["await"] = "params"
        return response(lines, chips, blocks, lang, intent=intent, generate_model=card.id, generate_prompt=prompt,
                        generate_params=params, ready=ready, degraded=degraded,
                        models=[{"id": card.id, "title": card.title, "price": price}])

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
        idea = ses.get("idea") or ctx.get("draft") or ""
        if not idea:
            ses["await"] = "idea"
            return response([t("describe_idea", lang)], [], intent=intent, generate_model=card.id)
        raw_params, adj = P.fit(P.extract(idea), card)
        kept = P.validate(card, ses.get("params"))
        params = P.with_defaults(card, {**kept, **raw_params})
        prompt, note, degraded = self._adapt(card, idea, params, ses, lang)
        if prompt is None:
            return self._i_safety(Intent("safety"), "", ctx, ses, lang)
        ses["prompt"], ses["params"] = prompt, params
        head = t("prompt_ready_simple" if degraded else "prompt_ready", lang, title=card.title)
        return self._setup_reply(card, ses, ctx, lang, intent, head, note, degraded, adj)

    # ============================================================== intents
    def _new_task(self, kind: str | None, msg: str, needs: list[str], topic: str, ses: dict) -> None:
        ses.update(kind=kind, topic=topic, needs=needs, idea=msg, picked=None, prompt="", params={}, shown=[])

    def _i_generate_task(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        self._new_task(it.kind, msg, it.needs, it.topic, ses)
        pick = self._recommend(it.kind or "image", it.needs, bool(ctx.get("has_image")))
        return self._show_models(pick, ses, lang, "generate_task")

    def _i_ask_type(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        self._new_task(None, msg, it.needs, it.topic, ses)
        return self._ask_type(ses, ctx, lang)

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
        params = P.validate(card, ses.get("params"))
        prompt, note, degraded = self._adapt(card, ses.get("idea") or "", params, ses, lang,
                                             change=change, prev=ses.get("prompt") or "")
        if prompt is None:
            return self._i_safety(Intent("safety"), "", ctx, ses, lang)
        ses["prompt"] = prompt
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
        return response([t(it.data.get("kind", "hello"), lang)], self._type_chips(ctx, lang), intent="smalltalk")

    def _i_off_topic(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        return response([t("off_topic", lang)], self._examples(lang), intent="off_topic")

    def _i_injection(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        return response([t("injection", lang)], self._examples(lang), intent="injection")

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
            ses.update(kind=value, picked=None, prompt="", params={}, shown=[])
            if not ses.get("needs"):
                ses["needs"] = detect_needs(ses.get("idea") or "")
            if not ses.get("idea"):
                ses["await"] = "idea"
                return response([t("describe_idea", lang)], [], intent="choose_type")
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
            ses["prompt"] = idea
            ses["params"] = P.with_defaults(card, P.validate(card, ses.get("params")))
            return self._setup_reply(card, ses, ctx, lang, "use_mine", t("kept_text", lang))
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
        if kind == "edit_prompt":
            return response([t("what_change", lang)], [], intent="edit_prompt")
        if kind == "rephrase":
            return response([t("rephrase_ask", lang)], [], intent="rephrase")
        if kind == "send" and isinstance(value, str):
            return self._message(value, ctx, ses, lang)
        return response([], [], intent="noop")


def _kind_by_number(msg: str) -> str | None:
    m = re.fullmatch(r"\s*([1-4])\s*[.)]?\s*", msg or "")
    return ["image", "video", "music", "sfx"][int(m.group(1)) - 1] if m else None


def _unsafe(text: str) -> bool:
    return bool(MINORS_SEXUAL.search(text) or VIOLENCE.search(text) or NSFW.search(text))


def _generic_error(lang: str) -> str:
    return "Что-то пошло не так. Попробуйте ещё раз." if lang != "en" else "Something went wrong. Please try again."
