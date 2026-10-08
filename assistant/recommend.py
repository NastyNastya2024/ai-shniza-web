"""Подбор моделей — без LLM.

Правила:
* всегда минимум 2 модели (если доступно хотя бы 2 во всём каталоге с учётом соседних типов);
* модели с упавшим каналом (health_fn → False) не предлагаем;
* без фото не предлагаем модели «только из фото», с фото для видео — сначала i2v;
* третьей добавляем самую дешёвую/бесплатную, если она дешевле обеих первых.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .cards import Card

PriceFn = Callable[[str], "str | None"]
HealthFn = Callable[[str], bool]

# Первая карточка в подборе по типу (если модель доступна и подходит).
PIN_FIRST = {"video": "seedance-2-5", "text": "omni-auto-free"}


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


def recommend(cards: dict[str, Card], kind: str, needs: list[str] | None = None, has_image: bool = False,
              health_fn: HealthFn | None = None, price_fn: PriceFn | None = None,
              neighbors: dict[str, list[str]] | None = None, exclude: Iterable[str] = (), n: int = 2,
              with_cheap: bool = True) -> Pick:
    needs = needs or []
    excl = set(exclude)

    def pool(kinds: Iterable[str]) -> list[Card]:
        ks = set(kinds)
        return [c for c in cards.values()
                if c.kind in ks and c.id not in excl and c.supports(has_image) and _healthy(c, health_fn)]

    main = sorted(pool([kind]), key=lambda c: (-score(c, needs, has_image, price_fn), c.id))
    pin_id = PIN_FIRST.get(kind)
    if pin_id:
        pinned = next((c for c in main if c.id == pin_id), None)
        if pinned is not None:
            main = [pinned] + [c for c in main if c.id != pin_id]
    exact = not needs or any(set(needs) & set(c.tags) for c in main[:n])
    # разнообразие: не показываем две модели одного семейства (Veo 3.1 + Veo 3.1 Fast), если есть альтернатива
    picked: list[Card] = []
    for c in main:
        if len(picked) >= n:
            break
        if family(c) not in {family(p) for p in picked}:
            picked.append(c)
    for c in main:
        if len(picked) >= n:
            break
        if c not in picked:
            picked.append(c)
    if len(picked) < n:
        extra = sorted(pool((neighbors or {}).get(kind, [])), key=lambda c: (-score(c, needs, has_image, price_fn), c.id))
        picked += extra[: n - len(picked)]
        if extra and len(main) < n:
            exact = False if needs else exact

    if with_cheap and price_fn is not None and len(picked) >= 2:
        rest = [c for c in main if c not in picked]
        prices = [price_value(price_fn(c.id)) for c in picked]
        known = [p for p in prices if p is not None]
        if rest and known:
            cheapest = min(rest, key=lambda c: (price_value(price_fn(c.id)) if price_value(price_fn(c.id)) is not None else 1e9))
            cv = price_value(price_fn(cheapest.id))
            if cv is not None and cv < min(known):
                picked.append(cheapest)
    return Pick(picked, exact)


def cheapest(cards: dict[str, Card], kind: str | None, price_fn: PriceFn, health_fn: HealthFn | None = None,
             limit: int = 5) -> list[tuple[Card, str | None]]:
    rows = [c for c in cards.values() if (kind is None or c.kind == kind) and _healthy(c, health_fn)]
    rows.sort(key=lambda c: (price_value(price_fn(c.id)) if price_value(price_fn(c.id)) is not None else 1e9, -c.rank, c.id))
    return [(c, price_fn(c.id)) for c in rows[:limit]]
