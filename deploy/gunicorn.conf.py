# Gunicorn: short HTTP timeouts; generation runs in queue_runtime workers.
# Sync generate (GENERATE_USE_QUEUE=0 / GENERATE_SYNC_WAIT=1) needs timeout >= 360 — not for prod.
import os

bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
worker_class = "gthread"
workers = int(os.getenv("GUNICORN_WORKERS", "3"))
threads = int(os.getenv("GUNICORN_THREADS", "8"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
accesslog = "-"
errorlog = "-"
capture_output = True
preload_app = False
