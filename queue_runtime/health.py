"""Channel health probes + Redis state."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from queue_runtime import (
    CHANNELS,
    HEALTH_FAIL_THRESHOLD,
    dumps,
    get_redis,
    health_key,
    loads,
)


def _default_health(channel: str) -> dict[str, Any]:
    return {
        "channel": channel,
        "state": "unknown",
        "error_streak": 0,
        "last_ok_at": None,
        "last_error": None,
        "checked_at": None,
        "detail": None,
    }


def read_health(channel: str) -> dict[str, Any]:
    r = get_redis()
    data = loads(r.get(health_key(channel)))
    if not isinstance(data, dict):
        return _default_health(channel)
    return data


def read_all_health() -> dict[str, dict[str, Any]]:
    return {ch: read_health(ch) for ch in CHANNELS}


def is_channel_healthy(channel: str) -> bool:
    if channel == "groq":
        return bool(os.getenv("GROQ_API_KEY", "").strip())
    state = read_health(channel).get("state")
    # unknown → allow until first probe (boot); after probe only healthy
    if state in (None, "unknown"):
        return True
    return state == "healthy"


def write_health(channel: str, ok: bool, detail: str | None = None) -> dict[str, Any]:
    prev = read_health(channel)
    now = time.time()
    if ok:
        entry = {
            "channel": channel,
            "state": "healthy",
            "error_streak": 0,
            "last_ok_at": now,
            "last_error": None,
            "checked_at": now,
            "detail": detail,
        }
    else:
        streak = int(prev.get("error_streak") or 0) + 1
        state = "down" if streak >= HEALTH_FAIL_THRESHOLD else "degraded"
        entry = {
            "channel": channel,
            "state": state,
            "error_streak": streak,
            "last_ok_at": prev.get("last_ok_at"),
            "last_error": detail,
            "checked_at": now,
            "detail": detail,
        }
    get_redis().set(health_key(channel), dumps(entry))
    return entry


def probe_replicate() -> tuple[bool, str]:
    token = (os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        return False, "REPLICATE_API_TOKEN missing"
    try:
        resp = requests.get(
            "https://api.replicate.com/v1/account",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, f"network:{exc.__class__.__name__}"
    if resp.status_code >= 400:
        return False, f"http:{resp.status_code}"
    return True, "ok"


def probe_fal() -> tuple[bool, str]:
    key = (os.getenv("FAL_KEY") or "").strip()
    if not key:
        return False, "FAL_KEY missing"
    try:
        # Lightweight authenticated call; 2xx/4xx-with-body means gateway reachable.
        resp = requests.get(
            "https://api.fal.ai/v1/models",
            headers={"Authorization": f"Key {key}"},
            params={"limit": 1},
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, f"network:{exc.__class__.__name__}"
    if resp.status_code in {401, 403}:
        return False, f"auth:{resp.status_code}"
    if resp.status_code >= 500:
        return False, f"http:{resp.status_code}"
    return True, f"http:{resp.status_code}"


def probe_omniroute() -> tuple[bool, str]:
    base = (os.getenv("OMNIROUTE_BASE_URL") or "http://127.0.0.1:20128").rstrip("/")
    key = (os.getenv("OMNIROUTE_API_KEY") or "").strip()
    try:
        resp = requests.get(f"{base}/healthz", timeout=10)
    except requests.RequestException as exc:
        return False, f"network:{exc.__class__.__name__}"
    if resp.status_code >= 400:
        return False, f"http:{resp.status_code}"
    if not key:
        return False, "OMNIROUTE_API_KEY missing"
    try:
        models = requests.get(
            f"{base}/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"models_network:{exc.__class__.__name__}"
    if models.status_code >= 400:
        return False, f"models_http:{models.status_code}"
    return True, "ok"


def probe_higgsfield() -> tuple[bool, str]:
    key = (os.getenv("HF_KEY") or "").strip()
    if not key or ":" not in key:
        return False, "HF_KEY missing"
    try:
        # Authenticated ping — 2xx/4xx (not 401/403) means gateway reachable with key.
        resp = requests.get(
            "https://platform.higgsfield.ai/v1/models",
            headers={"Authorization": f"Key {key}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        # Fallback: API root under api.higgsfield.ai
        try:
            resp = requests.get(
                "https://api.higgsfield.ai/",
                headers={"Authorization": f"Key {key}"},
                timeout=15,
            )
        except requests.RequestException as exc2:
            return False, f"network:{exc2.__class__.__name__}"
    if resp.status_code in {401, 403}:
        return False, f"auth:{resp.status_code}"
    if resp.status_code >= 500:
        return False, f"http:{resp.status_code}"
    return True, f"http:{resp.status_code}"


PROBES = {
    "replicate": probe_replicate,
    "fal": probe_fal,
    "omniroute": probe_omniroute,
    "higgsfield": probe_higgsfield,
}


def probe_all() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for channel, fn in PROBES.items():
        ok, detail = fn()
        out[channel] = write_health(channel, ok, detail)
    return out
