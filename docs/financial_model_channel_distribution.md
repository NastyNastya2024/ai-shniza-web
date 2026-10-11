# Финансовая модель: стоимость с учётом распределения по каналам

**Статус:** продуктовая модель + связка с soft-overflow контроллером  
**Дата:** 2026-10-10  
**Связано:** [`traffic_load_balancer.md`](./traffic_load_balancer.md) · [`pricing_channels_matrix.md`](./pricing_channels_matrix.md) · [`business/financial-model.md`](./business/financial-model.md) · `pricing.py`

---

## Зачем отдельный документ

При sticky-маршруте цена = цена канала модели.  
При **soft-overflow** часть запросов уходит на fal (иногда HF-карточку), где **COGS ≠** цене Replicate. Нужно явно разделить:

1. что **платит пользователь** (list / hold / settle);
2. что **платим мы** провайдеру (COGS);
3. как пик меняет **среднюю маржу**.

---

## Обозначения

| Символ | Смысл |
|---|---|
| \(c_p\) | себестоимость preferred (обычно Replicate), USD за единицу (с / картинка / run) |
| \(c_b\) | себестоимость backup (fal), та же единица |
| \(m\) | markup продукта (в `pricing.py` обычно ≥1.5–2.0) + налог/курс-фактор ~1.30 |
| \(P_{list}\) | цена в UI за логическую модель (почти всегда от \(c_p\)) |
| \(P_{hold}\) | резерв на балансе при старте job |
| \(P_{settle}\) | списание после успеха |
| \(\alpha\) | доля job, ушедших в overflow за период (\(0…1\)) |
| \(C_{blend}\) | ожидаемый COGS = \((1-\alpha) c_p + \alpha c_b\) |

Единица: для видео — **USD / секунду** клипа; для картинки — **USD / image**.

---

## Политика цены (принятая)

| Этап | Правило | Зачем |
|---|---|---|
| **List (UI)** | Цена **preferred** логической модели | UX не прыгает от нагрузки |
| **Hold** | \(P_{hold} = \max(P(c_p), P(c_b))\) если backup в `FAILOVER_MAP` | Не уйти в минус, если overflow на более дорогой fal |
| **Settle (цель)** | Списание по **фактическому** `job.provider` × markup | Честный COGS; пока каркас — hold max, settle-хук дописать |
| **Субсидия** | Если \(c_b > c_p\), а list остаётся от \(c_p\) — разницу несёт маржа | Пик «съедает» margin |

Код холда: `_generate_quote_kop(preferred, routed)` в `server.py`.

---

## Как меняется цена при распределении

### 1. Пользователь (видимая цена)

Обычно **не меняется** в момент клика: видит \(P_{list}(preferred)\).  
При overflow на более дорогой канал:

- либо мы **дотируем** (\(P_{settle}=P_{list}\), margin↓);
- либо позже включаем settle по факту и показываем «выполнено через fal · цена X» (прозрачнее, но UX сложнее).

Рекомендация фазы 1: **дотация + мониторинг \(\alpha\)** и \(\Delta\) маржи; фаза 2 — settle по факту для дорогих overflow.

### 2. Наш COGS

\[
C_{blend} = (1-\alpha)\,c_p + \alpha\,c_b
\]

Маржа на единицу (упрощённо, без курса):

\[
\text{margin} = P_{list}/m_{fx} - C_{blend}
\]

где \(m_{fx}\) — обратный пересчёт list→USD. Если \(\alpha\) растёт и \(c_b > c_p\), margin падает линейно по \(\alpha\).

### 3. Soft-порог и \(\alpha\)

Soft-overflow включается при `load_p ≥ soft_p` и свободном backup.  
\(\alpha\) ≈ доля времени/запросов, когда R выше soft (зависит от пика DAU и `CHANNEL_SOFT_LOAD_RATIO`).

| Soft ratio | Поведение | Эффект на \(C_{blend}\) |
|---|---|---|
| 0.9 | overflow редко | ближе к \(c_p\), длиннее очередь R |
| **0.7** (default) | баланс UX / маржи | умеренный \(\alpha\) |
| 0.5 | overflow рано | выше доля fal, \(C_{blend}\) ближе к \(c_b\) |

