"""Soft-load balancer: prefer primary, overflow before hard full."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from queue_runtime.load_balancer import ChannelLoad, choose_route  # noqa: E402


def _load(channel: str, load: int, capacity: int = 10, soft_ratio: float = 0.7) -> ChannelLoad:
    soft = max(1, int(__import__("math").ceil(capacity * soft_ratio)))
    return ChannelLoad(
        channel=channel,
        inflight=load,
        queued=0,
        processing=0,
        capacity=capacity,
        soft_cap=soft,
        load=load,
    )


def test_stays_on_preferred_when_cool():
    d = choose_route(
        "wan-3-0",
        "replicate",
        has_image=False,
        preferred_healthy=True,
        backup_model_id="wan-3-0-t2v-fal",
        backup_provider="fal",
        backup_healthy=True,
        preferred_load=_load("replicate", 3),
        backup_load=_load("fal", 1, capacity=6),
    )
    assert d.model_id == "wan-3-0"
    assert d.provider == "replicate"
    assert d.overflow is False
    assert d.reason == "preferred"


def test_soft_overflow_to_fal():
    d = choose_route(
        "wan-3-0",
        "replicate",
        has_image=False,
        preferred_healthy=True,
        backup_model_id="wan-3-0-t2v-fal",
        backup_provider="fal",
        backup_healthy=True,
        preferred_load=_load("replicate", 7),  # soft_cap=7 for capacity 10
        backup_load=_load("fal", 1, capacity=6),
    )
    assert d.overflow is True
    assert d.model_id == "wan-3-0-t2v-fal"
    assert d.provider == "fal"
    assert d.reason == "soft_overflow"


def test_no_overflow_when_backup_also_soft():
    d = choose_route(
        "wan-3-0",
        "replicate",
        has_image=False,
        preferred_healthy=True,
        backup_model_id="wan-3-0-t2v-fal",
        backup_provider="fal",
        backup_healthy=True,
        preferred_load=_load("replicate", 8),
        backup_load=_load("fal", 5, capacity=6),  # soft_cap=5
    )
    assert d.overflow is False
    assert d.model_id == "wan-3-0"
    assert d.reason == "preferred"


def test_hard_overflow_when_primary_full():
    d = choose_route(
        "wan-3-0",
        "replicate",
        has_image=False,
        preferred_healthy=True,
        backup_model_id="wan-3-0-t2v-fal",
        backup_provider="fal",
        backup_healthy=True,
        preferred_load=_load("replicate", 10),
        backup_load=_load("fal", 5, capacity=6),  # at soft but not hard
    )
    assert d.overflow is True
    assert d.reason == "hard_overflow"
    assert d.model_id == "wan-3-0-t2v-fal"


def test_preferred_unhealthy_uses_backup():
    d = choose_route(
        "wan-3-0",
        "replicate",
        has_image=True,
        preferred_healthy=False,
        backup_model_id="wan-3-0-i2v-fal",
        backup_provider="fal",
        backup_healthy=True,
        preferred_load=_load("replicate", 0),
        backup_load=_load("fal", 0, capacity=6),
    )
    assert d.overflow is True
    assert d.reason == "preferred_unhealthy"
    assert d.model_id == "wan-3-0-i2v-fal"


def test_disabled_stays_preferred_even_when_soft():
    d = choose_route(
        "wan-3-0",
        "replicate",
        has_image=False,
        preferred_healthy=True,
        backup_model_id="wan-3-0-t2v-fal",
        backup_provider="fal",
        backup_healthy=True,
        preferred_load=_load("replicate", 9),
        backup_load=_load("fal", 0, capacity=6),
        enabled=False,
    )
    assert d.overflow is False
    assert d.model_id == "wan-3-0"
