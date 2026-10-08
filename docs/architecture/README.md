# Архитектура Generate (целевая)

Актуальное описание маршрутизации Generate через три канала: **Replicate**, **fal.ai**, **OmniRoute**, плюс чат-ассистент с системной ролью-навигатором.

**English:** [`en/README.md`](./en/README.md)

| Файл | Содержание |
|------|------------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Целевая схема, диспетчер, очереди, интеграции, узкие места, §9 ассистент |
| [assistant-prompt.md](./assistant-prompt.md) | Роль «Навигатор + Экономический Адвокат», куда вшит промпт, поток `/api/chat` |
| [sequence.txt](./sequence.txt) | Sequence-диаграмма Generate + chat |
| [data-flow.txt](./data-flow.txt) | UML / поток данных (текстовая схема) |
| [ci-cd-plan.md](./ci-cd-plan.md) | План CI/CD (очереди, workers, staging) |
| [yandex-object-storage.md](./yandex-object-storage.md) | Object Storage (S3) в Yandex Cloud — опциональный слой медиа |

Каталог моделей + цены: [`../neural-networks-catalog.md`](../neural-networks-catalog.md)  
Полная таблица цен: [`../../models_catalog/CATALOG.md`](../../models_catalog/CATALOG.md)  
SQL каталога: [`../sql/neural_networks.sql`](../sql/neural_networks.sql)

## Статус относительно кода

| Слой | Сейчас в коде | Целевое |
|------|---------------|---------|
| Generate API | `POST /api/generate` → Redis inbound → wait result | + async job_id / poll UI |
| Chat API | `POST /api/chat` → OmniRoute → fallback DeepSeek (Replicate) | то же + метрики |
| Ассистент persona | `CHAT_SYSTEM_PROMPT` на chat + всех LLM `assistants` | + подгрузка цен в контекст |
| Каналы | replicate + fal + omniroute | + RouteMap failover |
| Очереди | Redis: inbound + 3 channel queues | то же + failover RouteMap |
| Health | probe каждые **30с**, threshold **2** → hide from UI | + метрики |
| OmniRoute | systemd / npm на staging `:20128` | catalog sync weekly |
| Workers | 4 процесса: dispatcher + repl/fal/omni | systemd на staging |
