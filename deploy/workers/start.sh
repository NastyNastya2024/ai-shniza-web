#!/usr/bin/env bash
# Start Redis (if needed) + 4 Generate workers as separate processes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! docker ps --format '{{.Names}}' | grep -qx 'ai-shniza-redis'; then
  echo "[workers] starting Redis…"
  docker compose -f deploy/redis/docker-compose.yml up -d
fi

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export OMNIROUTE_BASE_URL="${OMNIROUTE_BASE_URL:-http://127.0.0.1:20128}"
export HEALTH_INTERVAL_SEC="${HEALTH_INTERVAL_SEC:-30}"
PY="${PYTHON:-python}"
if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
fi

mkdir -p logs
# Stop previous workers of this project
if [[ -f logs/workers.pids ]]; then
  while read -r pid; do
    kill "$pid" 2>/dev/null || true
  done < logs/workers.pids
  rm -f logs/workers.pids
fi
pkill -f 'python -m queue_runtime.dispatcher' 2>/dev/null || true
pkill -f 'python -m queue_runtime.channel_worker' 2>/dev/null || true
pkill -f 'python -m queue_runtime.run_all' 2>/dev/null || true
sleep 1

nohup "$PY" -m queue_runtime.dispatcher > logs/dispatcher.log 2>&1 & echo $! >> logs/workers.pids
nohup "$PY" -m queue_runtime.channel_worker replicate > logs/replicate.log 2>&1 & echo $! >> logs/workers.pids
nohup "$PY" -m queue_runtime.channel_worker fal > logs/fal.log 2>&1 & echo $! >> logs/workers.pids
nohup "$PY" -m queue_runtime.channel_worker omniroute > logs/omniroute.log 2>&1 & echo $! >> logs/workers.pids

echo "[workers] started PIDs: $(tr '\n' ' ' < logs/workers.pids)"
echo "[workers] health interval=${HEALTH_INTERVAL_SEC}s"
sleep 3
"$PY" - <<'PY'
from auth import load_env
load_env('.')
from queue_runtime.health import read_all_health
print("[workers] health:", {k: v.get("state") for k, v in read_all_health().items()})
PY
