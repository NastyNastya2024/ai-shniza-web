# Контроллеры по интеграциям

Снято из `server.py`: `INTEGRATED_MODELS` · `FAILOVER_MAP` · `STUDIO_ONBOARD_IDS`  
Дата: **2026-10-09**.

**Контроллер** = одна запись маршрута (канал + endpoint), через которую продукт может отправить генерацию.  
У одной студийной модели их может быть несколько: primary + fal backup (t/i) + отдельная HF-карточка.

Каналы: **R** = Replicate · **fal** · **HF** = Higgsfield · **OR** = OmniRoute.

---

## Сводка

| | Кол-во |
|---|---:|
| Записей в `INTEGRATED_MODELS` | **105** |
| Студийных продуктов (логически, HF-сиблинги склеены) | **35** |
| Слотов контроллеров у студии | **70** |
| Моделей с `FAILOVER_MAP` (R→fal) | **19** |
| fal-endpoint’ов в failover | **31** |
| Записей с `backup_for` | **32** |

### По каналам (все INTEGRATED)

| Канал | Записей |
|---|---:|
| Replicate | 52 |
| fal | 44 |
| Higgsfield | 6 |
| OmniRoute | 3 |

### По каналам (только студийные контроллеры)

| Канал | Слотов |
|---|---:|
| Replicate | 30 |
| fal | 32 |
| Higgsfield | 6 |
| OmniRoute | 2 |

### Гистограмма: сколько контроллеров у продукта

| Контроллеров | Продуктов | Смысл |
|---:|---:|---|
| **4** | 3 | R + fal×2 + HF-карточка |
| **3** | 9 | R + fal t + fal i |
| **2** | 8 | R+fal · или HF+alias |
| **1** | 15 | один канал |

---

## Нагрузка каналов (запросы / время)

Два слоя: **upstream API** (лимиты провайдера) и **наши воркеры** (`queue_runtime`, env `WORKER_CONCURRENCY_*`).  
Фактический throughput ≈ `min(upstream, worker_concurrency) / среднее_время_job`.  
Видео 10–60+ с → узкое место почти всегда **concurrency**, не HTTP RPS.

### Upstream (публичные лимиты аккаунта)

