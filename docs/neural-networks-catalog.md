# Каталог нейросетей (live)

Актуальный список = модели из `INTEGRATED_MODELS` (`server.py`), которые отдаёт `/api/integrations`.

**Цены:** свежая таблица с Replicate + fal — [`models_catalog/CATALOG.md`](../models_catalog/CATALOG.md)  
(также `catalog.csv` / `catalog.json`). Снято: **2026-09-09 16:53 UTC**.

**Архитектура каналов + ассистент:** [`architecture/README.md`](./architecture/README.md)  
**Системный промпт навигатора:** [`architecture/assistant-prompt.md`](./architecture/assistant-prompt.md)

Провайдеры: `replicate` и `fal` живут рядом. Одинаковые capability **не заменяем** — дублируем (`…-fal`). OmniRoute — отдельный канал для chat/free-tier.

## Ассистент (продуктовая роль)

Независимо от бэкенд-модели (OmniRoute / DeepSeek fallback / другие LLM из группы `assistants`) на агента накладывается роль **«Заботливый Навигатор + Экономический Адвокат»**:

- рекомендует **только** модели из live-каталога (`INTEGRATED_MODELS` + цены);
- отвечает **по абзацам**;
- для каждой рекомендации: **исходники · ценовой диапазон · качество**;
- готовый улучшенный промпт + параметры под задачу;
- этические границы + линия помощи при кризисе.

Код: `CHAT_SYSTEM_PROMPT`, `_build_chat_system_prompt`, `_with_assistant_persona` в `server.py`.  
Подробнее: [`architecture/assistant-prompt.md`](./architecture/assistant-prompt.md).  
Чат UI: `POST /api/chat` → OmniRoute → fallback Replicate DeepSeek.

## Сводка по каналам

| Канал | Кол-во live | Биллинг |
|---|---|---|
| replicate | 39 | страница модели на replicate.com (token / image / second) |
| fal | 19 | fal.ai model page / llms.txt (обычно output unit) |
| omniroute | 3 | free-tier pool / router |

## Replicate vs fal (где есть пересечение)

| Family | Replicate | fal |
|---|---|---|
| Wan 3.0 | **$0.025/s** | 480p $0.05/s · 720p $0.10/s · 1080p $0.20/s |
| Seedance 2.0 | **$0.10/s** | 720p $0.3034/s · 1080p $0.682/s |

На бумаге Replicate дешевле по этим двум линейкам; у fal чаще явные тиры по разрешению и native audio. Точный TCO зависит от длительности, resolution и extras.

## Полная таблица

См. [`../models_catalog/CATALOG.md`](../models_catalog/CATALOG.md).

## Обновление цен

```bash
# при необходимости обновить fal_prices.json (или дать скрипту скачать llms.txt)
python3 models_catalog/build_priced_catalog.py
```

## SQL (legacy seed)

DDL + старый seed: [`sql/neural_networks.sql`](./sql/neural_networks.sql) — runtime сейчас опирается на `INTEGRATED_MODELS`, не на этот seed.
