# Generate: диспетчер, четыре очереди, четыре канала

Дата актуализации: 2026-10-10  
Статус: **целевая архитектура** (soft-overflow + async queue в коде; см. README).

--------------------------------------------------------------------------------
1. Картина целиком
--------------------------------------------------------------------------------

  Браузер (Generate)
       │
       │  POST /api/generate
       │  GET  /api/generate/jobs/:id
       ▼
  ┌─────────────────────────────────────────┐
  │ Flask API                               │
  │  · принять запрос                       │
  │  · load_balancer: preferred → soft R→fal│
  │  · enqueue job (provider уже выбран)    │
  └───────────────────┬─────────────────────┘
                      │
                      ▼
  ┌─────────────────────────────────────────┐
  │ queue:inbound                           │
  │ dispatcher → queue:{provider}           │
  │ (только маршрутизация по полю provider) │
  └───────────────────┬─────────────────────┘
                      │
        ┌─────────────┼─────────────┬─────────────┐
        ▼             ▼             ▼             ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │replicate│   │   fal   │   │omniroute│   │higgsfield│
   │ queue   │   │  queue  │   │  queue  │   │  queue  │
   └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘
        ▼             ▼             ▼             ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ worker  │   │ worker  │   │ worker  │   │ worker  │
   └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘
        ▼             ▼             ▼             ▼
   Replicate API  fal.run API   OmniRoute    Higgsfield API
                                                (HF_KEY)

Чтение сверху вниз: UI → Flask (выбор канала) → inbound → один из 4 каналов → upstream.

| Канал | Очередь | Воркер | Upstream | Как попадаем |
|---|---|---|---|---|
| **replicate** | `queue:replicate` | worker-replicate | api.replicate.com | UI-модель с `provider=replicate` |
| **fal** | `queue:fal` | worker-fal | fal.run | UI-модель fal **или** soft-overflow / failover из R |
| **omniroute** | `queue:omniroute` | worker-omniroute | :20128 | чат / auto |
| **higgsfield** | `queue:higgsfield` | worker-higgsfield | Higgsfield API | только явная HF-карточка (`*-hf`, Soul Cinema) |

Higgsfield — полноценный 4-й канал. В `FAILOVER_MAP` его нет: не auto-backup с Replicate.

--------------------------------------------------------------------------------
2. Логика диспетчера (failover)
--------------------------------------------------------------------------------

**Сейчас (без LogicalModel в БД):** пары Replicate → fal заданы в `FAILOVER_MAP`
и `INTEGRATED_MODELS` (`listed: false`, `backup_for`). Выбор резерва:
`_failover_target(primary_id, has_image)` → id fal-копии. Полный список и
исключения (p-video, gen4-turbo) — `docs/fal_backups_report.md`.

**Soft-overflow (B2 load):** `queue_runtime/load_balancer.py` — preferred грузим
до soft-cap (~70% concurrency), дальше новые job → fal backup; при down
preferred — сразу backup. Док: `docs/traffic_load_balancer.md`, деньги:
`docs/financial_model_channel_distribution.md`.

Вход (целевая модель): LogicalModel (то, что видит пользователь) + payload (prompt, media).

Шаги:

  1) Найти RouteMap: LogicalModel → список ChannelBinding
       пример: wan-3-0 → [ replicate:… , fal:…-fal , omniroute:… ]

  2) Прочитать ChannelHealth:
       replicate / fal / omniroute / higgsfield ∈ { healthy, degraded, down }

  3) Выбрать канал по политике:
       - preferred = модель UI (обычно replicate); soft-overflow → fal backup
       - если preferred down → fal из FAILOVER_MAP (если есть)
       - Higgsfield только если пользователь выбрал HF-карточку (не auto)
       - если ни один подходящий канал не healthy → job = failed (no_channel)

  4) Положить job в очередь выбранного канала
       queue:replicate | queue:fal | queue:omniroute | queue:higgsfield

  5) При ошибке воркера (5xx / timeout / auth):
       увеличить error counter канала
       порог → канал = degraded/down на cooldown
       опционально: requeue job в запасной канал (если есть binding)

