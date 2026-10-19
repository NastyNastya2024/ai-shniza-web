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
    # формула: usd × 90 × 1.30 × markup
    # Wan 0.025 ×1.5 → 5 ₽/с · 25 ₽ / 5s
    wan = pricing.price_rub_media(0.025, 1.5, "per_second")
    assert wan == 5 and wan * 5 == 25
    # Seedance 2.0 0.10 ×1.5 → 18 ₽/с · 90 / 5s
    s20 = pricing.price_rub_media(0.10, 1.5, "per_second")
    assert s20 * 5 == 90
    # Seedance 2.5 0.1028 ×1.5 → 19 ₽/с · 95 / 5s
    s25 = pricing.price_rub_media(0.1028, 1.5, "per_second")
    assert s25 * 5 == 95
    # Kling R 0.07 ×1.5 → 13 ₽/с · 65 / 5s
    kling = pricing.price_rub_media(0.07, 1.5, "per_second")
    assert kling == 13 and kling * 5 == 65
    # Kling 3.0 HF 0.042 ×1.5 → 8 ₽/с
    k3 = pricing.price_rub_media(0.042, 1.5, "per_second")
    assert k3 == 8
    # SDXL approx (markup 3.0)
    sdxl = pricing.price_rub_media(0.0014, 3.0, "per_run_approx")
    assert sdxl == 1


def test_default_markup_is_1_5():
    import pricing

    assert pricing.DEFAULT_MARKUP == 1.5
    keys = {r.model_key for r in pricing.PRICING_SEED}
    assert "kling-v2-5-turbo-pro" in keys and "kling-v3-0-hf" in keys


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