| Канал | Что режет нагрузку | Типичный потолок | При перегрузе | Источник |
|---|---|---|---|---|
| **Replicate** | Rate на *создание* predictions + (отдельно) слоты GPU | **600 create/min** (~10/s); прочие API **3000/min**. Без payment method: **1/s · max 6/min**. Concurrent predictions — **account-specific** (часто ~десятки, не публичный фикс) | HTTP **429** | [docs/rate-limits](https://replicate.com/docs/topics/predictions/rate-limits) |
| **fal** | Global **concurrency** (`IN_PROGRESS`), не RPM | Старт **2** concurrent → self-serve до **40** (по сумме paid invoices за 4 нед.); выше — sales. Очередь: submit можно много, в работе — по лимиту. Per-endpoint caps на hot-моделях возможны | queue ждёт / **429** `concurrent_requests_limit` на direct `run` | [Concurrency Limits](https://fal.ai/docs/documentation/model-apis/concurrency-limits) |
| **Higgsfield** | Concurrent generations (queued+processing) | Self-serve по депозиту (28д): **2** (default) → **10** (≥$25) → **20** (≥$100) → **40** (≥$1k). Маркетинг: ключ может стартовать с **20**. + per-model caps | HTTP **400** «Maximum number of concurrent requests (N)» | [open.higgsfield.ai/pricing](https://open.higgsfield.ai/pricing) · [docs rate-limits](https://docs.higgsfield.ai/docs/concepts/rate-limits) |
| **OmniRoute** | Локальный шлюз → лимиты *его* upstream (Replicate LLM и др.) | Нет отдельного публичного «N req/s» на OR; упирается в провайдера за combo + наш воркер | 429/cooldown у upstream | наш `worker-omniroute` + Resilience OR |

### Наши воркеры (дефолты продукта)

Из `queue_runtime/__init__.py` → `_DEFAULT_CONCURRENCY` (override через env):

| Канал | Default concurrent jobs | Env |
|---|---:|---|
| Replicate | **10** | `WORKER_CONCURRENCY_REPLICATE` |
| fal | **6** | `WORKER_CONCURRENCY_FAL` |
| Higgsfield | **4** | `WORKER_CONCURRENCY_HIGGSFIELD` |
| OmniRoute | **3** | `WORKER_CONCURRENCY_OMNIROUTE` |

Это потолок **параллельных job в нашем Redis-воркере**, не лимит провайдера. Имеет смысл держать worker ≤ upstream concurrent, иначе лишние 429/400 и ретраи.

### Ориентир sustained (оценка, не SLA)

Формула: `jobs/min ≈ 60 × concurrent / T_sec`, где `T` — среднее время генерации.

| Канал | Concurrent (наш default) | Картинка T≈8 с | Видео T≈40 с | Create RPS (если T мал) |
|---|---:|---:|---:|---|
| Replicate | 10 | ~75 job/min | ~15 job/min | API позволяет до ~10 create/s, но GPU/очередь модели обычно ниже |
| fal | 6 (до 40 на аккаунте) | ~45 / ~300 | ~9 / ~60 | RPM почти не лимит; лимит — слоты |
| Higgsfield | 4 (до 40 на аккаунте) | ~30 / ~300 | ~6 / ~60 | Нет RPM; при лимите — отказ 400 |
| OmniRoute | 3 | зависит от LLM upstream | — | чат: обычно десятки RPM у upstream |

**Практический вывод для студии:** при dual R+fal failover пиковая ёмкость ≈ сумма concurrent двух каналов (на разные endpoint’ы), пока оба healthy. HF-карточки (`*-hf`) — **отдельный** пул concurrent HF, не failover из R.

### Что проверить на живом аккаунте

1. Replicate dashboard / billing — payment method (иначе 6/min), auto-reload >$20.  
2. fal → Concurrency page — текущий tier (2…40).  
3. Higgsfield Console — concurrent N и model-specific.  
4. Наши метрики длины `queue:*` vs `WORKER_CONCURRENCY_*`.

---

## Видео

| Модель | N | Контроллеры |
|---|---:|---|
| Kling 2.5 Turbo Pro | **4** | R · fal t2v · fal i2v · HF |
| Seedance 2.5 | **4** | R · fal t2v · fal ref2v · HF |
| Veo 3.1 | **4** | R · fal t2v · fal i2v · HF |
| Hailuo 02 | **3** | R · fal t2v · fal i2v |
| MiniMax H3 | **3** | R · fal t2v · fal i2v |
| PixVerse V6 | **3** | R · fal t2v · fal i2v |
| Veo 3.1 Fast | **3** | R · fal t2v · fal i2v |
| Wan 3.0 | **3** | R · fal t2v · fal i2v |
| Grok Imagine Video 1.5 | **2** | R · fal i2v |
| Gemini Omni Flash | **1** | fal |
| Gen-4 Turbo | **1** | R |
| Kling 3.0 | **1** | HF |
| P-Video | **1** | R |

---

## Картинки

| Модель | N | Контроллеры |
|---|---:|---|
| GPT Image 2 | **3** | R · fal t2i · fal edit |
| Nano Banana 2 | **3** | R · fal · fal edit |
| Nano Banana Pro | **3** | R · fal · fal edit |
| Seedream 5.0 Pro | **3** | R · fal t2i · fal edit |
| GPT Image 2.5 Flare | **2** | R · fal |
| GPT Image 2.5 Sunburst | **2** | R · fal |
| Ideogram v3 Turbo | **2** | R · fal |
| Soul Cinema | **2** | HF · HF alias (`soul-cinema-hf`) |

---

## Музыка и звук

| Модель | N | Контроллеры |
|---|---:|---|
| ACE-Step | **2** | R · fal |
| ElevenLabs Music | **2** | R · fal |
| Stable Audio 2.5 | **2** | R · fal |

---

## Текст / чат

| Модель | N | Контроллеры |
|---|---:|---|
| DeepSeek V3 / V3.1 | **1** | R |
| Claude Haiku 4.5 / Sonnet 5 / Opus 4.7 | **1** | R |
| Gemini 3.5 Flash / 3.1 Pro | **1** | R |
| GPT-5.4 / GPT-5.6 Sol | **1** | R |
| Авто · чат / Авто · free | **1** | OR |

---

## Как устроен подсчёт

1. **Primary** — запись в `STUDIO_ONBOARD_IDS` без `backup_for`.
2. **fal backup** — `backup_for=<primary>` и/или `FAILOVER_MAP[primary][t|i]`.
3. **HF-сиблинг** — отдельная студийная карточка (`*-hf`), не failover: `seedance-2-5-hf`, `kling-v2-5-turbo-pro-hf`, `veo-3-1-hf`. В таблице выше склеены с основной моделью; в UI это отдельные пункты сайдбара.
4. Alias `soul-cinema-hf` — второй HF-контроллер той же модели (`listed: False`).

Цены по каналам: [`pricing_channels_matrix.md`](./pricing_channels_matrix.md).  
Балансировка трафика (soft-overflow): [`traffic_load_balancer.md`](./traffic_load_balancer.md).  
Финмодель при распределении: [`financial_model_channel_distribution.md`](./financial_model_channel_distribution.md).

### Пересъём

```bash
.venv/bin/python - <<'PY'
from server import INTEGRATED_MODELS, FAILOVER_MAP, STUDIO_ONBOARD_IDS
from collections import Counter
print(len(INTEGRATED_MODELS), Counter(s["provider"] for s in INTEGRATED_MODELS.values()))
print("failover", len(FAILOVER_MAP), sum(len(v) for v in FAILOVER_MAP.values()))
print("onboard", len(STUDIO_ONBOARD_IDS))
PY
```
