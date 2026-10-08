# CI/CD plan — ai-shniza Generate (queues + 3 channels)

Date: 2026-09-09  
Context: Flask + Redis queues + 4 workers (dispatcher / replicate / fal / omniroute) + OmniRoute Docker.

--------------------------------------------------------------------------------
1. Goal
--------------------------------------------------------------------------------

Automatically verify that:
  - Generate / routing / health code does not break on PR;
  - workers and Redis come up in CI (smoke);
  - staging deploy does not take down Flask and separately starts OmniRoute + workers.

--------------------------------------------------------------------------------
2. Health cadence (fixed in runtime)
--------------------------------------------------------------------------------

  HEALTH_INTERVAL_SEC = 30
  HEALTH_FAIL_THRESHOLD = 2

Why 30s: UI refreshes /api/integrations every 30s; a channel can
disappear from the front without storming Replicate/fal; 2 consecutive
fails cut flapping.

--------------------------------------------------------------------------------
3. CI — GitHub Actions (proposed stages)
--------------------------------------------------------------------------------

Workflow name: `.github/workflows/ci.yml`

On every PR / push to main:

  Stage A — lint
    - ruff (python) on server.py, queue_runtime/, auth.py
    - (optional) prettier/eslint on generate.js

  Stage B — unit
    - pytest:
        * health: 2 fails → down, 1 ok → healthy
        * dispatcher: unhealthy channel → result channel_unavailable,
          does not enqueue to queue:fal/replicate
        * jobs: enqueue → wait timeout shape
    - no network; redis mock (fakeredis) or redis service container

  Stage C — integration (compose)
    services: redis
    steps:
      - pip install -r requirements.txt
      - python -m queue_runtime.run_all &
      - curl/wait health keys in Redis (probe_all)
      - enqueue omniroute smoke job → wait for worker response
      - (optional) mock httpx/responses for replicate/fal probes

  Stage D — artifact
    - save logs/workers.log on fail

On PRs touching OmniRoute / deploy/omniroute:
  - docker compose config validate
  - do NOT pull the full image on every PR (expensive); only on tag/release

--------------------------------------------------------------------------------
4. CD — staging
--------------------------------------------------------------------------------

Today: manual scp + systemctl ai-shniza.

Target runbook (script `deploy/staging.sh`):

  1) backup app dir
  2) sync code (no .env, no OmniRoute-release bulk if already on the VM)
  3) pip install -r requirements.txt (venv)
  4) docker compose -f deploy/redis/docker-compose.yml up -d
  5) docker compose -f deploy/omniroute/docker-compose.yml up -d
  6) restart systemd:
       - ai-shniza.service          (Flask/gunicorn)
       - ai-shniza-workers.service  (python -m queue_runtime.run_all)
  7) smoke:
       - GET Flask /api/channels/health → replicate/fal/omniroute
       - GET OmniRoute /healthz
       - GET /api/integrations (no models from a down channel)
  8) rollback from backup on smoke fail

GitHub Environment `staging` + workflow_dispatch → SSH.

--------------------------------------------------------------------------------
5. systemd units (on the VM)
--------------------------------------------------------------------------------

ai-shniza-workers.service:
  WorkingDirectory=~/ai-shniza-web
  EnvironmentFile=~/ai-shniza-web/.env
  Environment=REDIS_URL=redis://127.0.0.1:6379/0
  Environment=OMNIROUTE_BASE_URL=http://127.0.0.1:20128
  Environment=HEALTH_INTERVAL_SEC=30
  ExecStart=/path/to/.venv/bin/python -m queue_runtime.run_all
  Restart=always

Dependencies: After=network.target docker.service ai-shniza-redis

--------------------------------------------------------------------------------
6. Secrets
--------------------------------------------------------------------------------

CI: mock / fakeredis only; live REPLICATE/FAL/OMNIROUTE keys —
only in staging Environment secrets / VM .env.

Never log tokens from health detail.

--------------------------------------------------------------------------------
7. Rollout order
--------------------------------------------------------------------------------

  P0  (done locally) Redis + 4 workers + health filter UI
  P1  pytest unit + fakeredis in CI
  P2  systemd unit workers on staging
  P3  deploy/staging.sh + smoke
  P4  GitHub Action workflow_dispatch deploy
  P5  metrics: depth of 3 queues, share of channel_unavailable

--------------------------------------------------------------------------------
8. “Green” release criteria
--------------------------------------------------------------------------------

  [ ] CI unit green
  [ ] Redis PONG
  [ ] 4 worker processes alive
  [ ] /api/channels/health → 3 channels not unknown
  [ ] down channel absent from /api/integrations
  [ ] OmniRoute /healthz = 200
  [ ] Generate via queue (GENERATE_USE_QUEUE=1) on 1 cheap model

--------------------------------------------------------------------------------
9. Out of scope
--------------------------------------------------------------------------------

  - Full E2E Playwright on every commit
  - Load test of 100 jobs (separate nightly)
  - Building OmniRoute from source in CI
