# Контроллер балансировки трафика (soft-overflow)

**Статус:** реализован каркас в `queue_runtime/load_balancer.py`, подключён в `/api/generate`  
**Дата:** 2026-10-10  
**Связано:** [`controllers_by_integration.md`](./controllers_by_integration.md) · [`financial_model_channel_distribution.md`](./financial_model_channel_distribution.md) · [`architecture/ARCHITECTURE.md`](./architecture/ARCHITECTURE.md) §2

---

## Правило одной фразой

**Сначала грузим выбранный (preferred) канал, но не до отказа — при soft-пороге перекидываем новые job на запасной fal; цена для холда = max(preferred, routed).**

---

## Зачем

Раньше: sticky `provider` модели → при пике очередь R растёт, fal простаивает, UX деградирует.  
Автоfailover по health (B2) закрывал только «канал мёртв», не «канал тёплый».

Контроллер добавляет **soft-overflow по нагрузке**, не ломая sticky UX (пользователь выбирает логическую модель; UI-карточки `*-hf` по-прежнему отдельные).

---

## Политика маршрутизации

```
preferred = модель из UI (обычно Replicate)
backup    = FAILOVER_MAP[preferred][t|i] → fal endpoint (если есть)

load(ch)  = inflight + llen(queue:ch) + llen(processing:ch)
cap(ch)   = WORKER_CONCURRENCY_*
soft(ch)  = ceil(cap × CHANNEL_SOFT_LOAD_RATIO)   # default 0.7
```

| Условие | Решение | `reason` |
|---|---|---|
| preferred healthy, `load < soft` | остаёмся | `preferred` |
| preferred healthy, `load ≥ soft`, backup healthy и `load_b < soft_b` | overflow → fal | `soft_overflow` |
| preferred `load ≥ cap`, backup `load < cap` | overflow → fal | `hard_overflow` |
| preferred **down**, backup healthy | overflow → fal | `preferred_unhealthy` |
| preferred down, backup нет/down | 503 | `preferred_unhealthy_no_backup` |
| balancer off (`CHANNEL_LOAD_BALANCER=0`) | sticky preferred | `preferred` |

**Не делает:** round-robin, % split, auto на Higgsfield (HF только явная карточка `*-hf`).

---

## Где в коде

| Компонент | Путь |
|---|---|
| Решение | `queue_runtime/load_balancer.py` → `choose_route` / `resolve_route` |
| Карта резервов | `server.FAILOVER_MAP` + `_failover_target` |
| Точка входа | `server.api_generate` — до enqueue |
| Тесты | `tests/test_load_balancer.py` |

Job и ответ API получают поле `route` (`reason`, `overflow`, loads, `preferred_model_id`).

---

## Env

| Переменная | Default | Смысл |
|---|---|---|
| `CHANNEL_LOAD_BALANCER` | `1` | вкл/выкл soft-overflow |
| `CHANNEL_SOFT_LOAD_RATIO` | `0.7` | доля concurrency, после которой overflow |
| `WORKER_CONCURRENCY_REPLICATE` | `10` | hard cap воркера R |
| `WORKER_CONCURRENCY_FAL` | `6` | hard cap воркера fal |

Имеет смысл: `soft_R ≤ concurrent_upstream_R`, worker ≤ аккаунт-лимит провайдера (см. нагрузку в `controllers_by_integration.md`).

---

## Поведение при пике (пример)

Defaults: R cap=10 soft=7 · fal cap=6 soft=5.

| Inflight+queue R | Inflight+queue fal | Куда пойдёт новый Wan 3.0 |
|---:|---:|---|
| 3 | 0 | Replicate |
| 7 | 1 | **fal** (soft_overflow) |
| 8 | 5 | Replicate (backup тоже soft) |
| 10 | 4 | **fal** (hard_overflow) |
| down | 0 | **fal** (preferred_unhealthy) |

---

## Цена (кратко)

Полная финмодель: [`financial_model_channel_distribution.md`](./financial_model_channel_distribution.md).

- **Холд баланса** при старте: `max(цена preferred, цена routed)`.
- **Себестоимость** = канал, который реально отработал.
- UI пока показывает цену preferred; при overflow фактический COGS может быть выше/ниже — разница = маржа продукта.

---

## Дальше (не в этом PR)

1. Settle charge по `job.provider` (не по UI slug).  
2. Per-model soft caps / per-endpoint fal limits.  
3. Метрики: доля `soft_overflow`, ΔCOGS overflow, длина очередей.  
4. Опционально: weighted overflow на HF-сиблинг (сейчас вне scope).
