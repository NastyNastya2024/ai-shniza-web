#!/usr/bin/env python3
"""Smoke-test fal backup models (paid). Default: print plan only; run with --yes."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auth import load_env  # noqa: E402

load_env(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cheap fal backup smoke tests")
    parser.add_argument("--only", help="INTEGRATED_MODELS backup id")
    parser.add_argument("--yes", action="store_true", help="Actually call fal (costs money)")
    args = parser.parse_args()

    import server as srv

    ids = sorted(
        {
            bid
            for modes in srv.FAILOVER_MAP.values()
            for bid in modes.values()
        }
    )
    if args.only:
        ids = [args.only]

    print("Fal backup smoke plan (cheapest params):")
    for mid in ids:
        spec = srv.INTEGRATED_MODELS.get(mid)
        if not spec:
            print(f"  skip {mid}: unknown")
            continue
        fal_model = spec.get("fal_model") or "?"
        print(f"  · {mid} → {fal_model}")

    if not args.yes:
        print("\nDry run. Re-run with --yes to execute (paid).")
        return 0

    if not srv._fal_key():
        print("FAL_KEY missing", file=sys.stderr)
        return 2

    for mid in ids:
        spec = srv.INTEGRATED_MODELS[mid]
        payload = srv._build_provider_input(spec, "smoke test", None, None, None)
        t0 = __import__("time").time()
        result = srv._fal_submit(spec["fal_model"], payload)
        if not result.get("ok"):
            print(f"{mid} · submit failed · {result.get('detail')}")
            continue
        deadline = t0 + min(int(spec.get("wait_sec") or 120), 120)
        waited = srv._fal_wait(result.get("status_url"), result.get("response_url"), deadline)
        elapsed = __import__("time").time() - t0
        ok = waited.get("ok")
        urls = srv._fal_extract_outputs((waited.get("prediction") or {}), spec.get("kind") or "image")
        link = urls[0] if urls else "—"
        print(f"{mid} · {'ok' if ok else 'fail'} · {elapsed:.1f}s · {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
