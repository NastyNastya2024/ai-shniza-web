"""Soft-load traffic balancer: prefer primary channel, overflow to backup before hard full.

Policy (B2 soft-overflow):
  1. Preferred = model the user selected (usually Replicate).
  2. While preferred load < soft_cap (ratio of worker concurrency) → stay.
  3. At/above soft_cap, if fal backup exists + healthy + below its soft_cap → overflow.
  4. If backup also soft-full → stay on preferred until hard full, then overflow if backup has room.
  5. If preferred unhealthy → backup if available; else fail upstream (caller returns 503).

Load signal = inflight + queue length + processing length (jobs already claimed by workers).
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable

from queue_runtime import (
    PROCESSING_BY_CHANNEL,
    QUEUE_BY_CHANNEL,
    get_redis,
    inflight_key,
    worker_concurrency,
)


def soft_load_ratio() -> float:
    raw = (os.getenv("CHANNEL_SOFT_LOAD_RATIO") or "0.7").strip()
    try:
        ratio = float(raw)
    except ValueError:
        ratio = 0.7
    return min(0.95, max(0.1, ratio))


def balancer_enabled() -> bool:
    return (os.getenv("CHANNEL_LOAD_BALANCER") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@dataclass(frozen=True)
class ChannelLoad:
    channel: str
    inflight: int
    queued: int
    processing: int
    capacity: int
    soft_cap: int
    load: int

    @property
    def at_soft(self) -> bool:
        return self.load >= self.soft_cap

    @property
    def at_hard(self) -> bool:
        return self.load >= self.capacity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDecision:
    model_id: str
    provider: str
    reason: str
    preferred_model_id: str
    preferred_provider: str
    overflow: bool
    preferred_load: dict[str, Any] | None = None
    backup_load: dict[str, Any] | None = None
    backup_model_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def measure_channel_load(channel: str, *, redis_client=None) -> ChannelLoad:
    r = redis_client if redis_client is not None else get_redis()
    capacity = worker_concurrency(channel)
    soft_cap = max(1, int(math.ceil(capacity * soft_load_ratio())))
    try:
        inflight = int(r.get(inflight_key(channel)) or 0)
    except Exception:  # noqa: BLE001
        inflight = 0
    try:
        queued = int(r.llen(QUEUE_BY_CHANNEL[channel]) or 0)
    except Exception:  # noqa: BLE001
        queued = 0
    try:
        processing = int(r.llen(PROCESSING_BY_CHANNEL[channel]) or 0)
    except Exception:  # noqa: BLE001
        processing = 0
    load = max(0, inflight) + max(0, queued) + max(0, processing)
    return ChannelLoad(
        channel=channel,
        inflight=max(0, inflight),
        queued=max(0, queued),
        processing=max(0, processing),
        capacity=capacity,
        soft_cap=soft_cap,
        load=load,
    )


def choose_route(
    preferred_model_id: str,
    preferred_provider: str,
    *,
    has_image: bool,
    preferred_healthy: bool,
    backup_model_id: str | None,
    backup_provider: str | None,
    backup_healthy: bool,
    preferred_load: ChannelLoad | None = None,
    backup_load: ChannelLoad | None = None,
    enabled: bool | None = None,
) -> RouteDecision:
    """Pure routing decision given health + load snapshots."""
    base = RouteDecision(
        model_id=preferred_model_id,
        provider=preferred_provider,
        reason="preferred",
        preferred_model_id=preferred_model_id,
        preferred_provider=preferred_provider,
        overflow=False,
        preferred_load=preferred_load.to_dict() if preferred_load else None,
        backup_load=backup_load.to_dict() if backup_load else None,
        backup_model_id=backup_model_id,
    )

    if enabled is None:
        enabled = balancer_enabled()

    # Preferred down → try backup immediately (health failover).
    if not preferred_healthy:
        if backup_model_id and backup_provider and backup_healthy:
            return RouteDecision(
                model_id=backup_model_id,
                provider=backup_provider,
                reason="preferred_unhealthy",
                preferred_model_id=preferred_model_id,
                preferred_provider=preferred_provider,
                overflow=True,
                preferred_load=preferred_load.to_dict() if preferred_load else None,
                backup_load=backup_load.to_dict() if backup_load else None,
                backup_model_id=backup_model_id,
            )
        return RouteDecision(
            model_id=preferred_model_id,
            provider=preferred_provider,
            reason="preferred_unhealthy_no_backup",
            preferred_model_id=preferred_model_id,
            preferred_provider=preferred_provider,
            overflow=False,
            preferred_load=preferred_load.to_dict() if preferred_load else None,
            backup_load=backup_load.to_dict() if backup_load else None,
            backup_model_id=backup_model_id,
        )

    if not enabled or not backup_model_id or not backup_provider:
        return base

    if not backup_healthy:
        return RouteDecision(
            model_id=preferred_model_id,
            provider=preferred_provider,
            reason="backup_unhealthy",
            preferred_model_id=preferred_model_id,
            preferred_provider=preferred_provider,
            overflow=False,
            preferred_load=preferred_load.to_dict() if preferred_load else None,
            backup_load=backup_load.to_dict() if backup_load else None,
            backup_model_id=backup_model_id,
        )

    pref = preferred_load
    bak = backup_load
    if pref is None:
        return base

    # Soft overflow: primary warm, backup has headroom.
    if pref.at_soft and bak is not None and not bak.at_soft:
        return RouteDecision(
            model_id=backup_model_id,
            provider=backup_provider,
            reason="soft_overflow",
            preferred_model_id=preferred_model_id,
            preferred_provider=preferred_provider,
            overflow=True,
            preferred_load=pref.to_dict(),
            backup_load=bak.to_dict() if bak else None,
            backup_model_id=backup_model_id,
        )

    # Hard overflow: primary saturated, backup still has any room under capacity.
    if pref.at_hard and bak is not None and not bak.at_hard:
        return RouteDecision(
            model_id=backup_model_id,
            provider=backup_provider,
            reason="hard_overflow",
            preferred_model_id=preferred_model_id,
            preferred_provider=preferred_provider,
            overflow=True,
            preferred_load=pref.to_dict(),
            backup_load=bak.to_dict(),
            backup_model_id=backup_model_id,
        )

    return base


def resolve_route(
    preferred_model_id: str,
    preferred_provider: str,
    *,
    has_image: bool,
    failover_target: Callable[[str, bool], str | None],
    models: dict[str, dict],
    is_healthy: Callable[[str], bool],
    redis_client=None,
) -> RouteDecision:
    """Measure Redis load and pick preferred vs fal backup."""
    backup_id = None
    backup_provider = None
    backup_healthy = False
    backup_load = None

    if preferred_provider == "replicate":
        backup_id = failover_target(preferred_model_id, has_image)
        if backup_id:
            bak = models.get(backup_id) or {}
            backup_provider = bak.get("provider")
            if backup_provider == "fal":
                backup_healthy = bool(is_healthy("fal"))
                backup_load = measure_channel_load("fal", redis_client=redis_client)

    preferred_healthy = bool(is_healthy(preferred_provider))
    preferred_load = measure_channel_load(preferred_provider, redis_client=redis_client)

    return choose_route(
        preferred_model_id,
        preferred_provider,
        has_image=has_image,
        preferred_healthy=preferred_healthy,
        backup_model_id=backup_id,
        backup_provider=backup_provider,
        backup_healthy=backup_healthy,
        preferred_load=preferred_load,
        backup_load=backup_load,
    )