---

## Примеры из матрицы цен (720p / типичный режим)

Источник: live Replicate + fal (`pricing_channels_matrix.md`). Markup условный ×2 для иллюстрации list; реальный RUB — через `price_rub_media`.

| Модель | \(c_p\) (R) | \(c_b\) (fal) | Δ backup | При \(\alpha=0.2\) \(C_{blend}\) | Комментарий |
|---|---:|---:|---:|---:|---|
| Wan 3.0 | $0.10/s | $0.10/s | 0% | $0.10 | overflow почти нейтрален |
| MiniMax H3 | $0.08/s | $0.06/s | **−25%** | $0.076 | overflow **дешевле** — маржа↑ |
| PixVerse V6 | ~$0.09–0.12/s | $0.045–0.06/s | **дешевле** | ниже | overflow выгоден |
| Seedance 2.5 | $0.1028/s | ~$0.473/s | **×4.6** | $0.177 | overflow **дорогой** — лимит \(\alpha\)! |
| Kling 2.5 Turbo | $0.07/s | $0.07/s | 0% | $0.07 | нейтрально; HF $0.021 — отдельная карточка |
| Nano Banana Pro | $0.15 | $0.15 | 0% | $0.15 | нейтрально |
| Seedream 5 Pro | $0.045 | $0.0675 | +50% | $0.0495 | лёгкий удар по марже |
| ElevenLabs Music | $0.0083/s | ~$0.01/s | +20% | ~$0.0086 | слабый удар |

**Правило продукта:** для семейств с \(c_b \gg c_p\) (Seedance) — либо выше soft ratio, либо отдельный cap overflow %, либо list сразу от max(\(c_p\),\(c_b\)).

---

## Hold / settle — численный пример

Seedance 2.5, клип 5 с, курс 90 ₽, markup 2.0, фактор 1.30:

| | Preferred (R) | Backup (fal) |
|---|---:|---:|
| COGS | $0.1028×5 = $0.514 | $0.473×5 = $2.365 |
| List RUB (упрощ.) | ceil(0.514×90×1.3×2) ≈ **121 ₽** | ceil(2.365×90×1.3×2) ≈ **554 ₽** |

- UI показывает ~121 ₽.  
- Hold при возможном overflow: **max(121, 554) = 554 ₽** (если backup price известен).  
- Если settle = list 121 ₽, а job ушёл на fal → **убыток ~$1.85** на клип.  
- Поэтому для Seedance критично: либо не overflow без доплаты, либо settle по факту, либо не держать fal в FAILOVER_MAP для этой модели.

---

## KPI для контроля

| Метрика | Как считать | Красная зона |
|---|---|---|
| \(\alpha\) overflow share | `route.overflow` / all jobs | >20% на дорогих backup |
| ΔCOGS | \(\sum(c_{actual}-c_p)\) | растущий тренд week-over-week |
| Queue wait p50/p95 | время queued→running | p95 > 60s при soft=0.7 → поднять concurrency или soft |
| Margin per model | settle − COGS | <15% на family |

---

## Связь с кодом

| Что | Где |
|---|---|
| Soft-overflow | `queue_runtime/load_balancer.py` |
| Hold max(preferred, routed) | `server._generate_quote_kop` |
| Seed COGS | `pricing.py` `PRICING_SEED` |
| Live сравнение каналов | `docs/pricing_channels_matrix.md` |
| Job audit | поле `route` в Redis job + ответ `/api/generate` |

---

## Решения, которые ещё нужно зафиксировать продуктом

1. **Settle:** всегда list preferred vs факт канала.  
2. **Seedance-класс:** выключить soft-overflow / поднять soft / list=max.  
3. **HF-сиблинги:** не в auto-balancer; цена отдельной карточки (часто дешевле — ок как явный выбор).  
4. Публиковать ли в UI «при пике может выполниться через fal».
