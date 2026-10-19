# Матрица цен: Replicate · fal · Higgsfield · pricing.py

Снято **2026-10-09** с публичных страниц Replicate (`__NEXT_DATA__` / unit pricing cards).  
fal / Higgsfield — из уже зафиксированных llms.txt / API (см. `models_catalog/fal_prices.json` и прошлый аудит).  
**pricing.py** — seed-каталог в репозитории.  
**Контроллер** — эффективные ставки, которыми оперирует продукт при primary + backup (из аудита маршрутов).  
Счётчики маршрутов по каналам: [`controllers_by_integration.md`](./controllers_by_integration.md).

Легенда ячеек:

- **✔** цена подтверждена на источнике
- **—** канала нет / не подключен
- **⚠** расхождение с `pricing.py` или контроллером

Сырые JSON: [`price_audit_replicate.json`](./price_audit_replicate.json), [`price_audit_canon.json`](./price_audit_canon.json).

---

## Видео

| Модель | Replicate (live) | fal | Higgsfield | pricing.py | Контроллер | Заметки |
|---|---|---|---|---|---|---|
| **Gen-4 Turbo** | **$0.05/s** ✔ ([runwayml/gen4-turbo](https://replicate.com/runwayml/gen4-turbo)) | — | — | `$0.05` per_second ✔ | Replicate `$0.05` | Ранее «цена не показана» — на странице есть |
| **Veo 3.1** | **$0.20/s** и **$0.40/s** ✔ ([google/veo-3.1](https://replicate.com/google/veo-3.1)) | `$0.20/s` no audio · `$0.40/s` audio (720p/1080p); 4K `$0.40`/`$0.60` ✔ | Lite 8s: 8 cr silent (~$0.60) · 12 cr audio (~$0.90) | `$0.20` per_second | R `$0.2` · fal `$0.4` · fal `$0.4` | В pricing.py только нижняя ступень `$0.20` |
| **Veo 3.1 Fast** | **$0.10/s** и **$0.15/s** ✔ ([google/veo-3.1-fast](https://replicate.com/google/veo-3.1-fast)) | `$0.10/s` no audio · `$0.15/s` audio; 4K `$0.30`/`$0.35` ✔ | — | `$0.10` per_second | R `$0.1` · fal `$0.15` · fal `$0.15` | |
| **Hailuo 02** | **per video** `$0.10` / `$0.15` / `$0.27` / `$0.45` / `$0.48` ✔ ([minimax/hailuo-02](https://replicate.com/minimax/hailuo-02)) | `$0.045/s` · 6s ≈ `$0.27` ✔ | — | `$0.10` per_item | R `$0.017` · fal `$0.045` ⚠ | Контроллер R `$0.017` не совпадает с Replicate (скорее amortized `/s`); seed — floor `$0.10/vid` |
| **Wan 3.0** | **$0.025 / $0.05 / $0.10 /s** (480/720/1080) ✔ ([alibaba/wan-3](https://replicate.com/alibaba/wan-3)) | `$0.05`/`$0.10`/`$0.20` per s ✔ | — | `$0.10` per_second (720p) | R `$0.1` · fal `$0.1` | |
| **Grok Imagine Video 1.5** | **$0.08/s** ✔ ([xai/grok-imagine-video-1.5](https://replicate.com/xai/grok-imagine-video-1.5)) | 480 `$0.08` · 720 `$0.14` · 1080 `$0.25` /s ✔ | — | `$0.08` per_second ✔ | R `$0.08` · fal `$0.14` | |
| **Seedance 2.5** | **$0.1028/s** (+ другие ступени `$0.2312` / `$0.4304` / `$0.9676`) ✔ ([bytedance/seedance-2.5](https://replicate.com/bytedance/seedance-2.5)) | ~`$0.473/s` 720p ✔ | API `$0.144/s` (30% off, list `$0.2057`) ✔ | `$0.1028` per_second ✔ | R `$0.1028` · fal `$0.473` · HF `$0.144` | HF дешевле fal |
| **Kling 2.5 Turbo Pro** | **$0.07/s** ✔ ([kwaivgi/kling-v2.5-turbo-pro](https://replicate.com/kwaivgi/kling-v2.5-turbo-pro)) | `$0.35` / 5s + `$0.07`/extra s ✔ | API `$0.021/s` (50% off) ✔ | `$0.07` per_second ✔ | R `$0.07` · fal `$0.07` · HF `$0.021` | HF сильно дешевле |
| **Kling 3.0** | — (нет replicate primary в onboard) | `$0.112/s` off · `$0.168` on · `$0.196` voice ✔ | API `$0.042/s` (50% off) ✔ | `$0.042` per_second (`kling-v3-0-hf`) ✔ | HF `$0.042` | Только HF (+ fal Twin в каталоге) |
| **Gemini Omni Flash** | — | ~`$0.125/s` @720p · `$21.875`/1M tokens ✔ | — | fal `$0.125` per_second ✔ | fal `$0.125` | fal-only |
| **P-Video** | **$0.005 / $0.01 / $0.02 / $0.04 /s** (draft/720/1080) ✔ ([prunaai/p-video](https://replicate.com/prunaai/p-video)) | — | — | `$0.005` per_second ✔ | R `$0.005` | |
| **MiniMax H3** | **$0.08/s** (768P) · **$0.13/s** (2K) ✔ ([minimax/h3](https://replicate.com/minimax/h3)) | `$0.05`/`$0.06`/`$0.13`/`$0.16` /s ✔ | — | R `$0.08` · fal `$0.06` ✔ | R `$0.08` · fal `$0.06` | fal дешевле на 768p |
| **PixVerse V6** | **$0.05–$0.23/s** (ступени res/audio) ✔ ([pixverse/pixverse-v6](https://replicate.com/pixverse/pixverse-v6)); типичный 720p **`$0.09`**, с audio **`$0.12`** | 720p `$0.045` / `$0.060` with audio ✔ | — | `$0.05` per_second ⚠ | R `$0.12` · fal `$0.06` | Seed занижен vs типичного 720p; контроллер ближе к `$0.12` |

---

## Картинки

| Модель | Replicate (live) | fal | Higgsfield | pricing.py | Контроллер | Заметки |
|---|---|---|---|---|---|---|
| **Nano Banana Pro** | **$0.15/img** · **$0.30** (4K) · также `$0.035` card ✔ ([google/nano-banana-pro](https://replicate.com/google/nano-banana-pro)) | `$0.15` · 4K 2× ✔ | UI only · API `model_disabled`; marketing ~2 cr/img | R `$0.15` · fal `$0.15` ✔ | R `$0.15` · fal `$0.15` | HF канал не подключаем |
| **Nano Banana 2** | **$0.067 / $0.101 / $0.151** (1K/2K/4K) ✔ ([google/nano-banana-2](https://replicate.com/google/nano-banana-2)) | `$0.08/img` ✔ | — | `$0.067` per_item ✔ | R `$0.067` · fal `$0.08` | |
| **Ideogram v3 Turbo** | **$0.03/img** ✔ | TURBO `$0.03` · BAL `$0.06` · QUAL `$0.09` ✔ | — | `$0.03` ✔ | R `$0.03` · fal `$0.03` | |
| **GPT Image 2** | **$0.012 / $0.047 / $0.128** (low/med/high) ✔ | token billing на странице fal | — | `$0.012` (low) ✔ | R `$0.012` | |
| **GPT Image 2.5 Flare** | **$0.012 / $0.047 / $0.128 / $0.25 / $0.50** ✔ | token billing | — | `$0.012` ✔ | R `$0.012` | |
| **GPT Image 2.5 Sunburst** | то же ✔ | token billing | — | `$0.012` ✔ | R `$0.012` | |
| **Soul Cinema** | — | — | API **from `$0.0032`/img** ✔ | `$0.0032` per_item ✔ (обновлено) | HF `$0.0032` | Было `$0.08` в seed — выровняли под API |
| **Seedream 5.0 Pro** | **$0.0225 / $0.045 / $0.09** ✔ ([bytedance/seedream-5-pro](https://replicate.com/bytedance/seedream-5-pro)) | ≤1536² `$0.0675` · ≤2048² `$0.135` ✔ | — | R `$0.045` · fal `$0.0675` ✔ | R `$0.045` · fal `$0.0675` | Replicate дешевле |

---

## Музыка и звук

| Модель | Replicate (live) | fal | Higgsfield | pricing.py | Контроллер | Заметки |
|---|---|---|---|---|---|---|
| **ElevenLabs Music** | **`$8.3` / 1000 s** = **`$0.0083/s`** ✔ ([elevenlabs/music](https://replicate.com/elevenlabs/music)) | `$0.6`/min rounded ≈ `$0.01/s` ✔ | — | `$0.0083` per_second ✔ | R `$0.25` · fal `$0.3` ⚠ | Контроллер выглядит как RUB/другие единицы — сверить |
| **Stable Audio 2.5** | **$0.20 / file** ✔ | `$0.2`/audio ✔ | — | `$0.20` per_item ✔ | R `$0.2` · fal `$0.2` | |
| **ACE-Step** | hardware **`$0.000975/s`**, p50 **`~$0.018`/run** ✔ ([lucataco/ace-step](https://replicate.com/lucataco/ace-step)) | `$0.0002/s` audio ✔ | — | `$0.022` per_run_approx ⚠ | R `$0.018` · fal `$0.006` | Seed чуть выше p50 |

---

## Текст

| Модель | Replicate (live) | fal | Higgsfield | pricing.py | Заметки |
|---|---|---|---|---|---|
| **DeepSeek V3.1** | **`$0.672` / `$2.016` per 1M in/out** ✔ | — | — | `$0.672` / `$2.016` ✔ | |
| **DeepSeek V3** | **`$1.45` / `$1.45` per 1M** ✔ | — | — | `$1.45` / `$1.45` ✔ | |
| **Claude Sonnet 5** | **`$2` / `$10` per 1M** ✔ | — | — | `$2` / `$10` ✔ | |
| **Claude Haiku 4.5** | **`$1` / `$5` per 1M** ✔ | — | — | `$1` / `$5` ✔ | |
| **Claude Opus 4.7** | **`$5` / `$25` per 1M** ✔ | — | — | `$5` / `$25` ✔ | |
| **Gemini 3.5 Flash** | **`$1.50` / `$9` per 1M** ✔ | — | — | `$1.5` / `$9` ✔ | |
| **Gemini 3.1 Pro** | **`$2` / `$12`** (≤200k) · **`$4` / `$18`** (>200k) ✔ | — | — | только `$2`/`$12` | Вторая ступень не в seed |
| **GPT-5.4** | **`$2.50` / `$15` per 1M** ✔ | — | — | `$2.5` / `$15` ✔ | |
| **GPT-5.6 Sol** | **`$2` / `$10` per 1M** ✔ ([openai/gpt-5.6-sol](https://replicate.com/openai/gpt-5.6-sol)) | — | — | `$2` / `$10` ✔ | UI раньше показывал `$2.5`/`$15` — live другое |
| **Авто · чат** | — | — | — | OmniRoute free / gateway | |

---

## Сводка расхождений (что править в коде)

| Приоритет | Модель | Проблема | Статус |
|---|---|---|---|
| P0 | Soul Cinema | seed `$0.08` → `$0.0032` | ✔ сделано в `pricing.py` + `app.html` cost≈1 |
| P1 | Gemini Omni Flash / GPT-5.6 Sol / DeepSeek V3 | не было seed | ✔ добавлено в `pricing.py` |
| P1 | PixVerse V6 | seed `$0.05`, типичный 720p `$0.09–0.12` | открыто — поднять до `$0.09`/`$0.12` |
| P2 | Hailuo 02 | контроллер R `$0.017/s` vs seed `$0.10/vid` | открыто — унифицировать unit |
| P2 | ACE-Step | seed `$0.022` vs p50 `$0.018` | открыто |
| P3 | Gemini 3.1 Pro | нет ступени >200k | опционально |
| P3 | ElevenLabs Music | контроллер `$0.25`/`$0.3` vs `$0.0083/s` | проверить единицы (₽?) |

---

## Метод

```bash
# пересъём Replicate
.venv/bin/python - <<'PY'
# см. историю: parse "price":"$X","title":"per …" с https://replicate.com/<owner>/<name>
PY
```

fal: `models_catalog/fal_prices.json` + llms.txt.  
Higgsfield: probe API / pricing page (Soul Cinema, Seedance/Kling discounts).
