"""Подбор моделей — без LLM.

Правила:
* по умолчанию (n=None) — все модели выбранного типа; UI для видео режет первой страницей (n=6);
* модели с упавшим каналом (health_fn → False) не предлагаем;
* с фото для видео — i2v выше в ранге, но без фото i2v-модели тоже показываем;
* если среди первых нет самой дешёвой и n ограничен — подменяем последнюю (with_cheap);
* общее видео: Seedance первым, остальные — от дешёвых к дорогим.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .cards import Card

PriceFn = Callable[[str], "str | None"]
HealthFn = Callable[[str], bool]

# Первая карточка в подборе по типу (если модель доступна и подходит).
PIN_FIRST = {"text": "omni-auto-free", "video": "seedance-2-5"}


@dataclass
class Pick:
    cards: list[Card]
    exact: bool  # False → «точной модели нет, ближе всего…»


def price_value(price: str | None) -> float | None:
    """'15 ₽' → 15.0; 'бесплатно'/'free'/'0' → 0.0; None/непонятно → None."""
    if price is None:
        return None
    s = str(price).lower()
    if "беспл" in s or "free" in s:
        return 0.0
    m = re.search(r"(\d+(?:[.,]\d+)?)", s.replace(" ", "").replace(" ", ""))
    return float(m.group(1).replace(",", ".")) if m else None


def family(card: Card) -> str:
    return str(card.extra.get("family") or card.title.split()[0]).lower()


def _healthy(card: Card, health_fn: HealthFn | None) -> bool:
    if health_fn is None:
        return True
    try:
        return bool(health_fn(card.id))
    except Exception:
        return True  # health недоступен — не прячем каталог целиком


def score(card: Card, needs: Iterable[str], has_image: bool, price_fn: PriceFn | None = None) -> float:
    needs = list(needs)
    hit = len(set(needs) & set(card.tags))
    s = card.rank + 3.0 * hit
    if has_image and card.kind == "video" and "i2v" in card.modes:
        s += 1.0 + (2.0 if "оживить фото" in card.tags else 0.0)
    if "дешево" in needs and price_fn is not None:
        v = price_value(price_fn(card.id))
        if v is not None:
            s += 4.0 / (1.0 + v / 10.0)
    return s


def _price_key(card: Card, price_fn: PriceFn | None) -> float:
    if price_fn is None:
        return 1e9
    v = price_value(price_fn(card.id))
    return v if v is not None else 1e9


def recommend(cards: dict[str, Card], kind: str, needs: list[str] | None = None, has_image: bool = False,
              health_fn: HealthFn | None = None, price_fn: PriceFn | None = None,
              neighbors: dict[str, list[str]] | None = None, exclude: Iterable[str] = (), n: int | None = None,
              with_cheap: bool = True) -> Pick:
    needs = needs or []
    excl = set(exclude)

    def pool(kinds: Iterable[str]) -> list[Card]:
        ks = set(kinds)
        # Все модели типа — включая i2v-only (Grok, Gen-4 Turbo) без фото.
        return [c for c in cards.values()
                if c.kind in ks and c.id not in excl and _healthy(c, health_fn)]

    # общее «видео» без узких тегов — Seedance + дешёвые; иначе score важнее
    prefer_price = kind == "video" and not needs

    def _sort_key(c: Card) -> tuple:
        sc = -score(c, needs, has_image, price_fn)
        if prefer_price:
            return (_price_key(c, price_fn), sc, c.id)
        return (sc, _price_key(c, price_fn), c.id)

    main = sorted(pool([kind]), key=_sort_key)
    pin_id = PIN_FIRST.get(kind)
    if pin_id:
        pinned = next((c for c in main if c.id == pin_id), None)
        if pinned is not None:
            main = [pinned] + [c for c in main if c.id != pin_id]
    limit = len(main) if n is None else max(0, int(n))
    exact = not needs or any(set(needs) & set(c.tags) for c in main[: max(limit, 1)])
    # разнообразие семейств только когда режем список; при полном каталоге — все модели
    picked: list[Card] = []
    if n is None:
        picked = list(main)
    else:
        for c in main:
            if len(picked) >= limit:
                break
            if family(c) not in {family(p) for p in picked}:
                picked.append(c)
        for c in main:
            if len(picked) >= limit:
                break
            if c not in picked:
                picked.append(c)
    # узкий тип (sfx и т.п.) — добираем соседей, чтобы было из чего выбрать
    need = 2 if n is None else limit
    if len(picked) < need:
        extra = sorted(pool((neighbors or {}).get(kind, [])), key=_sort_key)
        picked += [c for c in extra if c not in picked][: need - len(picked)]
        if extra and len(main) < need:
            exact = False if needs else exact

    if with_cheap and n is not None and price_fn is not None and picked:
        rest = [c for c in main if c not in picked]
        prices = [price_value(price_fn(c.id)) for c in picked]
        known = [p for p in prices if p is not None]
        if rest and known:
            cheap = min(rest, key=lambda c: _price_key(c, price_fn))
            cv = price_value(price_fn(cheap.id))
            if cv is not None and cv < min(known):
                if len(picked) < limit:
                    picked.append(cheap)
                elif len(picked) >= 2 and picked[-1].id != pin_id:
                    picked[-1] = cheap
    # общее видео в UI: Seedance первым, остальные — от дешёвых к дорогим
    if prefer_price and picked and price_fn is not None:
        head = [c for c in picked if c.id == pin_id]
        tail = [c for c in picked if c.id != pin_id]
        tail.sort(key=lambda c: (_price_key(c, price_fn), c.id))
        picked = head + tail if head else sorted(picked, key=lambda c: (_price_key(c, price_fn), c.id))
    return Pick(picked, exact)


def _gen4_after_kling(cards: list[Card]) -> list[Card]:
    """Gen-4 Turbo не в первом ряду: сразу после последнего Kling, ближе к середине списка."""
    gen = next((c for c in cards if c.id == "gen4-turbo"), None)
    if gen is None:
        return cards
    rest = [c for c in cards if c.id != "gen4-turbo"]
    kling_at = [i for i, c in enumerate(rest) if str(c.id).startswith("kling")]
    if not kling_at:
        return cards
    insert_at = kling_at[-1] + 1
    if insert_at < 3:
        insert_at = min(len(rest), max(3, len(rest) // 2))
    rest.insert(insert_at, gen)
    return rest


def advise(cards: dict[str, Card], caps: dict, profile: dict, price_fn: PriceFn,
            health_fn: HealthFn | None = None, catalog_fn: Callable[[str], bool] | None = None,
            n: int | None = 3, price_order: bool = False) -> list[Card]:
    """Модели под уже собранную задачу. price_order — весь список, сначала самые дешёвые.

    Неизвестные оценки в caps не подставляем: null не участвует в счёте.
    """
    kind = profile.get("kind") or "image"
    kinds = {"image", "edit"} if kind == "image" else {kind}
    pool = [c for c in cards.values() if c.kind in kinds and _healthy(c, health_fn)]
    if catalog_fn is not None:
        vis = [c for c in pool if catalog_fn(c.id)]
        if vis:
            pool = vis
    aspect = profile.get("aspect")
    if aspect and not price_order:
        fitted = [c for c in pool if aspect in (c.params.get("aspect_ratio") or [])]
        if fitted:
            pool = fitted
    if profile.get("text"):
        fitted = [c for c in pool if isinstance((caps.get(c.id) or {}).get("text_render"), (int, float))
                  and (caps.get(c.id) or {})["text_render"] >= 2]
        if fitted:
            pool = fitted
    # Полный список (сначала дешёвые) не режем по фото: текстовые модели вроде Gemini тоже в каталоге.
    if profile.get("needs_image") and not price_order:
        fitted = [c for c in pool if "i2v" in (c.modes or []) or "i2i" in (c.modes or [])]
        if fitted:
            pool = fitted
    if not pool:
        return []

    def score(c: Card) -> float:
        cap = caps.get(c.id) or {}
        s = c.rank / 100.0
        tr = cap.get("text_render")
        if profile.get("text") and isinstance(tr, (int, float)):
            s += float(tr) * 4
        if profile.get("audio") and cap.get("audio") in ("native", "lipsync", "music"):
            s += 6
        cons = cap.get("consistency")
        if profile.get("same_hero") and isinstance(cons, (int, float)):
            s += float(cons) * 2
        pv = price_value(price_fn(c.id))
        if pv is not None:
            s += max(0.0, 8.0 - min(pv, 40.0) / 5.0)
        return s

    if price_order:
        ordered = sorted(pool, key=lambda c: (
            price_value(price_fn(c.id)) if price_value(price_fn(c.id)) is not None else 1e9, c.id))
        return _gen4_after_kling(ordered)
    ranked = sorted(pool, key=lambda c: (-score(c), c.id))
    best = ranked[0]
    best_price = price_value(price_fn(best.id))
    out = [best]
    alt = next((c for c in ranked[1:]
                if best_price is not None and (price_value(price_fn(c.id)) or 0) > best_price), None)
    if alt:
        out.append(alt)
    cheap = min(ranked, key=lambda c: (price_value(price_fn(c.id)) if price_value(price_fn(c.id)) is not None else 1e9, c.id))
    if cheap.id not in {c.id for c in out}:
        out.append(cheap)
    cur = profile.get("current")
    if cur:
        hit = next((c for c in pool if c.id == cur), None)
        if hit and hit.id not in {c.id for c in out[:1]}:
            out = [hit] + [c for c in out if c.id != hit.id]
    return out[:n]


def cheapest(cards: dict[str, Card], kind: str | None, price_fn: PriceFn, health_fn: HealthFn | None = None,
             limit: int = 5) -> list[tuple[Card, str | None]]:
    rows = [c for c in cards.values() if (kind is None or c.kind == kind) and _healthy(c, health_fn)]
    rows.sort(key=lambda c: (price_value(price_fn(c.id)) if price_value(price_fn(c.id)) is not None else 1e9, -c.rank, c.id))
    return [(c, price_fn(c.id)) for c in rows[:limit]]