Почему не три независимых диспетчера:
  failover «Replicate мёртв → больше в fal» требует ОДНОЙ точки,
  которая видит health всех каналов и карту дублей.
  Три изолированных диспетчера не смогут перекидывать нагрузку.

--------------------------------------------------------------------------------
3. Четыре очереди и четыре воркера
--------------------------------------------------------------------------------

Очередь              Воркер              Upstream
-------------------  ------------------  -------------------------
queue:replicate      worker-replicate    api.replicate.com
queue:fal            worker-fal          queue.fal.run / fal.run
queue:omniroute      worker-omniroute    OmniRoute :20128 /v1/...
queue:higgsfield     worker-higgsfield   Higgsfield API (HF_KEY)

Правила:
  - воркер читает ТОЛЬКО свою очередь;
  - каналы не блокируют друг друга;
  - масштабирование: +N процессов на горячий канал;
  - concurrency defaults: R=10 · fal=6 · OR=3 · HF=4 (`WORKER_CONCURRENCY_*`);
  - результат → Job.status = succeeded|failed + urls/text в Postgres
    (байты медиа опционально → Object Storage, см. yandex-object-storage.md).

--------------------------------------------------------------------------------
3b. Higgsfield-канал
--------------------------------------------------------------------------------

Роль: четвёртый медиа-канал рядом с Replicate/fal, **не** запись в FAILOVER_MAP.

Модели в студии: `soul-cinema`, `seedance-2-5-hf`, `kling-v2-5-turbo-pro-hf`,
`kling-v3-0-hf`, `veo-3-1-hf` (+ alias `soul-cinema-hf`). Пользователь выбирает
их явно; soft-overflow балансер R→fal на HF не перекидывает.

Flask → worker-higgsfield → Higgsfield queue/API → URL результата.

--------------------------------------------------------------------------------
4. OmniRoute-канал
--------------------------------------------------------------------------------

Роль: канал чата / auto рядом с медиа-каналами, не замена Replicate/fal/HF.

Размещение: отдельный сервис (в репо: OmniRoute-release-v3.8.51/),
порт по умолчанию 20128, свой .env / API key.

Flask → worker-omniroute → HTTP OpenAI-compatible (и др.) → OmniRoute
→ дальше маршрутизация внутри OmniRoute на подключённые провайдеры.

Дубликаты с Replicate/fal РАЗРЕШЕНЫ (отдельные binding / id),
как уже принято для пар replicate ↔ …-fal.

Синхронизация каталога OmniRoute (GET /v1/models): периодический
снимок (цель — weekly), merge в integrations snapshot без удаления
существующих replicate/fal записей.

UI-лейблы источника пока не обязательны (добавятся отдельно).

--------------------------------------------------------------------------------
5. Текущие интеграции (рантайм на 2026-09-09)
--------------------------------------------------------------------------------

Источник правды Generate: INTEGRATED_MODELS в server.py
(каталог Postgres neural_networks — витрина/метаданные).
Цены live-моделей: models_catalog/CATALOG.md (скрипт build_priced_catalog.py).

Канал        Число моделей (ориентир)   Примечание
----------   ------------------------   --------------------------------
replicate    ~52                        LLM, image, video, audio, music
fal          ~44                        backup `-fal` + solo (Omni Flash), FAL_KEY
higgsfield   6                          Soul Cinema + HF-сиблинги, HF_KEY
omniroute    3                          assistant + auto/chat + auto/coding:free
ИТОГО        ~105 INTEGRATED_MODELS     chat + generate (см. controllers_by_integration)

Паттерн дублей уже есть: одна задача — две записи
(например wan-3-0 на replicate и wan-3-0-*-fal на fal).
Для диспетчера это нужно свернуть в LogicalModel + RouteMap.

Как сейчас (as-is):

  Generate (медиа/LLM):
    Browser ──POST /api/generate──► Flask ──(опц. Redis queue)──► Replicate | fal | Omni
  Chat (навигатор):
    Browser ──POST /api/chat──► Flask ──► OmniRoute ──(fail)──► Replicate DeepSeek
    См. §9 и assistant-prompt.md.

