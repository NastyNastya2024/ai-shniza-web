"""Unit tests for Higgsfield channel wiring (no live API calls)."""

from __future__ import annotations

import os

import pytest


def test_channels_include_higgsfield():
    from queue_runtime import CHANNELS, QUEUE_BY_CHANNEL, PROCESSING_BY_CHANNEL, worker_concurrency

    assert "higgsfield" in CHANNELS
    assert QUEUE_BY_CHANNEL["higgsfield"].endswith(":higgsfield")
    assert PROCESSING_BY_CHANNEL["higgsfield"].endswith(":higgsfield")
    assert worker_concurrency("higgsfield") >= 1


def test_probe_higgsfield_missing_key(monkeypatch):
    from queue_runtime import health as h

    monkeypatch.delenv("HF_KEY", raising=False)
    ok, detail = h.probe_higgsfield()
    assert ok is False
    assert "HF_KEY" in detail


def test_seedance_hf_model_in_registry():
    import server as srv

    spec = srv.INTEGRATED_MODELS["seedance-2-5-hf"]
    assert spec["provider"] == "higgsfield"
    assert spec["higgsfield_model"] == "bytedance/seedance-2.5/text-to-video"
    assert spec["higgsfield_model_i2v"] == "bytedance/seedance-2.5/image-to-video"
    assert "seedance-2-5-hf" in srv.STUDIO_ONBOARD_IDS


def test_kling_and_veo_hf_models_in_registry():
    import server as srv

    k25 = srv.INTEGRATED_MODELS["kling-v2-5-turbo-pro-hf"]
    k3 = srv.INTEGRATED_MODELS["kling-v3-0-hf"]
    veo = srv.INTEGRATED_MODELS["veo-3-1-hf"]
    assert k25["provider"] == "higgsfield"
    assert k25["higgsfield_model"] == "kling-video/v2.5-turbo/pro/text-to-video"
    assert k3["higgsfield_model"] == "kling-video/v3.0/pro/text-to-video"
    assert veo["higgsfield_model"] == "veo3.1/text-to-video"
    assert "kling-v3-0-hf" in srv.STUDIO_ONBOARD_IDS
    assert "kling-v2-5-turbo-pro-hf" in srv.STUDIO_ONBOARD_IDS
    assert "veo-3-1-hf" in srv.STUDIO_ONBOARD_IDS


def test_build_provider_input_seedance_hf():
    import server as srv

    payload = srv._build_provider_input(
        srv.INTEGRATED_MODELS["seedance-2-5-hf"],
        "A cinematic scene at sunset",
        None,
        None,
        None,
    )
    assert payload["prompt"] == "A cinematic scene at sunset"
    assert payload["duration"] == 5
    assert payload["resolution"] == "720p"
    assert payload["aspect_ratio"] == "16:9"


def test_build_provider_input_seedance_hf_i2v():
    import server as srv

    payload = srv._build_provider_input(
        srv.INTEGRATED_MODELS["seedance-2-5-hf"],
        "Animate",
        "https://example.com/frame.jpg",
        None,
        None,
    )
    assert payload["image_url"] == "https://example.com/frame.jpg"
    assert "aspect_ratio" not in payload


def test_build_provider_input_kling_v3_hf():
    import server as srv

    payload = srv._build_provider_input(
        srv.INTEGRATED_MODELS["kling-v3-0-hf"],
        "Forest dawn push-in",
        None,
        None,
        None,
    )
    assert payload["sound"] == "on"
    assert payload["aspect_ratio"] == "16:9"


def test_higgsfield_extract_outputs():
    import server as srv

    urls = srv._higgsfield_extract_outputs(
        {"video": {"url": "https://example.com/v.mp4"}, "status": "completed"},
        "video",
    )
    assert urls == ["https://example.com/v.mp4"]


def test_provider_model_ref_higgsfield():
    import server as srv

    ref = srv._provider_model_ref(srv.INTEGRATED_MODELS["seedance-2-5-hf"])
    assert ref == "bytedance/seedance-2.5/text-to-video"
    ref_i2v = srv._provider_model_ref(
        srv.INTEGRATED_MODELS["seedance-2-5-hf"], has_image=True
    )
    assert ref_i2v == "bytedance/seedance-2.5/image-to-video"
    k3 = srv._provider_model_ref(srv.INTEGRATED_MODELS["kling-v3-0-hf"], has_image=True)
    assert k3 == "kling-video/v3.0/pro/image-to-video"


def test_fal_and_replicate_still_present():
    import server as srv

    assert srv.INTEGRATED_MODELS["seedance-2-5"]["provider"] == "replicate"
    assert srv.INTEGRATED_MODELS["seedance-2-5-t2v-fal"]["provider"] == "fal"
