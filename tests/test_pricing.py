"""Pricing formula checks from product spec."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")


def test_price_targets_at_90(monkeypatch):
    import pricing

    monkeypatch.setattr(pricing, "get_usd_rub_rate", lambda force=False: (90.0, False))
    # Wan 0.025 → 30 ₽ / 5s
    wan = pricing.price_rub_media(0.025, 2.0, "per_second")
    assert wan * 5 == 30
    # Seedance 2.0 0.10 → 120
    s20 = pricing.price_rub_media(0.10, 2.0, "per_second")
    assert s20 * 5 == 120
    # Seedance 2.5 0.1028 → 125
    s25 = pricing.price_rub_media(0.1028, 2.0, "per_second")
    assert s25 * 5 == 125
    # Kling 0.084 → 100
    kling = pricing.price_rub_media(0.084, 2.0, "per_second")
    assert kling * 5 == 100
    # SDXL approx
    sdxl = pricing.price_rub_media(0.0014, 3.0, "per_run_approx")
    assert sdxl == 1


def test_markup_min():
    import pricing

    with pytest.raises(ValueError):
        pricing.price_rub_media(0.1, 1.4, "per_second")


def test_api_pricing_hides_intl_in_ru(monkeypatch):
    monkeypatch.setenv("REGION", "RU")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    import pricing

    monkeypatch.setattr(pricing, "get_usd_rub_rate", lambda force=False: (90.0, False))
    items = pricing.list_pricing_public("RU")
    assert items
    assert all(i.get("region") != "INTL" for i in items)
    assert "channel" not in items[0]