--------------------------------------------------------------------------------
6. Состояния Job
--------------------------------------------------------------------------------

  queued → dispatched → running → succeeded
                              └→ failed
                              └→ requeued (failover на другой канал)

Поля минимум: id, logical_model, chosen_channel, upstream_ref,
status, error, result_urls|reply, created_at, updated_at.

--------------------------------------------------------------------------------
7. Узкие места архитектуры
--------------------------------------------------------------------------------

A. Синхронный Flask (as-is)
   Долгий HTTP держит gunicorn-воркер. При всплеске (десятки Generate)
   сайт и API встают в очередь ОС / получают 504. Лечится job+poll.

B. Диспетчер без карты дублей
   Failover «в fal» невозможен, если нет второго binding.
   Узкое место продукта: покрытие пар replicate↔fal↔omni.

C. Ложный health
   Один таймаут ≠ down. Нужны порог ошибок + cooldown, иначе
   флаппинг каналов и хаотичный failover.

D. Одна VM на всё
   Flask + 3 воркера + OmniRoute (Node) делят CPU/диск/сеть.
   При пике медиа + sync OmniRoute возможен iowait.
   Митигация: лимиты systemd/cgroup, sync ночью, позже — вынос Omni.

E. Очередь внутри канала
   Один worker-replicate при 33 job = последовательная обработка.
   Диспетчер балансирует МЕЖДУ каналами; внутри канала — concurrency
   воркера (1..N).

F. Нет идемпотентности / дедупа
   Повторный клик = второй job. Нужен client request_id или UI lock.

G. Секреты и границы
   REPLICATE_API_TOKEN, FAL_KEY, OMNIROUTE_API_KEY — разные контуры.
   Утечка .env OmniRoute / коммит secrets — операционный риск.

H. Медиа в теле JSON (data URL)
   Крупные image/audio/video в POST раздувают память API.
   Узкое место до S3/presign upload.

I. Weekly sync OmniRoute
   Большой /v1/models может тормозить импорт; делать offline/job,
   не в request path Generate.

J. Наблюдаемость
   Без метрик длины трёх очередей и health каналов failover слепой.

--------------------------------------------------------------------------------
8. Что не входит в этот документ
--------------------------------------------------------------------------------

- Детали RBAC / email confirm (отдельное продуктовое решение).
- Полная схема B2b webhook→S3 как единственный путь — устарела как
  «только Replicate»; S3 остаётся опциональным sink медиа
  (yandex-object-storage.md).
- Внутренняя архитектура самого OmniRoute (см. их README в релизе).
- Полный текст системного промпта ассистента — в assistant-prompt.md
  и константе CHAT_SYSTEM_PROMPT (server.py).

--------------------------------------------------------------------------------
9. Ассистент-навигатор (чат + persona)
--------------------------------------------------------------------------------

Продуктовая роль: «Заботливый Навигатор + Экономический Адвокат».
Документ: assistant-prompt.md. Код: CHAT_SYSTEM_PROMPT, _with_assistant_persona.

Задачи агента:
  - услышать задачу / формат / бюджет / тон;
  - предложить 2–3 модели с честным цена/качество;
  - выдать улучшенный промпт и параметры запуска;
  - этический отказ от опасных тем + линия помощи при кризисе.

Маршрутизация чата (отдельно от media-generate):

                    ┌─────────────┐
                    │  Generate   │
                    │  UI chat    │
                    └──────┬──────┘
                           │ POST /api/chat
                           ▼
                    ┌─────────────┐
                    │ Flask       │
                    │ + system    │
                    │   prompt    │
                    └──────┬──────┘
              ┌────────────┴────────────┐
              ▼                         ▼
        OmniRoute                  Replicate
        auto/coding:free           DeepSeek
        (primary)                  (fallback)

Та же persona накладывается на любой LLM из group=assistants
через /api/generate (не только на кнопку «Ассистент»).
Медиа-модели (image/video/audio) persona не получают.
