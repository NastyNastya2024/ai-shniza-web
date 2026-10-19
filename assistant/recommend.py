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


def cheapest(cards: dict[str, Card], kind: str | None, price_fn: PriceFn, health_fn: HealthFn | None = None,
             limit: int = 5) -> list[tuple[Card, str | None]]:
    rows = [c for c in cards.values() if (kind is None or c.kind == kind) and _healthy(c, health_fn)]
    rows.sort(key=lambda c: (price_value(price_fn(c.id)) if price_value(price_fn(c.id)) is not None else 1e9, -c.rank, c.id))
    return [(c, price_fn(c.id)) for c in rows[:limit]]
