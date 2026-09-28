# План CI/CD — ai-shniza Generate (очереди + 3 канала)

Дата: 2026-09-09  
Контекст: Flask + Redis queues + 4 воркера (dispatcher / replicate / fal / omniroute) + OmniRoute Docker.

--------------------------------------------------------------------------------
1. Цель
--------------------------------------------------------------------------------

Автоматически проверять, что:
  - код Generate / routing / health не ломается на PR;
  - воркеры и Redis поднимаются в CI (smoke);
  - деплой на staging не роняет Flask и отдельно поднимает OmniRoute + workers.

--------------------------------------------------------------------------------
2. Периодичность health (зафиксировано в рантайме)
--------------------------------------------------------------------------------

  HEALTH_INTERVAL_SEC = 30
  HEALTH_FAIL_THRESHOLD = 2

Почему 30с: UI обновляет /api/integrations раз в 30с; канал успевает
скрыться с фронта без шторма к Replicate/fal; 2 фейла подряд режут флапы.

--------------------------------------------------------------------------------
3. CI — GitHub Actions (предложение стадий)
--------------------------------------------------------------------------------

Имя workflow: `.github/workflows/ci.yml`

На каждый PR / push в main:

  Stage A — lint
    - ruff (python) на server.py, queue_runtime/, auth.py
    - (опционально) prettier/eslint на generate.js

  Stage B — unit
    - pytest:
        * health: 2 fails → down, 1 ok → healthy
        * dispatcher: unhealthy channel → result channel_unavailable,
          не кладёт в queue:fal/replicate
        * jobs: enqueue → wait timeout shape
    - без сети; redis mock (fakeredis) или redis service container

  Stage C — integration (compose)
    services: redis
    steps:
      - pip install -r requirements.txt
      - python -m queue_runtime.run_all &
      - curl/wait health keys в Redis (probe_all)
      - enqueue omniroute smoke job → ожидать ответ воркера
      - (опционально) mock httpx/responses для replicate/fal probes

  Stage D — artifact
    - сохранить logs/workers.log при fail

На PR к файлам OmniRoute / deploy/omniroute:
  - docker compose config validate
  - НЕ тянуть полный образ на каждый PR (дорого); только на tag/release

--------------------------------------------------------------------------------
4. CD — staging
--------------------------------------------------------------------------------

Сейчас: ручной scp + systemctl ai-shniza.

Целевой runbook (скрипт `deploy/staging.sh`):

  1) backup app dir
  2) sync кода (без .env, без OmniRoute-release bulk если уже на VM)
  3) pip install -r requirements.txt (venv)
  4) docker compose -f deploy/redis/docker-compose.yml up -d
  5) docker compose -f deploy/omniroute/docker-compose.yml up -d
  6) restart systemd:
       - ai-shniza.service          (Flask/gunicorn)
       - ai-shniza-workers.service  (python -m queue_runtime.run_all)
  7) smoke:
       - GET Flask /api/channels/health → replicate/fal/omniroute
       - GET OmniRoute /healthz
       - GET /api/integrations (нет моделей down-канала)
  8) rollback из backup при fail smoke

GitHub Environment `staging` + workflow_dispatch → SSH.

--------------------------------------------------------------------------------
5. systemd units (на VM)
--------------------------------------------------------------------------------

ai-shniza-workers.service:
  WorkingDirectory=~/ai-shniza-web
  EnvironmentFile=~/ai-shniza-web/.env
  Environment=REDIS_URL=redis://127.0.0.1:6379/0
  Environment=OMNIROUTE_BASE_URL=http://127.0.0.1:20128
  Environment=HEALTH_INTERVAL_SEC=30
  ExecStart=/path/to/.venv/bin/python -m queue_runtime.run_all
  Restart=always

Зависимости: After=network.target docker.service ai-shniza-redis

--------------------------------------------------------------------------------
6. Секреты
--------------------------------------------------------------------------------

CI: только mock / fakeredis; живые REPLICATE/FAL/OMNIROUTE ключи —
только в staging Environment secrets / VM .env.

Никогда не логировать токены из health detail.

--------------------------------------------------------------------------------
7. Порядок внедрения
--------------------------------------------------------------------------------

  P0  (сделано локально) Redis + 4 workers + health filter UI
  P1  pytest unit + fakeredis в CI
  P2  systemd unit workers на staging
  P3  deploy/staging.sh + smoke
  P4  GitHub Action workflow_dispatch deploy
  P5  метрики: длина 3 очередей, доля channel_unavailable

--------------------------------------------------------------------------------
8. Критерии «зелёного» релиза
--------------------------------------------------------------------------------

  [ ] CI unit green
  [ ] Redis PONG
  [ ] 4 процесса workers alive
  [ ] /api/channels/health → 3 канала не unknown
  [ ] down-канал отсутствует в /api/integrations
  [ ] OmniRoute /healthz = 200
  [ ] Generate через queue (GENERATE_USE_QUEUE=1) на 1 дешёвой модели

--------------------------------------------------------------------------------
9. Вне скоупа
--------------------------------------------------------------------------------

  - Полный E2E Playwright на каждый commit
  - Нагрузочный тест 100 job (отдельный nightly)
  - Сборка OmniRoute из исходников в CI
