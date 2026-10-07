"""Ядро ассистента: маршрут → обработчик → ответ. Без Flask, без сети (сеть — только внутри LLMChain).

Контракт:
    Assistant(deps).handle(message, context, session_id, action=None) -> dict
        reply            str   короткий markdown (≤12 строк, ≤1200 символов)
        chips            list  кнопки [{label, action, value?}]
        intent           str   какой обработчик сработал
        lang             str   ru | en
        models           list  [{id, title, price}] — показанные модели
        generate_model   str?  модель для формы генерации (заполнить, НЕ запускать)
        generate_prompt  str?  промпт для формы генерации
        generate_params  dict? параметры из белого списка карточки
        ready            bool  всё уточнено — можно показывать «Сгенерировать»
        llm              dict  {used, provider, tokens, latency_ms, error?}
        degraded         bool  ответ без LLM там, где LLM была бы нужна

Ассистент НИКОГДА не запускает генерацию и не тратит деньги: он только заполняет форму.
Запуск — отдельный POST /api/generate по кнопке пользователя (там же биллинг, модерация, rate-limit).
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
from .recommend import Pick, cheapest, recommend
from .render import chip, model_line, quote_prompt, response, std_chip
from .router import MINORS_SEXUAL, NSFW, VIOLENCE, Intent, route
from .session import MAX_SESSION_ID, MemoryStore, load
from .texts import EXAMPLES, b, t
from .ui_help import ui_help

log = logging.getLogger("assistant")

KINDS = ("video", "image", "edit", "music", "sfx")
PARAM_HINT = {"9:16": {"ru": "9:16 вертикально", "en": "9:16 vertical"},
              "16:9": {"ru": "16:9 горизонтально", "en": "16:9 horizontal"},
              "1:1": {"ru": "1:1 квадрат", "en": "1:1 square"}}


@dataclass
class AssistantDeps:
    cards: dict[str, Card]
    neighbors: dict[str, list[str]] = field(default_factory=dict)
    price_fn: Callable[[str], "str | None"] = lambda _mid: None
    health_fn: Callable[[str], bool] | None = None
    llm: LLMChain | None = None
    store: Any = field(default_factory=MemoryStore)
    vitrina_url: str = "/vitrina.html"
    token_budget: int = 6000        # LLM-токенов на сессию (≈ 10–12 адаптаций промпта)
    max_llm_calls: int = 15         # LLM-вызовов на сессию
    on_event: Callable[[dict], None] | None = None  # метрики: assistant_metrics, логи


class Assistant:
    def __init__(self, deps: AssistantDeps):
        self.d = deps
        self.titles = {c.id: c.title for c in deps.cards.values()}
        self._tls = threading.local()  # gthread: один Assistant на воркер, запросы в разных потоках

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

    # ------------------------------------------------------------------ entry
    def handle(self, message: str = "", context: dict | None = None, session_id: str = "",
               action: dict | None = None) -> dict[str, Any]:
        t0 = time.monotonic()
        ctx = dict(context or {})
        sid = (session_id or "")[:MAX_SESSION_ID]
        ses = load(self.d.store, sid)
        msg = (message or "").strip()[:2000]
        fallback_lang = ses.get("lang") or (ctx.get("lang") if ctx.get("lang") in ("ru", "en") else None) or "ru"
        lang = detect_lang(msg, default=fallback_lang) if msg else fallback_lang
        ses["lang"] = lang
        ses["turns"] = int(ses.get("turns") or 0) + 1
        self._llm_info: dict[str, Any] = {"used": False, "provider": None, "tokens": 0, "latency_ms": 0}
        try:
            if action and isinstance(action, dict) and action.get("type"):
                out = self._action(str(action["type"]), action.get("value"), ctx, ses, lang)
            else:
                intent = route(msg, ctx, ses, self.titles)
                out = getattr(self, "_i_" + intent.name)(intent, msg, ctx, ses, lang)
        except Exception:  # ассистент не должен ронять чат
            log.exception("assistant handler failed")
            out = response([_generic_error(lang)],
                           [std_chip("retry", "retry", lang)], intent="internal_error")
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

    # ------------------------------------------------------------- helpers
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

    def _show_models(self, pick: Pick, ses: dict, lang: str, head: str, intent: str,
                     extra_top: list[str] | None = None) -> dict[str, Any]:
        if not pick.cards:
            return response((extra_top or []) + [t("none_available", lang)],
                            [std_chip("open_models", "open_models", lang)], intent=intent)
        lines = list(extra_top or [])
        lines.append(head if pick.exact else t("closest", lang))
        models = []
        for i, c in enumerate(pick.cards, 1):
            price = self._price(c.id)
            lines += model_line(c, price, lang, self.d.vitrina_url, ses.get("topic") or "", i)
            models.append({"id": c.id, "title": c.title, "price": price})
        ses["shown"] = list(dict.fromkeys((ses.get("shown") or []) + [c.id for c in pick.cards]))
        chips = [chip(b("pick", lang, title=c.title), "pick_model", c.id) for c in pick.cards]
        chips.append(std_chip("more", "more", lang))
        return response(lines, chips, intent=intent, models=models)

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
        return fallback_prompt(card, idea, change, prev), "", True

    def _param_chips(self, card: Card, name: str, lang: str) -> list[dict]:
        out = []
        for v in card.params.get(name, [])[:3]:
            label = PARAM_HINT.get(str(v), {}).get(lang) or P.label(name, v, lang)
            out.append(chip(label, "param", {"name": name, "value": v}))
        return out

    def _ask_line(self, name: str, lang: str) -> str:
        key = "ask_" + name
        return t(key, lang) if key in _TKEYS else t("ask_param", lang, name=name)

    def _prompt_reply(self, card: Card, prompt: str, note: str, degraded: bool, params: dict, adj: list[dict],
                      ses: dict, ctx: dict, lang: str, intent: str, head_lines: list[str] | None = None) -> dict:
        lines = list(head_lines or [])
        lines.append(t("prompt_simple" if degraded else "prompt_for", lang, title=card.title))
        lines.append(quote_prompt(prompt))
        if note:
            lines.append(f"_{note}_")
        for a in adj:
            if a["param"] == "duration":
                lines.append(t("params_adjusted", lang, asked=a["asked"], got=a["got"]))
        if degraded:
            lines.append(t("degraded", lang))
        miss = P.missing(card, params)
        if card.needs_image and not ctx.get("has_image"):
            lines.append(t("needs_image", lang))
            chips = [std_chip("attach", "attach", lang), std_chip("no_photo_model", "no_photo_model", lang)]
            ready = False
        elif miss:
            lines.append(self._ask_line(miss[0], lang))
            chips = self._param_chips(card, miss[0], lang) + [std_chip("other_model", "more", lang)]
            ready = False
        else:
            lines.append(t("confirm_generate", lang))
            chips = [std_chip("generate", "generate", lang, card.id), std_chip("edit_prompt", "edit_prompt", lang),
                     std_chip("use_mine", "use_mine", lang), std_chip("other_model", "more", lang)]
            ready = True
        return response(lines, chips, intent=intent, generate_model=card.id, generate_prompt=prompt,
                        generate_params=dict(params), ready=ready, degraded=degraded,
                        models=[{"id": card.id, "title": card.title, "price": self._price(card.id)}])

    def _current_card(self, ses: dict, ctx: dict) -> Card | None:
        mid = ses.get("picked") or ctx.get("selected_model_id")
        return self.d.cards.get(mid) if mid else None

    def _examples(self, lang: str) -> list[dict]:
        return [chip(b(k, lang), "send", EXAMPLES[k][lang]) for k in ("ex_video", "ex_image", "ex_music")]

    # ---------------------------------------------------------- pick flow
    def _pick(self, mid: str, ctx: dict, ses: dict, lang: str, intent: str = "pick_model") -> dict:
        card = self.d.cards.get(mid or "")
        if not card:
            kind = ses.get("kind")
            if kind:
                pick = self._recommend(kind, ses.get("needs") or [], bool(ctx.get("has_image")))
                return self._show_models(pick, ses, lang, t("unknown_model", lang), intent)
            return response([t("ask_type", lang)], self._type_chips(ctx, lang), intent="ask_type")
        if not self._healthy(card.id):
            pick = self._recommend(card.kind, ses.get("needs") or [], bool(ctx.get("has_image")), exclude=[card.id])
            return self._show_models(pick, ses, lang, t("alternatives", lang), "model_down",
                                     extra_top=[t("model_down", lang, title=card.title)])
        ses["picked"] = card.id
        if not ses.get("kind"):
            ses["kind"] = card.kind
        idea = ses.get("idea") or ctx.get("draft") or ""
        if not idea:
            return response([t("describe_idea", lang)], [], intent=intent, generate_model=card.id)
        params, adj = P.fit(P.extract(idea), card)
        kept = P.validate(card, ses.get("params"))
        params = {**kept, **params}
        prompt, note, degraded = self._adapt(card, idea, params, ses, lang)
        if prompt is None:
            return self._i_safety(Intent("safety"), "", ctx, ses, lang)
        ses["prompt"], ses["params"] = prompt, params
        return self._prompt_reply(card, prompt, note, degraded, params, adj, ses, ctx, lang, intent)

    def _type_chips(self, ctx: dict, lang: str) -> list[dict]:
        kinds = ["video", "image", "music", "edit" if ctx.get("has_image") else "sfx"]
        if ctx.get("has_image"):
            kinds = ["video", "edit", "image", "music"]
        return [chip(b("type_" + k, lang), "choose_type", k) for k in kinds]

    # ------------------------------------------------------------- intents
    def _i_generate_task(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses.update(kind=it.kind, topic=it.topic, needs=it.needs, idea=msg, picked=None, prompt="", params={}, shown=[])
        pick = self._recommend(it.kind or "image", it.needs, bool(ctx.get("has_image")))
        n = len(pick.cards)
        head = t("picked", lang, n=n, topic=it.topic) if it.topic else t("picked_notopic", lang, n=n)
        return self._show_models(pick, ses, lang, head, "generate_task")

    def _i_ask_type(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ses.update(kind=None, topic=it.topic, needs=it.needs, idea=msg, picked=None, prompt="", params={}, shown=[])
        return response([t("ask_type", lang)], self._type_chips(ctx, lang), intent="ask_type")

    def _i_prompt_improve(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        card = self._current_card(ses, ctx)
        if not card:
            if ses.get("kind"):
                pick = self._recommend(ses["kind"], ses.get("needs") or [], bool(ctx.get("has_image")))
                return self._show_models(pick, ses, lang, t("picked_notopic", lang, n=len(pick.cards)), "prompt_improve")
            return response([t("ask_type", lang)], self._type_chips(ctx, lang), intent="ask_type")
        if ses.get("prompt"):
            change = it.data.get("change") or msg
            prompt, note, degraded = self._adapt(card, ses.get("idea") or "", ses.get("params") or {}, ses, lang,
                                                 change=change, prev=ses["prompt"])
            if prompt is None:
                return self._i_safety(Intent("safety"), "", ctx, ses, lang)
            ses["prompt"] = prompt
            return self._prompt_reply(card, prompt, note, degraded, ses.get("params") or {}, [], ses, ctx, lang,
                                      "prompt_improve")
        # «улучши промпт: …» с выбранной в UI моделью — берём текст из сообщения или из поля ввода студии
        idea = re.sub(r"^\W*(улучши|перепиши|доработай|improve|rewrite)\w*\s*(промпт|текст|prompt|the prompt|my prompt)?\s*[:\-—]?\s*",
                      "", msg, flags=re.I).strip() or (ctx.get("draft") or "")
        ses.update(idea=idea, kind=card.kind, picked=card.id)
        return self._pick(card.id, ctx, ses, lang, intent="prompt_improve")

    def _i_generate_now(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        card = self._current_card(ses, ctx)
        if not card:
            return response([t("ask_type", lang)], self._type_chips(ctx, lang), intent="ask_type")
        prompt = ses.get("prompt") or ses.get("idea") or ctx.get("draft") or ""
        if not prompt:
            return response([t("describe_idea", lang)], [], intent="generate_now", generate_model=card.id)
        params = P.validate(card, ses.get("params"))
        return self._prompt_reply(card, prompt, "", False, params, [], ses, ctx, lang, "generate_now")

    def _i_compare(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        ids = [m for m in it.data.get("models", []) if m in self.d.cards]
        lines = [t("compare_head", lang)]
        for mid in ids:
            c = self.d.cards[mid]
            price = self._price(mid) or t("price_unknown", lang)
            lines.append(f"**{c.title}** — {c.text('strengths', lang)}")
            lines.append(f"   {c.text('limits', lang)} · {price} · {c.text('speed', lang)}")
        chips = [chip(b("pick", lang, title=self.d.cards[m].title), "pick_model", m) for m in ids]
        return response(lines, chips, intent="compare",
                        models=[{"id": m, "title": self.d.cards[m].title, "price": self._price(m)} for m in ids])

    def _i_price(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        kind = ses.get("kind")
        rows = cheapest(self.d.cards, kind, self._price, self.d.health_fn, limit=5)
        lines = [t("cheapest_head", lang) if "дешево" in it.needs or not kind else t("price_head", lang)]
        for c, p in rows:
            lines.append(f"• **{c.title}** — {p or t('price_unknown', lang)}")
        chips = [chip(b("pick", lang, title=c.title), "pick_model", c.id) for c, _ in rows[:2]]
        chips.append(std_chip("open_models", "open_models", lang))
        return response(lines, chips, intent="price", models=[{"id": c.id, "title": c.title, "price": p} for c, p in rows])

    def _i_error_help(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        card = self.d.cards.get(ctx.get("selected_model_id") or ses.get("picked") or "")
        kind = card.kind if card else ses.get("kind")
        code, lines, chip_keys = err_mod.explain(ctx, lang, kind)
        chips = [std_chip(key, action, lang) for key, action in chip_keys]
        if code == "channel_unavailable" and card:
            pick = self._recommend(card.kind, ses.get("needs") or [], bool(ctx.get("has_image")), exclude=[card.id],
                                   with_cheap=False)
            out = self._show_models(pick, ses, lang, t("alternatives", lang), "error_help", extra_top=lines)
            out["error_code"] = code
            return out
        return response(lines, chips, intent="error_help", error_code=code)

    def _i_ui_help(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        lines, chip_keys = ui_help(it.data.get("topic", "models"), lang)
        chips = [std_chip(k, a, lang, self.d.vitrina_url if a == "open_vitrina" else None) for k, a in chip_keys]
        return response(lines, chips, intent="ui_help", topic=it.data.get("topic"))

    def _i_smalltalk(self, it: Intent, msg: str, ctx: dict, ses: dict, lang: str) -> dict:
        kind = it.data.get("kind", "hello")
        return response([t(kind, lang)], self._examples(lang), intent="smalltalk")

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

    # -------------------------------------------------------------- actions
    def _action(self, kind: str, value: Any, ctx: dict, ses: dict, lang: str) -> dict:
        has_image = bool(ctx.get("has_image"))
        if kind == "pick_model":
            return self._pick(str(value or ""), ctx, ses, lang)
        if kind == "choose_type" and value in KINDS:
            ses.update(kind=value, picked=None, prompt="", params={}, shown=[])
            pick = self._recommend(value, ses.get("needs") or [], has_image)
            topic = ses.get("topic") or ""
            n = len(pick.cards)
            head = t("picked", lang, n=n, topic=topic) if topic else t("picked_notopic", lang, n=n)
            return self._show_models(pick, ses, lang, head, "choose_type")
        if kind in {"more", "similar", "cheaper", "faster", "no_photo_model"}:
            cur = self._current_card(ses, ctx)
            k = ses.get("kind") or (cur.kind if cur else None)
            if not k:
                return response([t("ask_type", lang)], self._type_chips(ctx, lang), intent="ask_type")
            needs = list(ses.get("needs") or [])
            if kind == "cheaper":
                needs = ["дешево"] + needs
            if kind == "faster":
                needs = ["быстро", "черновик"] + needs
            exclude = list(ses.get("shown") or []) if kind == "more" else ([cur.id] if cur else [])
            img = False if kind == "no_photo_model" else has_image
            pick = self._recommend(k, needs, img, exclude=exclude, with_cheap=False)
            if not pick.cards:
                return response([t("no_more", lang)], [std_chip("open_models", "open_models", lang)], intent=kind)
            head = t("more", lang) if kind == "more" else t("alternatives", lang)
            out = self._show_models(Pick(pick.cards, True), ses, lang, head, kind)
            return out
        if kind == "use_mine":
            card = self._current_card(ses, ctx)
            idea = ses.get("idea") or ""
            if not card or not idea:
                return response([t("describe_idea", lang)], [], intent="use_mine")
            ses["prompt"] = idea
            out = self._prompt_reply(card, idea, "", False, P.validate(card, ses.get("params")), [], ses, ctx, lang,
                                     "use_mine", head_lines=[t("kept_text", lang)])
            return out
        if kind == "param" and isinstance(value, dict):
            card = self._current_card(ses, ctx)
            if not card:
                return response([t("ask_type", lang)], self._type_chips(ctx, lang), intent="ask_type")
            clean = P.validate(card, {value.get("name"): value.get("value")})
            params = {**P.validate(card, ses.get("params")), **clean}
            ses["params"] = params
            head = [t("param_saved", lang, label=P.label(k, v, lang)) for k, v in clean.items()]
            prompt = ses.get("prompt") or ses.get("idea") or ""
            return self._prompt_reply(card, prompt, "", False, params, [], ses, ctx, lang, "param", head_lines=head)
        if kind == "edit_prompt":
            return response([t("what_change", lang)], [], intent="edit_prompt")
        if kind == "rephrase":
            return response([t("rephrase_ask", lang)], [], intent="rephrase")
        if kind == "send" and isinstance(value, str):
            return self.handle_inner(value, ctx, ses, lang)
        # retry/wait/open_*/login/attach/support/generate — чисто фронтовые действия
        return response([], [], intent="noop")

    def handle_inner(self, text: str, ctx: dict, ses: dict, lang: str) -> dict:
        intent = route(text, ctx, ses, self.titles)
        return getattr(self, "_i_" + intent.name)(intent, text, ctx, ses, lang)


_TKEYS = {"ask_aspect_ratio", "ask_duration", "ask_resolution"}


def _unsafe(text: str) -> bool:
    return bool(MINORS_SEXUAL.search(text) or VIOLENCE.search(text) or NSFW.search(text))


def _generic_error(lang: str) -> str:
    return "Что-то пошло не так. Попробуйте ещё раз." if lang != "en" else "Something went wrong. Please try again."
