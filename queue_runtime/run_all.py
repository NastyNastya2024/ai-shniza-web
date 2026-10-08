"""Start all workers: dispatcher (+ health) + channel consumers + free queue.

If a child exits while we are not shutting down, restart that child only
with exponential backoff (1→2→4…≤30s). Reset backoff after 5 minutes up.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import sys
import threading
import time
from typing import Callable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auth import load_env  # noqa: E402

load_env(_ROOT)

from queue_runtime import WORKER_SHUTDOWN_GRACE_SEC  # noqa: E402


def _run_dispatcher() -> None:
    from queue_runtime.dispatcher import run_dispatcher

    run_dispatcher()


def _run_replicate() -> None:
    from queue_runtime.channel_worker import run_channel_worker

    run_channel_worker("replicate")


def _run_fal() -> None:
    from queue_runtime.channel_worker import run_channel_worker

    run_channel_worker("fal")


def _run_omniroute() -> None:
    from queue_runtime.channel_worker import run_channel_worker

    run_channel_worker("omniroute")


def _run_higgsfield() -> None:
    from queue_runtime.channel_worker import run_channel_worker

    run_channel_worker("higgsfield")


def _run_free() -> None:
    from queue_runtime.free_dispatcher import run_free_dispatcher

    run_free_dispatcher()


DEFAULT_ROLES: list[tuple[str, Callable[[], None]]] = [
    ("dispatcher", _run_dispatcher),
    ("replicate", _run_replicate),
    ("fal", _run_fal),
    ("omniroute", _run_omniroute),
    ("higgsfield", _run_higgsfield),
    ("free", _run_free),
]


def _start_child(name: str, target: Callable[[], None]) -> mp.Process:
    p = mp.Process(target=target, name=f"ai-shniza-{name}", daemon=False)
    p.start()
    print(f"[run_all] started {p.name} pid={p.pid}", flush=True)
    return p


def main(
    roles: list[tuple[str, Callable[[], None]]] | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    roles = list(roles or DEFAULT_ROLES)
    state: dict[str, dict] = {}
    for name, target in roles:
        state[name] = {
            "target": target,
            "proc": _start_child(name, target),
            "backoff": 1.0,
            "started_at": time.time(),
        }

    stopping = {"v": False}

    def _stop(*_a) -> None:
        if stopping["v"]:
            return
        stopping["v"] = True
        print("[run_all] shutting down…", flush=True)
        for info in state.values():
            p = info.get("proc")
            if p and p.is_alive():
                p.terminate()

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except ValueError:
        pass

    try:
        while not stopping["v"]:
            if stop_event is not None and stop_event.is_set():
                _stop()
                break
            for name, info in state.items():
                p: mp.Process | None = info.get("proc")
                if p is None:
                    continue
                if p.is_alive():
                    if time.time() - float(info["started_at"]) >= 300:
                        info["backoff"] = 1.0
                    continue
                code = p.exitcode
                print(f"[run_all] process exited name={name} exitcode={code}", flush=True)
                if stopping["v"]:
                    break
                delay = float(info["backoff"])
                print(f"[run_all] restarting {name} in {delay:.0f}s", flush=True)
                end = time.time() + delay
                while time.time() < end:
                    if stopping["v"] or (stop_event is not None and stop_event.is_set()):
                        _stop()
                        break
                    time.sleep(0.1)
                if stopping["v"]:
                    break
                info["backoff"] = min(30.0, delay * 2.0)
                info["proc"] = _start_child(name, info["target"])
                info["started_at"] = time.time()
            time.sleep(0.2)
    finally:
        join_timeout = WORKER_SHUTDOWN_GRACE_SEC + 5
        for info in state.values():
            p = info.get("proc")
            if not p:
                continue
            if p.is_alive():
                p.terminate()
            p.join(timeout=join_timeout)
            if p.is_alive():
                p.kill()
                p.join(timeout=2)
        print("[run_all] done", flush=True)


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
    sys.exit(0)
