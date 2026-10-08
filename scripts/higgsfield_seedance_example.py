#!/usr/bin/env python3
"""Billable smoke test: Seedance 2.5 via Higgsfield official SDK.

Loads HF_KEY from .env (gitignored). Does not print credentials.
Usage:
  .venv/bin/python scripts/higgsfield_seedance_example.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auth import load_env  # noqa: E402

load_env(ROOT)


def main() -> int:
    key = (os.getenv("HF_KEY") or "").strip()
    if not key or ":" not in key:
        print("FAIL: HF_KEY missing in environment / .env", file=sys.stderr)
        return 2

    import higgsfield_client as hf
    from higgsfield_client import Cancelled, Completed, Failed, NSFW
    from higgsfield_client.exceptions import HiggsfieldClientError

    model = "bytedance/seedance-2.5/text-to-video"
    arguments = {
        "prompt": "A cinematic scene at sunset",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "output_format": "mp4",
        "generate_audio": True,
    }

    print(f"submit {model} …", flush=True)
    try:
        result = hf.subscribe(model, arguments)
    except HiggsfieldClientError as exc:
        detail = str(exc)
        low = detail.lower()
        if "not_enough_credits" in low or "insufficient" in low:
            print("FAIL: Higgsfield account has not_enough_credits (API auth OK)", file=sys.stderr)
            return 3
        print(f"FAIL: SDK error: {exc.__class__.__name__}: {detail[:200]}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc.__class__.__name__}", file=sys.stderr)
        return 1

    # subscribe() returns the completed JSON body (not a Status object).
    if isinstance(result, (Failed, Cancelled, NSFW)):
        print(f"FAIL: terminal status {type(result).__name__}", file=sys.stderr)
        return 1
    if isinstance(result, Completed):
        # unusual; fetch not needed
        pass

    video = None
    if isinstance(result, dict):
        status = str(result.get("status") or "").lower()
        if status in {"failed", "canceled", "cancelled", "nsfw", "moderated"}:
            print(f"FAIL: status={status}", file=sys.stderr)
            return 1
        v = result.get("video")
        if isinstance(v, dict):
            video = v.get("url") or v.get("uri")
        elif isinstance(v, str):
            video = v

    if not video:
        print("FAIL: no video URL in result", file=sys.stderr)
        print(f"keys={list(result) if isinstance(result, dict) else type(result)}", file=sys.stderr)
        return 1

    print("OK video_url=", video, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
