"""Start all 4 workers: dispatcher (+ health probes) + 3 channel consumers."""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auth import load_env  # noqa: E402

load_env(_ROOT)


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


<<<<<<< HEAD
def _run_free() -> None:
    from queue_runtime.free_dispatcher import run_free_dispatcher

    run_free_dispatcher()


=======
>>>>>>> 4404398504bd139f0127103f56fd9a4a82bda600
def main() -> None:
    roles = [
        ("dispatcher", _run_dispatcher),
        ("replicate", _run_replicate),
        ("fal", _run_fal),
        ("omniroute", _run_omniroute),
<<<<<<< HEAD
        ("free", _run_free),
=======
>>>>>>> 4404398504bd139f0127103f56fd9a4a82bda600
    ]
    procs: list[mp.Process] = []
    for name, target in roles:
        p = mp.Process(target=target, name=f"ai-shniza-{name}", daemon=False)
        p.start()
        procs.append(p)
        print(f"[run_all] started {p.name} pid={p.pid}", flush=True)

    stopping = {"v": False}

    def _stop(*_a) -> None:
        if stopping["v"]:
            return
        stopping["v"] = True
        print("[run_all] shutting down…", flush=True)
        for p in procs:
            if p.is_alive():
                p.terminate()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while not stopping["v"]:
            alive = [(p.name, p.is_alive(), p.exitcode) for p in procs]
            if any(not a[1] for a in alive):
                print(f"[run_all] process exited: {alive}", flush=True)
                _stop()
                break
            time.sleep(2)
    finally:
        for p in procs:
            p.join(timeout=5)
        print("[run_all] done", flush=True)


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
    sys.exit(0)
